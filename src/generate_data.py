"""Synthetic Bronze source data for the householding POC.

Nothing here is real. Names are drawn from fixed lists, tax identifiers are
one-way hashes of synthetic strings, and addresses are invented. The generator
is seeded, so the same seed always produces the same demo.

What makes this useful rather than decorative is that the messiness is
deliberate and recorded. Every row knows which truth identity produced it, so
`demo_eval.ground_truth_identity` can score the matcher honestly.

Shape at the default spec: 200 people, 110 households, roughly 420 customer
rows across three systems, about 480 accounts, 30 businesses.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

import pandas as pd

from . import config
from .textmatch import NICKNAMES_BY_ROOT


FIRST_NAMES_M = [
    "ROBERT", "WILLIAM", "MICHAEL", "JAMES", "JOHN", "JOSEPH", "THOMAS",
    "RICHARD", "DANIEL", "CHRISTOPHER", "ANTHONY", "STEPHEN", "EDWARD",
    "NICHOLAS", "MATTHEW", "ANDREW", "TIMOTHY", "GREGORY", "VINCENT",
    "LAWRENCE", "FRANCIS", "PATRICK", "SEAN", "BRIAN", "KEVIN",
]
FIRST_NAMES_F = [
    "ELIZABETH", "SUSAN", "KATHERINE", "MARGARET", "JENNIFER", "PATRICIA",
    "DEBORAH", "BARBARA", "THERESA", "MARY", "LINDA", "NANCY", "KAREN",
    "LISA", "DONNA", "CAROL", "SANDRA", "SHARON", "LAURA", "EMILY",
    "RACHEL", "AMANDA", "MEGAN", "NICOLE", "HEATHER",
]
LAST_NAMES = [
    "SULLIVAN", "OBRIEN", "MURPHY", "FITZGERALD", "DONOVAN", "KELLEY",
    "WALSH", "CONNOLLY", "GALLAGHER", "MCCARTHY", "RYAN", "BRENNAN",
    "DOHERTY", "FLYNN", "LYNCH", "QUINN", "KEANE", "MORRISON", "HAYES",
    "BARRETT", "CHEN", "NGUYEN", "PATEL", "SILVA", "SANTOS", "ROSSI",
    "ROMANO", "COHEN", "KAPLAN", "ANDERSON", "JOHNSON", "WILLIAMS",
    "MARTINEZ", "RODRIGUEZ", "GARCIA", "DASILVA", "TRAN", "LIU",
]
STREETS = [
    "MAPLE", "OAK", "ELM", "WASHINGTON", "MAIN", "HIGHLAND", "SUMMER",
    "WINTER", "BEACON", "CHESTNUT", "WALNUT", "CEDAR", "LINCOLN", "FRANKLIN",
    "PLEASANT", "CENTRAL", "SCHOOL", "CHURCH", "BRIDGE", "LAKEVIEW",
    "ESSEX", "SALEM", "UNION", "PROSPECT", "COMMONWEALTH",
]
STREET_TYPES = ["STREET", "AVENUE", "ROAD", "DRIVE", "LANE", "COURT", "TERRACE"]

# Eastern Bank's footprint is eastern Massachusetts, so the geography matches.
CITIES = [
    ("BOSTON", "MA", "02108"), ("CAMBRIDGE", "MA", "02139"),
    ("SOMERVILLE", "MA", "02143"), ("LYNN", "MA", "01902"),
    ("SALEM", "MA", "01970"), ("MEDFORD", "MA", "02155"),
    ("QUINCY", "MA", "02169"), ("NEWTON", "MA", "02458"),
    ("BROOKLINE", "MA", "02445"), ("WALTHAM", "MA", "02451"),
    ("PEABODY", "MA", "01960"), ("BEVERLY", "MA", "01915"),
    ("DANVERS", "MA", "01923"), ("SAUGUS", "MA", "01906"),
    ("REVERE", "MA", "02151"), ("MALDEN", "MA", "02148"),
    ("EVERETT", "MA", "02149"), ("WOBURN", "MA", "01801"),
    ("LEXINGTON", "MA", "02420"), ("ARLINGTON", "MA", "02474"),
]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "comcast.net", "verizon.net"]

DEPOSIT_PRODUCTS = ["CHECKING", "SAVINGS", "MONEY_MARKET", "CD"]
LOAN_PRODUCTS = ["MORTGAGE", "HELOC", "AUTO_LOAN", "PERSONAL_LOAN"]
CARD_PRODUCTS = ["VISA_PLATINUM", "VISA_SIGNATURE", "VISA_CASH_REWARDS"]
BUSINESS_SUFFIX = ["LLC", "INC", "& SONS", "GROUP", "ASSOCIATES", "CORP"]
BUSINESS_TYPES = [
    "HVAC", "PLUMBING", "LANDSCAPING", "AUTO REPAIR", "CONSULTING",
    "CATERING", "DENTAL", "REALTY", "CONSTRUCTION", "PRINTING",
]
AGE_BANDS = ["25-34", "35-44", "45-54", "55-64", "65-74", "75+"]
INCOME_BANDS = ["<50K", "50-75K", "75-100K", "100-150K", "150-250K", "250K+"]
SEGMENTS = ["MASS_MARKET", "EMERGING_AFFLUENT", "AFFLUENT", "SMALL_BUSINESS"]
NEXT_BEST_ACTIONS = [
    "OFFER_HELOC", "OFFER_CREDIT_CARD", "OFFER_MONEY_MARKET",
    "DIGITAL_ONBOARDING", "WEALTH_REVIEW", "NO_ACTION",
]


def _tax_hash(seed_text: str) -> str:
    """One-way hash stands in for a tax identifier. No real SSN exists here."""
    return hashlib.sha256(f"EB-DEMO-{seed_text}".encode()).hexdigest()[:24]


def _typo(rng: random.Random, value: str) -> str:
    """Introduce one realistic keying error: transpose, drop or double a char."""
    if len(value) < 4:
        return value
    i = rng.randrange(1, len(value) - 1)
    mode = rng.choice(["transpose", "drop", "double"])
    if mode == "transpose":
        return value[:i] + value[i + 1] + value[i] + value[i + 2:]
    if mode == "drop":
        return value[:i] + value[i + 1:]
    return value[:i] + value[i] + value[i:]


def _format_phone(rng: random.Random, digits: str, reformat: bool) -> str:
    if not reformat:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    style = rng.choice(["plain", "dash", "dot", "country"])
    if style == "plain":
        return digits
    if style == "dash":
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if style == "dot":
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"
    return f"+1 {digits[:3]} {digits[3:6]} {digits[6:]}"


def _abbreviate_street(street_line: str) -> str:
    swaps = {
        "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
        "LANE": "LN", "COURT": "CT", "TERRACE": "TER",
    }
    for long, short in swaps.items():
        street_line = street_line.replace(long, short)
    return street_line


def build_identities(spec: config.DataSpec) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create truth households and the people who live in them."""
    rng = random.Random(spec.seed)

    # ---- households -------------------------------------------------------
    households = []
    for i in range(spec.n_households):
        city, state, base_zip = CITIES[rng.randrange(len(CITIES))]
        number = rng.randrange(1, 480)
        street = f"{number} {rng.choice(STREETS)} {rng.choice(STREET_TYPES)}"
        # Roughly a third of addresses carry a unit, which is where naive
        # address-only householding usually goes wrong.
        unit = ""
        if rng.random() < 0.30:
            unit = f"APT {rng.choice(['1', '2', '3', '1A', '2B', '4C', '12'])}"
        households.append({
            "truth_household_id": f"TH{i:04d}",
            "address_line_1": street,
            "address_line_2": unit,
            "city": city,
            "state": state,
            "postal_code": base_zip,
        })
    hh = pd.DataFrame(households)

    # ---- people -----------------------------------------------------------
    people = []
    today = date.fromisoformat(spec.as_of_date)
    household_cursor = 0
    while len(people) < spec.n_identities:
        if household_cursor >= len(hh):
            household_cursor = 0
        home = hh.iloc[household_cursor]
        household_cursor += 1
        # Most households have 1-3 adults on file.
        size = rng.choices([1, 2, 3], weights=[0.42, 0.45, 0.13])[0]
        surname = rng.choice(LAST_NAMES)
        for member in range(size):
            if len(people) >= spec.n_identities:
                break
            is_male = rng.random() < 0.5
            given = rng.choice(FIRST_NAMES_M if is_male else FIRST_NAMES_F)
            # A minority of adults in a household keep a different surname.
            member_surname = surname if (member == 0 or rng.random() < 0.82) \
                else rng.choice(LAST_NAMES)
            age = rng.randrange(26, 84)
            dob = today - timedelta(days=age * 365 + rng.randrange(0, 365))
            idx = len(people)
            phone_digits = f"617{rng.randrange(2000000, 9999999)}"
            people.append({
                "truth_identity_id": f"TI{idx:05d}",
                "truth_household_id": home["truth_household_id"],
                "first_name": given,
                "middle_initial": rng.choice("ABCDEFGHJKLMNPRSTW") if rng.random() < 0.55 else "",
                "last_name": member_surname,
                "date_of_birth": dob.isoformat(),
                "tax_id_hash": _tax_hash(f"{idx}-{given}-{member_surname}"),
                "tax_id_last4": f"{rng.randrange(1000, 9999)}",
                "phone_digits": phone_digits,
                "email": f"{given[0].lower()}{member_surname.lower()}{rng.randrange(1, 99)}"
                         f"@{rng.choice(EMAIL_DOMAINS)}",
                "address_line_1": home["address_line_1"],
                "address_line_2": home["address_line_2"],
                "city": home["city"],
                "state": home["state"],
                "postal_code": home["postal_code"],
            })

    ident = pd.DataFrame(people)

    # ---- the scripted hero household -------------------------------------
    # The demo narrative needs one family that behaves exactly the same every
    # run: a man known by three different given names, a spouse who appears
    # under a maiden name, an adult child, and a family business.
    hero_home = {
        "address_line_1": "47 MAPLE STREET",
        "address_line_2": "",
        "city": "SALEM",
        "state": "MA",
        "postal_code": "01970",
    }
    hh.loc[0, list(hero_home.keys())] = list(hero_home.values())
    hero = [
        ("ROBERT", "J", "SULLIVAN", "1968-04-12", "6175550142"),
        ("SUSAN", "M", "SULLIVAN", "1970-09-03", "6175550188"),
        ("EMILY", "", "SULLIVAN", "1998-02-21", "6175550233"),
    ]
    for pos, (first, mid, last, dob, phone) in enumerate(hero):
        ident.loc[pos, "truth_household_id"] = "TH0000"
        ident.loc[pos, "first_name"] = first
        ident.loc[pos, "middle_initial"] = mid
        ident.loc[pos, "last_name"] = last
        ident.loc[pos, "date_of_birth"] = dob
        ident.loc[pos, "phone_digits"] = phone
        ident.loc[pos, "tax_id_hash"] = _tax_hash(f"hero-{pos}-{first}")
        ident.loc[pos, "tax_id_last4"] = ["4417", "2209", "8831"][pos]
        ident.loc[pos, "email"] = [
            "rsullivan@comcast.net", "ssullivan70@gmail.com", "emily.sullivan@gmail.com",
        ][pos]
        for key, value in hero_home.items():
            ident.loc[pos, key] = value

    return hh, ident


