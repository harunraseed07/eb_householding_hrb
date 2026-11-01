"""Central configuration for the Eastern Bank householding POC.

Everything tunable lives here so a demo can be re-pointed or re-tuned without
touching engine code. The same values are read by the local pipeline, the
Databricks notebooks and the Streamlit app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Eastern Bank brand palette
# ---------------------------------------------------------------------------
BRAND = {
    "midnight": "#003366",   # primary dark
    "cerulean": "#009CDE",   # primary accent
    "orange": "#FF5F00",     # highlight / call to action
    "white": "#FFFFFF",
    "ink": "#13263B",
    "slate": "#5A6B7D",
    "mist": "#EEF4F9",
    "line": "#D5E2EC",
    "green": "#00875A",
    "amber": "#B8860B",
    "red": "#C0392B",
}

# Ordered categorical sequence for charts, brand first.
CHART_SEQUENCE = [
    BRAND["midnight"],
    BRAND["cerulean"],
    BRAND["orange"],
    "#4C7FA8",
    "#7FC4E8",
    "#A8651F",
    "#8299AD",
]


# ---------------------------------------------------------------------------
# Matching policy
# ---------------------------------------------------------------------------
POLICY_VERSION = "demo-policy-v1"
MODEL_VERSION = "deterministic-weighted-v1"

AUTO_MATCH_THRESHOLD = 0.92   # >= this is linked with no human review
REVIEW_THRESHOLD = 0.70       # [review, auto) goes to the steward queue
                              # < review is discarded

# Feature weights. They sum to 1.0 so the score reads as a 0-1 confidence.
# These are hand set for a demo, not fitted on labelled data.
FEATURE_WEIGHTS = {
    "tax_id": 0.30,
    "last_name": 0.14,
    "first_name": 0.12,
    "date_of_birth": 0.14,
    "address": 0.12,
    "postal_code": 0.06,
    "phone": 0.06,
    "email": 0.06,
}

# Household grouping rule. ADDRESS_ONLY puts everyone at one address together.
# NAME_AND_ADDRESS additionally requires a shared surname.
HOUSEHOLD_RULE = os.environ.get("EB_HOUSEHOLD_RULE", "ADDRESS_ONLY")

# Source precedence when the same party has conflicting addresses.
SOURCE_PRIORITY = ["CORE", "CARD", "CRM"]


# ---------------------------------------------------------------------------
# Synthetic data shape. Kept small on purpose: this is a POC.
# ---------------------------------------------------------------------------
@dataclass
class DataSpec:
    seed: int = 42
    n_identities: int = 200        # distinct real people
    n_households: int = 110        # truth households they live in
    n_businesses: int = 30
    core_coverage: float = 0.88    # share of identities present in CORE
    card_coverage: float = 0.55
    crm_coverage: float = 0.65
    as_of_date: str = "2026-10-31"
    currency: str = "USD"
    variant_rates: dict = field(default_factory=lambda: {
        "nickname": 0.35,
        "typo": 0.18,
        "address_abbrev": 0.45,
        "drop_dob": 0.20,
        "drop_tax_id": 0.30,
        "maiden_name": 0.08,
        "phone_reformat": 0.50,
        "email_variant": 0.25,
    })

    def as_dict(self) -> dict:
        return asdict(self)


DATA_SPEC = DataSpec()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# Local POC writes parquet here. Databricks notebooks write to Unity Catalog.
LOCAL_DATA_DIR = os.environ.get(
    "EB_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
DEMO_CATALOG = os.environ.get("DEMO_CATALOG", "main")

SCHEMAS = ["bronze", "silver", "mdm", "gold", "demo_eval"]

# Table name -> schema it belongs in. The datastore uses this to build the
# fully qualified Unity Catalog name, and the flat file name locally.
TABLE_SCHEMA = {
    # bronze: raw-shaped source extracts
    "core_customer": "bronze",
    "card_customer": "bronze",
    "crm_contact": "bronze",
    "core_account": "bronze",
    "card_account": "bronze",
    "account_party_relationship": "bronze",
    "business": "bronze",
    "party_business_relationship": "bronze",
    "demographic_enrichment": "bronze",
    # silver: standardized, conformed
    "customer_record": "silver",
    # mdm: match + governance workspace
    "match_candidate": "mdm",
    "steward_decision": "mdm",
    "household_override": "mdm",
    "refresh_run": "mdm",
    # gold: published, analytics ready
    "dim_party": "gold",
    "dim_household": "gold",
    "dim_super_household": "gold",
    "dim_account": "gold",
    "dim_business": "gold",
    "bridge_household_party": "gold",
    "bridge_super_household_member": "gold",
    "bridge_party_account": "gold",
    "bridge_party_source_record": "gold",
    "fact_account_balance": "gold",
    "fact_household_summary": "gold",
    "fact_household_business_link": "gold",
    "fact_party_relationship": "gold",
    "fact_source_refresh": "gold",
    "fact_match_quality": "gold",
    "party_demographic_enrichment": "gold",
    # evaluation only, never exposed to business users
    "ground_truth_identity": "demo_eval",
}

# Columns treated as Non-Public Information. The app masks these unless the
# viewer holds the unmasked role.
NPI_COLUMNS = [
    "tax_id_last4", "tax_id_hash", "date_of_birth", "phone", "email",
    "address_line_1", "address_line_2",
]
