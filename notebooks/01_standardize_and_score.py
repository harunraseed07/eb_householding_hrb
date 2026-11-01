# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Standardize and score
# MAGIC
# MAGIC Two jobs, in this order:
# MAGIC
# MAGIC 1. **Bronze to Silver.** Union CORE, CARD and CRM into one conformed
# MAGIC    `silver.customer_record`. Names get a canonical root so BOB and ROBERT
# MAGIC    compare as the same given name, addresses get one abbreviation style,
# MAGIC    phones become ten digits, and every row carries its blocking keys.
# MAGIC 2. **Candidate generation and scoring.** Six blocking keys produce the
# MAGIC    pairs worth comparing, each pair gets a graded feature vector, and the
# MAGIC    weighted score is cut into three bands.
# MAGIC
# MAGIC Blocking is the part that makes this scale. Comparing every record
# MAGIC against every other at Eastern Bank's stated 570,000 customers is
# MAGIC 162 billion comparisons. Blocking turns that into a few hundred thousand
# MAGIC without losing true pairs, and notebook 02 measures whether that claim
# MAGIC actually held.

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
dbutils.widgets.text("auto_match_threshold", str(config.AUTO_MATCH_THRESHOLD),
                     "Auto-match at or above")
dbutils.widgets.text("review_threshold", str(config.REVIEW_THRESHOLD),
                     "Steward review from")

catalog = dbutils.widgets.get("catalog").strip()
auto_threshold = float(dbutils.widgets.get("auto_match_threshold"))
review_threshold = float(dbutils.widgets.get("review_threshold"))

assert 0.0 <= review_threshold <= auto_threshold <= 1.0, \
    "Thresholds must satisfy 0 <= review <= auto <= 1"

store = SparkStore(catalog=catalog, spark=spark)
print(f"Catalog `{catalog}` · auto >= {auto_threshold} · review >= {review_threshold}")

# COMMAND ----------

# MAGIC %md ## Run

# COMMAND ----------

counts = pipeline.standardize_and_score(
    store, auto_threshold=auto_threshold, review_threshold=review_threshold
)
for name, value in counts.items():
    print(f"{name:24s} {value:>8,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What standardization did
# MAGIC
# MAGIC The same person, as three systems hold him, and as Silver now sees him.

# COMMAND ----------

display(spark.sql(f"""
    SELECT source_system, source_customer_id, full_name, first_name_root,
           last_name_soundex, address_norm, postal5, phone_digits,
           block_tax <> '' AS has_tax_key,
           block_name_postal
    FROM `{catalog}`.silver.customer_record
    WHERE record_id IN ('CORE:C10000000', 'CARD:ELAN2000000', 'CRM:CRM-70000')
    ORDER BY source_system
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## How much work blocking avoided

# COMMAND ----------

display(spark.sql(f"""
    WITH counts AS (
      SELECT (SELECT COUNT(*) FROM `{catalog}`.silver.customer_record) AS records,
             (SELECT COUNT(*) FROM `{catalog}`.mdm.match_candidate) AS compared
    )
    SELECT records,
           CAST(records * (records - 1) / 2 AS BIGINT) AS pairs_if_exhaustive,
           compared AS pairs_actually_scored,
           ROUND(100 * (1 - compared / (records * (records - 1) / 2)), 3) AS pct_avoided
    FROM counts
"""))

# COMMAND ----------

# MAGIC %md ## The band split

# COMMAND ----------

display(spark.sql(f"""
    SELECT classification,
           COUNT(*) AS pairs,
           ROUND(MIN(match_score), 3) AS min_score,
           ROUND(MAX(match_score), 3) AS max_score
    FROM `{catalog}`.mdm.match_candidate
    GROUP BY classification
    ORDER BY max_score DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## The cases a human has to settle
# MAGIC
# MAGIC These are the pairs the App's review queue will show. They are not
# MAGIC failures of the model; they are the pairs where the evidence genuinely
# MAGIC does not settle the question, and a bank wants a person to decide.

# COMMAND ----------

display(spark.sql(f"""
    SELECT c.candidate_id, c.match_score, c.reason_codes, c.blocking_rules,
           l.full_name AS left_name, l.source_system AS left_system,
           r.full_name AS right_name, r.source_system AS right_system
    FROM `{catalog}`.mdm.match_candidate c
    JOIN `{catalog}`.silver.customer_record l ON l.record_id = c.left_record_id
    JOIN `{catalog}`.silver.customer_record r ON r.record_id = c.right_record_id
    WHERE c.classification = 'STEWARD_REVIEW'
    ORDER BY c.match_score DESC
"""))

# COMMAND ----------

print("Next: run 02_apply_decisions_and_publish")