def _emit_source_row(
    rng: random.Random, person: pd.Series, system: str, source_id: str,
    spec: config.DataSpec, forced: dict | None = None,
) -> dict:
    """Render one truth identity as it would appear in one source system."""
    rates = spec.variant_rates
    forced = forced or {}

    first = forced.get("first_name", person["first_name"])
    last = forced.get("last_name", person["last_name"])
    middle = person["middle_initial"]

    if "first_name" not in forced:
        aliases = NICKNAMES_BY_ROOT.get(first, [])
        if aliases and rng.random() < rates["nickname"]:
            first = rng.choice(aliases)
        if rng.random() < rates["typo"]:
            first = _typo(rng, first)
    if "last_name" not in forced:
        if rng.random() < rates["typo"] * 0.6:
            last = _typo(rng, last)
        elif rng.random() < rates["maiden_name"]:
            last = f"{last}-{rng.choice(LAST_NAMES)}"

    # CRM is the sloppiest system: fewer identifiers, more free text.
    street = person["address_line_1"]
    if rng.random() < rates["address_abbrev"]:
        street = _abbreviate_street(street)
    if system == "CRM" and rng.random() < 0.12:
        street = f"PO BOX {rng.randrange(100, 9999)}"

    dob = person["date_of_birth"]
    if rng.random() < rates["drop_dob"] or (system == "CRM" and rng.random() < 0.25):
        dob = ""

    tax_hash = person["tax_id_hash"]
    tax_last4 = person["tax_id_last4"]
    if system == "CRM" or rng.random() < rates["drop_tax_id"]:
        if system == "CRM" and rng.random() < 0.75:
            tax_hash, tax_last4 = "", ""
        elif rng.random() < 0.4:
            tax_hash, tax_last4 = "", ""

    email = person["email"]
    if rng.random() < rates["email_variant"]:
        local, _, domain = email.partition("@")
        email = rng.choice([
            f"{local}.{rng.randrange(1, 9)}@{domain}",
            f"{local}+bank@{domain}",
            f"{local.upper()}@{domain}",
            "",
        ])

    if middle and rng.random() < 0.45:
        middle = ""

    record = {
        "source_system": system,
        "source_customer_id": source_id,
        "first_name": first,
        "middle_initial": middle,
        "last_name": last,
        "full_name": "",
        "date_of_birth": dob,
        "tax_id_hash": tax_hash,
        "tax_id_last4": tax_last4,
        "address_line_1": street,
        "address_line_2": person["address_line_2"],
        "city": person["city"],
        "state": person["state"],
        "postal_code": person["postal_code"],
        "phone": _format_phone(rng, person["phone_digits"], rng.random() < rates["phone_reformat"]),
        "email": email,
        "record_loaded_at": spec.as_of_date,
        # Carried for evaluation only. Stage 0 strips it from Bronze.
        "_truth_identity_id": person["truth_identity_id"],
    }

    # Forced values win over every random variant. This is how the scripted
    # hero family stays byte-identical across runs while everyone else gets
    # realistic noise.
    record.update({k: v for k, v in forced.items() if k in record})
    record["full_name"] = " ".join(
        p for p in [record["first_name"], record["middle_initial"], record["last_name"]] if p
    )
    return record


