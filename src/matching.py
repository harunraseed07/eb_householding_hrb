"""Candidate generation and scoring: the matching engine.

Three stages, in the order any real record linkage system runs them.

1. Blocking. Comparing 420 records every-which-way is 88,000 pairs. At the
   client's stated 570,000 customers it is 162 billion, which is why blocking
   is not an optimization, it is the design. Six keys are used; a pair only
   needs to agree on one to be considered.

2. Comparison. Each surviving pair gets a feature vector. Features are graded,
   not binary: an exact birth date is not the same evidence as a matching
   birth year, and BOB against ROBERT is a nickname hit rather than a
   near-miss string.

3. Scoring and banding. Features are combined with the weights in config and
   the result is cut into three bands: auto match, steward review, reject.

The score is a transparent weighted sum on purpose. In a demo a reviewer can
be shown exactly which evidence moved the number, which a fitted probabilistic
model cannot do without extra explanation machinery.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

import pandas as pd

from . import config
from . import textmatch as tm


BLOCK_KEYS = [
    ("block_tax", "EXACT_TAX_ID"),
    ("block_email", "EXACT_EMAIL"),
    ("block_phone", "EXACT_PHONE"),
    ("block_name_postal", "NAME_SOUNDEX_POSTAL"),
    ("block_dob_postal", "DOB_POSTAL_PREFIX"),
    ("block_initial_street", "INITIAL_NAME_STREET"),
]

# Guard rail: if any single blocking key collects more than this many records
# it is too coarse to be useful and is skipped for that value.
MAX_BLOCK_SIZE = 40


def generate_candidate_pairs(silver: pd.DataFrame) -> dict[tuple[str, str], list[str]]:
    """Return {(left_id, right_id): [blocking rules that produced it]}.

    Pairs are only formed across different source systems or within the same
    system; both are legitimate, since one system can hold duplicates too.
    """
    pairs: dict[tuple[str, str], list[str]] = {}
    for column, rule_name in BLOCK_KEYS:
        groups = silver[silver[column] != ""].groupby(column)["record_id"].apply(list)
        for key, record_ids in groups.items():
            if len(record_ids) < 2 or len(record_ids) > MAX_BLOCK_SIZE:
                continue
            for left, right in itertools.combinations(sorted(record_ids), 2):
                pairs.setdefault((left, right), []).append(rule_name)
    return pairs


def compare_pair(left: pd.Series, right: pd.Series) -> dict:
    """Graded agreement per attribute, each in [0, 1], plus null awareness.

    A feature value of None means 'no evidence either way'. Null features are
    excluded from the score and their weight is redistributed, so a record
    missing its SSN is not penalised as if the SSN disagreed.
    """
    features: dict[str, float | None] = {}

    # Tax identifier: the strongest single piece of evidence when present.
    if left["tax_id_hash"] and right["tax_id_hash"]:
        features["tax_id"] = 1.0 if left["tax_id_hash"] == right["tax_id_hash"] else 0.0
    elif left["tax_id_last4"] and right["tax_id_last4"]:
        features["tax_id"] = 0.55 if left["tax_id_last4"] == right["tax_id_last4"] else 0.0
    else:
        features["tax_id"] = None

    # Surname. Hyphenated names compare token-wise so SULLIVAN matches
    # SULLIVAN-MARTINEZ rather than scoring as a weak string similarity.
    ln_l, ln_r = left["last_name"], right["last_name"]
    if ln_l and ln_r:
        tokens_l = set(ln_l.replace("-", " ").split())
        tokens_r = set(ln_r.replace("-", " ").split())
        if ln_l == ln_r:
            features["last_name"] = 1.0
        elif tokens_l & tokens_r:
            features["last_name"] = 0.90
        elif left["last_name_soundex"] and left["last_name_soundex"] == right["last_name_soundex"]:
            features["last_name"] = max(0.80, tm.jaro_winkler(ln_l, ln_r))
        else:
            features["last_name"] = tm.jaro_winkler(ln_l, ln_r)
    else:
        features["last_name"] = None

    # Given name: exact, then nickname equivalence, then fuzzy.
    fn_l, fn_r = left["first_name"], right["first_name"]
    if fn_l and fn_r:
        if fn_l == fn_r:
            features["first_name"] = 1.0
        elif left["first_name_root"] and left["first_name_root"] == right["first_name_root"]:
            features["first_name"] = 0.92
        else:
            features["first_name"] = tm.jaro_winkler(fn_l, fn_r)
    else:
        features["first_name"] = None

    # Birth date: exact, same year, or disagree.
    if left["date_of_birth"] and right["date_of_birth"]:
        if left["date_of_birth"] == right["date_of_birth"]:
            features["date_of_birth"] = 1.0
        elif left["birth_year"] == right["birth_year"]:
            features["date_of_birth"] = 0.60
        else:
            features["date_of_birth"] = 0.0
    else:
        features["date_of_birth"] = None

    # Street address, with the unit treated separately: same building but a
    # different apartment is weaker evidence than an identical line.
    if left["address_norm"] and right["address_norm"]:
        base = 1.0 if left["address_norm"] == right["address_norm"] \
            else tm.jaro_winkler(left["address_norm"], right["address_norm"])
        if left["unit_norm"] and right["unit_norm"] and left["unit_norm"] != right["unit_norm"]:
            base *= 0.55
        features["address"] = base
    else:
        features["address"] = None

    if left["postal5"] and right["postal5"]:
        features["postal_code"] = 1.0 if left["postal5"] == right["postal5"] else 0.0
    else:
        features["postal_code"] = None

    if len(left["phone_digits"]) == 10 and len(right["phone_digits"]) == 10:
        features["phone"] = 1.0 if left["phone_digits"] == right["phone_digits"] else 0.0
    else:
        features["phone"] = None

    if left["email_norm"] and right["email_norm"]:
        if left["email_norm"] == right["email_norm"]:
            features["email"] = 1.0
        else:
            local_l = left["email_norm"].split("@")[0]
            local_r = right["email_norm"].split("@")[0]
            features["email"] = 0.70 if local_l == local_r else 0.0
    else:
        features["email"] = None

    return features


def score_features(features: dict) -> float:
    """Weighted mean over the features that have evidence."""
    weight_total = 0.0
    score_total = 0.0
    for name, value in features.items():
        if value is None:
            continue
        weight = config.FEATURE_WEIGHTS.get(name, 0.0)
        weight_total += weight
        score_total += weight * float(value)
    if weight_total == 0.0:
        return 0.0
    return round(score_total / weight_total, 4)


def reason_codes(features: dict) -> list[str]:
    """Short, human readable evidence labels for the steward UI."""
    codes = []
    labels = {
        "tax_id": "TAX_ID", "last_name": "SURNAME", "first_name": "GIVEN_NAME",
        "date_of_birth": "DOB", "address": "ADDRESS", "postal_code": "POSTAL",
        "phone": "PHONE", "email": "EMAIL",
    }
    for name, value in features.items():
        label = labels.get(name, name.upper())
        if value is None:
            codes.append(f"{label}_MISSING")
        elif value >= 0.99:
            codes.append(f"{label}_EXACT")
        elif value >= 0.85:
            codes.append(f"{label}_STRONG")
        elif value >= 0.60:
            codes.append(f"{label}_PARTIAL")
        else:
            codes.append(f"{label}_CONFLICT")
    return codes


def classify(score: float, auto: float, review: float) -> str:
    if score >= auto:
        return "AUTO_MATCH"
    if score >= review:
        return "STEWARD_REVIEW"
    return "NO_MATCH"


def build_candidates(
    silver: pd.DataFrame,
    auto_threshold: float | None = None,
    review_threshold: float | None = None,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Score every blocked pair and return the mdm.match_candidate table."""
    auto = config.AUTO_MATCH_THRESHOLD if auto_threshold is None else auto_threshold
    review = config.REVIEW_THRESHOLD if review_threshold is None else review_threshold
    if not 0.0 <= review <= auto <= 1.0:
        raise ValueError("Thresholds must satisfy 0 <= review <= auto <= 1")

    run_id = run_id or datetime.now(timezone.utc).strftime("run-%Y%m%d%H%M%S")
    policy_version = f"{config.POLICY_VERSION}|auto={auto}|review={review}"
    indexed = silver.set_index("record_id")
    pairs = generate_candidate_pairs(silver)

    rows = []
    for (left_id, right_id), rules in pairs.items():
        left, right = indexed.loc[left_id], indexed.loc[right_id]
        features = compare_pair(left, right)
        score = score_features(features)
        if score < review:
            # Below the review floor the pair is discarded, but the count is
            # kept for the quality panel so recall loss stays visible.
            rows.append({
                "candidate_id": f"{left_id}__{right_id}",
                "left_record_id": left_id, "right_record_id": right_id,
                "left_source_system": left["source_system"],
                "left_source_customer_id": left["source_customer_id"],
                "right_source_system": right["source_system"],
                "right_source_customer_id": right["source_customer_id"],
                "blocking_rules": ",".join(sorted(set(rules))),
                "match_score": score,
                "classification": "NO_MATCH",
                "reason_codes": ",".join(reason_codes(features)),
                "feature_vector_json": json.dumps(features),
                "model_version": config.MODEL_VERSION,
                "policy_version": policy_version,
                "run_id": run_id,
                "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            continue
        rows.append({
            "candidate_id": f"{left_id}__{right_id}",
            "left_record_id": left_id, "right_record_id": right_id,
            "left_source_system": left["source_system"],
            "left_source_customer_id": left["source_customer_id"],
            "right_source_system": right["source_system"],
            "right_source_customer_id": right["source_customer_id"],
            "blocking_rules": ",".join(sorted(set(rules))),
            "match_score": score,
            "classification": classify(score, auto, review),
            "reason_codes": ",".join(reason_codes(features)),
            "feature_vector_json": json.dumps(features),
            "model_version": config.MODEL_VERSION,
            "policy_version": policy_version,
            "run_id": run_id,
            "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates
    return candidates.sort_values("match_score", ascending=False).reset_index(drop=True)


def resolve_decisions(decisions: pd.DataFrame) -> dict[str, str]:
    """Collapse the append-only decision log to one verdict per candidate.

    Last write wins, and DEFER is ignored when resolving. Deferring keeps a
    case open for a human; it must never silently undo an earlier accept.
    """
    if decisions is None or decisions.empty:
        return {}
    final = decisions[decisions["decision"].isin(["ACCEPT_MATCH", "REJECT_MATCH"])].copy()
    if final.empty:
        return {}
    final = final.sort_values(["decision_timestamp", "decision_id"])
    return dict(zip(final["candidate_id"], final["decision"]))


def accepted_pairs(candidates: pd.DataFrame, decisions: pd.DataFrame) -> list[tuple[str, str]]:
    """Which record pairs are the same person, after human review.

    Automation proposes, the steward disposes. An AUTO_MATCH stands unless a
    steward rejected it; a STEWARD_REVIEW only counts once accepted.
    """
    if candidates is None or candidates.empty:
        return []
    verdicts = resolve_decisions(decisions)
    pairs = []
    for _, row in candidates.iterrows():
        verdict = verdicts.get(row["candidate_id"])
        if verdict == "REJECT_MATCH":
            continue
        if verdict == "ACCEPT_MATCH" or row["classification"] == "AUTO_MATCH":
            pairs.append((row["left_record_id"], row["right_record_id"]))
    return pairs
