from __future__ import annotations

import random
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

KYC_PATH = Path("data/kyc_customers.csv")
IRAN_NAMES_PATH = Path("iran_names.txt")

# Persisted KYC schema. Older CSVs missing the trailing CDD/sanctions columns
# are migrated in-place by ``get_kyc_customers``.
KYC_COLUMNS = [
    "id",
    "FullName",
    "AccountNo",
    "Address",
    "ContactNo",
    "RiskStatus",
    "CDDLevel",
    "SanctionsReview",
    "LastCDDReviewAt",
    "Comments",
]

RISK_LOW = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH = "High"

CDD_SIMPLIFIED = "Simplified"
CDD_STANDARD = "Standard"
CDD_ENHANCED = "Enhanced"

SANCTIONS_REVIEW_NONE = ""
SANCTIONS_REVIEW_PENDING = "Pending"
SANCTIONS_REVIEW_CLEARED = "Cleared"
SANCTIONS_REVIEW_ESCALATED = "Escalated"


def _seed_row(
    customer_id: str,
    full_name: str,
    account_no: str,
    address: str,
    contact_no: str,
    comments: str,
) -> dict[str, str]:
    return {
        "id": customer_id,
        "FullName": full_name,
        "AccountNo": account_no,
        "Address": address,
        "ContactNo": contact_no,
        "RiskStatus": RISK_LOW,
        "CDDLevel": CDD_SIMPLIFIED,
        "SanctionsReview": SANCTIONS_REVIEW_NONE,
        "LastCDDReviewAt": "",
        "Comments": comments,
    }


MOCK_KYC_ROWS: list[dict[str, str]] = [
    _seed_row("4624222122", "Elena Vasquez",   "2512073279", "14 Marina View, Singapore 018961",          "+65 8123 4401",     "Priority retail; verified passport 2024"),
    _seed_row("1847293056", "James Whitmore",  "685933721",  "88 Baker Street, London W1U 6RJ, UK",        "+44 7700 900321",   "SME payroll account"),
    _seed_row("9031847265", "Amara Okafor",    "6125211006", "22 Victoria Island, Lagos, Nigeria",         "+234 803 221 9988", "Cross-border trade client"),
    _seed_row("5519023847", "Hiroshi Tanaka",  "566022042",  "3-5-12 Shibuya, Tokyo 150-0002, Japan",      "+81 90 1234 5678",  "Tech contractor remittances"),
    _seed_row("7721049583", "Sophie Laurent",  "3797478122", "17 Rue de Rivoli, Paris 75001, France",      "+33 6 12 34 56 78", "Private banking referral"),
    _seed_row("3384710295", "Marcus Reid",     "5855075691", "401 King Street West, Toronto ON M5V 1K4",   "+1 416 555 0192",   "University tuition payments"),
    _seed_row("6190384721", "Priya Sharma",    "6590269298", "9 MG Road, Bengaluru 560001, India",         "+91 98 7654 3210",  "Family support transfers"),
    _seed_row("2048571936", "Daniel Kowalski", "73806488",   "55 Nowy Swiat, Warsaw 00-042, Poland",       "+48 501 234 567",   "Import/export operating account"),
    _seed_row("8901234567", "Isabella Romero", "1631823864", "Calle Mayor 12, Madrid 28013, Spain",        "+34 600 111 222",   "Hospitality sector"),
    _seed_row("1273849506", "Thomas Berg",     "2774166966", "Hauptstrasse 44, Berlin 10117, Germany",     "+49 151 9876 543",  "Manufacturing supplier payments"),
    _seed_row("4455667788", "Chloe Nguyen",    "4918821034", "220 Collins Street, Melbourne VIC 3000",     "+61 4 1234 5678",   "Freelance consulting income"),
    _seed_row("9988776655", "Oliver Grant",    "3301948572", "500 Fifth Avenue, New York NY 10110, USA",   "+1 212 555 0147",   "Legal trust distributions"),
    _seed_row("3344556677", "Fatima Al-Hassan","7182930456", "Sheikh Zayed Road, Dubai, UAE",              "+971 50 123 4567",  "Real estate escrow"),
    _seed_row("5566778899", "Liam O'Connor",   "9021345678", "12 St Stephen's Green, Dublin 2, Ireland",   "+353 87 123 4567",  "Charity foundation treasurer"),
    _seed_row("6677889900", "Yuki Sato",       "1048572930", "2-8-1 Nishi-Shinjuku, Tokyo 163-8001, Japan","+81 80 9876 5432",  "Corporate travel card settlement"),
]


