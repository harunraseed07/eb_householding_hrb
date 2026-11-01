"""Eastern Bank Householding POC: the stewardship and analytics app.

Five tabs, each one answering a section of the client's scope document:

    Executive summary   household-level analytics, balances, product holdings
    Household 360       the single accurate household view
    Match stewardship   configurable matching plus manual override
    Model quality       is the matching trustworthy, and at what threshold
    Governance          NPI handling, audit trail, refresh

Runs unchanged against local parquet or against Unity Catalog. Synthetic data
only. Nothing in this app is derived from real customers.
"""

from __future__ import annotations

import json
import os
import sys

# The engine lives one level up. Streamlit puts this file's folder on the path,
# not the project root, so add it before importing src.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data_access as da
import theme
from src import config, evaluate


st.set_page_config(
    page_title="Eastern Bank Householding",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject()


def money(value: float, decimals: int = 0) -> str:
    try:
        return f"${float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "$0"


def compact_money(value: float) -> str:
    value = float(value or 0)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            return f"${value / limit:,.1f}{suffix}"
    return f"${value:,.0f}"


# ===========================================================================
# Sidebar
# ===========================================================================
with st.sidebar:
    st.markdown(f"### <span style='color:{theme.MIDNIGHT}'>Demo controls</span>",
                unsafe_allow_html=True)

    active_store, store_error = da.store_or_error()
    backend = active_store.kind if active_store else "none"
    st.caption(
        {"local": "Reading local parquet (`./data`)",
         "spark": "Reading Unity Catalog through Spark",
         "sql": f"Reading Unity Catalog `{config.DEMO_CATALOG}` through DBSQL",
         "none": "Not connected to any data store"}[backend]
    )

    # The diagnostic that answers "why can the app not see anything". Always
    # available, because the moment you need it is the moment the app is
    # broken and you do not want to go editing code to find out why. The
    # result renders in the main area; the sidebar is far too narrow for it.
    if st.button("Run connection check", use_container_width=True):
        st.session_state["show_diagnostics"] = True

    st.divider()
    st.markdown("**Data protection**")
    st.toggle(
        "Show unmasked NPI",
        key="npi_unmasked",
        help="Off, every viewer sees masked birth dates, tax digits, phone, "
             "email and street address. This mirrors a role check; in a real "
             "deployment Unity Catalog column masks enforce it in the warehouse.",
    )
    st.caption(f"Signed in as `{da.current_user()}`")

    st.divider()
    st.markdown("**Householding policy**")
    st.caption(f"Rule in force: `{config.HOUSEHOLD_RULE}`")
    st.caption(
        f"Auto-match at or above **{config.AUTO_MATCH_THRESHOLD:.2f}**, "
        f"steward review from **{config.REVIEW_THRESHOLD:.2f}**."
    )

    if backend == "local":
        st.divider()
        st.markdown("**Rehearsal**")
        if st.button("Reset demo to seed", use_container_width=True):
            with st.spinner("Rebuilding from the seed..."):
                da.reset_demo()
            st.success("Demo reset.")
            st.rerun()
        if st.button("Run monthly refresh", use_container_width=True,
                     help="Re-runs the whole pipeline the way a monthly batch "
                          "would, carrying every steward decision forward."):
            with st.spinner("Running refresh..."):
                try:
                    from src import pipeline
                    result = pipeline.refresh(da.store())
                    da.republish()
                    st.success(f"Refresh {result['status']}: "
                               f"{result['households']} households published.")
                except Exception as exc:
                    st.error(f"Refresh failed: {exc}")
            st.rerun()

    st.divider()
    st.caption("Synthetic demonstration data. No real customer, account or "
               "tax information is present in this application.")


# ===========================================================================
# Masthead and readiness gate
# ===========================================================================
theme.masthead(
    "Eastern Bank &nbsp;·&nbsp; Enterprise Householding",
    "A single household view across core banking, the Elan card platform and CRM, "
    "with human stewardship over every uncertain match.",
)

if st.session_state.get("show_diagnostics") and not store_error:
    with st.expander("Connection check", expanded=True):
        report = da.connection_report()
        failures = int((report["Status"] == "FAIL").sum())
        if failures:
            theme.band(f"<b>{failures} check(s) failed.</b> The Detail column "
                       "says what to fix.", "warn")
        else:
            theme.band("<b>All checks passed.</b> Every table the app needs is "
                       "readable from this environment.", "ok")
        st.dataframe(report, use_container_width=True, hide_index=True)
        if st.button("Hide check"):
            st.session_state["show_diagnostics"] = False
            st.rerun()

if store_error:
    theme.band(
        "<b>The app cannot reach a data store.</b> Open <b>Connection check</b> "
        "in the sidebar: it names which setting is missing.", "warn",
    )
    st.code(store_error, language="text")
    st.markdown(
        "On Databricks Apps the usual causes, in order of likelihood:\n\n"
        "1. `DEMO_CATALOG` is not set in `app.yaml` or the Apps UI.\n"
        "2. No SQL Warehouse is bound to the App as a resource.\n"
        "3. `EB_STORE` is not set to `sql`, so the app looked for local "
        "parquet that does not exist on an App instance.\n\n"
        "See `docs/DEPLOY_DATABRICKS.md`."
    )
    st.stop()

if not da.pipeline_has_run():
    theme.band(
        "<b>No published data yet.</b> The app is connected but the pipeline has "
        "not been run against this store.", "warn",
    )
    st.markdown("")
    if da.store().kind == "local":
        st.markdown(
            "Run the pipeline once, then reload this page:\n\n"
            "```bash\npython scripts/run_pipeline.py --reset\n```"
        )
        if st.button("Build the demo data now", type="primary"):
            with st.spinner("Generating, matching and publishing..."):
                da.reset_demo()
            st.rerun()
    else:
        st.markdown(
            "Run the Databricks notebooks in order against "
            f"catalog `{config.DEMO_CATALOG}`:\n\n"
            "1. `notebooks/00_generate_bronze`\n"
            "2. `notebooks/01_standardize_and_score`\n"
            "3. `notebooks/02_apply_decisions_and_publish`\n\n"
            "Then confirm the App's service principal holds `USE CATALOG`, "
            "`USE SCHEMA` and `SELECT` on the demo schemas, plus `CAN USE` on "
            "the SQL Warehouse."
        )
    st.stop()


# ---------------------------------------------------------------------------
# Shared frames
# ---------------------------------------------------------------------------
summary = da.load("fact_household_summary")
silver = da.load("customer_record")
candidates = da.load("match_candidate")
decisions = da.load("steward_decision")
overrides = da.load("household_override")
party_map = da.load("bridge_party_source_record")
dim_party = da.load("dim_party")
truth = da.load("ground_truth_identity")
unmasked = da.viewer_is_cleared()

tab_exec, tab_360, tab_queue, tab_quality, tab_gov = st.tabs([
    "Executive summary", "Household 360", "Match stewardship",
    "Model quality", "Governance and refresh",
])


# ===========================================================================
# TAB 1 — Executive summary
# ===========================================================================
with tab_exec:
    source_records = len(silver)
    parties = len(dim_party)
    household_count = len(summary)
    collapse = (1 - household_count / source_records) * 100 if source_records else 0
    total_balance = summary["total_relationship_balance"].sum()
    deposits = summary["deposit_balance"].sum()
    avg_products = summary["product_count"].mean() if household_count else 0
    cross_sell = summary[summary["cross_sell_flag"]]

    tiles = [
        theme.kpi("Source customer records", f"{source_records:,}",
                  "CORE + Elan card + CRM", "deep"),
        theme.kpi("Resolved parties", f"{parties:,}",
                  f"{source_records - parties:,} duplicate records collapsed"),
        theme.kpi("Households", f"{household_count:,}",
                  f"{collapse:.0f}% fewer entities to manage"),
        theme.kpi("Avg products per household", f"{avg_products:.2f}",
                  "Across deposit, loan and card"),
        theme.kpi("Relationship balance under one view", compact_money(total_balance),
                  f"{compact_money(deposits)} on deposit"),
        theme.kpi("Cross-sell opportunity", compact_money(
                      cross_sell["cross_sell_opportunity_value"].sum()),
                  f"{len(cross_sell)} households flagged", "accent"),
    ]
    columns = st.columns(6, gap="small")
    for column, tile in zip(columns, tiles):
        column.markdown(tile, unsafe_allow_html=True)

    theme.section(
        "What householding changed",
        "The same book of business, counted as households instead of as rows in "
        "three systems.",
    )
    left, right = st.columns([1, 1], gap="large")

    with left:
        st.caption("**Collapse from source rows to households**")
        funnel = pd.DataFrame({
            "Stage": ["Source customer records", "Resolved parties", "Households"],
            "Count": [source_records, parties, household_count],
        })
        figure = px.bar(funnel, x="Count", y="Stage", orientation="h", text="Count")
        figure.update_traces(
            marker_color=[theme.SLATE, theme.CERULEAN, theme.MIDNIGHT],
            texttemplate="%{text:,}", textposition="outside", cliponaxis=False,
        )
        figure.update_layout(yaxis=dict(categoryorder="array",
                                        categoryarray=funnel["Stage"][::-1]))
        figure.update_xaxes(title=None, range=[0, source_records * 1.18])
        figure.update_yaxes(title=None)
        st.plotly_chart(theme.style_plot(figure, 230), use_container_width=True)

        st.caption("**Households by number of members**")
        sizes = (summary["member_count"].clip(upper=4)
                 .map({1: "1 member", 2: "2 members", 3: "3 members", 4: "4+ members"})
                 .value_counts().rename_axis("Household size").reset_index(name="Households"))
        sizes = sizes.sort_values("Household size")
        figure = px.bar(sizes, x="Household size", y="Households", text="Households")
        figure.update_traces(marker_color=theme.CERULEAN, textposition="outside",
                             cliponaxis=False)
        figure.update_xaxes(title=None)
        st.plotly_chart(theme.style_plot(figure, 250), use_container_width=True)

    with right:
        st.caption("**Product penetration across households**")
        products = (summary["product_types"].str.split(",").explode()
                    .replace("", pd.NA).dropna()
                    .value_counts().rename_axis("Product").reset_index(name="Households")
                    .head(10).sort_values("Households"))
        figure = px.bar(products, x="Households", y="Product", orientation="h",
                        text="Households")
        figure.update_traces(marker_color=theme.MIDNIGHT, textposition="outside",
                             cliponaxis=False)
        figure.update_xaxes(title=None, range=[0, products["Households"].max() * 1.2])
        figure.update_yaxes(title=None)
        st.plotly_chart(theme.style_plot(figure, 300), use_container_width=True)

        st.caption("**Household count and deposit value, by balance band**")
        banded = summary.copy()
        banded["Band"] = pd.cut(
            banded["deposit_balance"],
            bins=[-1, 10000, 50000, 150000, 500000, float("inf")],
            labels=["< $10K", "$10K-50K", "$50K-150K", "$150K-500K", "$500K+"],
        )
        bands = (banded.groupby("Band", observed=True)
                 .agg(Households=("household_id", "count"),
                      Deposits=("deposit_balance", "sum")).reset_index())
        figure = go.Figure()
        figure.add_bar(x=bands["Band"].astype(str), y=bands["Households"],
                       name="Households", marker_color=theme.CERULEAN)
        figure.add_scatter(x=bands["Band"].astype(str), y=bands["Deposits"],
                           name="Deposits", yaxis="y2", mode="lines+markers",
                           line=dict(color=theme.ORANGE, width=2.5))
        figure.update_layout(
            yaxis2=dict(overlaying="y", side="right", showgrid=False,
                        tickprefix="$", tickformat=".2s"),
        )
        st.plotly_chart(theme.style_plot(figure, 300, legend=True),
                        use_container_width=True)

    theme.section(
        "Cross-sell opportunities this view makes visible",
        "Households holding deposits of $50,000 or more with no lending and no "
        "card relationship. Invisible when the same people are counted as "
        "separate customer rows in three systems.",
    )
    if cross_sell.empty:
        theme.band("No households meet the cross-sell rule in this data set.", "ok")
    else:
        display = cross_sell[[
            "household_name", "city", "member_count", "account_count",
            "deposit_balance", "product_types", "relationship_segment",
            "next_best_action", "cross_sell_opportunity_value",
        ]].head(25).rename(columns={
            "household_name": "Household", "city": "City",
            "member_count": "Members", "account_count": "Accounts",
            "deposit_balance": "Deposits", "product_types": "Products held",
            "relationship_segment": "Segment", "next_best_action": "Next best action",
            "cross_sell_opportunity_value": "Indicative value",
        })
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Deposits": st.column_config.NumberColumn(format="dollar"),
                "Indicative value": st.column_config.NumberColumn(format="dollar"),
            },
        )
        st.caption(
            "Indicative value is 8% of idle deposit balance, a placeholder "
            "assumption for the demo. Eastern Bank would substitute its own "
            "product economics."
        )

    theme.section("Largest household relationships")
    top = summary.head(12)[[
        "household_name", "city", "state", "member_count", "account_count",
        "deposit_balance", "loan_balance", "card_balance",
        "total_relationship_balance", "relationship_segment",
    ]].rename(columns={
        "household_name": "Household", "city": "City", "state": "ST",
        "member_count": "Members", "account_count": "Accounts",
        "deposit_balance": "Deposits", "loan_balance": "Loans",
        "card_balance": "Cards", "total_relationship_balance": "Net relationship",
        "relationship_segment": "Segment",
    })
    st.dataframe(
        top, use_container_width=True, hide_index=True,
        column_config={
            c: st.column_config.NumberColumn(format="dollar")
            for c in ("Deposits", "Loans", "Cards", "Net relationship")
        },
    )
    st.caption("Loan and card balances are shown as negative amounts so the net "
               "relationship figure is meaningful.")


