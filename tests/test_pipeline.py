"""Tests for the behaviour the demo depends on.

These are not exhaustive unit tests. Each one guards something that, if it
broke silently, would ruin a live client session.

    pytest tests/ -v
"""

from __future__ import annotations

import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, evaluate, generate_data, households, matching, pipeline, standardize
from src import textmatch as tm
from src.datastore import LocalStore


SMALL = config.DataSpec(**{**config.DATA_SPEC.as_dict(),
                           "n_identities": 80, "n_households": 45})


@pytest.fixture(scope="module")
def built():
    """Build the whole pipeline once into a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(tmp)
        pipeline.run_all(store, SMALL)
        yield store


# ---------------------------------------------------------------------------
# String and name primitives
# ---------------------------------------------------------------------------
def test_nickname_roots_collapse_both_ways():
    assert tm.given_name_root("BOB") == "ROBERT"
    assert tm.given_name_root("ROB") == "ROBERT"
    assert tm.given_name_root("ROBERT") == "ROBERT"
    assert tm.given_name_root("SUE") == tm.given_name_root("SUSAN")


def test_unknown_name_is_its_own_root():
    assert tm.given_name_root("XQVPLT") == "XQVPLT"


def test_address_normalization_collapses_abbreviations():
    assert tm.normalize_address("47 Maple Street") == tm.normalize_address("47 MAPLE ST")
    assert tm.normalize_address("12 North Beacon Avenue") == "12 N BEACON AVE"


def test_address_key_is_empty_without_street_or_postal():
    # Thin evidence must not produce a shared key, or every record with a
    # missing address collapses into one enormous fake household.
    assert tm.address_key("", "", "SALEM", "MA", "01970") == ""
    assert tm.address_key("47 MAPLE ST", "", "SALEM", "MA", "") == ""
    assert tm.address_key("47 MAPLE ST", "", "SALEM", "MA", "01970") != ""


def test_jaro_winkler_bounds_and_ordering():
    assert tm.jaro_winkler("SULLIVAN", "SULLIVAN") == 1.0
    assert 0.0 <= tm.jaro_winkler("SULLIVAN", "ZXQWRT") < 0.6
    assert tm.jaro_winkler("SULLIVAN", "SULIVAN") > tm.jaro_winkler("SULLIVAN", "MURPHY")


def test_soundex_groups_the_typo_with_the_original():
    assert tm.soundex("SULLIVAN") == tm.soundex("SULIVAN")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def test_generation_is_deterministic():
    first = generate_data.generate_all(SMALL)["core_customer"]
    second = generate_data.generate_all(SMALL)["core_customer"]
    pd.testing.assert_frame_equal(first, second)


def test_bronze_never_leaks_truth_keys():
    tables = generate_data.generate_all(SMALL)
    for name, df in tables.items():
        if name == "ground_truth_identity":
            continue
        assert "_truth_identity_id" not in df.columns, f"{name} leaks the answer key"


def test_hero_family_is_present_and_scripted():
    tables = generate_data.generate_all(SMALL)
    core = tables["core_customer"]
    card = tables["card_customer"]
    crm = tables["crm_contact"]

    robert_core = core[core["source_customer_id"] == "C10000000"].iloc[0]
    robert_card = card[card["source_customer_id"] == "ELAN2000000"].iloc[0]
    robert_crm = crm[crm["source_customer_id"] == "CRM-70000"].iloc[0]

    assert robert_core["first_name"] == "ROBERT"
    assert robert_card["first_name"] == "BOB"
    assert robert_crm["first_name"] == "ROB"
    assert robert_crm["last_name"] == "SULIVAN", "the scripted typo is missing"
    # CORE and CARD must share a tax id so that pair auto-matches.
    assert robert_core["tax_id_hash"] == robert_card["tax_id_hash"]
    # CRM must have neither tax id nor DOB so that pair needs a human.
    assert robert_crm["tax_id_hash"] == ""
    assert robert_crm["date_of_birth"] == ""


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def test_blocking_cuts_the_comparison_space(built):
    silver = built.read("customer_record")
    candidates = built.read("match_candidate")
    exhaustive = len(silver) * (len(silver) - 1) // 2
    assert len(candidates) < exhaustive * 0.05, "blocking is not reducing enough"


def test_blocking_keeps_every_true_pair(built):
    metrics = evaluate.evaluate_matching(
        built.read("bridge_party_source_record"),
        built.read("ground_truth_identity"),
        built.read("match_candidate"),
    )
    assert metrics["blocking_recall"] == 1.0, (
        "blocking dropped a true pair; no amount of scoring can recover it"
    )


def test_no_false_links_at_the_default_threshold(built):
    metrics = evaluate.evaluate_matching(
        built.read("bridge_party_source_record"),
        built.read("ground_truth_identity"),
    )
    assert metrics["precision"] == 1.0
    assert metrics["recall"] > 0.70


def test_hero_pair_lands_in_the_review_band(built):
    candidates = built.read("match_candidate")
    hero = candidates[
        (candidates["left_record_id"] == "CRM:CRM-70000")
        | (candidates["right_record_id"] == "CRM:CRM-70000")
    ]
    assert not hero.empty, "the scripted review case was not generated"
    assert (hero["classification"] == "STEWARD_REVIEW").any(), (
        "the scripted case must need a human, or the demo has no decision moment"
    )


def test_missing_fields_are_excluded_not_penalised():
    """A blank field must not score the same as a disagreeing one."""
    base = {
        "tax_id_hash": "", "tax_id_last4": "", "last_name": "SULLIVAN",
        "last_name_soundex": "S415", "first_name": "ROBERT",
        "first_name_root": "ROBERT", "date_of_birth": "1968-04-12",
        "birth_year": "1968", "address_norm": "47 MAPLE ST", "unit_norm": "",
        "postal5": "01970", "phone_digits": "6175550142",
        "email_norm": "r@x.com",
    }
    missing = matching.compare_pair(pd.Series(base), pd.Series({**base, "phone_digits": ""}))
    conflict = matching.compare_pair(pd.Series(base),
                                     pd.Series({**base, "phone_digits": "9995550000"}))
    assert missing["phone"] is None
    assert conflict["phone"] == 0.0
    assert matching.score_features(missing) > matching.score_features(conflict)


# ---------------------------------------------------------------------------
# Decisions and precedence
# ---------------------------------------------------------------------------
def _decision(candidate_id: str, decision: str, timestamp: str) -> dict:
    return {
        "decision_id": f"d-{timestamp}", "candidate_id": candidate_id,
        "decision": decision, "decision_reason": "TEST", "steward_id": "test",
        "decision_timestamp": timestamp, "notes": "", "policy_version": "v",
        "status": "CLOSED",
    }


def test_latest_decision_wins():
    log = pd.DataFrame([
        _decision("c1", "ACCEPT_MATCH", "2026-01-01T00:00:00"),
        _decision("c1", "REJECT_MATCH", "2026-02-01T00:00:00"),
    ])
    assert matching.resolve_decisions(log)["c1"] == "REJECT_MATCH"


def test_defer_never_reverses_an_earlier_verdict():
    log = pd.DataFrame([
        _decision("c1", "ACCEPT_MATCH", "2026-01-01T00:00:00"),
        _decision("c1", "DEFER", "2026-02-01T00:00:00"),
    ])
    assert matching.resolve_decisions(log)["c1"] == "ACCEPT_MATCH"


def test_steward_rejection_overrides_an_auto_match():
    candidates = pd.DataFrame([{
        "candidate_id": "c1", "left_record_id": "A", "right_record_id": "B",
        "classification": "AUTO_MATCH", "match_score": 0.99,
    }])
    none = pd.DataFrame(columns=["candidate_id", "decision",
                                 "decision_timestamp", "decision_id"])
    assert matching.accepted_pairs(candidates, none) == [("A", "B")]

    rejected = pd.DataFrame([_decision("c1", "REJECT_MATCH", "2026-01-01T00:00:00")])
    assert matching.accepted_pairs(candidates, rejected) == []


def test_accepting_one_pair_merges_three_records_by_transitivity():
    silver = pd.DataFrame({"record_id": ["A", "B", "C", "D"]})
    party_map = households.resolve_parties(silver, [("A", "B"), ("B", "C")])
    groups = party_map.groupby("party_id")["record_id"].apply(set).tolist()
    assert {"A", "B", "C"} in groups
    assert {"D"} in groups


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------
def test_party_without_an_address_becomes_a_household_of_one():
    dim_party = pd.DataFrame([
        {"party_id": "P1", "address_key": "", "last_name": "SMITH"},
        {"party_id": "P2", "address_key": "", "last_name": "JONES"},
    ])
    party_map = pd.DataFrame([{"record_id": "R1", "party_id": "P1"},
                              {"record_id": "R2", "party_id": "P2"}])
    bridge = households.build_households(dim_party, party_map, None, "ADDRESS_ONLY")
    assert bridge["household_id"].nunique() == 2
    assert set(bridge["membership_rule"]) == {"NO_ADDRESS_EVIDENCE"}


def test_name_and_address_rule_splits_unrelated_people_at_one_address():
    dim_party = pd.DataFrame([
        {"party_id": "P1", "address_key": "K", "last_name": "SMITH"},
        {"party_id": "P2", "address_key": "K", "last_name": "JONES"},
    ])
    party_map = pd.DataFrame([{"record_id": "R1", "party_id": "P1"},
                              {"record_id": "R2", "party_id": "P2"}])
    together = households.build_households(dim_party, party_map, None, "ADDRESS_ONLY")
    apart = households.build_households(dim_party, party_map, None, "NAME_AND_ADDRESS")
    assert together["household_id"].nunique() == 1
    assert apart["household_id"].nunique() == 2


def test_split_override_separates_a_party(built):
    bridge = built.read("bridge_household_party")
    party_map = built.read("bridge_party_source_record")
    dim_party = built.read("dim_party")

    shared = bridge.groupby("household_id").size()
    multi = shared[shared > 1]
    if multi.empty:
        pytest.skip("no multi-member household in this sample")

    household_id = multi.index[0]
    party_id = bridge[bridge["household_id"] == household_id]["party_id"].iloc[0]
    record_id = party_map[party_map["party_id"] == party_id]["record_id"].iloc[0]

    override = pd.DataFrame([{
        "override_id": "o1", "subject_record_id": record_id,
        "action": "SPLIT_HOUSEHOLD", "target_record_id": "", "business_id": "",
        "reason": "test", "steward_id": "test",
        "decision_timestamp": "2026-01-01T00:00:00",
    }])
    after = households.build_households(dim_party, party_map, override, "ADDRESS_ONLY")
    moved = after[after["party_id"] == party_id].iloc[0]
    assert moved["membership_rule"] == "STEWARD_SPLIT"
    assert moved["override_id"] == "o1"


def test_override_requires_a_reason():
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(tmp)
        with pytest.raises(ValueError):
            pipeline.record_override(store, "CORE:X", "SPLIT_HOUSEHOLD", "   ")


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------
def test_joint_accounts_are_not_double_counted(built):
    bridge = built.read("bridge_household_party")
    link = built.read("bridge_party_account")
    summary = built.read("fact_household_summary")

    joined = link.merge(bridge[["party_id", "household_id"]], on="party_id")
    for household_id, group in joined.groupby("household_id"):
        expected = group["account_id"].nunique()
        row = summary[summary["household_id"] == household_id]
        if not row.empty:
            assert int(row["account_count"].iloc[0]) == expected


def test_business_links_never_merge_two_parties(built):
    """A super household may span households; it must not merge identities."""
    links = built.read("fact_household_business_link")
    party_map = built.read("bridge_party_source_record")
    if links.empty:
        pytest.skip("no business links in this sample")
    # Every party in a business link still maps to exactly one party id, and
    # no party id covers records that the match engine did not link.
    counts = party_map.groupby("record_id")["party_id"].nunique()
    assert (counts == 1).all()


def test_every_gold_table_is_published(built):
    for table in ["dim_party", "dim_household", "dim_super_household",
                  "bridge_household_party", "bridge_super_household_member",
                  "bridge_party_account", "bridge_party_source_record",
                  "dim_account", "fact_account_balance", "fact_household_summary",
                  "fact_match_quality", "fact_source_refresh"]:
        assert built.exists(table), f"{table} was not published"


def test_refresh_preserves_governance():
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(tmp)
        pipeline.run_all(store, SMALL)

        candidates = store.read("match_candidate")
        review = candidates[candidates["classification"] == "STEWARD_REVIEW"]
        if review.empty:
            pytest.skip("no review case in this sample")

        pipeline.record_decision(store, review["candidate_id"].iloc[0],
                                 "ACCEPT_MATCH", "SAME_PERSON_CONFIRMED")
        before, _ = pipeline.read_governance(store)

        pipeline.refresh(store, scenario="MONTHLY_FULL")
        after, _ = pipeline.read_governance(store)

        assert len(after) == len(before) == 1
        runs = store.read("refresh_run")
        assert runs["status"].iloc[-1] == "SUCCEEDED"


def test_reset_can_keep_governance():
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(tmp)
        pipeline.run_all(store, SMALL)
        pipeline.record_decision(store, "c1", "ACCEPT_MATCH", "TEST")

        result = pipeline.reset(store, keep_governance=True)
        assert result["decisions_kept"] == 1
        assert not store.exists("fact_household_summary")
        assert len(store.read("steward_decision")) == 1
