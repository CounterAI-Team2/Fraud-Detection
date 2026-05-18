from __future__ import annotations

import random
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

KYC_PATH = Path("data/kyc_customers.csv")
IRAN_NAMES_PATH = Path("iran_names.txt")

KYC_COLUMNS = [
    "id",
    "FullName",
    "AccountNo",
    "Address",
    "ContactNo",
    "RiskStatus",
    "Comments",
]

RISK_LOW = "Low"
RISK_MEDIUM = "Medium"

MOCK_KYC_ROWS: list[dict[str, str]] = [
    {
        "id": "4624222122",
        "FullName": "Elena Vasquez",
        "AccountNo": "2512073279",
        "Address": "14 Marina View, Singapore 018961",
        "ContactNo": "+65 8123 4401",
        "RiskStatus": RISK_LOW,
        "Comments": "Priority retail; verified passport 2024",
    },
    {
        "id": "1847293056",
        "FullName": "James Whitmore",
        "AccountNo": "685933721",
        "Address": "88 Baker Street, London W1U 6RJ, UK",
        "ContactNo": "+44 7700 900321",
        "RiskStatus": RISK_LOW,
        "Comments": "SME payroll account",
    },
    {
        "id": "9031847265",
        "FullName": "Amara Okafor",
        "AccountNo": "6125211006",
        "Address": "22 Victoria Island, Lagos, Nigeria",
        "ContactNo": "+234 803 221 9988",
        "RiskStatus": RISK_LOW,
        "Comments": "Cross-border trade client",
    },
    {
        "id": "5519023847",
        "FullName": "Hiroshi Tanaka",
        "AccountNo": "566022042",
        "Address": "3-5-12 Shibuya, Tokyo 150-0002, Japan",
        "ContactNo": "+81 90 1234 5678",
        "RiskStatus": RISK_LOW,
        "Comments": "Tech contractor remittances",
    },
    {
        "id": "7721049583",
        "FullName": "Sophie Laurent",
        "AccountNo": "3797478122",
        "Address": "17 Rue de Rivoli, Paris 75001, France",
        "ContactNo": "+33 6 12 34 56 78",
        "RiskStatus": RISK_LOW,
        "Comments": "Private banking referral",
    },
    {
        "id": "3384710295",
        "FullName": "Marcus Reid",
        "AccountNo": "5855075691",
        "Address": "401 King Street West, Toronto ON M5V 1K4",
        "ContactNo": "+1 416 555 0192",
        "RiskStatus": RISK_LOW,
        "Comments": "University tuition payments",
    },
    {
        "id": "6190384721",
        "FullName": "Priya Sharma",
        "AccountNo": "6590269298",
        "Address": "9 MG Road, Bengaluru 560001, India",
        "ContactNo": "+91 98 7654 3210",
        "RiskStatus": RISK_LOW,
        "Comments": "Family support transfers",
    },
    {
        "id": "2048571936",
        "FullName": "Daniel Kowalski",
        "AccountNo": "73806488",
        "Address": "55 Nowy Swiat, Warsaw 00-042, Poland",
        "ContactNo": "+48 501 234 567",
        "RiskStatus": RISK_LOW,
        "Comments": "Import/export operating account",
    },
    {
        "id": "8901234567",
        "FullName": "Isabella Romero",
        "AccountNo": "1631823864",
        "Address": "Calle Mayor 12, Madrid 28013, Spain",
        "ContactNo": "+34 600 111 222",
        "RiskStatus": RISK_LOW,
        "Comments": "Hospitality sector",
    },
    {
        "id": "1273849506",
        "FullName": "Thomas Berg",
        "AccountNo": "2774166966",
        "Address": "Hauptstrasse 44, Berlin 10117, Germany",
        "ContactNo": "+49 151 9876 543",
        "RiskStatus": RISK_LOW,
        "Comments": "Manufacturing supplier payments",
    },
    {
        "id": "4455667788",
        "FullName": "Chloe Nguyen",
        "AccountNo": "4918821034",
        "Address": "220 Collins Street, Melbourne VIC 3000",
        "ContactNo": "+61 4 1234 5678",
        "RiskStatus": RISK_LOW,
        "Comments": "Freelance consulting income",
    },
    {
        "id": "9988776655",
        "FullName": "Oliver Grant",
        "AccountNo": "3301948572",
        "Address": "500 Fifth Avenue, New York NY 10110, USA",
        "ContactNo": "+1 212 555 0147",
        "RiskStatus": RISK_LOW,
        "Comments": "Legal trust distributions",
    },
    {
        "id": "3344556677",
        "FullName": "Fatima Al-Hassan",
        "AccountNo": "7182930456",
        "Address": "Sheikh Zayed Road, Dubai, UAE",
        "ContactNo": "+971 50 123 4567",
        "RiskStatus": RISK_LOW,
        "Comments": "Real estate escrow",
    },
    {
        "id": "5566778899",
        "FullName": "Liam O'Connor",
        "AccountNo": "9021345678",
        "Address": "12 St Stephen's Green, Dublin 2, Ireland",
        "ContactNo": "+353 87 123 4567",
        "RiskStatus": RISK_LOW,
        "Comments": "Charity foundation treasurer",
    },
    {
        "id": "6677889900",
        "FullName": "Yuki Sato",
        "AccountNo": "1048572930",
        "Address": "2-8-1 Nishi-Shinjuku, Tokyo 163-8001, Japan",
        "ContactNo": "+81 80 9876 5432",
        "RiskStatus": RISK_LOW,
        "Comments": "Corporate travel card settlement",
    },
]


