"""Data loading, caching, NPI masking and republish, for the app only.

Everything the UI needs goes through here so the tabs stay about presentation.
Two details matter:

* Caching is keyed on a version counter held in session state. A steward
  decision bumps the counter, which is what makes the screen update straight
  after a save instead of serving a stale household.
* Masking happens on read, not in the warehouse. A viewer without the
  unmasked role never receives the NPI value in the browser payload.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, pipeline                        # noqa: E402
from src.datastore import get_store                     # noqa: E402


# ---------------------------------------------------------------------------
# Store and cache
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def store():
    return get_store()


def store_or_error():
    """The store, or the exception that stopped it being built.

    A misconfigured App should explain itself, not throw a traceback at a
    client. Returns (store, None) or (None, message).
    """
    try:
        return store(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def version() -> int:
    return st.session_state.get("data_version", 0)


def bump_version() -> None:
    st.session_state["data_version"] = version() + 1


@st.cache_data(show_spinner=False)
def _read(table: str, _version: int) -> pd.DataFrame:
    return store().read(table)


def load(table: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a published table, or an empty frame if the pipeline has not run."""
    try:
        return _read(table, version())
    except Exception:
        return pd.DataFrame(columns=columns or [])


def pipeline_has_run() -> bool:
    return not load("fact_household_summary").empty


