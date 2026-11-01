# Deploy to Databricks

Follow this in order. The two steps that break most first deployments are
marked. Budget about an hour the first time.

---

## Prerequisites

| Need | Detail |
|---|---|
| Workspace | Unity Catalog enabled |
| Catalog | A **demo-only** catalog you can create schemas in. Do not use `main`. |
| Cluster | Any small cluster, DBR 13.3 LTS or newer, Python 3.10+ |
| SQL Warehouse | Serverless is fine. Needed by the App. |
| Permissions | Create schemas and tables in the demo catalog; create Apps |

No library installs are needed on the cluster. The engine is pandas and the
standard library, both already present on every Databricks runtime.

---

## 1 · Put the project in a Git folder

Push this project to your Git provider, then in Databricks:

**Workspace → Create → Git folder**, and clone it.

Keep the layout intact. The notebooks find the engine with
`os.path.join(os.getcwd(), "..")`, which resolves to the project root only if
`notebooks/` stays one level below it.

## 2 · Create the catalog

```sql
CREATE CATALOG IF NOT EXISTS eb_householding_demo;
```

Use that name throughout, or substitute your own consistently.

## 3 · Run the notebooks in order

Attach each to your cluster and run all cells.

| Notebook | Does | Takes |
|---|---|---|
| `00_generate_bronze` | Creates schemas, writes synthetic sources and the truth table | ~2 min |
| `01_standardize_and_score` | Silver plus scored match candidates | ~2 min |
| `02_apply_decisions_and_publish` | Resolves parties, builds households, publishes Gold, measures accuracy | ~3 min |

Set the `catalog` widget on each one. Notebook 00 also exposes `seed`,
`identities` and `households`; notebook 01 exposes both thresholds; notebook 02
exposes the household rule.

Check after notebook 02 that `precision` is 1.0 and `blocking_recall` is 1.0 in
the quality output. If blocking recall has dropped, the blocking keys need
attention before you demo anything.

## 4 · Create the App

**Compute → Apps → Create app → Custom**, and point it at **the project root**,
not at `app/`. `app.yaml` lives at the root on purpose, because the app imports
the engine from `src/`.

### ⚠ Step that breaks first deployments, part 1: environment variables

`app.yaml` ships with the right shape, but you must set the values:

| Variable | Value | If missing |
|---|---|---|
| `DEMO_CATALOG` | your catalog name | The app shows a setup panel and cannot build a table name |
| `EB_STORE` | `sql` | The app looks for local parquet that does not exist on an App instance |
| `DATABRICKS_WAREHOUSE_ID` | bound warehouse resource | Every panel errors |

`DATABRICKS_HOST` is supplied by the Apps runtime; do not set it, and never put
a personal access token anywhere in this project.

#### The warehouse ID vs HTTP path trap

Bind the warehouse to the App as a **resource** with the key `sql-warehouse`.
The shipped `app.yaml` references it with `valueFrom`.

The detail that catches people out: a SQL Warehouse resource injects the
warehouse **ID**, like `a1b2c3d4e5f6g7h8`, not an HTTP path. Handing that
straight to a SQL connector fails with an error that never mentions the
warehouse, so it is hard to diagnose.

This project handles it. `src/datastore.resolve_http_path()` accepts any of:

| What you give it | What it uses |
|---|---|
| `a1b2c3d4e5f6g7h8` | `/sql/1.0/warehouses/a1b2c3d4e5f6g7h8` |
| `/sql/1.0/warehouses/a1b2c3d4e5f6g7h8` | unchanged |
| `sql/1.0/warehouses/a1b2c3d4e5f6g7h8` | leading slash added |

and it reads `DATABRICKS_HTTP_PATH`, `DATABRICKS_WAREHOUSE_ID` or
`DATABRICKS_SQL_WAREHOUSE_ID`, whichever is set. So either approach works:
bind the resource, or paste the HTTP path from **SQL Warehouses → your
warehouse → Connection details** as a literal `value`.

### ⚠ Step that breaks first deployments, part 2: grants

The App runs as its **own service principal**, not as you. Your own permissions
are irrelevant to it. Find the principal on the app's detail page, then run the
last cell of `02_apply_decisions_and_publish` with the
`app_service_principal` widget filled in. It issues:

```sql
GRANT USE CATALOG ON CATALOG  eb_householding_demo       TO `<principal>`;
GRANT USE SCHEMA  ON SCHEMA   eb_householding_demo.gold   TO `<principal>`;
GRANT USE SCHEMA  ON SCHEMA   eb_householding_demo.silver TO `<principal>`;
GRANT USE SCHEMA  ON SCHEMA   eb_householding_demo.mdm    TO `<principal>`;
GRANT SELECT      ON SCHEMA   eb_householding_demo.gold   TO `<principal>`;
GRANT SELECT      ON SCHEMA   eb_householding_demo.silver TO `<principal>`;
GRANT SELECT      ON SCHEMA   eb_householding_demo.mdm    TO `<principal>`;
GRANT MODIFY      ON TABLE    eb_householding_demo.mdm.steward_decision   TO `<principal>`;
GRANT MODIFY      ON TABLE    eb_householding_demo.mdm.household_override TO `<principal>`;
```