def _ensure_parent() -> None:
    KYC_PATH.parent.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


@lru_cache(maxsize=1)
def load_iran_sanctions_names() -> frozenset[str]:
    """Fallback sanctions source bundled with the repo."""
    if not IRAN_NAMES_PATH.exists():
        return frozenset()
    lines = IRAN_NAMES_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(_normalize_name(line) for line in lines if line.strip())


def name_on_un_sanctions_list(full_name: str) -> bool:
    """Backward-compatible boolean screen used by older call sites."""
    from utils.mas_sanctions_sync import screen_name  # local import to avoid cycle

    return screen_name(full_name)["matched"]


def generate_customer_id(existing_ids: set[str] | None = None) -> str:
    existing = existing_ids or set()
    for _ in range(500):
        candidate = str(random.randint(1_000_000_000, 9_999_999_999))
        if candidate not in existing:
            return candidate
    raise RuntimeError("Unable to generate a unique 10-digit customer id")


def ensure_kyc_database() -> None:
    _ensure_parent()
    if KYC_PATH.exists():
        df = pd.read_csv(KYC_PATH)
        if not df.empty:
            # Backfill any newly added columns without losing existing rows.
            changed = False
            for column in KYC_COLUMNS:
                if column not in df.columns:
                    df[column] = CDD_SIMPLIFIED if column == "CDDLevel" else ""
                    changed = True
            if changed:
                df[KYC_COLUMNS].to_csv(KYC_PATH, index=False)
            return
    seed = pd.DataFrame(MOCK_KYC_ROWS, columns=KYC_COLUMNS)
    seed.to_csv(KYC_PATH, index=False)


def get_kyc_customers() -> pd.DataFrame:
    ensure_kyc_database()
    df = pd.read_csv(KYC_PATH, dtype=str)
    for column in KYC_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[KYC_COLUMNS].fillna("")
    # Default any blank CDD level to Simplified so downstream rules stay safe.
    df.loc[df["CDDLevel"].astype(str).str.strip() == "", "CDDLevel"] = CDD_SIMPLIFIED
    return df


def save_kyc_customers(df: pd.DataFrame) -> None:
    _ensure_parent()
    out = df.copy()
    for column in KYC_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out[KYC_COLUMNS].to_csv(KYC_PATH, index=False)


def get_kyc_by_account(account_no: str) -> dict[str, str] | None:
    """Return a KYC row (as dict) matching an account number, or None."""
    if not account_no:
        return None
    customers = get_kyc_customers()
    needle = str(account_no).strip()
    match = customers[customers["AccountNo"].astype(str).str.strip() == needle]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_kyc_by_id(customer_id: str) -> dict[str, str] | None:
    if not customer_id:
        return None
    customers = get_kyc_customers()
    match = customers[customers["id"].astype(str) == str(customer_id)]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def update_kyc_record(customer_id: str, updates: dict[str, str]) -> dict[str, str] | None:
    customers = get_kyc_customers()
    mask = customers["id"].astype(str) == str(customer_id)
    if not mask.any():
        return None
    for key, value in updates.items():
        if key not in KYC_COLUMNS:
            continue
        customers.loc[mask, key] = value
    customers.loc[mask, "LastCDDReviewAt"] = _utc_now_iso()
    save_kyc_customers(customers)
    return customers.loc[mask].iloc[0].to_dict()


