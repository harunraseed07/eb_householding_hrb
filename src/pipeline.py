"""The four pipeline stages, callable from a script, a notebook or the app.

Keeping the orchestration here is what stops the notebooks and the local
runner from drifting apart. A notebook cell is three lines: pick a store, call
a stage, display the result.

    stage 0   generate_bronze              synthetic source extracts
    stage 1   standardize_and_score        Silver plus the match candidates
    stage 2   apply_decisions_and_publish  Gold, after human decisions
    stage 3   refresh                      re-run 0 to 2, keeping governance
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd

from . import config, evaluate, generate_data, households, matching, standardize
from .datastore import BaseStore, get_store


BRONZE_TABLES = [
    "core_customer", "card_customer", "crm_contact",
    "core_account", "card_account", "account_party_relationship",
    "business", "party_business_relationship", "demographic_enrichment",
]

GOVERNANCE_TABLES = ["steward_decision", "household_override"]

DECISION_COLUMNS = [
    "decision_id", "candidate_id", "decision", "decision_reason", "steward_id",
    "decision_timestamp", "notes", "policy_version", "status",
]
OVERRIDE_COLUMNS = [
    "override_id", "subject_record_id", "action", "target_record_id",
    "business_id", "reason", "steward_id", "decision_timestamp",
]
REFRESH_COLUMNS = [
    "run_id", "scenario", "seed", "status", "detail", "event_timestamp",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_refresh_run(
    store: BaseStore, run_id: str, scenario: str, seed: int, status: str, detail: str = ""
) -> None:
    store.append("refresh_run", pd.DataFrame([{
        "run_id": run_id, "scenario": scenario, "seed": seed,
        "status": status, "detail": detail[:500], "event_timestamp": _now(),
    }]))


def read_governance(store: BaseStore) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Decisions and overrides survive every refresh. That is the whole point."""
    decisions = store.read_or_empty("steward_decision", DECISION_COLUMNS)
    overrides = store.read_or_empty("household_override", OVERRIDE_COLUMNS)
    return decisions, overrides


# ---------------------------------------------------------------------------
# Stage 0
# ---------------------------------------------------------------------------
def generate_bronze(
    store: BaseStore | None = None,
    spec: config.DataSpec | None = None,
    keep_governance: bool = True,
) -> dict[str, int]:
    """Write the synthetic Bronze tables and the evaluation truth table."""
    store = store or get_store()
    spec = spec or config.DATA_SPEC

    decisions, overrides = (read_governance(store) if keep_governance
                            else (pd.DataFrame(), pd.DataFrame()))

    tables = generate_data.generate_all(spec)
    for name, df in tables.items():
        store.write(name, df)

    # Create the governance tables if they are new, and never clobber them if
    # they already hold steward history.
    if decisions.empty and not store.exists("steward_decision"):
        store.write("steward_decision", pd.DataFrame(columns=DECISION_COLUMNS))
    if overrides.empty and not store.exists("household_override"):
        store.write("household_override", pd.DataFrame(columns=OVERRIDE_COLUMNS))
    if not store.exists("refresh_run"):
        store.write("refresh_run", pd.DataFrame(columns=REFRESH_COLUMNS))

    return {name: len(df) for name, df in tables.items()}


# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------
def standardize_and_score(
    store: BaseStore | None = None,
    auto_threshold: float | None = None,
    review_threshold: float | None = None,
) -> dict[str, int]:
    """Build Silver, then generate and score match candidates."""
    store = store or get_store()
    bronze = {name: store.read(name) for name in BRONZE_TABLES if store.exists(name)}

    silver = standardize.build_silver(bronze)
    store.write("customer_record", silver)

    candidates = matching.build_candidates(
        silver, auto_threshold=auto_threshold, review_threshold=review_threshold
    )
    store.write("match_candidate", candidates)

    if candidates.empty:
        return {"silver_records": len(silver), "candidates": 0}

    counts = candidates["classification"].value_counts().to_dict()
    return {
        "silver_records": len(silver),
        "candidates": len(candidates),
        "auto_match": int(counts.get("AUTO_MATCH", 0)),
        "steward_review": int(counts.get("STEWARD_REVIEW", 0)),
        "no_match": int(counts.get("NO_MATCH", 0)),
    }


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------
def apply_decisions_and_publish(
    store: BaseStore | None = None, rule: str | None = None
) -> dict[str, int]:
    """Resolve parties, build households, publish every Gold table."""
    store = store or get_store()
    publish_id = f"pub-{uuid.uuid4().hex[:12]}"

    silver = store.read("customer_record")
    candidates = store.read_or_empty("match_candidate")
    decisions, overrides = read_governance(store)
    bronze = {name: store.read(name) for name in BRONZE_TABLES if store.exists(name)}

    # --- identity ---
    pairs = matching.accepted_pairs(candidates, decisions)
    party_map = households.resolve_parties(silver, pairs)
    dim_party = households.build_dim_party(silver, party_map)

    # --- households ---
    bridge = households.build_households(dim_party, party_map, overrides, rule=rule)
    dim_household = households.build_dim_household(bridge, dim_party)

    # --- super households ---
    dim_super, bridge_super, household_business = households.build_super_households(
        bridge, party_map, bronze.get("party_business_relationship", pd.DataFrame()), overrides
    )

    # --- accounts and relationships ---
    account_tables = households.build_account_tables(bronze, party_map)

    # --- enrichment and the analytics summary ---
    enrichment_by_party = households.map_enrichment_to_party(
        bronze.get("demographic_enrichment", pd.DataFrame()), party_map
    )
    summary = households.build_household_summary(
        bridge, dim_household, account_tables["bridge_party_account"],
        account_tables["dim_account"], account_tables["fact_account_balance"],
        enrichment_by_party,
    )

    # --- match quality, scored against the evaluation truth ---
    truth = store.read_or_empty("ground_truth_identity")
    quality_rows = []
    if not truth.empty:
        identity_metrics = evaluate.evaluate_matching(party_map, truth, candidates)
        household_metrics = evaluate.evaluate_households(bridge, party_map, truth)
        for metric, value in {**identity_metrics, **household_metrics}.items():
            quality_rows.append({
                "publish_id": publish_id, "metric_name": metric,
                "metric_value": float(value), "measured_at": _now(),
            })

    # --- write Gold ---
    store.write("dim_party", dim_party)
    # The record -> party map is published because governance overrides are
    # anchored to source records and must be resolvable to a current party.
    store.write("bridge_party_source_record", party_map)
    store.write("dim_household", dim_household)
    store.write("bridge_household_party", bridge)
    store.write("dim_super_household", dim_super)
    store.write("bridge_super_household_member", bridge_super)
    store.write("fact_household_business_link", household_business)
    store.write("dim_business", bronze.get("business", pd.DataFrame()))
    store.write("dim_account", account_tables["dim_account"])
    store.write("fact_account_balance", account_tables["fact_account_balance"])
    store.write("bridge_party_account", account_tables["bridge_party_account"])
    store.write("fact_party_relationship", account_tables["fact_party_relationship"])
    store.write("party_demographic_enrichment", enrichment_by_party)
    store.write("fact_household_summary", summary)
    store.write("fact_match_quality", pd.DataFrame(quality_rows))
    store.append("fact_source_refresh", households.build_source_refresh(bronze, publish_id))

    return {
        "publish_id_written": 1,
        "parties": int(dim_party["party_id"].nunique()) if not dim_party.empty else 0,
        "households": int(dim_household["household_id"].nunique()) if not dim_household.empty else 0,
        "super_households": int(dim_super["super_household_id"].nunique()) if not dim_super.empty else 0,
        "extended_super_households": int(dim_super["is_extended"].sum()) if not dim_super.empty else 0,
        "accounts": int(len(account_tables["dim_account"])),
        "accepted_match_pairs": len(pairs),
        "steward_decisions": int(len(decisions)),
        "household_overrides": int(len(overrides)),
    }