# ---------------------------------------------------------------------------
# NPI masking
# ---------------------------------------------------------------------------
def _mask_value(column: str, value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return ""
    text = str(value)
    if column == "date_of_birth":
        return f"{text[:4]}-**-**" if len(text) >= 4 else "****"
    if column == "email":
        local, _, domain = text.partition("@")
        return f"{local[:1]}{'*' * 5}@{domain}" if domain else "*****"
    if column == "phone":
        digits = "".join(c for c in text if c.isdigit())
        return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"
    if column in ("tax_id_last4", "tax_id_hash"):
        return "****"
    if column in ("address_line_1", "address_line_2"):
        parts = text.split()
        return f"{parts[0]} {'*' * 6}" if parts else "*****"
    return "****"


def mask(df: pd.DataFrame, unmasked: bool) -> pd.DataFrame:
    """Redact the NPI columns listed in config unless the viewer is cleared."""
    if unmasked or df.empty:
        return df
    out = df.copy()
    for column in df.columns:
        if column in config.NPI_COLUMNS:
            out[column] = [_mask_value(column, v) for v in out[column]]
    return out


def viewer_is_cleared() -> bool:
    """Who may see unmasked NPI.

    In the POC this is a sidebar switch so the control can be demonstrated.
    In a real deployment it reads the signed-in user's group membership and
    the underlying tables carry Unity Catalog column masks, so the app cannot
    grant itself access it does not have.
    """
    return bool(st.session_state.get("npi_unmasked", False))


def current_user() -> str:
    for key in ("DATABRICKS_USER", "USER", "USERNAME"):
        value = os.environ.get(key)
        if value:
            return value
    return "demo-steward"


# ---------------------------------------------------------------------------
# Writes and republish
# ---------------------------------------------------------------------------
def save_decision(candidate_id: str, decision: str, reason: str,
                  notes: str, policy_version: str) -> str:
    return pipeline.record_decision(
        store(), candidate_id, decision, reason, notes,
        policy_version, steward_id=current_user(),
    )


def save_override(subject: str, action: str, reason: str,
                  target: str = "", business_id: str = "") -> str:
    return pipeline.record_override(
        store(), subject, action, reason, target, business_id,
        steward_id=current_user(),
    )


def can_republish_in_app() -> bool:
    """Only the local store rebuilds Gold in process.

    On Databricks the published tables belong to the pipeline, not the app, so
    the app triggers the publish Job instead of writing Gold itself.
    """
    return store().kind == "local"


def republish() -> dict:
    """Rebuild Gold so a saved decision shows up immediately."""
    result = pipeline.apply_decisions_and_publish(store())
    _read.clear()
    bump_version()
    return result


def trigger_publish_job() -> str:
    """Run the Databricks Job that executes notebook 02.

    Set EB_PUBLISH_JOB_ID on the App and grant the app's service principal
    CAN MANAGE RUN on that job. This is the pattern to use in a real
    deployment: the app records the decision, the job owns the data.
    """
    job_id = os.environ.get("EB_PUBLISH_JOB_ID", "").strip()
    if not job_id:
        raise RuntimeError("EB_PUBLISH_JOB_ID is not set on this App.")
    from databricks.sdk import WorkspaceClient
    run = WorkspaceClient().jobs.run_now(job_id=int(job_id))
    return str(run.run_id)


def reset_demo() -> dict:
    """Clear everything and rebuild from the seed. Used between dry runs."""
    local = store()
    if local.kind != "local":
        raise RuntimeError("Reset is only available against the local store.")
    local.reset_dir()
    result = pipeline.run_all(local)
    _read.clear()
    bump_version()
    return result


# ---------------------------------------------------------------------------
# Derived views used by more than one tab
# ---------------------------------------------------------------------------
def household_members() -> pd.DataFrame:
    """Household bridge joined to the party golden record and enrichment."""
    bridge = load("bridge_household_party")
    party = load("dim_party")
    enrichment = load("party_demographic_enrichment")
    if bridge.empty or party.empty:
        return pd.DataFrame()
    out = bridge.merge(party, on="party_id", how="left")
    if not enrichment.empty:
        out = out.merge(enrichment, on="party_id", how="left", suffixes=("", "_enr"))
    return out


def household_accounts() -> pd.DataFrame:
    """Accounts per household, de-duplicated so joint accounts count once."""
    bridge = load("bridge_household_party")
    link = load("bridge_party_account")
    accounts = load("dim_account")
    balances = load("fact_account_balance")
    if bridge.empty or link.empty or accounts.empty:
        return pd.DataFrame()
    out = (link.merge(bridge[["party_id", "household_id"]], on="party_id", how="inner")
              .merge(accounts, on="account_id", how="left"))
    if not balances.empty:
        out = out.merge(balances[["account_id", "balance", "as_of_date"]],
                        on="account_id", how="left")
    return out


def connection_report() -> pd.DataFrame:
    """Per-check diagnosis of why the app can or cannot see the data.

    Run this first when a deployment misbehaves. Nearly every failed Databricks
    Apps deployment of this project is one of three things: DEMO_CATALOG not
    set, no warehouse bound, or grants given to a person instead of to the
    app's service principal. This names which one.
    """
    from src.datastore import resolve_http_path

    rows = []

    def check(name: str, ok: bool | None, detail: str) -> None:
        rows.append({
            "Check": name,
            "Status": {True: "pass", False: "FAIL", None: "info"}[ok],
            "Detail": detail,
        })

    active, error = store_or_error()
    check("Store created", active is not None,
          f"{active.kind} backend" if active else error)

    backend = os.environ.get("EB_STORE", "").strip()
    check("EB_STORE", None, backend or "unset (auto-detecting)")

    # DEMO_CATALOG only matters when the data lives in Unity Catalog. Flagging
    # it in local mode would be a false alarm, and a diagnostic that cries
    # wolf is worse than no diagnostic.
    catalog = os.environ.get("DEMO_CATALOG", "").strip()
    needs_catalog = active is not None and active.kind in ("sql", "spark")
    if needs_catalog:
        check("DEMO_CATALOG", bool(catalog),
              catalog or "Not set. The app cannot build a table name without it.")
    else:
        check("DEMO_CATALOG", None,
              "not used by the local parquet backend")

    if active is None:
        return pd.DataFrame(rows)

    if active.kind == "local":
        check("Data directory", os.path.isdir(active.data_dir), active.data_dir)

    if active.kind == "sql":
        path = resolve_http_path()
        check("SQL Warehouse", bool(path),
              path or "No warehouse. Bind one as an app resource.")
        check("Workspace auth", True,
              "Supplied by the Apps runtime; no token is stored in this project.")

    # Table-by-table read check. The first failure usually names the problem:
    # a missing table means the notebooks have not run, a permission error
    # means the grants went to the wrong principal.
    required = [
        "customer_record", "match_candidate", "steward_decision",
        "household_override", "dim_party", "dim_household",
        "bridge_household_party", "bridge_party_source_record",
        "dim_account", "bridge_party_account", "fact_account_balance",
        "fact_household_summary", "fact_match_quality", "fact_source_refresh",
    ]
    for table in required:
        try:
            frame = active.read(table)
            check(active.qualified_name(table), True, f"{len(frame):,} rows")
        except Exception as exc:
            message = str(exc)
            if "PERMISSION" in message.upper() or "ACCESS DENIED" in message.upper():
                hint = "Grant SELECT to the APP's service principal, not to you."
            elif "NOT FOUND" in message.upper() or "FileNotFound" in type(exc).__name__:
                hint = "Run notebooks 00, 01 and 02 against this catalog."
            else:
                hint = message[:160]
            check(active.qualified_name(table), False, hint)

    # Optional: the evaluation table is deliberately not granted in production.
    try:
        rows_count = len(active.read("ground_truth_identity"))
        check("demo_eval.ground_truth_identity", None,
              f"readable, {rows_count:,} rows. Model quality charts will show.")
    except Exception:
        check("demo_eval.ground_truth_identity", None,
              "not readable. Expected in production; Model quality hides two "
              "charts rather than erroring.")

    return pd.DataFrame(rows)


def quality_metrics() -> dict:
    """fact_match_quality as a plain dict for the metric tiles."""
    quality = load("fact_match_quality")
    if quality.empty:
        return {}
    latest = quality.sort_values("measured_at").drop_duplicates("metric_name", keep="last")
    return dict(zip(latest["metric_name"], latest["metric_value"]))