def enrol_customer(
    full_name: str,
    account_no: str,
    address: str,
    contact_no: str,
    comments: str = "",
    sanctions_match: dict | None = None,
) -> tuple[dict[str, str], dict]:
    """Register a customer. Returns (row, sanctions_match_info)."""
    from utils.mas_sanctions_sync import screen_name  # local import to avoid cycle

    customers = get_kyc_customers()
    existing_ids = set(customers["id"].astype(str))
    existing_accounts = set(customers["AccountNo"].astype(str).str.strip())

    account_no = str(account_no).strip()
    if account_no in existing_accounts:
        raise ValueError(f"Account number {account_no} is already registered.")

    match_info = sanctions_match if sanctions_match is not None else screen_name(full_name)
    sanctions_review = SANCTIONS_REVIEW_PENDING if match_info.get("matched") else SANCTIONS_REVIEW_NONE

    row = {
        "id": generate_customer_id(existing_ids),
        "FullName": full_name.strip(),
        "AccountNo": account_no,
        "Address": address.strip(),
        "ContactNo": contact_no.strip(),
        "RiskStatus": RISK_LOW,
        "CDDLevel": CDD_SIMPLIFIED,
        "SanctionsReview": sanctions_review,
        "LastCDDReviewAt": _utc_now_iso(),
        "Comments": comments.strip(),
    }
    customers = pd.concat([customers, pd.DataFrame([row])], ignore_index=True)
    save_kyc_customers(customers)
    return row, match_info


def _suspicious_accounts(scored_df: pd.DataFrame) -> dict[str, str]:
    """Map account/id -> highest risk tier seen on a flagged transaction."""
    if scored_df is None or scored_df.empty:
        return {}
    suspicious = scored_df[scored_df["rf_prediction"].astype(int) == 1]
    if suspicious.empty:
        return {}

    tier_rank = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    involved: dict[str, str] = {}

    def _record(key: str, tier: str) -> None:
        key = str(key).strip()
        if not key:
            return
        prior = involved.get(key, "Low")
        if tier_rank.get(tier, 0) > tier_rank.get(prior, 0):
            involved[key] = tier

    for _, txn in suspicious.iterrows():
        tier = str(txn.get("risk_tier", "Medium"))
        for column in ("Sender_account", "Receiver_account", "transaction_id"):
            if column in suspicious.columns:
                _record(txn.get(column, ""), tier)
    return involved


def upgrade_kyc_risk_from_transactions(scored_df: pd.DataFrame) -> list[str]:
    """Backward-compat shim: still returns the list of upgraded customer ids."""
    result = apply_cdd_escalation_from_transactions(scored_df)
    return [item["id"] for item in result]


def apply_cdd_escalation_from_transactions(scored_df: pd.DataFrame) -> list[dict[str, str]]:
    """
    Walk each KYC customer and upgrade RiskStatus + CDDLevel based on the highest
    risk tier their account/id appears under in flagged transactions.

    Returns the list of changed rows (id, old/new RiskStatus, old/new CDDLevel).
    """
    from utils.cdd_rules import recommend_cdd_level, recommend_risk_status  # avoid cycle

    involved = _suspicious_accounts(scored_df)
    if not involved:
        return []

    customers = get_kyc_customers()
    changes: list[dict[str, str]] = []
    now = _utc_now_iso()

    for idx, row in customers.iterrows():
        customer_id = str(row["id"]).strip()
        account_no = str(row["AccountNo"]).strip()
        hit_tier = involved.get(customer_id) or involved.get(account_no)
        if not hit_tier:
            continue

        sanctions_pending = str(row.get("SanctionsReview", "")).strip() == SANCTIONS_REVIEW_PENDING
        new_risk = recommend_risk_status(row["RiskStatus"], hit_tier)
        new_cdd = recommend_cdd_level(
            current_cdd=row["CDDLevel"],
            risk_status=new_risk,
            top_txn_tier=hit_tier,
            sanctions_pending=sanctions_pending,
        )

        if new_risk == row["RiskStatus"] and new_cdd == row["CDDLevel"]:
            continue

        change = {
            "id": customer_id,
            "FullName": str(row["FullName"]),
            "old_risk": str(row["RiskStatus"]),
            "new_risk": new_risk,
            "old_cdd": str(row["CDDLevel"]),
            "new_cdd": new_cdd,
            "trigger_tier": hit_tier,
        }
        customers.at[idx, "RiskStatus"] = new_risk
        customers.at[idx, "CDDLevel"] = new_cdd
        customers.at[idx, "LastCDDReviewAt"] = now
        changes.append(change)

    if changes:
        save_kyc_customers(customers)
    return changes
