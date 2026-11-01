# Eastern Bank · Enterprise Householding POC

A working proof of concept for the Householding Scope Document: one household
view across core banking, the Elan card platform and CRM, with a human steward
in control of every uncertain match.

Everything here is synthetic. No real customer, account or tax data is used.

```
python scripts/run_pipeline.py --reset      # build the data (about 10 seconds)
streamlit run app/app.py                    # open the app
```

---

## What this proves

| Scope document requirement | Where it is demonstrated |
|---|---|
| Single accurate household view | Household 360 tab, Gold star schema |
| Household-level analytics, balances, product holdings | Executive summary tab, `gold.fact_household_summary` |
| Cross-sell and segmentation | Executive summary, cross-sell panel |
| Consumer and business connections | Super households, `gold.dim_super_household` |
| Executive reporting | Executive summary tab, Power BI recipe below |
| Aggregate core, card, third-party and analytics feeds | `bronze` schema, four source feeds |
| Standard and super households | `dim_household`, `dim_super_household` |
| Configurable matching logic | `src/config.py` thresholds and feature weights |
| Fuzzy matching and standardization | `src/textmatch.py`, `src/standardize.py` |
| Hierarchical relationships | party → household → super household |
| Manual override for governance | Match stewardship and Governance tabs |
| Monthly refresh, full and incremental | `notebooks/03_refresh_demo.py` |
| NPI, RBAC, audit | Governance tab, append-only decision log, column masking |

---

## Results on the shipped sample

200 synthetic people, rendered as 415 customer rows across three systems.

| Measure | Value | What it means |
|---|---|---|
| Precision | 100% | Every link the engine made is correct |
| Recall | 84% | It found 84% of the links that exist; the steward queue closes the rest |
| F1 | 0.913 | |
| Blocking recall | 100% | No true pair was lost to make the problem tractable |
| Comparisons avoided | 99.65% | 298 pairs scored instead of 86,320 |
| Source rows → households | 415 → 123 | 70% fewer entities to manage |

The recall figure is the honest and useful one. Automation gets to 84%, and the
remaining cases are exactly the ambiguous pairs a bank wants a person to look
at. That is the argument for the stewardship queue, not a weakness to hide.

---

## How it is built

```
Bronze                Silver              MDM                    Gold
──────                ──────              ───                    ────
core_customer    ┐                   ┌─ match_candidate     dim_party
card_customer    ├─→ customer_record ┤  steward_decision    dim_household
crm_contact      ┘   (standardized,  │  household_override  dim_super_household
core_account          blocking keys) └─ refresh_run         dim_account
card_account                                                dim_business
account_party_relationship                                  bridge_household_party
business                                                    bridge_super_household_member
party_business_relationship                                 bridge_party_account
demographic_enrichment                                      bridge_party_source_record
                                                            fact_account_balance
demo_eval                                                   fact_household_summary
──────────                                                  fact_party_relationship
ground_truth_identity  (evaluation only, never granted)     fact_household_business_link
                                                            fact_source_refresh
                                                            fact_match_quality
```

### The four stages

**0 · Generate.** Seeded synthetic sources with deliberate, realistic mess:
nicknames, keying typos, abbreviated addresses, maiden names, missing tax ids
and birth dates, reformatted phone numbers. Every row records which invented
person produced it, which is the only way to grade the engine honestly.

**1 · Standardize and score.** Conform three extracts into one Silver record,
then block, compare and score. Six blocking keys decide which pairs are worth
comparing at all. Each surviving pair gets a graded feature vector and a
weighted score, cut into three bands.

**2 · Resolve and publish.** Accepted pairs cluster into parties by union-find,
so accepting one pair can merge three records transitively. Parties group into
households by address policy, with steward overrides on top. Households and
businesses connect into super households. Gold is published and the matching is
scored against the truth table.

**3 · Refresh.** The monthly cycle, with every steward decision and override
carried through.

### Three design decisions worth defending

**Blocking is the design, not an optimisation.** 415 records is 86,320 possible
pairs. Eastern Bank's stated 570,000 customers is 162 *billion*. Blocking is
what makes the problem finite, and blocking recall is measured separately
because recall lost there can never be recovered by better scoring.

**Missing evidence is not conflicting evidence.** A record with no tax id
scores as "no evidence on tax id" and its weight is redistributed. A record
with a *different* tax id scores zero. Treating those the same is the most
common way a householding engine quietly loses recall on CRM data.

