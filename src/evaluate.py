"""Scoring the matcher against the synthetic ground truth.

This is the part the previous build was missing, and it is the most persuasive
panel in the demo. The generator knows which source rows came from the same
invented person, so the engine's output can be graded honestly instead of
described as "looks about right".

Metrics are pairwise, which is the standard for record linkage:

    TP  two records the engine linked, that really are one person
    FP  two records it linked, that are not
    FN  two records it should have linked, and did not

Blocking recall is reported separately because a pair that blocking never
generated can never be recovered by better scoring. Losing recall at the
blocking stage is the most expensive mistake in this kind of system, and the
only way to see it is to measure it.
"""

from __future__ import annotations

import itertools

import pandas as pd


def _pairs_from_clusters(mapping: dict[str, str]) -> set[frozenset]:
    """Every within-cluster pair, from a {record_id: cluster_id} mapping."""
    clusters: dict[str, list[str]] = {}
    for record_id, cluster_id in mapping.items():
        clusters.setdefault(cluster_id, []).append(record_id)
    pairs = set()
    for members in clusters.values():
        if len(members) < 2:
            continue
        for left, right in itertools.combinations(sorted(members), 2):
            pairs.add(frozenset((left, right)))
    return pairs


def evaluate_matching(
    party_map: pd.DataFrame,
    truth: pd.DataFrame,
    candidates: pd.DataFrame | None = None,
) -> dict:
    """Pairwise precision, recall and F1 for identity resolution."""
    if party_map.empty or truth.empty:
        return {}

    truth_scope = truth[truth["record_id"].isin(set(party_map["record_id"]))]
    predicted = _pairs_from_clusters(dict(zip(party_map["record_id"], party_map["party_id"])))
    actual = _pairs_from_clusters(
        dict(zip(truth_scope["record_id"], truth_scope["truth_identity_id"]))
    )

    tp = len(predicted & actual)
    fp = len(predicted - actual)
    fn = len(actual - predicted)

    # True negatives are every other pair in the record space. Reported for
    # completeness; at these volumes it is a very large, uninformative number.
    n = len(truth_scope)
    total_pairs = n * (n - 1) // 2
    tn = total_pairs - tp - fp - fn

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    metrics = {
        "records_evaluated": int(n),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": int(tn),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "predicted_parties": int(party_map["party_id"].nunique()),
        "actual_identities": int(truth_scope["truth_identity_id"].nunique()),
        "total_possible_pairs": int(total_pairs),
    }

    if candidates is not None and not candidates.empty:
        blocked = {
            frozenset((row["left_record_id"], row["right_record_id"]))
            for _, row in candidates.iterrows()
        }
        recoverable = len(actual & blocked)
        metrics["pairs_compared"] = len(blocked)
        metrics["blocking_recall"] = round(recoverable / len(actual), 4) if actual else 0.0
        metrics["pairs_avoided_by_blocking"] = int(total_pairs - len(blocked))
        metrics["reduction_ratio"] = round(1 - len(blocked) / total_pairs, 6) if total_pairs else 0.0

    return metrics


def evaluate_households(
    bridge: pd.DataFrame, party_map: pd.DataFrame, truth: pd.DataFrame
) -> dict:
    """How well predicted households recover the truth households.

    Measured at party level: a party's truth household is the one its source
    records came from. Disagreement among a party's own records means identity
    resolution merged two people, so those parties are reported separately.
    """
    if bridge.empty or truth.empty:
        return {}

    joined = party_map.merge(
        truth[["record_id", "truth_household_id"]], on="record_id", how="inner"
    )
    # A party whose records disagree on truth household is an over-merge.
    per_party = joined.groupby("party_id")["truth_household_id"].agg(["nunique", "first"])
    conflicted = int((per_party["nunique"] > 1).sum())

    clean = per_party[per_party["nunique"] == 1].reset_index()
    clean = clean.rename(columns={"first": "truth_household_id"})
    merged = clean.merge(bridge[["party_id", "household_id"]], on="party_id", how="inner")
    if merged.empty:
        return {"parties_evaluated": 0, "conflicted_parties": conflicted}

    predicted_pairs = _pairs_from_clusters(
        dict(zip(merged["party_id"], merged["household_id"]))
    )
    actual_pairs = _pairs_from_clusters(
        dict(zip(merged["party_id"], merged["truth_household_id"]))
    )
    tp = len(predicted_pairs & actual_pairs)
    fp = len(predicted_pairs - actual_pairs)
    fn = len(actual_pairs - predicted_pairs)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "parties_evaluated": int(len(merged)),
        "conflicted_parties": conflicted,
        "household_precision": round(precision, 4),
        "household_recall": round(recall, 4),
        "household_f1": round(f1, 4),
        "predicted_households": int(merged["household_id"].nunique()),
        "actual_households": int(merged["truth_household_id"].nunique()),
    }


def score_distribution(candidates: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    """Histogram of match scores, split by whether the pair is truly a match.

    Used by the Model Quality tab. A well separated pair of humps is the
    clearest single picture of whether the scoring works.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame()
    working = candidates.copy()
    working["bucket"] = (working["match_score"] * bins).astype(int).clip(0, bins - 1) / bins
    group_columns = ["bucket"]
    if "is_true_match" in working.columns:
        group_columns.append("is_true_match")
    return (
        working.groupby(group_columns).size().reset_index(name="pair_count")
        .sort_values("bucket")
    )


def label_candidates(candidates: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Tag each candidate pair with whether it is really the same person.

    Evaluation only. Never join this into anything a business user can read,
    or the demo stops being a demonstration of the engine.
    """
    if candidates is None or candidates.empty or truth.empty:
        return candidates
    lookup = dict(zip(truth["record_id"], truth["truth_identity_id"]))
    labelled = candidates.copy()
    labelled["is_true_match"] = [
        bool(
            lookup.get(left) is not None
            and lookup.get(left) == lookup.get(right)
        )
        for left, right in zip(labelled["left_record_id"], labelled["right_record_id"])
    ]
    return labelled


def threshold_sweep(
    candidates: pd.DataFrame, truth: pd.DataFrame, steps: int = 19
) -> pd.DataFrame:
    """Precision and recall at a range of auto-match thresholds.

    This is what powers the threshold slider: it shows the client the tradeoff
    they are actually buying when they ask for "fewer false matches".
    """
    if candidates is None or candidates.empty or truth.empty:
        return pd.DataFrame()
    labelled = label_candidates(candidates, truth)
    lookup = dict(zip(truth["record_id"], truth["truth_identity_id"]))
    scope = {r for r in truth["record_id"]}
    actual_total = len(_pairs_from_clusters(
        {r: lookup[r] for r in scope if r in lookup}
    ))

    rows = []
    for step in range(steps + 1):
        threshold = round(0.50 + step * (0.49 / steps), 3)
        linked = labelled[labelled["match_score"] >= threshold]
        tp = int(linked["is_true_match"].sum())
        fp = int((~linked["is_true_match"]).sum())
        fn = actual_total - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / actual_total if actual_total else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rows.append({
            "threshold": threshold,
            "linked_pairs": len(linked),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        })
    return pd.DataFrame(rows)
