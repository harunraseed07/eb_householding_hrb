# Quickstart · run it on your laptop

Two minutes from zip to a running app. No Databricks, no cloud account, no
database. This is the fastest way to see the output and decide what to change
before anything is deployed.

## 1. Install

Python 3.10 or newer.

```bash
cd eb_householding
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The two Databricks packages in `requirements.txt` are only used when the app
runs in a workspace. They install fine locally and are never imported in local
mode.

## 2. Build the data

```bash
python scripts/run_pipeline.py --reset
```

About ten seconds. You should see roughly this:

```
== Stage 0: generate Bronze ==
   core_customer                          164
   card_customer                          113
   crm_contact                            139
   ...
== Match quality vs synthetic ground truth ==
   precision                          1.0
   recall                             0.8393
   f1                                 0.9126
   blocking_recall                    1.0
   reduction_ratio                    0.996548
```

Parquet files land in `./data`. Nothing leaves your machine.

## 3. Open the app

```bash
streamlit run app/app.py
```

Browse to `http://localhost:8501`.

---

## Changing the demo

| Goal | Command |
|---|---|
| More or fewer people | `python scripts/run_pipeline.py --reset --identities 400` |
| A different data set | `python scripts/run_pipeline.py --reset --seed 7` |
| Require a shared surname to be a household | `python scripts/run_pipeline.py --reset --rule NAME_AND_ADDRESS` |
| Tighten auto-matching | `python scripts/run_pipeline.py --reset --auto 0.97` |
| Loosen the review floor | `python scripts/run_pipeline.py --reset --review 0.60` |

Anything deeper lives in `src/config.py`: feature weights, source priority, how
much mess the generator injects.

## Running the tests

```bash
pytest tests/ -q
```

27 tests, about 25 seconds. They guard the things that would ruin a live
session: blocking keeping every true pair, a steward rejection overriding an
auto-match, defer never reversing an accept, joint accounts not being
double-counted, and governance surviving a refresh.

---

## Troubleshooting

**The app says no published data.** The pipeline has not run against `./data`.
Run step 2, or press the button the app offers.

**Numbers differ from this document.** You changed the seed or the identity
count. Both are fine; `--reset` with the defaults restores the shipped figures.

**A tab shows an empty panel instead of a chart.** The truth table is missing,
so the Model quality tab hides score separation. Re-run stage 0.

**Port 8501 is taken.** `streamlit run app/app.py --server.port 8600`.

**Reset between dry runs.** The sidebar has a "Reset demo to seed" button, or
re-run `python scripts/run_pipeline.py --reset`.
