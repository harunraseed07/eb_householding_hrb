# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Reset the demo
# MAGIC
# MAGIC Drops the demo tables so the walkthrough can be run again from scratch.
# MAGIC Use this between dry runs and before the real session.
# MAGIC
# MAGIC **This deletes data.** It is deliberately guarded: you must type the
# MAGIC catalog name into the confirm widget, and it refuses to run against a
# MAGIC catalog whose name looks production-like.

# COMMAND ----------

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import config, pipeline
from src.datastore import SparkStore

# COMMAND ----------

dbutils.widgets.text("catalog", config.DEMO_CATALOG, "Unity Catalog to clear")
dbutils.widgets.text("confirm_catalog", "", "Retype the catalog name to confirm")
dbutils.widgets.dropdown("keep_governance", "false", ["true", "false"],
                         "Keep steward decisions and overrides")

catalog = dbutils.widgets.get("catalog").strip()
confirm = dbutils.widgets.get("confirm_catalog").strip()
keep_governance = dbutils.widgets.get("keep_governance") == "true"

# COMMAND ----------

BLOCKED = {"main", "prod", "production", "hive_metastore", "system", "samples"}

assert catalog, "Choose a catalog."
assert catalog == confirm, (
    "Confirmation does not match. Retype the catalog name in the confirm widget."
)
assert catalog.lower() not in BLOCKED, (
    f"`{catalog}` looks like a shared or production catalog. "
    "Point this demo at a catalog of its own."
)

print(f"Clearing demo tables in `{catalog}`. "
      f"Governance will be {'kept' if keep_governance else 'deleted'}.")

# COMMAND ----------

store = SparkStore(catalog=catalog, spark=spark)
result = pipeline.reset(store, keep_governance=keep_governance)
for name, value in result.items():
    print(f"{name:24s} {value}")

# COMMAND ----------

# MAGIC %md ## Confirm the schemas are empty

# COMMAND ----------

for schema in config.SCHEMAS:
    try:
        tables = spark.sql(f"SHOW TABLES IN `{catalog}`.{schema}").collect()
        print(f"{schema:12s} {len(tables)} table(s) remaining")
    except Exception as exc:
        print(f"{schema:12s} not present ({type(exc).__name__})")

# COMMAND ----------

print("Reset complete. Run 00_generate_bronze to rebuild the demo.")