def build_sources(spec: config.DataSpec, ident: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Project the truth identities into CORE, CARD and CRM extracts."""
    rng = random.Random(spec.seed + 7)
    core, card, crm = [], [], []

    for _, person in ident.iterrows():
        pos = int(person["truth_identity_id"][2:])

        # Hero family: fix exactly how they appear in each system so the
        # narrative is identical on every run.
        # Robert appears three times under three given names. CORE and CARD
        # share a tax identifier so they link automatically. CRM has a
        # keyed-in surname typo, a stale phone number and no tax id or birth
        # date, so it lands in the steward queue instead. That single pair is
        # the live human-decision moment in the demo.
        if pos == 0:
            core.append(_emit_source_row(
                rng, person, "CORE", f"C{10000000 + pos}", spec,
                forced={"first_name": "ROBERT", "middle_initial": "J",
                        "last_name": "SULLIVAN", "date_of_birth": "1968-04-12",
                        "address_line_1": "47 MAPLE STREET",
                        "phone": "(617) 555-0142", "email": "rsullivan@comcast.net"}))
            card.append(_emit_source_row(
                rng, person, "CARD", f"ELAN{2000000 + pos}", spec,
                forced={"first_name": "BOB", "middle_initial": "",
                        "last_name": "SULLIVAN", "date_of_birth": "1968-04-12",
                        "address_line_1": "47 MAPLE ST",
                        "phone": "6175550142", "email": "rsullivan@comcast.net"}))
            crm.append(_emit_source_row(
                rng, person, "CRM", f"CRM-{70000 + pos}", spec,
                forced={"first_name": "ROB", "middle_initial": "",
                        "last_name": "SULIVAN", "date_of_birth": "",
                        "tax_id_hash": "", "tax_id_last4": "",
                        "address_line_1": "47 MAPLE ST",
                        "phone": "(978) 555-0199", "email": ""}))
            continue

        # Susan is on file under her maiden name in CRM. Token overlap on the
        # hyphenated surname lets this one link without a human.
        if pos == 1:
            core.append(_emit_source_row(
                rng, person, "CORE", f"C{10000000 + pos}", spec,
                forced={"first_name": "SUSAN", "middle_initial": "M",
                        "last_name": "SULLIVAN", "date_of_birth": "1970-09-03",
                        "address_line_1": "47 MAPLE STREET",
                        "phone": "(617) 555-0188", "email": "ssullivan70@gmail.com"}))
            crm.append(_emit_source_row(
                rng, person, "CRM", f"CRM-{70000 + pos}", spec,
                forced={"first_name": "SUE", "middle_initial": "",
                        "last_name": "SULLIVAN-MARTINEZ", "date_of_birth": "1970-09-03",
                        "tax_id_hash": "", "tax_id_last4": "",
                        "address_line_1": "47 Maple St", "phone": "617.555.0188",
                        "email": "ssullivan70@gmail.com"}))
            continue

        # Emily exists in one system only: a legitimate single-source party,
        # and the answer to "does every party need three records?".
        if pos == 2:
            core.append(_emit_source_row(
                rng, person, "CORE", f"C{10000000 + pos}", spec,
                forced={"first_name": "EMILY", "middle_initial": "",
                        "last_name": "SULLIVAN", "date_of_birth": "1998-02-21",
                        "address_line_1": "47 MAPLE STREET",
                        "phone": "(617) 555-0233", "email": "emily.sullivan@gmail.com"}))
            continue

        if rng.random() < spec.core_coverage:
            core.append(_emit_source_row(rng, person, "CORE", f"C{10000000 + pos}", spec))
        if rng.random() < spec.card_coverage:
            card.append(_emit_source_row(rng, person, "CARD", f"ELAN{2000000 + pos}", spec))
        if rng.random() < spec.crm_coverage:
            crm.append(_emit_source_row(rng, person, "CRM", f"CRM-{70000 + pos}", spec))

    return {
        "core_customer": pd.DataFrame(core),
        "card_customer": pd.DataFrame(card),
        "crm_contact": pd.DataFrame(crm),
    }


def build_accounts(
    spec: config.DataSpec, ident: pd.DataFrame, sources: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Deposit, loan and card accounts, including genuine joint ownership."""
    rng = random.Random(spec.seed + 13)
    core_cust = sources["core_customer"]
    card_cust = sources["card_customer"]

    core_accounts, card_accounts, relationships = [], [], []
    account_seq = 0

    # Map truth identity -> household so we can create joint accounts between
    # people who actually live together.
    by_household: dict[str, list[str]] = {}
    for _, p in ident.iterrows():
        by_household.setdefault(p["truth_household_id"], []).append(p["truth_identity_id"])

    core_by_truth = dict(zip(core_cust["_truth_identity_id"], core_cust["source_customer_id"]))

    for _, row in core_cust.iterrows():
        truth_id = row["_truth_identity_id"]
        n_deposit = rng.choices([1, 2, 3], weights=[0.45, 0.40, 0.15])[0]
        for _ in range(n_deposit):
            account_seq += 1
            product = rng.choice(DEPOSIT_PRODUCTS)
            balance = {
                "CHECKING": rng.uniform(400, 18000),
                "SAVINGS": rng.uniform(1000, 85000),
                "MONEY_MARKET": rng.uniform(10000, 240000),
                "CD": rng.uniform(5000, 150000),
            }[product]
            account_id = f"DDA{account_seq:06d}"
            core_accounts.append({
                "account_id": account_id,
                "source_system": "CORE",
                "account_category": "DEPOSIT",
                "product_type": product,
                "primary_source_customer_id": row["source_customer_id"],
                "open_date": (date.fromisoformat(spec.as_of_date)
                              - timedelta(days=rng.randrange(60, 5200))).isoformat(),
                "balance": round(balance, 2),
                "currency": spec.currency,
                "as_of_date": spec.as_of_date,
                "status": "OPEN",
            })
            relationships.append({
                "account_id": account_id,
                "source_system": "CORE",
                "source_customer_id": row["source_customer_id"],
                "relationship_type": "PRIMARY",
                "_truth_identity_id": truth_id,
            })
            # Joint ownership with another adult in the same truth household.
            others = [t for t in by_household.get(
                ident.set_index("truth_identity_id").loc[truth_id, "truth_household_id"], []
            ) if t != truth_id and t in core_by_truth]
            if others and rng.random() < 0.30:
                joint = rng.choice(others)
                relationships.append({
                    "account_id": account_id,
                    "source_system": "CORE",
                    "source_customer_id": core_by_truth[joint],
                    "relationship_type": "JOINT",
                    "_truth_identity_id": joint,
                })

        if rng.random() < 0.34:
            account_seq += 1
            product = rng.choice(LOAN_PRODUCTS)
            principal = {
                "MORTGAGE": rng.uniform(140000, 820000),
                "HELOC": rng.uniform(15000, 160000),
                "AUTO_LOAN": rng.uniform(8000, 62000),
                "PERSONAL_LOAN": rng.uniform(3000, 40000),
            }[product]
            account_id = f"LN{account_seq:06d}"
            core_accounts.append({
                "account_id": account_id,
                "source_system": "CORE",
                "account_category": "LOAN",
                "product_type": product,
                "primary_source_customer_id": row["source_customer_id"],
                "open_date": (date.fromisoformat(spec.as_of_date)
                              - timedelta(days=rng.randrange(90, 6000))).isoformat(),
                # Loans carry a negative balance so household net position works.
                "balance": -round(principal, 2),
                "currency": spec.currency,
                "as_of_date": spec.as_of_date,
                "status": "OPEN",
            })
            relationships.append({
                "account_id": account_id, "source_system": "CORE",
                "source_customer_id": row["source_customer_id"],
                "relationship_type": "BORROWER", "_truth_identity_id": truth_id,
            })

    for _, row in card_cust.iterrows():
        account_seq += 1
        account_id = f"CC{account_seq:06d}"
        card_accounts.append({
            "account_id": account_id,
            "source_system": "CARD",
            "account_category": "CARD",
            "product_type": rng.choice(CARD_PRODUCTS),
            "primary_source_customer_id": row["source_customer_id"],
            "open_date": (date.fromisoformat(spec.as_of_date)
                          - timedelta(days=rng.randrange(30, 4000))).isoformat(),
            "balance": -round(rng.uniform(0, 14000), 2),
            "credit_limit": round(rng.choice([5000, 10000, 15000, 25000, 40000]), 2),
            "currency": spec.currency,
            "as_of_date": spec.as_of_date,
            "status": "OPEN",
        })
        relationships.append({
            "account_id": account_id, "source_system": "CARD",
            "source_customer_id": row["source_customer_id"],
            "relationship_type": "PRIMARY",
            "_truth_identity_id": row["_truth_identity_id"],
        })

    # ---- scripted joint accounts for the hero household -------------------
    # Robert and Susan hold two accounts together. This is the drill-down the
    # relationship explorer uses on stage.
    robert = core_by_truth.get("TI00000")
    susan = core_by_truth.get("TI00001")
    if robert and susan:
        for label, product, balance in [
            ("DDA900001", "CHECKING", 11240.55),
            ("DDA900002", "MONEY_MARKET", 86300.00),
        ]:
            core_accounts.append({
                "account_id": label, "source_system": "CORE",
                "account_category": "DEPOSIT", "product_type": product,
                "primary_source_customer_id": robert,
                "open_date": "2014-06-02", "balance": balance,
                "currency": spec.currency, "as_of_date": spec.as_of_date, "status": "OPEN",
            })
            relationships.append({
                "account_id": label, "source_system": "CORE",
                "source_customer_id": robert, "relationship_type": "PRIMARY",
                "_truth_identity_id": "TI00000",
            })
            relationships.append({
                "account_id": label, "source_system": "CORE",
                "source_customer_id": susan, "relationship_type": "JOINT",
                "_truth_identity_id": "TI00001",
            })

    return {
        "core_account": pd.DataFrame(core_accounts),
        "card_account": pd.DataFrame(card_accounts),
        "account_party_relationship": pd.DataFrame(relationships),
    }


def build_businesses(
    spec: config.DataSpec, ident: pd.DataFrame, sources: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Small businesses and their owners, the basis for super households."""
    rng = random.Random(spec.seed + 21)
    core_cust = sources["core_customer"]
    core_by_truth = dict(zip(core_cust["_truth_identity_id"], core_cust["source_customer_id"]))
    eligible = [t for t in core_by_truth if t not in ("TI00000", "TI00001", "TI00002")]

    businesses, links = [], []
    for i in range(spec.n_businesses):
        owner_count = rng.choices([1, 2], weights=[0.72, 0.28])[0]
        owners = rng.sample(eligible, min(owner_count, len(eligible)))
        anchor = ident.set_index("truth_identity_id").loc[owners[0]]
        business_id = f"BIZ{i:04d}"
        businesses.append({
            "business_id": business_id,
            "business_name": f"{anchor['last_name'].title()} "
                             f"{rng.choice(BUSINESS_TYPES).title()} {rng.choice(BUSINESS_SUFFIX)}",
            "tax_id_hash": _tax_hash(f"biz-{i}"),
            "business_type": rng.choice(["LLC", "S_CORP", "SOLE_PROP", "C_CORP"]),
            "address_line_1": f"{rng.randrange(1, 900)} {rng.choice(STREETS)} STREET",
            "city": anchor["city"], "state": anchor["state"],
            "postal_code": anchor["postal_code"],
            "annual_revenue_band": rng.choice(["<500K", "500K-2M", "2M-10M", "10M+"]),
        })
        for owner in owners:
            links.append({
                "business_id": business_id,
                "source_system": "CORE",
                "source_customer_id": core_by_truth[owner],
                "relationship_type": "OWNER",
                "ownership_pct": round(100.0 / len(owners), 1),
                "_truth_identity_id": owner,
            })

    # ---- scripted: Sullivan HVAC, owned by Robert plus an outside co-owner
    # The co-owner lives in a different household, which is what turns two
    # standard households into one super household.
    if "TI00000" in core_by_truth and eligible:
        co_owner = eligible[0]
        businesses.append({
            "business_id": "BIZ9001",
            "business_name": "Sullivan HVAC LLC",
            "tax_id_hash": _tax_hash("biz-sullivan-hvac"),
            "business_type": "LLC",
            "address_line_1": "47 MAPLE STREET",
            "city": "SALEM", "state": "MA", "postal_code": "01970",
            "annual_revenue_band": "2M-10M",
        })
        links.append({
            "business_id": "BIZ9001", "source_system": "CORE",
            "source_customer_id": core_by_truth["TI00000"],
            "relationship_type": "OWNER", "ownership_pct": 60.0,
            "_truth_identity_id": "TI00000",
        })
        links.append({
            "business_id": "BIZ9001", "source_system": "CORE",
            "source_customer_id": core_by_truth[co_owner],
            "relationship_type": "OWNER", "ownership_pct": 40.0,
            "_truth_identity_id": co_owner,
        })

    return {
        "business": pd.DataFrame(businesses),
        "party_business_relationship": pd.DataFrame(links),
    }


def build_enrichment(spec: config.DataSpec, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Third-party demographics, joined on the CORE customer id.

    Deliberately a separate feed keyed to a source id. Demographics must never
    drive identity matching, only describe a party once it has been resolved.
    """
    rng = random.Random(spec.seed + 31)
    rows = []
    for _, row in sources["core_customer"].iterrows():
        if rng.random() < 0.08:
            continue  # coverage gaps are normal with purchased data
        rows.append({
            "source_system": "CORE",
            "source_customer_id": row["source_customer_id"],
            "provider": "ACXIOM_DEMO",
            "age_band": rng.choice(AGE_BANDS),
            "income_band": rng.choice(INCOME_BANDS),
            "homeowner_flag": rng.choice(["Y", "N"]),
            "relationship_segment": rng.choice(SEGMENTS),
            "digital_engagement_score": round(rng.uniform(0, 100), 1),
            "next_best_action": rng.choice(NEXT_BEST_ACTIONS),
            "as_of_date": spec.as_of_date,
        })
    return pd.DataFrame(rows)


def generate_all(spec: config.DataSpec | None = None) -> dict[str, pd.DataFrame]:
    """Produce every Bronze table plus the evaluation-only truth table."""
    spec = spec or config.DATA_SPEC
    hh, ident = build_identities(spec)
    sources = build_sources(spec, ident)
    accounts = build_accounts(spec, ident, sources)
    businesses = build_businesses(spec, ident, sources)
    enrichment = build_enrichment(spec, sources)

    # Truth table: one row per source record, naming the person it came from.
    truth_rows = []
    for name, df in sources.items():
        for _, row in df.iterrows():
            truth_rows.append({
                "record_id": f"{row['source_system']}:{row['source_customer_id']}",
                "source_system": row["source_system"],
                "source_customer_id": row["source_customer_id"],
                "truth_identity_id": row["_truth_identity_id"],
            })
    truth = pd.DataFrame(truth_rows).merge(
        ident[["truth_identity_id", "truth_household_id"]], on="truth_identity_id", how="left"
    )

    tables = {**sources, **accounts, **businesses}
    tables["demographic_enrichment"] = enrichment
    tables["ground_truth_identity"] = truth

    # Bronze must not leak truth keys. Strip the helper column everywhere.
    for name, df in tables.items():
        if name == "ground_truth_identity":
            continue
        if "_truth_identity_id" in df.columns:
            tables[name] = df.drop(columns=["_truth_identity_id"])

    return tables