def _ensure_parent() -> None:
    KYC_PATH.parent.mkdir(parents=True, exist_ok=True)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


@lru_cache(maxsize=1)
def load_iran_sanctions_names() -> frozenset[str]:
    if not IRAN_NAMES_PATH.exists():
        return frozenset()
    lines = IRAN_NAMES_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(_normalize_name(line) for line in lines if line.strip())


def name_on_un_sanctions_list(full_name: str) -> bool:
    normalized = _normalize_name(full_name)
    if not normalized:
        return False
    sanctions = load_iran_sanctions_names()
    if normalized in sanctions:
        return True
    for entry in sanctions:
        if entry in normalized or normalized in entry:
            return True
    return False


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
            return
    seed = pd.DataFrame(MOCK_KYC_ROWS, columns=KYC_COLUMNS)
    seed.to_csv(KYC_PATH, index=False)


def get_kyc_customers() -> pd.DataFrame:
    ensure_kyc_database()
    df = pd.read_csv(KYC_PATH, dtype=str)
    for column in KYC_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[KYC_COLUMNS].fillna("")


def save_kyc_customers(df: pd.DataFrame) -> None:
    _ensure_parent()
    out = df.copy()
    for column in KYC_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out[KYC_COLUMNS].to_csv(KYC_PATH, index=False)


def enrol_customer(
    full_name: str,
    account_no: str,
    address: str,
    contact_no: str,
    comments: str = "",
) -> tuple[dict[str, str], bool]:
    """Register a customer. Returns (row, sanctions_warning_shown)."""
    customers = get_kyc_customers()
    existing_ids = set(customers["id"].astype(str))
    existing_accounts = set(customers["AccountNo"].astype(str).str.strip())

    account_no = str(account_no).strip()
    if account_no in existing_accounts:
        raise ValueError(f"Account number {account_no} is already registered.")

    row = {
        "id": generate_customer_id(existing_ids),
        "FullName": full_name.strip(),
        "AccountNo": account_no,
        "Address": address.strip(),
        "ContactNo": contact_no.strip(),
        "RiskStatus": RISK_LOW,
        "Comments": comments.strip(),
    }
    customers = pd.concat([customers, pd.DataFrame([row])], ignore_index=True)
    save_kyc_customers(customers)
    return row, name_on_un_sanctions_list(full_name)


def _accounts_in_suspicious_transactions(scored_df: pd.DataFrame) -> set[str]:
    if scored_df is None or scored_df.empty:
        return set()
    suspicious = scored_df[scored_df["rf_prediction"].astype(int) == 1]
    if suspicious.empty:
        return set()
    involved: set[str] = set()
    for column in ("Sender_account", "Receiver_account", "transaction_id"):
        if column not in suspicious.columns:
            continue
        involved.update(suspicious[column].astype(str).str.strip())
    return {value for value in involved if value}


def upgrade_kyc_risk_from_transactions(scored_df: pd.DataFrame) -> list[str]:
    """Upgrade Low -> Medium when customer id or account appears on suspicious txns."""
    involved = _accounts_in_suspicious_transactions(scored_df)
    if not involved:
        return []

    customers = get_kyc_customers()
    upgraded_ids: list[str] = []
    for idx, row in customers.iterrows():
        if str(row["RiskStatus"]).strip().lower() != RISK_LOW.lower():
            continue
        customer_id = str(row["id"]).strip()
        account_no = str(row["AccountNo"]).strip()
        if customer_id in involved or account_no in involved:
            customers.at[idx, "RiskStatus"] = RISK_MEDIUM
            upgraded_ids.append(customer_id)

    if upgraded_ids:
        save_kyc_customers(customers)
    return upgraded_ids
