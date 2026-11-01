"""Silver plus decisions to published Gold: parties, households, super households.

The order matters and is easy to get wrong:

    records -> parties        entity resolution over accepted match pairs
    parties -> households     address policy, then steward overrides
    households -> super       connected components over business ownership

A party is a person. A household is people who share an address. A super
household is households and businesses tied together by ownership. Business
links never merge two people into one party; that distinction is the thing a
bank's data governance team will probe hardest, so it is enforced in code
rather than left to convention.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# Union find, used for both identity clustering and super households
# ---------------------------------------------------------------------------
class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        # Path compression keeps repeated lookups flat.
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic merge direction so party ids are stable per run.
            lo, hi = sorted([ra, rb])
            self.parent[hi] = lo

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in self.parent:
            out.setdefault(self.find(item), []).append(item)
        return {root: sorted(members) for root, members in out.items()}


# ---------------------------------------------------------------------------
# Step 1: records -> parties
# ---------------------------------------------------------------------------
def resolve_parties(silver: pd.DataFrame, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """Cluster source records into parties. Returns record_id -> party_id.

    Clusters are transitive: if A matches B and B matches C then A, B and C
    are one party even when A and C were never compared directly.
    """
    uf = UnionFind()
    for record_id in silver["record_id"]:
        uf.add(record_id)
    for left, right in pairs:
        uf.union(left, right)

    rows = []
    for index, (_, members) in enumerate(sorted(uf.groups().items())):
        party_id = f"P{index:06d}"
        for record_id in members:
            rows.append({"record_id": record_id, "party_id": party_id})
    return pd.DataFrame(rows)


def _survivorship_pick(group: pd.DataFrame, column: str) -> str:
    """Choose one value for a party attribute.

    Rule: highest priority source wins, then the most recently loaded record,
    and a populated value always beats a blank one. This is a demo survivorship
    rule, recorded explicitly so the client can argue with it.
    """
    ranked = group.copy()
    ranked["_priority"] = ranked["source_system"].map(
        {s: i for i, s in enumerate(config.SOURCE_PRIORITY)}
    ).fillna(99)
    ranked["_has_value"] = ranked[column].astype(str).str.strip().ne("")
    ranked = ranked.sort_values(
        ["_has_value", "_priority", "record_loaded_at"], ascending=[False, True, False]
    )
    value = ranked.iloc[0][column]
    return "" if pd.isna(value) else value


def build_dim_party(silver: pd.DataFrame, party_map: pd.DataFrame) -> pd.DataFrame:
    """One golden record per party, with its contributing sources named."""
    joined = silver.merge(party_map, on="record_id", how="inner")
    attributes = [
        "first_name", "middle_initial", "last_name", "date_of_birth",
        "tax_id_last4", "address_line_1", "address_line_2", "city", "state",
        "postal_code", "phone", "email",
    ]
    rows = []
    for party_id, group in joined.groupby("party_id"):
        record = {"party_id": party_id}
        for column in attributes:
            record[column] = _survivorship_pick(group, column)
        record["full_name"] = " ".join(
            p for p in [record["first_name"], record["middle_initial"], record["last_name"]] if p
        )
        record["source_systems"] = ",".join(sorted(group["source_system"].unique()))
        record["source_record_count"] = int(len(group))
        record["source_record_ids"] = ",".join(sorted(group["record_id"]))
        # The address the household rule will actually use.
        record["address_key"] = _survivorship_pick(
            group[group["address_key"] != ""] if (group["address_key"] != "").any() else group,
            "address_key",
        )
        rows.append(record)
    return pd.DataFrame(rows).sort_values("party_id").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 2: parties -> households
# ---------------------------------------------------------------------------
def _latest_overrides(overrides: pd.DataFrame, actions: list[str]) -> pd.DataFrame:
    """Last override per subject record, for the given action family."""
    if overrides is None or overrides.empty:
        return pd.DataFrame(columns=["subject_record_id", "action", "target_record_id",
                                     "business_id", "override_id"])
    scoped = overrides[overrides["action"].isin(actions)].copy()
    if scoped.empty:
        return scoped
    scoped = scoped.sort_values(["decision_timestamp", "override_id"])
    return scoped.groupby("subject_record_id", as_index=False).last()


def build_households(
    dim_party: pd.DataFrame,
    party_map: pd.DataFrame,
    overrides: pd.DataFrame | None = None,
    rule: str | None = None,
) -> pd.DataFrame:
    """Assign each party to a household. Returns the household bridge.

    Automatic rule first, then steward overrides on top. Overrides are anchored
    to a source record id rather than a party id, because party ids are
    regenerated whenever identity clustering is re-run.
    """
    rule = rule or config.HOUSEHOLD_RULE
    record_to_party = dict(zip(party_map["record_id"], party_map["party_id"]))

    # --- automatic assignment ---
    assignment: dict[str, tuple[str, str]] = {}   # party_id -> (group_key, rule)
    for _, party in dim_party.iterrows():
        key = party["address_key"]
        if not key:
            # No usable address evidence means a household of one. Lumping
            # these together would invent a giant fake "unknown" household.
            assignment[party["party_id"]] = (f"SOLO:{party['party_id']}", "NO_ADDRESS_EVIDENCE")
            continue
        if rule == "NAME_AND_ADDRESS":
            surname = (party["last_name"] or "").replace("-", " ").split(" ")[0]
            assignment[party["party_id"]] = (f"{key}|{surname}", "NAME_AND_ADDRESS")
        else:
            assignment[party["party_id"]] = (key, "ADDRESS_ONLY")

    # --- steward overrides ---
    applied: dict[str, str] = {}   # party_id -> override_id
    household_actions = ["ASSIGN_HOUSEHOLD", "SPLIT_HOUSEHOLD", "RESET_HOUSEHOLD"]
    for _, override in _latest_overrides(overrides, household_actions).iterrows():
        subject_party = record_to_party.get(override["subject_record_id"])
        if subject_party is None or subject_party not in assignment:
            continue
        action = override["action"]
        if action == "RESET_HOUSEHOLD":
            continue   # automatic rule already stands
        if action == "SPLIT_HOUSEHOLD":
            assignment[subject_party] = (f"SPLIT:{subject_party}", "STEWARD_SPLIT")
            applied[subject_party] = override["override_id"]
        elif action == "ASSIGN_HOUSEHOLD":
            target_party = record_to_party.get(override.get("target_record_id", ""))
            if target_party and target_party in assignment:
                assignment[subject_party] = (assignment[target_party][0], "STEWARD_ASSIGN")
                applied[subject_party] = override["override_id"]

    # --- stable, readable household ids ---
    group_keys = sorted({key for key, _ in assignment.values()})
    household_ids = {key: f"HH{index:05d}" for index, key in enumerate(group_keys)}

    rows = []
    for party_id, (group_key, membership_rule) in sorted(assignment.items()):
        rows.append({
            "household_id": household_ids[group_key],
            "party_id": party_id,
            "membership_rule": membership_rule,
            "group_key": group_key,
            "override_id": applied.get(party_id, ""),
        })
    return pd.DataFrame(rows)


def build_dim_household(
    bridge: pd.DataFrame, dim_party: pd.DataFrame
) -> pd.DataFrame:
    """Household header: address, size, and a display name for the UI."""
    joined = bridge.merge(dim_party, on="party_id", how="left")
    rows = []
    for household_id, group in joined.groupby("household_id"):
        anchor = group.sort_values("party_id").iloc[0]
        surnames = sorted({(s or "").split("-")[0] for s in group["last_name"] if s})
        rows.append({
            "household_id": household_id,
            "household_name": (" / ".join(surnames[:2]) or "UNKNOWN") + " HOUSEHOLD",
            "address_line_1": anchor["address_line_1"],
            "address_line_2": anchor["address_line_2"],
            "city": anchor["city"],
            "state": anchor["state"],
            "postal_code": anchor["postal_code"],
            "member_count": int(len(group)),
            "membership_rules": ",".join(sorted(group["membership_rule"].unique())),
            "has_steward_override": bool((group["override_id"] != "").any()),
        })
    return pd.DataFrame(rows).sort_values("household_id").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 3: households + businesses -> super households
# ---------------------------------------------------------------------------
def build_super_households(
    bridge: pd.DataFrame,
    party_map: pd.DataFrame,
    business_links: pd.DataFrame,
    overrides: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Link households that share a business owner.

    Returns (dim_super_household, bridge_super_household_member,
    fact_household_business_link).
    """
    party_of_record = dict(zip(party_map["record_id"], party_map["party_id"]))
    household_of_party = dict(zip(bridge["party_id"], bridge["household_id"]))

    # Effective party -> business links, after include/exclude overrides.
    links: dict[tuple[str, str], str] = {}    # (party_id, business_id) -> evidence
    if business_links is not None and not business_links.empty:
        for _, link in business_links.iterrows():
            record_id = f"{link['source_system']}:{link['source_customer_id']}"
            party_id = party_of_record.get(record_id)
            if party_id:
                links[(party_id, link["business_id"])] = \
                    f"SOURCE_{link.get('relationship_type', 'OWNER')}"

    business_actions = ["INCLUDE_BUSINESS", "EXCLUDE_BUSINESS", "RESET_BUSINESS"]
    for _, override in _latest_overrides(overrides, business_actions).iterrows():
        party_id = party_of_record.get(override["subject_record_id"])
        business_id = override.get("business_id", "")
        if not party_id or not business_id:
            continue
        if override["action"] == "INCLUDE_BUSINESS":
            links[(party_id, business_id)] = "STEWARD_INCLUDE"
        elif override["action"] == "EXCLUDE_BUSINESS":
            links.pop((party_id, business_id), None)
        # RESET_BUSINESS leaves whatever the source evidence produced.

    link_rows = [
        {
            "household_id": household_of_party.get(party_id, ""),
            "party_id": party_id,
            "business_id": business_id,
            "link_evidence": evidence,
        }
        for (party_id, business_id), evidence in sorted(links.items())
    ]
    household_business = pd.DataFrame(
        link_rows, columns=["household_id", "party_id", "business_id", "link_evidence"]
    )

    # Connected components over the bipartite household/business graph.
    uf = UnionFind()
    for household_id in bridge["household_id"].unique():
        uf.add(f"HH:{household_id}")
    for _, row in household_business.iterrows():
        if not row["household_id"]:
            continue
        uf.union(f"HH:{row['household_id']}", f"BIZ:{row['business_id']}")

    members, headers = [], []
    for index, (_, nodes) in enumerate(sorted(uf.groups().items())):
        super_id = f"SH{index:05d}"
        household_nodes = [n[3:] for n in nodes if n.startswith("HH:")]
        business_nodes = [n[4:] for n in nodes if n.startswith("BIZ:")]
        for household_id in sorted(household_nodes):
            members.append({"super_household_id": super_id,
                            "member_type": "HOUSEHOLD", "member_id": household_id})
        for business_id in sorted(business_nodes):
            members.append({"super_household_id": super_id,
                            "member_type": "BUSINESS", "member_id": business_id})
        headers.append({
            "super_household_id": super_id,
            "standard_household_count": len(household_nodes),
            "business_count": len(business_nodes),
            "is_extended": len(household_nodes) > 1 or len(business_nodes) > 0,
        })

    return (
        pd.DataFrame(headers).sort_values("super_household_id").reset_index(drop=True),
        pd.DataFrame(members),
        household_business,
    )


