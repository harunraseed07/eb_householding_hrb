# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Apply decisions and publish Gold
# MAGIC
# MAGIC This is the notebook that turns scored pairs into a household view, and
# MAGIC it is the one to re-run after a steward makes a decision in the App.
# MAGIC
# MAGIC Order matters:
# MAGIC
# MAGIC 1. **Records to parties.** Automation proposes, the steward disposes. An
# MAGIC    auto-match stands unless a steward rejected it; a review case counts
# MAGIC    only once accepted. Clustering is transitive, so accepting one pair can
# MAGIC    merge three records.
# MAGIC 2. **Parties to households.** The address policy runs first, then steward
# MAGIC    overrides sit on top of it.
# MAGIC 3. **Households to super households.** Connected components over business
# MAGIC    ownership. A business link never merges two people into one party.
# MAGIC 4. **Publish.** Gold dimensions, bridges and facts, plus the analytics
# MAGIC    summary Power BI reads.
# MAGIC 5. **Measure.** Precision, recall and F1 against `demo_eval`.

# COMMAND ----------

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import config, pipeline
from src.datastore import SparkStore

# COMMAND ----------

dbutils.widgets.text("catalog", config.DEMO_CATALOG, "Unity Catalog (demo only)")
dbutils.widgets.dropdown("household_rule", config.HOUSEHOLD_RULE,
                         ["ADDRESS_ONLY", "NAME_AND_ADDRESS"], "Household rule")

catalog = dbutils.widgets.get("catalog").strip()
rule = dbutils.widgets.get("household_rule")
store = SparkStore(catalog=catalog, spark=spark)

print(f"Catalog `{catalog}` · household rule {rule}")

# COMMAND ----------

# MAGIC %md ## What the stewards have decided so far

# COMMAND ----------

display(spark.sql(f"""
    SELECT decision, COUNT(*) AS decisions, MAX(decision_timestamp) AS latest
    FROM `{catalog}`.mdm.steward_decision
    GROUP BY decision ORDER BY decisions DESC
"""))

# COMMAND ----------

# MAGIC %md ## Resolve, household and publish

# COMMAND ----------

counts = pipeline.apply_decisions_and_publish(store, rule=rule)
for name, value in counts.items():
    print(f"{name:28s} {value:>8,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Did the matching actually work
# MAGIC
# MAGIC Measured against `demo_eval.ground_truth_identity`, which knows which
# MAGIC synthetic rows came from the same invented person.
# MAGIC
# MAGIC Read **blocking recall** before anything else. Recall lost at the
# MAGIC blocking stage can never be recovered by better scoring, so if that
# MAGIC number drops, the blocking keys are the thing to fix.

# COMMAND ----------

display(spark.sql(f"""
    SELECT metric_name, metric_value
    FROM `{catalog}`.gold.fact_match_quality
    WHERE metric_name IN (
      'precision', 'recall', 'f1', 'blocking_recall', 'reduction_ratio',
      'true_positive', 'false_positive', 'false_negative',
      'predicted_parties', 'actual_identities',
      'household_precision', 'household_recall', 'household_f1'
    )
    ORDER BY metric_name
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## The household view the business asked for

# COMMAND ----------

display(spark.sql(f"""
    SELECT household_name, city, member_count, account_count, product_count,
           deposit_balance, loan_balance, card_balance,
           total_relationship_balance, relationship_segment, cross_sell_flag
    FROM `{catalog}`.gold.fact_household_summary
    ORDER BY total_relationship_balance DESC
    LIMIT 25
"""))

# COMMAND ----------

# MAGIC %md ### The scripted household, end to end

# COMMAND ----------

display(spark.sql(f"""
    SELECT h.household_id, p.party_id, p.full_name, p.source_systems,
           p.source_record_count, b.membership_rule,
           a.account_id, a.account_category, a.product_type, f.balance
    FROM `{catalog}`.gold.bridge_household_party b
    JOIN `{catalog}`.gold.dim_party p ON p.party_id = b.party_id
    JOIN `{catalog}`.gold.dim_household h ON h.household_id = b.household_id
    LEFT JOIN `{catalog}`.gold.bridge_party_account pa ON pa.party_id = p.party_id
    LEFT JOIN `{catalog}`.gold.dim_account a ON a.account_id = pa.account_id
    LEFT JOIN `{catalog}`.gold.fact_account_balance f ON f.account_id = a.account_id
    WHERE b.household_id = (
      SELECT household_id FROM `{catalog}`.gold.bridge_household_party
      WHERE party_id = (
        SELECT party_id FROM `{catalog}`.gold.bridge_party_source_record
        WHERE record_id = 'CORE:C10000000'
      ) LIMIT 1
    )
    ORDER BY p.full_name, a.account_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Super households
# MAGIC
# MAGIC Extended households link a consumer household to a business through
# MAGIC ownership. When two households own the same business they land in one
# MAGIC super household, without their members ever being treated as the same
# MAGIC person.

# COMMAND ----------

display(spark.sql(f"""
    SELECT s.super_household_id, s.standard_household_count, s.business_count,
           m.member_type, m.member_id,
           COALESCE(bus.business_name, hh.household_name) AS member_name
    FROM `{catalog}`.gold.dim_super_household s
    JOIN `{catalog}`.gold.bridge_super_household_member m
      ON m.super_household_id = s.super_household_id
    LEFT JOIN `{catalog}`.gold.dim_business bus
      ON m.member_type = 'BUSINESS' AND bus.business_id = m.member_id
    LEFT JOIN `{catalog}`.gold.dim_household hh
      ON m.member_type = 'HOUSEHOLD' AND hh.household_id = m.member_id
    WHERE s.standard_household_count > 1 AND s.business_count > 0
    ORDER BY s.standard_household_count DESC, s.super_household_id, m.member_type
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grants for the App
# MAGIC
# MAGIC The App runs as its own service principal. It reads Gold and Silver and
# MAGIC appends to the two governance tables, and that is all it may do. Set
# MAGIC `app_service_principal` and run this cell once.

# COMMAND ----------

dbutils.widgets.text("app_service_principal", "", "App service principal (optional)")
principal = dbutils.widgets.get("app_service_principal").strip()

if not principal:
    print("No service principal given. Fill the widget and re-run this cell "
          "once the App exists.")
else:
    statements = [
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{principal}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.gold TO `{principal}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.silver TO `{principal}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.mdm TO `{principal}`",
        f"GRANT SELECT ON SCHEMA `{catalog}`.gold TO `{principal}`",
        f"GRANT SELECT ON SCHEMA `{catalog}`.silver TO `{principal}`",
        f"GRANT SELECT ON SCHEMA `{catalog}`.mdm TO `{principal}`",
        # Append-only governance: the App writes decisions, never Gold.
        f"GRANT MODIFY ON TABLE `{catalog}`.mdm.steward_decision TO `{principal}`",
        f"GRANT MODIFY ON TABLE `{catalog}`.mdm.household_override TO `{principal}`",
    ]
    for statement in statements:
        spark.sql(statement)
        print("OK  ", statement)
    print("\nNote: demo_eval is deliberately NOT granted. The App hides the "
          "score-distribution panels when it cannot read the truth table.")

# COMMAND ----------

print("Gold published. Start the App, or run 03_refresh_demo for a monthly cycle.")