# ===========================================================================
# TAB 2 — Household 360
# ===========================================================================
with tab_360:
    members = da.household_members()
    accounts = da.household_accounts()
    business_links = da.load("fact_household_business_link")
    businesses = da.load("dim_business")
    super_members = da.load("bridge_super_household_member")
    super_households = da.load("dim_super_household")
    relationships = da.load("fact_party_relationship")

    options = summary[["household_id", "household_name", "city"]].copy()
    options["label"] = (options["household_name"] + "  ·  " + options["city"]
                        + "  ·  " + options["household_id"])

    # Open on the scripted hero household so the demo always starts on the
    # narrative the client was walked through. It is found by the stable CORE
    # record id rather than by surname, because other Sullivans exist.
    hero_party = dim_party[dim_party["source_record_ids"].str.contains(
        "CORE:C10000000", na=False)]
    hero_id = ""
    if not hero_party.empty:
        hero_row = members[members["party_id"] == hero_party["party_id"].iloc[0]]
        if not hero_row.empty:
            hero_id = hero_row["household_id"].iloc[0]
    hero = options[options["household_id"] == hero_id]
    ordered = pd.concat([hero, options.drop(hero.index)]) if not hero.empty else options

    picker, _ = st.columns([2, 1])
    with picker:
        chosen = st.selectbox("Household", ordered["label"].tolist(),
                              label_visibility="collapsed")
    household_id = ordered[ordered["label"] == chosen]["household_id"].iloc[0]
    header = summary[summary["household_id"] == household_id].iloc[0]
    household_members_df = members[members["household_id"] == household_id]
    household_accounts_df = (accounts[accounts["household_id"] == household_id]
                             .drop_duplicates("account_id"))

    address = da.mask(
        household_members_df[["address_line_1", "address_line_2", "city",
                              "state", "postal_code"]].head(1), unmasked,
    ).iloc[0] if not household_members_df.empty else {}
    address_text = " ".join(str(address.get(k, "") or "") for k in
                            ("address_line_1", "address_line_2", "city",
                             "state", "postal_code"))

    st.markdown(
        f"""<div style="margin:6px 0 12px 0;">
              <span style="font-size:1.25rem;font-weight:700;color:{theme.MIDNIGHT};">
                {header['household_name']}</span>
              <span style="font-size:.82rem;color:{theme.SLATE};margin-left:12px;">
                {address_text.strip()} &nbsp;·&nbsp;
                <code>{household_id}</code></span>
            </div>""",
        unsafe_allow_html=True,
    )
    tiles = [
        theme.kpi("Members", f"{int(header['member_count'])}",
                  "Resolved people, not source rows", "deep"),
        theme.kpi("Accounts", f"{int(header['account_count'])}",
                  "Joint accounts counted once"),
        theme.kpi("Deposits", money(header["deposit_balance"]), "Core banking"),
        theme.kpi("Lending", money(header["loan_balance"]), "Core banking"),
        theme.kpi("Cards", money(header["card_balance"]), "Elan platform"),
        theme.kpi("Net relationship", money(header["total_relationship_balance"]),
                  header["relationship_segment"] or "No segment on file", "accent"),
    ]
    for column, tile in zip(st.columns(6, gap="small"), tiles):
        column.markdown(tile, unsafe_allow_html=True)

    theme.section(
        "Members",
        "One row per resolved person. The source systems column shows which "
        "systems contributed to that single identity.",
    )
    member_columns = ["party_id", "full_name", "date_of_birth", "tax_id_last4",
                      "phone", "email", "source_systems", "source_record_count",
                      "membership_rule", "age_band", "income_band",
                      "relationship_segment", "next_best_action"]
    available = [c for c in member_columns if c in household_members_df.columns]
    st.dataframe(
        da.mask(household_members_df[available], unmasked),
        use_container_width=True, hide_index=True,
        column_config={
            "party_id": "Party", "full_name": "Name",
            "date_of_birth": "Date of birth", "tax_id_last4": "Tax ID",
            "source_systems": "Source systems",
            "source_record_count": "Records", "membership_rule": "Why in household",
            "age_band": "Age band", "income_band": "Income band",
            "relationship_segment": "Segment", "next_best_action": "Next best action",
        },
    )
    if not unmasked:
        st.caption("NPI fields are masked for this viewer. Use the sidebar switch "
                   "to demonstrate the cleared-role view.")

    left, right = st.columns([3, 2], gap="large")
    with left:
        theme.section(
            "Accounts across every source",
            "Joint accounts appear once. Counting them per member is the most "
            "common error in hand-built household reporting.",
        )
        if household_accounts_df.empty:
            theme.band("No accounts are linked to this household.", "warn")
        else:
            display = household_accounts_df[[
                "account_id", "source_system", "account_category",
                "product_type", "relationship_type", "balance", "as_of_date",
            ]].sort_values(["account_category", "account_id"]).rename(columns={
                "account_id": "Account", "source_system": "Source",
                "account_category": "Category", "product_type": "Product",
                "relationship_type": "Role", "balance": "Balance",
                "as_of_date": "As of",
            })
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={"Balance": st.column_config.NumberColumn(format="dollar")},
            )

        theme.section("Source record provenance",
                      "The raw rows that collapsed into each party above.")
        household_parties = set(household_members_df["party_id"])
        provenance = (party_map[party_map["party_id"].isin(household_parties)]
                      .merge(silver, on="record_id", how="left"))
        if not provenance.empty:
            display = da.mask(provenance[[
                "party_id", "record_id", "source_system", "full_name",
                "date_of_birth", "address_line_1", "phone", "email",
            ]], unmasked).sort_values(["party_id", "record_id"]).rename(columns={
                "party_id": "Party", "record_id": "Source record",
                "source_system": "System", "full_name": "Name as held",
                "date_of_birth": "DOB", "address_line_1": "Address",
                "phone": "Phone", "email": "Email",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)

    with right:
        theme.section("Extended household",
                      "Consumer and business relationships linked by ownership.")
        own_links = business_links[business_links["household_id"] == household_id]
        if own_links.empty:
            theme.band("No business relationship is linked to this household.")
        else:
            display = own_links.merge(businesses, on="business_id", how="left")
            columns = [c for c in ["business_name", "business_type",
                                   "annual_revenue_band", "link_evidence"]
                       if c in display.columns]
            st.dataframe(
                display[columns].rename(columns={
                    "business_name": "Business", "business_type": "Entity",
                    "annual_revenue_band": "Revenue band", "link_evidence": "Evidence",
                }), use_container_width=True, hide_index=True,
            )

        if not super_members.empty:
            own_super = super_members[
                (super_members["member_type"] == "HOUSEHOLD")
                & (super_members["member_id"] == household_id)
            ]
            if not own_super.empty:
                super_id = own_super["super_household_id"].iloc[0]
                siblings = super_members[super_members["super_household_id"] == super_id]
                head = super_households[
                    super_households["super_household_id"] == super_id
                ].iloc[0]
                theme.band(
                    f"Super household <b>{super_id}</b> covers "
                    f"<b>{int(head['standard_household_count'])}</b> household(s) and "
                    f"<b>{int(head['business_count'])}</b> business(es).",
                    "ok" if head["is_extended"] else "",
                )
                labels = []
                for _, row in siblings.iterrows():
                    if row["member_type"] == "BUSINESS":
                        name = businesses[businesses["business_id"] == row["member_id"]]
                        labels.append({
                            "Member": "Business",
                            "Name": name["business_name"].iloc[0] if not name.empty
                                    else row["member_id"],
                            "Id": row["member_id"],
                        })
                    else:
                        name = summary[summary["household_id"] == row["member_id"]]
                        labels.append({
                            "Member": "Household",
                            "Name": name["household_name"].iloc[0] if not name.empty
                                    else row["member_id"],
                            "Id": row["member_id"],
                        })
                st.dataframe(pd.DataFrame(labels), use_container_width=True,
                             hide_index=True)

        theme.section("Joint account relationships",
                      "Financial relationship evidence, not an identity match.")
        if relationships.empty:
            theme.band("No joint holdings published.")
        else:
            own = relationships[
                relationships["left_party_id"].isin(household_parties)
                | relationships["right_party_id"].isin(household_parties)
            ]
            if own.empty:
                theme.band("No joint holdings for this household.")
            else:
                names = dict(zip(dim_party["party_id"], dim_party["full_name"]))
                display = own.copy()
                display["Holder A"] = display["left_party_id"].map(names)
                display["Holder B"] = display["right_party_id"].map(names)
                st.dataframe(
                    display[["Holder A", "Holder B", "shared_account_count",
                             "shared_products"]].rename(columns={
                        "shared_account_count": "Shared", "shared_products": "Products",
                    }), use_container_width=True, hide_index=True,
                )


# ===========================================================================
# TAB 3 — Match stewardship
# ===========================================================================
with tab_queue:
    from src.matching import resolve_decisions
    verdicts = resolve_decisions(decisions)


    # The readiness gate above guarantees stage 1 and 2 have both run, so
    # candidates is populated here. Stopping inside a tab would blank the
    # later tabs as well, so there is no early exit in this block.

    review_count = int((candidates["classification"] == "STEWARD_REVIEW").sum())
    open_count = int(sum(
        1 for _, row in candidates.iterrows()
        if row["classification"] == "STEWARD_REVIEW"
        and row["candidate_id"] not in verdicts
    ))
    tiles = [
        theme.kpi("Pairs compared", f"{len(candidates):,}",
                  "After blocking", "deep"),
        theme.kpi("Auto-matched", f"{int((candidates['classification'] == 'AUTO_MATCH').sum()):,}",
                  f"Score at or above {config.AUTO_MATCH_THRESHOLD:.2f}"),
        theme.kpi("Sent to review", f"{review_count:,}",
                  f"Between {config.REVIEW_THRESHOLD:.2f} and "
                  f"{config.AUTO_MATCH_THRESHOLD:.2f}"),
        theme.kpi("Open in queue", f"{open_count:,}", "Awaiting a decision", "accent"),
        theme.kpi("Decisions recorded", f"{len(decisions):,}", "Append-only log"),
    ]
    for column, tile in zip(st.columns(5, gap="small"), tiles):
        column.markdown(tile, unsafe_allow_html=True)

    theme.section("Review queue")
    scope = st.radio(
        "Scope", ["Open reviews", "All candidates"],
        horizontal=True, label_visibility="collapsed",
    )
    working = candidates.copy()
    working["latest_decision"] = working["candidate_id"].map(verdicts).fillna("")
    if scope == "Open reviews":
        working = working[(working["classification"] == "STEWARD_REVIEW")
                          & (working["latest_decision"] == "")]
    else:
        working = working[working["classification"] != "NO_MATCH"]

    # Put the scripted case first so the demo opens on it. ROB SULIVAN against
    # Robert Sullivan is the one the client has been walked up to.
    HERO_RECORD = "CRM:CRM-70000"
    working["_hero"] = (
        (working["left_record_id"] == HERO_RECORD)
        | (working["right_record_id"] == HERO_RECORD)
    )
    working = working.sort_values(
        ["_hero", "match_score"], ascending=[False, False]
    ).drop(columns="_hero")

    if working.empty:
        theme.band("<b>Queue is clear.</b> Every review case has a recorded "
                   "decision. Switch to All candidates to revisit or reverse one.", "ok")
    else:
        names = dict(zip(silver["record_id"], silver["full_name"]))
        table = working.copy()
        table["Left"] = table["left_record_id"].map(names)
        table["Right"] = table["right_record_id"].map(names)
        st.dataframe(
            table[["candidate_id", "Left", "left_record_id", "Right",
                   "right_record_id", "match_score", "classification",
                   "latest_decision"]].rename(columns={
                "candidate_id": "Candidate", "left_record_id": "Record A",
                "right_record_id": "Record B", "match_score": "Score",
                "classification": "Band", "latest_decision": "Decision",
            }).head(60),
            use_container_width=True, hide_index=True,
            column_config={"Score": st.column_config.ProgressColumn(
                format="%.3f", min_value=0.0, max_value=1.0)},
        )

        theme.section("Evidence and decision")
        labels = {
            row["candidate_id"]: (
                f"{names.get(row['left_record_id'], row['left_record_id'])}  ↔  "
                f"{names.get(row['right_record_id'], row['right_record_id'])}"
                f"   ·   {row['match_score']:.3f}"
            )
            for _, row in working.iterrows()
        }
        picked = st.selectbox(
            "Candidate", list(labels), format_func=lambda c: labels[c],
            label_visibility="collapsed",
        )
        candidate = working[working["candidate_id"] == picked].iloc[0]

        score_columns = st.columns([1, 1, 2])
        score_columns[0].metric("Match score", f"{candidate['match_score']:.1%}")
        score_columns[1].metric("Band", candidate["classification"].replace("_", " ").title())
        score_columns[2].caption(
            f"Blocked by `{candidate['blocking_rules']}`  ·  "
            f"model `{candidate['model_version']}`  ·  "
            f"policy `{candidate['policy_version']}`"
        )

        st.markdown(
            "".join(theme.chip(c) for c in str(candidate["reason_codes"]).split(",") if c),
            unsafe_allow_html=True,
        )

        # ---- side by side source records, with disagreements in orange ----
        fields = [
            ("full_name", "Name"), ("date_of_birth", "Date of birth"),
            ("tax_id_last4", "Tax ID last 4"), ("address_line_1", "Address"),
            ("address_line_2", "Unit"), ("city", "City"), ("state", "State"),
            ("postal_code", "Postal"), ("phone", "Phone"), ("email", "Email"),
        ]
        pair = silver[silver["record_id"].isin(
            [candidate["left_record_id"], candidate["right_record_id"]]
        )].set_index("record_id")
        display_pair = da.mask(pair.reset_index(), unmasked).set_index("record_id")

        def record_card(record_id: str, other_id: str) -> str:
            row = display_pair.loc[record_id]
            other = display_pair.loc[other_id]
            cells = []
            for key, label in fields:
                value = str(row.get(key, "") or "")
                compare = str(other.get(key, "") or "")
                if not value:
                    css, shown = "none", "not provided"
                elif value == compare:
                    css, shown = "same", value
                else:
                    css, shown = "diff", value
                cells.append(f'<tr><td class="k">{label}</td>'
                             f'<td class="v {css}">{shown}</td></tr>')
            return (f'<div class="eb-rec"><span class="sys">{row["source_system"]}'
                    f' · {record_id}</span><table>{"".join(cells)}</table></div>')

        card_columns = st.columns(2, gap="medium")
        card_columns[0].markdown(
            record_card(candidate["left_record_id"], candidate["right_record_id"]),
            unsafe_allow_html=True,
        )
        card_columns[1].markdown(
            record_card(candidate["right_record_id"], candidate["left_record_id"]),
            unsafe_allow_html=True,
        )
        st.caption("Green means the two records agree, orange means they differ, "
                   "grey italic means one system has no value.")

        with st.expander("Feature vector as scored"):
            try:
                vector = json.loads(candidate["feature_vector_json"] or "{}")
                rows = [{
                    "Feature": name.replace("_", " ").title(),
                    "Agreement": "no evidence" if value is None else round(float(value), 3),
                    "Weight": config.FEATURE_WEIGHTS.get(name, 0.0),
                    "Contribution": 0.0 if value is None
                                    else round(float(value) * config.FEATURE_WEIGHTS.get(name, 0.0), 4),
                } for name, value in vector.items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                st.caption("The score is the weighted mean over features that have "
                           "evidence. Missing fields are excluded rather than "
                           "counted as a disagreement.")
            except json.JSONDecodeError:
                st.code(candidate["feature_vector_json"])

        # ---- the decision ----
        theme.section("Record a decision")
        reason_column, notes_column = st.columns([1, 2], gap="medium")
        reason = reason_column.selectbox("Reason code", [
            "SAME_PERSON_CONFIRMED", "SHARED_CONTACT_NOT_SAME_PERSON",
            "JOINT_ACCOUNT_RELATIONSHIP", "BUSINESS_OWNER_CONFIRMED",
            "INSUFFICIENT_EVIDENCE", "INCORRECT_SOURCE_DATA", "HOUSEHOLD_EXCEPTION",
        ])
        notes = notes_column.text_area("Steward notes", max_chars=1000, height=90,
                                       placeholder="What evidence settled it?")

        action_columns = st.columns([1, 1, 1, 3])
        buttons = [
            ("Accept match", "ACCEPT_MATCH", "primary"),
            ("Reject match", "REJECT_MATCH", "secondary"),
            ("Defer", "DEFER", "secondary"),
        ]
        for column, (label, verdict, kind) in zip(action_columns, buttons):
            if column.button(label, use_container_width=True, type=kind, key=verdict):
                try:
                    da.save_decision(picked, verdict, reason, notes,
                                     candidate["policy_version"])
                    if verdict == "DEFER":
                        da.bump_version()
                        st.success("Deferred. The case stays open for later review.")
                    elif da.can_republish_in_app():
                        with st.spinner("Re-resolving identities and republishing..."):
                            result = da.republish()
                        st.success(
                            f"{verdict.replace('_', ' ').title()} recorded and applied. "
                            f"{result['parties']} parties in "
                            f"{result['households']} households."
                        )
                    elif os.environ.get("EB_PUBLISH_JOB_ID"):
                        run_id = da.trigger_publish_job()
                        st.success(f"Decision recorded. Publish job run {run_id} started.")
                    else:
                        st.success("Decision recorded. Run notebook 02 to republish Gold.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Decision was not saved: {exc}")

        action_columns[3].caption(
            "Decisions are appended, never edited. Deferring keeps a case open "
            "and never reverses an earlier accept or reject."
        )


# ===========================================================================
# TAB 4 — Model quality
# ===========================================================================
with tab_quality:
    metrics = da.quality_metrics()
    if not metrics:
        theme.band("Match quality has not been measured. It is computed at "
                   "publish time against the evaluation-only truth table.", "warn")
    else:
        tiles = [
            theme.kpi("Precision", f"{metrics.get('precision', 0):.1%}",
                      "Of the links made, how many are right", "deep"),
            theme.kpi("Recall", f"{metrics.get('recall', 0):.1%}",
                      "Of the links that exist, how many we found"),
            theme.kpi("F1", f"{metrics.get('f1', 0):.3f}", "Harmonic mean"),
            theme.kpi("Blocking recall", f"{metrics.get('blocking_recall', 0):.1%}",
                      "True pairs that survived blocking"),
            theme.kpi("Comparisons avoided",
                      f"{metrics.get('reduction_ratio', 0) * 100:.2f}%",
                      f"{int(metrics.get('pairs_compared', 0)):,} pairs scored "
                      f"of {int(metrics.get('total_possible_pairs', 0)):,}", "accent"),
        ]
        for column, tile in zip(st.columns(5, gap="small"), tiles):
            column.markdown(tile, unsafe_allow_html=True)

        theme.band(
            "Measured against the generator's own record of which synthetic rows "
            "came from the same invented person. This is why the data set is "
            "synthetic: it is the only way to grade the engine honestly.",
        )

        left, right = st.columns([2, 3], gap="large")
        with left:
            theme.section("Confusion matrix", "Pairwise, the standard for record linkage.")
            tp = int(metrics.get("true_positive", 0))
            fp = int(metrics.get("false_positive", 0))
            fn = int(metrics.get("false_negative", 0))
            tn = int(metrics.get("true_negative", 0))

            # Cells are coloured by whether the engine was right, not by how
            # big the number is. Otherwise the true-negative count, which is
            # always enormous, swamps the only two cells that matter.
            def cell(count: int, caption: str, good: bool) -> str:
                border = theme.GREEN if good else theme.ORANGE
                tint = "#EFF8F3" if good else "#FFF4E6"
                return (
                    f'<div style="background:{tint};border:1px solid {theme.LINE};'
                    f'border-left:4px solid {border};border-radius:7px;'
                    f'padding:11px 13px;">'
                    f'<div style="font-size:1.35rem;font-weight:700;'
                    f'color:{theme.MIDNIGHT};">{count:,}</div>'
                    f'<div style="font-size:.73rem;color:{theme.SLATE};'
                    f'font-weight:600;">{caption}</div></div>'
                )

            grid = st.columns(2, gap="small")
            grid[0].markdown(cell(tp, "Linked · same person", True),
                             unsafe_allow_html=True)
            grid[1].markdown(cell(fp, "Linked · different people", False),
                             unsafe_allow_html=True)
            st.markdown("")
            grid = st.columns(2, gap="small")
            grid[0].markdown(cell(fn, "Not linked · same person", False),
                             unsafe_allow_html=True)
            grid[1].markdown(cell(tn, "Not linked · different people", True),
                             unsafe_allow_html=True)
            st.markdown("")
            st.markdown(
                f"""<div class="eb-band">
                <b>{tp:,}</b> correct links · <b>{fp:,}</b> wrong links ·
                <b>{fn:,}</b> missed links.<br>
                Resolved <b>{int(metrics.get('predicted_parties', 0)):,}</b> parties
                against <b>{int(metrics.get('actual_identities', 0)):,}</b> real people.
                </div>""", unsafe_allow_html=True,
            )
            if not truth.empty:
                household_metrics = {
                    k: v for k, v in metrics.items() if k.startswith("household_")
                }
                if household_metrics:
                    theme.section("Household accuracy")
                    st.dataframe(
                        pd.DataFrame([
                            {"Metric": k.replace("household_", "").title(),
                             "Value": f"{v:.3f}"}
                            for k, v in household_metrics.items()
                        ]), use_container_width=True, hide_index=True,
                    )

        with right:
            if truth.empty:
                theme.band("The truth table is not available to this viewer, so the "
                           "score distribution and threshold sweep are hidden.", "warn")
            else:
                theme.section(
                    "Score separation",
                    "Two clean humps mean the score is doing real work. Overlap in "
                    "the middle is exactly what the steward queue exists to handle.",
                )
                labelled = evaluate.label_candidates(candidates, truth)
                labelled["Pair type"] = labelled["is_true_match"].map(
                    {True: "Same person", False: "Different people"}
                )
                figure = px.histogram(
                    labelled, x="match_score", color="Pair type", nbins=28,
                    barmode="overlay", opacity=0.78,
                    color_discrete_map={"Same person": theme.CERULEAN,
                                        "Different people": theme.ORANGE},
                )
                figure.add_vline(x=config.REVIEW_THRESHOLD, line_dash="dot",
                                 line_color=theme.SLATE,
                                 annotation_text="review floor", annotation_font_size=10)
                figure.add_vline(x=config.AUTO_MATCH_THRESHOLD, line_dash="dot",
                                 line_color=theme.MIDNIGHT,
                                 annotation_text="auto-match", annotation_font_size=10)
                figure.update_xaxes(title="Match score")
                figure.update_yaxes(title="Candidate pairs")
                st.plotly_chart(theme.style_plot(figure, 300, legend=True),
                                use_container_width=True)

                theme.section(
                    "The tradeoff behind the threshold",
                    "What the bank actually buys when it asks for fewer false "
                    "matches. Move the line and recall falls.",
                )
                sweep = evaluate.threshold_sweep(candidates, truth)
                figure = go.Figure()
                for column_name, color, label in (
                    ("precision", theme.MIDNIGHT, "Precision"),
                    ("recall", theme.CERULEAN, "Recall"),
                    ("f1", theme.ORANGE, "F1"),
                ):
                    figure.add_scatter(
                        x=sweep["threshold"], y=sweep[column_name], name=label,
                        mode="lines", line=dict(color=color, width=2.5),
                    )
                figure.add_vline(x=config.AUTO_MATCH_THRESHOLD, line_dash="dot",
                                 line_color=theme.SLATE,
                                 annotation_text="in force", annotation_font_size=10)
                figure.update_xaxes(title="Auto-match threshold")
                figure.update_yaxes(title=None, range=[0, 1.04], tickformat=".0%")
                st.plotly_chart(theme.style_plot(figure, 290, legend=True),
                                use_container_width=True)

                with st.expander("Threshold sweep as a table"):
                    st.dataframe(sweep, use_container_width=True, hide_index=True)

        theme.section("Why blocking is the design, not an optimisation")
        compared = int(metrics.get("pairs_compared", 0))
        possible = int(metrics.get("total_possible_pairs", 0))
        projected = 570_000 * (570_000 - 1) // 2
        st.dataframe(
            pd.DataFrame([
                {"Scale": f"This POC ({int(metrics.get('records_evaluated', 0)):,} records)",
                 "Pairs if compared exhaustively": f"{possible:,}",
                 "Pairs actually scored": f"{compared:,}",
                 "Avoided": f"{metrics.get('reduction_ratio', 0) * 100:.2f}%"},
                {"Scale": "Eastern Bank stated volume (570,000 customers)",
                 "Pairs if compared exhaustively": f"{projected:,}",
                 "Pairs actually scored": "blocked the same way",
                 "Avoided": "same order of reduction"},
            ]), use_container_width=True, hide_index=True,
        )
        st.caption(
            "Blocking recall of "
            f"{metrics.get('blocking_recall', 0):.1%} says no true pair was lost "
            "to get that reduction. Recall lost at the blocking stage can never "
            "be recovered by better scoring, which is why it is measured "
            "separately."
        )


# ===========================================================================
# TAB 5 — Governance and refresh
# ===========================================================================
with tab_gov:
    refresh_runs = da.load("refresh_run")
    source_refresh = da.load("fact_source_refresh")

    tiles = [
        theme.kpi("Steward decisions", f"{len(decisions):,}", "Append-only", "deep"),
        theme.kpi("Household overrides", f"{len(overrides):,}", "Append-only"),
        theme.kpi("Refresh runs", f"{len(refresh_runs):,}", "With status and detail"),
        theme.kpi("NPI columns masked", f"{len(config.NPI_COLUMNS)}",
                  "Unmasked only for a cleared role", "accent"),
    ]
    for column, tile in zip(st.columns(4, gap="small"), tiles):
        column.markdown(tile, unsafe_allow_html=True)

    theme.section("Source freshness at the last publish",
                  "Row counts and as-of dates per feed, appended at every publish.")
    if source_refresh.empty:
        theme.band("No publish has been recorded yet.", "warn")
    else:
        latest = source_refresh[
            source_refresh["publish_id"] == source_refresh.sort_values("published_at")
            ["publish_id"].iloc[-1]
        ]
        st.dataframe(
            latest[["source_table", "row_count", "source_as_of",
                    "household_policy", "published_at"]].rename(columns={
                "source_table": "Source", "row_count": "Rows",
                "source_as_of": "As of", "household_policy": "Policy",
                "published_at": "Published",
            }), use_container_width=True, hide_index=True,
        )

    left, right = st.columns(2, gap="large")
    with left:
        theme.section("Match decision audit trail",
                      "Who decided what, when, and on what grounds.")
        if decisions.empty:
            theme.band("No decisions recorded yet. Accept or reject a case in "
                       "Match stewardship and it appears here.")
        else:
            st.dataframe(
                decisions.sort_values("decision_timestamp", ascending=False)[[
                    "decision_timestamp", "steward_id", "decision",
                    "decision_reason", "candidate_id", "notes", "policy_version",
                ]].rename(columns={
                    "decision_timestamp": "When", "steward_id": "Steward",
                    "decision": "Decision", "decision_reason": "Reason",
                    "candidate_id": "Candidate", "notes": "Notes",
                    "policy_version": "Policy",
                }), use_container_width=True, hide_index=True, height=260,
            )

    with right:
        theme.section("Refresh run history",
                      "A partial run must never be presented as a clean one.")
        if refresh_runs.empty:
            theme.band("No refresh has been run. Use the sidebar to run one.")
        else:
            ordered_runs = refresh_runs.sort_values("event_timestamp", ascending=False)
            newest = ordered_runs.iloc[0]
            if newest["status"] != "SUCCEEDED":
                theme.band(f"Latest refresh is <b>{newest['status']}</b>. Published "
                           "data may be stale or partial.", "warn")
            st.dataframe(
                ordered_runs[["event_timestamp", "run_id", "scenario",
                              "status", "detail"]].rename(columns={
                    "event_timestamp": "When", "run_id": "Run",
                    "scenario": "Scenario", "status": "Status", "detail": "Detail",
                }), use_container_width=True, hide_index=True, height=260,
            )

    theme.section(
        "Manual household correction",
        "Overrides are anchored to a source record, never to a party id, because "
        "party ids are regenerated whenever identity resolution runs again. "
        "Nothing here edits source data or merges two people.",
    )
    anchors = silver[silver["source_system"] == "CORE"].copy()
    if anchors.empty:
        theme.band("No CORE source records available to anchor an override.", "warn")
    else:
        anchors["label"] = (anchors["full_name"] + "  ·  " + anchors["record_id"]
                            + "  ·  " + anchors["address_line_1"])
        businesses = da.load("dim_business")

        form_left, form_right = st.columns([1, 1], gap="medium")
        subject = form_left.selectbox("Customer source anchor",
                                      anchors["label"].tolist())
        subject_id = anchors[anchors["label"] == subject]["record_id"].iloc[0]
        action = form_right.selectbox("Action", [
            "ASSIGN_HOUSEHOLD", "SPLIT_HOUSEHOLD", "RESET_HOUSEHOLD",
            "INCLUDE_BUSINESS", "EXCLUDE_BUSINESS", "RESET_BUSINESS",
        ])

        target_id, business_id = "", ""
        if action == "ASSIGN_HOUSEHOLD":
            target = form_left.selectbox("Move into this record's household",
                                         anchors["label"].tolist(), key="target")
            target_id = anchors[anchors["label"] == target]["record_id"].iloc[0]
        elif action.endswith("BUSINESS") and action != "RESET_BUSINESS":
            if businesses.empty:
                form_right.warning("No businesses published.")
            else:
                business_labels = (businesses["business_name"] + "  ·  "
                                   + businesses["business_id"]).tolist()
                picked_business = form_right.selectbox("Business", business_labels)
                business_id = businesses.iloc[
                    business_labels.index(picked_business)
                ]["business_id"]

        reason = st.text_input("Governance reason (required)",
                               placeholder="Why is this correction justified?")
        blocked = action in ("INCLUDE_BUSINESS", "EXCLUDE_BUSINESS") and not business_id
        if st.button("Save override", type="primary", disabled=blocked):
            try:
                override_id = da.save_override(subject_id, action, reason,
                                               target_id, business_id)
                if da.can_republish_in_app():
                    with st.spinner("Rebuilding households..."):
                        da.republish()
                    st.success(f"Override {override_id[:8]} saved and applied.")
                else:
                    st.success(f"Override {override_id[:8]} saved. Run notebook 02 "
                               "to apply it to published Gold.")
                st.rerun()
            except Exception as exc:
                st.error(f"Override was not saved: {exc}")

        st.markdown("")
        theme.section("Override history")
        if overrides.empty:
            theme.band("No household overrides recorded.")
        else:
            st.dataframe(
                overrides.sort_values("decision_timestamp", ascending=False)[[
                    "decision_timestamp", "steward_id", "action",
                    "subject_record_id", "target_record_id", "business_id", "reason",
                ]].rename(columns={
                    "decision_timestamp": "When", "steward_id": "Steward",
                    "action": "Action", "subject_record_id": "Subject",
                    "target_record_id": "Target", "business_id": "Business",
                    "reason": "Reason",
                }), use_container_width=True, hide_index=True,
            )

    theme.section("How this maps to the bank's security requirements")
    st.dataframe(pd.DataFrame([
        {"Requirement": "Secure handling of Non-Public Information",
         "In this POC": "NPI columns masked on read unless the viewer holds the "
                        "cleared role. The sidebar switch demonstrates both views.",
         "In production": "Unity Catalog column masks and row filters, so the "
                          "app cannot grant itself access it does not hold."},
        {"Requirement": "Role-based access control",
         "In this POC": "A single demo role switch, and the app runs as its own "
                        "service principal with explicit table grants.",
         "In production": "Account groups mapped to catalog, schema and table "
                          "grants. Stewards, analysts and auditors get different "
                          "grants."},
        {"Requirement": "Audit capability",
         "In this POC": "Every match decision and household override is appended "
                        "with steward, timestamp, reason and policy version. "
                        "Nothing is updated or deleted.",
         "In production": "Same tables as Delta with history, plus Unity Catalog "
                          "audit logs for reads."},
        {"Requirement": "Evaluation data separation",
         "In this POC": "Ground truth lives in `demo_eval` and is never granted "
                        "to business users or joined into Gold.",
         "In production": "No equivalent exists: real matching has no ground "
                          "truth, which is why the steward queue is the control."},
    ]), use_container_width=True, hide_index=True)


st.markdown(
    '<div class="eb-foot">Eastern Bank Householding POC · synthetic data only · '
    f'engine v{__import__("src").__version__} · policy '
    f'<code>{config.POLICY_VERSION}</code> · model '
    f'<code>{config.MODEL_VERSION}</code></div>',
    unsafe_allow_html=True,
)
