# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Monthly refresh
# MAGIC
# MAGIC The client asked for monthly updates with support for full and
# MAGIC incremental loads. This notebook runs the full-snapshot cycle: regenerate
# MAGIC the source extracts, re-standardize, re-score, re-resolve and republish.
# MAGIC
# MAGIC The question a bank's data governance team asks first is **what happens
# MAGIC to my corrections when the data refreshes**. The answer here is that they
# MAGIC survive, because:
# MAGIC
# MAGIC * Decisions and overrides live in `mdm`, which the refresh never rewrites.
# MAGIC * Overrides are anchored to a **source record id**, not to a party id.
# MAGIC   Party ids are regenerated every time identity resolution runs, so an
# MAGIC   override pinned to a party id would silently attach to the wrong person
# MAGIC   after a refresh.
# MAGIC
# MAGIC Every run appends to `mdm.refresh_run` with a status. A partial or failed
# MAGIC run must never be presented as a clean one, and the App shows a warning
# MAGIC banner when the latest run did not succeed.
# MAGIC
# MAGIC Schedule this as a Job with **one concurrent run**.

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
dbutils.widgets.dropdown("scenario", "MONTHLY_FULL",
                         ["MONTHLY_FULL", "CUSTOMER_MOVE"], "Scenario")
dbutils.widgets.text("seed", str(config.DATA_SPEC.seed), "Seed")

catalog = dbutils.widgets.get("catalog").strip()
scenario = dbutils.widgets.get("scenario")
# A different seed regenerates the sources with different noise, which stands
# in for a month of real-world change: people move, names get re-keyed.
seed = int(dbutils.widgets.get("seed")) + (1 if scenario == "CUSTOMER_MOVE" else 0)

store = SparkStore(catalog=catalog, spark=spark)

# COMMAND ----------

# MAGIC %md ## Governance carried into the refresh

# COMMAND ----------

decisions_before, overrides_before = pipeline.read_governance(store)
print(f"Carrying forward {len(decisions_before)} steward decisions and "
      f"{len(overrides_before)} household overrides.")

# COMMAND ----------

# MAGIC %md ## Run

# COMMAND ----------

result = pipeline.refresh(store, scenario=scenario, seed=seed)
for name, value in result.items():
    print(f"{name:28s} {value}")

# COMMAND ----------

# MAGIC %md ## Governance after the refresh: the counts must match

# COMMAND ----------

decisions_after, overrides_after = pipeline.read_governance(store)
print(f"Decisions  before {len(decisions_before):>4} · after {len(decisions_after):>4}")
print(f"Overrides  before {len(overrides_before):>4} · after {len(overrides_after):>4}")

assert len(decisions_after) >= len(decisions_before), \
    "Refresh lost steward decisions. Stop and investigate before demoing."
assert len(overrides_after) >= len(overrides_before), \
    "Refresh lost household overrides. Stop and investigate before demoing."
print("\nGovernance survived the refresh.")

# COMMAND ----------

# MAGIC %md ## Run history

# COMMAND ----------

display(spark.sql(f"""
    SELECT event_timestamp, run_id, scenario, seed, status, detail
    FROM `{catalog}`.mdm.refresh_run
    ORDER BY event_timestamp DESC
    LIMIT 20
"""))

# COMMAND ----------

# MAGIC %md ## Source freshness after this publish

# COMMAND ----------

display(spark.sql(f"""
    SELECT source_table, row_count, source_as_of, household_policy, published_at
    FROM `{catalog}`.gold.fact_source_refresh
    WHERE publish_id = (
      SELECT publish_id FROM `{catalog}`.gold.fact_source_refresh
      ORDER BY published_at DESC LIMIT 1
    )
    ORDER BY source_table
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### On incremental loads
# MAGIC
# MAGIC This POC refreshes a full snapshot, which is honest about what it does
# MAGIC and is the right shape at demo volume. For Eastern Bank's real volumes
# MAGIC the production path is:
# MAGIC
# MAGIC * Land each monthly file into Bronze with Auto Loader, partitioned by
# MAGIC   load date.
# MAGIC * Re-standardize only records whose source row changed.
# MAGIC * Re-block and re-score only pairs touching a changed record, which is a
# MAGIC   small fraction of the book in any given month.
# MAGIC * Re-resolve only the connected components those pairs sit in.
# MAGIC
# MAGIC The accepted-pairs model already supports this: identity is a function of
# MAGIC the pair set, so recomputing a subset of pairs and re-clustering the
# MAGIC affected components gives the same answer as a full rebuild.