# ---------------------------------------------------------------------------
# Stage 3 and utilities
# ---------------------------------------------------------------------------
def refresh(
    store: BaseStore | None = None,
    scenario: str = "MONTHLY_FULL",
    seed: int | None = None,
) -> dict:
    """Re-run the whole pipeline the way a monthly batch would.

    Governance is read before and reapplied after, so an accepted match and a
    manual household correction both survive the refresh. That is the behaviour
    a bank's data governance team will ask about first.
    """
    store = store or get_store()
    run_id = f"refresh-{uuid.uuid4().hex[:10]}"
    spec = config.DataSpec(**{**config.DATA_SPEC.as_dict(),
                              **({"seed": seed} if seed is not None else {})})

    decisions_before, overrides_before = read_governance(store)
    log_refresh_run(store, run_id, scenario, spec.seed, "RUNNING",
                    f"{len(decisions_before)} decisions and "
                    f"{len(overrides_before)} overrides carried forward")
    try:
        bronze_counts = generate_bronze(store, spec, keep_governance=True)
        score_counts = standardize_and_score(store)
        publish_counts = apply_decisions_and_publish(store)
        log_refresh_run(store, run_id, scenario, spec.seed, "SUCCEEDED",
                        f"{publish_counts['households']} households published")
        return {"run_id": run_id, "status": "SUCCEEDED",
                **bronze_counts, **score_counts, **publish_counts}
    except Exception as exc:                        # surfaced, never swallowed
        log_refresh_run(store, run_id, scenario, spec.seed, "FAILED", str(exc))
        raise


def run_all(
    store: BaseStore | None = None,
    spec: config.DataSpec | None = None,
    rule: str | None = None,
) -> dict:
    """Stages 0 to 2 from a clean slate. Used by the local runner and tests."""
    store = store or get_store()
    out = {}
    out.update(generate_bronze(store, spec, keep_governance=True))
    out.update(standardize_and_score(store))
    out.update(apply_decisions_and_publish(store, rule=rule))
    return out


def record_decision(
    store: BaseStore, candidate_id: str, decision: str, reason: str,
    notes: str = "", policy_version: str = "", steward_id: str = "demo-steward",
) -> str:
    """Append one steward verdict. Nothing is ever edited or deleted."""
    decision_id = str(uuid.uuid4())
    store.append("steward_decision", pd.DataFrame([{
        "decision_id": decision_id,
        "candidate_id": candidate_id,
        "decision": decision,
        "decision_reason": reason,
        "steward_id": steward_id,
        "decision_timestamp": _now(),
        "notes": (notes or "")[:1000],
        "policy_version": policy_version,
        "status": "OPEN" if decision == "DEFER" else "CLOSED",
    }]))
    return decision_id


def record_override(
    store: BaseStore, subject_record_id: str, action: str, reason: str,
    target_record_id: str = "", business_id: str = "", steward_id: str = "demo-steward",
) -> str:
    """Append one household correction, anchored to a stable source record."""
    if not (reason or "").strip():
        raise ValueError("A governance reason is required for every override.")
    override_id = str(uuid.uuid4())
    store.append("household_override", pd.DataFrame([{
        "override_id": override_id,
        "subject_record_id": subject_record_id,
        "action": action,
        "target_record_id": target_record_id,
        "business_id": business_id,
        "reason": reason.strip()[:1000],
        "steward_id": steward_id,
        "decision_timestamp": _now(),
    }]))
    return override_id


def reset(store: BaseStore | None = None, keep_governance: bool = False) -> dict[str, int]:
    """Clear the demo. Optionally keep the steward history."""
    store = store or get_store()
    decisions, overrides = (read_governance(store) if keep_governance
                            else (pd.DataFrame(), pd.DataFrame()))
    dropped = 0
    for table in list(config.TABLE_SCHEMA):
        try:
            store.drop(table)
            dropped += 1
        except Exception:
            pass
    if keep_governance:
        store.write("steward_decision", decisions if not decisions.empty
                    else pd.DataFrame(columns=DECISION_COLUMNS))
        store.write("household_override", overrides if not overrides.empty
                    else pd.DataFrame(columns=OVERRIDE_COLUMNS))
    return {"tables_dropped": dropped,
            "decisions_kept": int(len(decisions)),
            "overrides_kept": int(len(overrides))}