# ---------------------------------------------------------------------------
# Accounts, balances and relationships
# ---------------------------------------------------------------------------
def build_account_tables(
    bronze: dict[str, pd.DataFrame], party_map: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Gold account dimension, party/account bridge, balances, joint relationships."""
    frames = [bronze[t] for t in ("core_account", "card_account")
              if t in bronze and not bronze[t].empty]
    accounts = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    dim_account = pd.DataFrame()
    fact_balance = pd.DataFrame()
    if not accounts.empty:
        dim_account = accounts[[
            "account_id", "source_system", "account_category", "product_type",
            "primary_source_customer_id", "open_date", "status",
        ]].drop_duplicates("account_id").reset_index(drop=True)
        fact_balance = accounts[[
            "account_id", "balance", "currency", "as_of_date",
        ]].drop_duplicates("account_id").reset_index(drop=True)
        if "credit_limit" in accounts.columns:
            fact_balance = fact_balance.merge(
                accounts[["account_id", "credit_limit"]].drop_duplicates("account_id"),
                on="account_id", how="left",
            )

    party_of_record = dict(zip(party_map["record_id"], party_map["party_id"]))
    relationships = bronze.get("account_party_relationship", pd.DataFrame())
    bridge_rows = []
    if not relationships.empty:
        for _, row in relationships.iterrows():
            record_id = f"{row['source_system']}:{row['source_customer_id']}"
            party_id = party_of_record.get(record_id)
            if not party_id:
                continue
            bridge_rows.append({
                "account_id": row["account_id"],
                "party_id": party_id,
                "relationship_type": row["relationship_type"],
                "source_record_id": record_id,
            })
    bridge_party_account = pd.DataFrame(
        bridge_rows, columns=["account_id", "party_id", "relationship_type", "source_record_id"]
    ).drop_duplicates(["account_id", "party_id"])

    # Joint holding is a financial relationship between two distinct parties.
    # It is evidence about people, not evidence that they are the same person.
    relationship_rows = []
    if not bridge_party_account.empty:
        for account_id, group in bridge_party_account.groupby("account_id"):
            holders = sorted(group["party_id"].unique())
            if len(holders) < 2:
                continue
            for i in range(len(holders)):
                for j in range(i + 1, len(holders)):
                    relationship_rows.append({
                        "left_party_id": holders[i],
                        "right_party_id": holders[j],
                        "account_id": account_id,
                    })
    fact_relationship = pd.DataFrame(
        relationship_rows, columns=["left_party_id", "right_party_id", "account_id"]
    )
    if not fact_relationship.empty and not dim_account.empty:
        fact_relationship = fact_relationship.merge(
            dim_account[["account_id", "product_type"]], on="account_id", how="left"
        )
        fact_relationship = (
            fact_relationship.groupby(["left_party_id", "right_party_id"])
            .agg(
                shared_account_count=("account_id", "nunique"),
                shared_account_ids=("account_id", lambda s: ",".join(sorted(set(s)))),
                shared_products=("product_type", lambda s: ",".join(sorted(set(s.dropna())))),
            )
            .reset_index()
        )
        fact_relationship["relationship_type"] = "JOINT_ACCOUNT_HOLDER"

    return {
        "dim_account": dim_account,
        "fact_account_balance": fact_balance,
        "bridge_party_account": bridge_party_account,
        "fact_party_relationship": fact_relationship,
    }


def build_household_summary(
    bridge: pd.DataFrame,
    dim_household: pd.DataFrame,
    bridge_party_account: pd.DataFrame,
    dim_account: pd.DataFrame,
    fact_balance: pd.DataFrame,
    enrichment_by_party: pd.DataFrame,
) -> pd.DataFrame:
    """The analytics table the executive view and Power BI read.

    Joint accounts are counted once per household, which is the single most
    common error in hand built household reporting.
    """
    if dim_household.empty:
        return pd.DataFrame()

    accounts = bridge_party_account.merge(
        dim_account, on="account_id", how="left"
    ).merge(fact_balance[["account_id", "balance"]], on="account_id", how="left")
    accounts = accounts.merge(bridge[["party_id", "household_id"]], on="party_id", how="left")
    # One row per household/account kills the double count.
    accounts = accounts.drop_duplicates(["household_id", "account_id"])

    rows = []
    for _, household in dim_household.iterrows():
        household_id = household["household_id"]
        held = accounts[accounts["household_id"] == household_id]
        deposits = held[held["account_category"] == "DEPOSIT"]["balance"].sum()
        loans = held[held["account_category"] == "LOAN"]["balance"].sum()
        cards = held[held["account_category"] == "CARD"]["balance"].sum()
        products = sorted(held["product_type"].dropna().unique())
        categories = sorted(held["account_category"].dropna().unique())

        members = bridge[bridge["household_id"] == household_id]["party_id"]
        segment, engagement, action = "", 0.0, ""
        if not enrichment_by_party.empty:
            member_enrichment = enrichment_by_party[
                enrichment_by_party["party_id"].isin(members)
            ]
            if not member_enrichment.empty:
                segment = member_enrichment["relationship_segment"].mode().iloc[0] \
                    if member_enrichment["relationship_segment"].notna().any() else ""
                engagement = round(float(member_enrichment["digital_engagement_score"].mean()), 1)
                if member_enrichment["next_best_action"].notna().any():
                    action = member_enrichment["next_best_action"].mode().iloc[0]

        rows.append({
            "household_id": household_id,
            "household_name": household["household_name"],
            "city": household["city"],
            "state": household["state"],
            "postal_code": household["postal_code"],
            "member_count": household["member_count"],
            "account_count": int(held["account_id"].nunique()),
            "product_count": len(products),
            "product_types": ",".join(products),
            "account_categories": ",".join(categories),
            "deposit_balance": round(float(deposits), 2),
            "loan_balance": round(float(loans), 2),
            "card_balance": round(float(cards), 2),
            "total_relationship_balance": round(float(deposits + loans + cards), 2),
            "deposit_only": bool(categories == ["DEPOSIT"]),
            "relationship_segment": segment,
            "digital_engagement_score": engagement,
            "next_best_action": action,
            "has_steward_override": household["has_steward_override"],
        })

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    # A simple, explainable cross-sell flag: meaningful money on deposit but no
    # lending and no card relationship. Deliberately a rule a banker can argue
    # with on the spot, not a black box score.
    summary["cross_sell_flag"] = (
        summary["deposit_only"] & (summary["deposit_balance"] >= 50000)
    )
    summary["cross_sell_reason"] = summary.apply(
        lambda r: ("Deposit balance with no lending or card relationship"
                   if r["cross_sell_flag"] else ""), axis=1
    )
    # Indicative annual value: 8% of idle deposit placed into a lending or card
    # product. A placeholder assumption the client replaces with their own.
    summary["cross_sell_opportunity_value"] = summary.apply(
        lambda r: round(r["deposit_balance"] * 0.08, 2) if r["cross_sell_flag"] else 0.0, axis=1
    )
    return summary.sort_values("total_relationship_balance", ascending=False).reset_index(drop=True)


def map_enrichment_to_party(
    enrichment: pd.DataFrame, party_map: pd.DataFrame
) -> pd.DataFrame:
    """Attach purchased demographics to a resolved party.

    The join goes through the source customer id, after matching. Demographics
    describe a party; they are never allowed to decide who a party is.
    """
    if enrichment is None or enrichment.empty:
        return pd.DataFrame()
    enriched = enrichment.copy()
    enriched["record_id"] = (
        enriched["source_system"] + ":" + enriched["source_customer_id"]
    )
    joined = enriched.merge(party_map, on="record_id", how="inner")
    keep = [
        "party_id", "provider", "age_band", "income_band", "homeowner_flag",
        "relationship_segment", "digital_engagement_score", "next_best_action", "as_of_date",
    ]
    return joined[keep].drop_duplicates("party_id").reset_index(drop=True)


def build_source_refresh(bronze: dict[str, pd.DataFrame], publish_id: str) -> pd.DataFrame:
    """Row counts and freshness per source, appended at every publish."""
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for table in ["core_customer", "card_customer", "crm_contact", "core_account",
                  "card_account", "business", "demographic_enrichment"]:
        df = bronze.get(table)
        if df is None:
            continue
        as_of = ""
        for column in ("record_loaded_at", "as_of_date"):
            if column in df.columns and len(df):
                as_of = str(df[column].max())
                break
        rows.append({
            "publish_id": publish_id,
            "source_table": table,
            "row_count": int(len(df)),
            "source_as_of": as_of,
            "household_policy": config.HOUSEHOLD_RULE,
            "published_at": published_at,
        })
    return pd.DataFrame(rows)
