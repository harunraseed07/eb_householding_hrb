"""Bronze to Silver: conform three source extracts into one customer record.

Standardization is doing most of the work in any householding solution. By the
time a row leaves this module, a nickname has a canonical root, an address is
in one abbreviation style, a phone is nine digits, and the row carries the
blocking keys the matcher will use. Nothing is matched here.
"""

from __future__ import annotations

import pandas as pd

from . import textmatch as tm


SILVER_COLUMNS = [
    "record_id", "source_system", "source_customer_id",
    "first_name", "middle_initial", "last_name", "full_name",
    "first_name_root", "last_name_soundex",
    "date_of_birth", "birth_year",
    "tax_id_hash", "tax_id_last4",
    "address_line_1", "address_line_2", "city", "state", "postal_code",
    "address_norm", "unit_norm", "postal5", "address_key",
    "phone", "phone_digits", "email", "email_norm",
    "record_loaded_at",
    "block_tax", "block_email", "block_phone", "block_name_postal",
    "block_dob_postal", "block_initial_street",
]


def standardize_record(row: pd.Series) -> dict:
    first = tm.normalize_name(row.get("first_name", ""))
    last = tm.normalize_name(row.get("last_name", ""))
    middle = tm.normalize_name(row.get("middle_initial", ""))[:1]

    street = row.get("address_line_1", "") or ""
    unit = row.get("address_line_2", "") or ""
    city = row.get("city", "") or ""
    state = row.get("state", "") or ""
    postal = row.get("postal_code", "") or ""

    address_norm = tm.normalize_address(street)
    unit_norm = tm.normalize_unit(unit)
    postal5 = tm.normalize_postal(postal)
    phone_digits = tm.digits_only(row.get("phone", ""))[-10:]
    email_norm = tm.normalize_email(row.get("email", ""))
    tax_hash = (row.get("tax_id_hash", "") or "").strip()
    dob = (row.get("date_of_birth", "") or "").strip()
    first_root = tm.given_name_root(first)
    last_soundex = tm.soundex(last.replace("-", " ").split(" ")[0])

    # Street number plus first street token: a cheap, high-recall locality key.
    street_tokens = address_norm.split()
    street_stub = " ".join(street_tokens[:2]) if street_tokens else ""

    record = {
        "record_id": f"{row['source_system']}:{row['source_customer_id']}",
        "source_system": row["source_system"],
        "source_customer_id": row["source_customer_id"],
        "first_name": first,
        "middle_initial": middle,
        "last_name": last,
        "full_name": " ".join(p for p in [first, middle, last] if p),
        "first_name_root": first_root,
        "last_name_soundex": last_soundex,
        "date_of_birth": dob,
        "birth_year": dob[:4] if len(dob) >= 4 else "",
        "tax_id_hash": tax_hash,
        "tax_id_last4": (row.get("tax_id_last4", "") or "").strip(),
        "address_line_1": street,
        "address_line_2": unit,
        "city": city,
        "state": state,
        "postal_code": postal,
        "address_norm": address_norm,
        "unit_norm": unit_norm,
        "postal5": postal5,
        "address_key": tm.address_key(street, unit, city, state, postal),
        "phone": row.get("phone", "") or "",
        "phone_digits": phone_digits,
        "email": row.get("email", "") or "",
        "email_norm": email_norm,
        "record_loaded_at": row.get("record_loaded_at", ""),
    }

    # Blocking keys. Each is either a usable key or empty. Empty never blocks,
    # which is what stops every record with a missing SSN from colliding.
    record["block_tax"] = f"TAX:{tax_hash}" if tax_hash else ""
    record["block_email"] = f"EML:{email_norm}" if email_norm else ""
    record["block_phone"] = f"PHN:{phone_digits}" if len(phone_digits) == 10 else ""
    record["block_name_postal"] = (
        f"NMP:{last_soundex}:{first_root[:3]}:{postal5}" if last_soundex and postal5 else ""
    )
    record["block_dob_postal"] = f"DBP:{dob}:{postal5[:3]}" if dob and postal5 else ""
    record["block_initial_street"] = (
        f"INS:{first_root[:1]}:{last_soundex}:{street_stub}" if street_stub and last_soundex else ""
    )
    return record


def build_silver(bronze: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Union CORE, CARD and CRM into one standardized Silver table."""
    frames = []
    for table in ("core_customer", "card_customer", "crm_contact"):
        df = bronze.get(table)
        if df is None or df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    raw = pd.concat(frames, ignore_index=True)
    records = [standardize_record(row) for _, row in raw.iterrows()]
    silver = pd.DataFrame(records)
    return silver.reindex(columns=SILVER_COLUMNS).fillna("")