Then grant **CAN USE** on the SQL Warehouse to the same principal.

`demo_eval` is deliberately not granted. The app detects it cannot read the
truth table and hides the score-separation and threshold panels rather than
erroring. That is the correct production posture: there is no answer key in
real life.

## 5 · Run the connection check before you trust it

Open the App and press **Run connection check** in the sidebar. It renders a
row per check in the main pane:

- whether `DEMO_CATALOG` and `EB_STORE` are set
- whether the store was created, and which backend it picked
- which warehouse path it resolved
- a read test against each of the 14 tables the app needs, with a row count
- whether `demo_eval` is readable, which decides if two Model quality charts
  appear

A failing row tells you which problem you have. A permission error says to
grant the **app's** service principal; a not-found error says to run the
notebooks against this catalog.

Do this before the client is in the room. It takes five seconds and it is the
difference between a confident demo and debugging in front of people.

## 6 · Make decisions apply without you touching a notebook

Optional, and worth doing before a client sees it.

1. Create a Job whose single task runs `notebooks/02_apply_decisions_and_publish`.
2. Grant the app's service principal **CAN MANAGE RUN** on that job.
3. Set `EB_PUBLISH_JOB_ID` on the App to the job id.

The app then records a steward decision and starts the publish job, instead of
telling you to go run a notebook. Published tables stay owned by the pipeline,
which is the right boundary.

## 7 · Schedule the monthly refresh

Create a Job running `notebooks/03_refresh_demo`, monthly, with **maximum
concurrent runs set to 1**. Two overlapping publishes would interleave writes
to Gold.

---

## Power BI

The Gold schema is a star, so there is nothing to reshape.

1. Power BI Desktop → **Get Data → Azure Databricks**.
2. Server hostname and HTTP path from the SQL Warehouse connection details.
3. Sign in with Azure AD or a personal access token.
4. Choose **DirectQuery** so the report follows every republish.
5. Load:

| Role | Table |
|---|---|
| Fact | `gold.fact_household_summary` |
| Fact | `gold.fact_account_balance` |
| Dimension | `gold.dim_household` |
| Dimension | `gold.dim_party` |
| Dimension | `gold.dim_account` |
| Bridge | `gold.bridge_household_party` |
| Bridge | `gold.bridge_party_account` |

Relationships: `dim_household[household_id]` 1-to-many to
`fact_household_summary` and to `bridge_household_party`;
`dim_party[party_id]` 1-to-many to `bridge_household_party` and
`bridge_party_account`; `dim_account[account_id]` 1-to-many to
`bridge_party_account` and `fact_account_balance`.

Measures to start with:

```
Households          = DISTINCTCOUNT(fact_household_summary[household_id])
Household Deposits  = SUM(fact_household_summary[deposit_balance])
Net Relationship    = SUM(fact_household_summary[total_relationship_balance])
Avg Products        = AVERAGE(fact_household_summary[product_count])
Cross-sell Value    = SUM(fact_household_summary[cross_sell_opportunity_value])
Cross-sell Count    = CALCULATE([Households], fact_household_summary[cross_sell_flag] = TRUE)
```

Set the balance measures to the currency format and `Avg Products` to one
decimal.

If a Databricks AI/BI dashboard is acceptable for the session, it is quicker:
build it directly on `gold.fact_household_summary` and it needs no gateway, no
desktop install and no separate refresh.

---

## Troubleshooting

**Press "Run connection check" in the sidebar first.** It names the failing
check and what to do about it, which is faster than reading this table.

| Symptom | Cause | Fix |
|---|---|---|
| App shows a setup panel instead of data | `DEMO_CATALOG` unset | Set it in `app.yaml` or the Apps UI |
| Every panel errors | No warehouse bound, or no CAN USE grant | Bind the warehouse resource; grant CAN USE |
| `Invalid HTTP path` or a connector error naming no warehouse | You pasted a warehouse ID where a path was expected | Already handled, but confirm the value reached the app: the connection check prints the resolved path |
| `Table or view not found` | Notebooks not run, or wrong catalog | Run 00, 01, 02 against the catalog in `DEMO_CATALOG` |
| `PERMISSION_DENIED` on a Gold table | Grants went to you, not the app | Re-run the grants cell with the app's service principal |
| App shows local-parquet messages in the workspace | `EB_STORE` unset | Set `EB_STORE=sql` |
| Model quality tab hides two charts | `demo_eval` not granted | Expected and correct. Grant it only if you want those panels in the demo. |
| `ModuleNotFoundError: src` | App deployed from `app/` | Redeploy from the project root |
| Decisions do not change the household view | No publish job configured | Run notebook 02, or set `EB_PUBLISH_JOB_ID` |
