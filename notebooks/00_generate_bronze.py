# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Generate Bronze
# MAGIC
# MAGIC Writes the synthetic source extracts into Unity Catalog. Run this first.
# MAGIC
# MAGIC | Schema | Contents |
# MAGIC |---|---|
# MAGIC | `bronze` | CORE customers and accounts, Elan-style card customers and accounts, CRM contacts, joint-ownership rows, businesses and owners, third-party demographics |
# MAGIC | `demo_eval` | `ground_truth_identity`, evaluation only. **Never grant this to business users or to the App.** |
# MAGIC | `silver`, `mdm`, `gold` | Created empty, filled by notebooks 01 and 02 |
# MAGIC
# MAGIC Everything is generated from a seed. The same seed gives the same demo,
# MAGIC which is what makes a rehearsed walkthrough possible. No real customer,
# MAGIC account or tax data is used anywhere.
# MAGIC
# MAGIC Existing steward decisions and household overrides are **kept**, so you
# MAGIC can re-run this without losing governance history.

# COMMAND ----------

# MAGIC %md ## Setup

# COMMAND ----------

import os
import sys

# In a Databricks Git folder the notebook's working directory is this folder,
# so the project root is one level up.
PROJECT_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import config, pipeline
from src.datastore import SparkStore

print("Project root:", PROJECT_ROOT)

# COMMAND ----------

dbutils.widgets.text("catalog", config.DEMO_CATALOG, "Unity Catalog (demo only)")
dbutils.widgets.text("seed", str(config.DATA_SPEC.seed), "Random seed")
dbutils.widgets.text("identities", str(config.DATA_SPEC.n_identities), "Distinct people")
dbutils.widgets.text("households", str(config.DATA_SPEC.n_households), "Truth households")

catalog = dbutils.widgets.get("catalog").strip()
spec = config.DataSpec(**{
    **config.DATA_SPEC.as_dict(),
    "seed": int(dbutils.widgets.get("seed")),
    "n_identities": int(dbutils.widgets.get("identities")),
    "n_households": int(dbutils.widgets.get("households")),
})

assert catalog and catalog.replace("_", "").isalnum(), \
    "Choose a simple, non-production catalog name."
print(f"Writing to catalog `{catalog}` with seed {spec.seed}, "
      f"{spec.n_identities} people in {spec.n_households} households.")

# COMMAND ----------

store = SparkStore(catalog=catalog, spark=spark)
store.ensure_schemas()
print("Schemas ready:", ", ".join(config.SCHEMAS))

# COMMAND ----------

# MAGIC %md ## Generate

# COMMAND ----------

counts = pipeline.generate_bronze(store, spec, keep_governance=True)
display(spark.createDataFrame(
    [(name, int(count)) for name, count in sorted(counts.items())],
    "table string, row_count long",
))

# COMMAND ----------

# MAGIC %md
# MAGIC ## The scripted family
# MAGIC
# MAGIC Robert Sullivan appears three times under three given names. CORE and
# MAGIC CARD share a tax identifier so they will link automatically. The CRM row
# MAGIC has a keyed-in surname typo, a stale phone number, and neither a tax id
# MAGIC nor a birth date, so it will land in the steward queue instead.

# COMMAND ----------

display(spark.sql(f"""
    SELECT 'CORE' AS source, source_customer_id, full_name, date_of_birth,
           tax_id_last4, address_line_1, phone
    FROM `{catalog}`.bronze.core_customer WHERE source_customer_id LIKE 'C1000000%'
    UNION ALL
    SELECT 'CARD', source_customer_id, full_name, date_of_birth,
           tax_id_last4, address_line_1, phone
    FROM `{catalog}`.bronze.card_customer WHERE source_customer_id = 'ELAN2000000'
    UNION ALL
    SELECT 'CRM', source_customer_id, full_name, date_of_birth,
           tax_id_last4, address_line_1, phone
    FROM `{catalog}`.bronze.crm_contact WHERE source_customer_id LIKE 'CRM-7000%'
    ORDER BY source_customer_id
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Protect the evaluation table
# MAGIC
# MAGIC `demo_eval.ground_truth_identity` is the answer key. It exists so the
# MAGIC matcher can be graded honestly in notebook 02. Real matching has no such
# MAGIC table, which is exactly why the steward queue is the control in
# MAGIC production. Keep it out of every grant you hand to demo users.

# COMMAND ----------

try:
    spark.sql(f"REVOKE ALL PRIVILEGES ON SCHEMA `{catalog}`.demo_eval "
              f"FROM `account users`")
    print("Revoked broad access to demo_eval.")
except Exception as exc:
    # A revoke with nothing to revoke is fine; anything else is worth seeing.
    print(f"Could not revoke on demo_eval (check this yourself): {exc}")

print("Next: run 01_standardize_and_score")