**Overrides are anchored to source records, never to party ids.** Party ids are
regenerated every time identity resolution runs. An override pinned to a party
id would silently attach to the wrong person after the next refresh.

---

## The app

| Tab | What it answers |
|---|---|
| **Executive summary** | What did householding change, and what is it worth |
| **Household 360** | Show me one household completely |
| **Match stewardship** | Here is an uncertain pair; you decide |
| **Model quality** | Can I trust this, and what does the threshold cost me |
| **Governance and refresh** | Who changed what, and is the data current |

Accepting a match in the local app re-resolves identities and republishes Gold
in process, so the household view updates on screen immediately. On Databricks
the app records the decision and triggers the publish Job instead, because
published tables belong to the pipeline, not to the app.

A **Run connection check** button in the sidebar reports, row by row, whether
each setting is present and each required table is readable. Run it before any
demo on Databricks; it turns "the app does not work" into a named cause.

Eastern Bank palette throughout: Midnight Blue `#003366`, Cerulean `#009CDE`,
Blaze Orange `#FF5F00`. Orange is reserved for things needing a human decision.

---

## Layout

```
app.yaml                     Databricks Apps entry point (project root, on purpose)
requirements.txt
src/
  config.py                  thresholds, weights, palette, table map
  textmatch.py               Jaro-Winkler, Soundex, nicknames, normalization
  generate_data.py           synthetic sources plus ground truth
  standardize.py             Bronze to Silver
  matching.py                blocking, comparison, scoring, decision precedence
  households.py              parties, households, super households, Gold
  evaluate.py                precision, recall, F1, threshold sweep
  datastore.py               parquet / Spark / DBSQL behind one interface
  pipeline.py                the four stages
notebooks/
  00_generate_bronze.py
  01_standardize_and_score.py
  02_apply_decisions_and_publish.py
  03_refresh_demo.py
  04_reset_demo.py
app/
  app.py                     the five tabs
  theme.py                   Eastern Bank visual identity
  data_access.py             caching, NPI masking, republish
scripts/run_pipeline.py      local end-to-end runner
tests/test_pipeline.py       27 tests
docs/
  QUICKSTART.md              run it locally
  DEPLOY_DATABRICKS.md       notebooks, App, grants, Power BI
  DEMO_SCRIPT.md             the 20-minute client walkthrough
```

The engine is pure pandas with no Spark import at module level. That is what
lets the identical code run on a laptop and inside a Databricks notebook.

---

## Tuning it

Everything a client will ask to change is in `src/config.py`:

| Setting | Default | Effect |
|---|---|---|
| `AUTO_MATCH_THRESHOLD` | 0.92 | Above this, no human sees it |
| `REVIEW_THRESHOLD` | 0.70 | Below this, the pair is discarded |
| `FEATURE_WEIGHTS` | tax id 0.30, surname 0.14, … | What counts as evidence |
| `HOUSEHOLD_RULE` | `ADDRESS_ONLY` | Or `NAME_AND_ADDRESS` to require a shared surname |
| `SOURCE_PRIORITY` | CORE, CARD, CRM | Which system wins a survivorship conflict |
| `DataSpec` | 200 people | Sample size and how much mess to inject |

The Model quality tab shows the precision and recall curve across thresholds,
so a threshold change can be argued with numbers rather than opinion.

---

## What this POC does not do

Stated plainly, because a client will ask.

- **It does not run at 570,000 customers as written.** Identity clustering
  happens on one machine. At full volume, replace union-find with GraphFrames
  connected components on Spark. Blocking and scoring already parallelise.
- **It does not do incremental loads.** The refresh regenerates a full
  snapshot. `notebooks/03_refresh_demo.py` sets out the incremental design.
- **The score is not a calibrated probability.** It is a transparent weighted
  sum, chosen so a reviewer can see exactly which evidence moved the number.
  A fitted model (Splink, or a trained classifier) is the production path once
  there is labelled data.
- **It provisions nothing.** No workspace, cluster, warehouse or PBIX is
  created. It supplies the code and the runbook.
- **The cross-sell value is a placeholder.** 8% of idle deposit balance.
  Eastern Bank substitutes its own product economics.

---

## Next

- `docs/QUICKSTART.md` to run it in two minutes
- `docs/DEMO_SCRIPT.md` before you present it
- `docs/DEPLOY_DATABRICKS.md` to put it in a workspace
