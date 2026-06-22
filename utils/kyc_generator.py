from __future__ import annotations

import random
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from utils.kyc_store import (
    CDD_ENHANCED,
    CDD_SIMPLIFIED,
    CDD_STANDARD,
    CUSTOMER_TYPE_CORPORATE,
    CUSTOMER_TYPE_INDIVIDUAL,
    KYC_COLUMNS,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    generate_customer_id,
)

KYC_TARGET_ROW_COUNT = 10_000

# Primary transaction dataset — unique Sender_account + Receiver_account values.
PRIMARY_TRANSACTION_DATASET = Path("Dataset.csv")

# Optional explicit account-id list in repo root.
ROOT_ACCOUNT_ID_CSV_CANDIDATES: tuple[Path, ...] = (
    Path("kyc_account_ids.csv"),
    Path("account_ids.csv"),
)

TRANSACTION_ACCOUNT_SOURCES: tuple[Path, ...] = (
    Path("Dataset.csv"),
    Path("data/pilot/aml_pilot_data.csv"),
    Path("data/demo/aml_demo_data.csv"),
)

SENDER_RECEIVER_COLUMNS: tuple[str, ...] = (
    "Sender_account",
    "Receiver_account",
)

ACCOUNT_COLUMN_ALIASES: tuple[str, ...] = (
    "account_id",
    "accountno",
    "account_no",
    "account",
    "sender_account",
    "receiver_account",
    "accountnumber",
    "acct",
    "acct_id",
)

_FIRST_NAMES = (
    "Elena", "James", "Amara", "Hiroshi", "Sophie", "Marcus", "Priya", "Daniel",
    "Isabella", "Thomas", "Chloe", "Oliver", "Fatima", "Liam", "Yuki", "Wei",
    "Ananya", "Carlos", "Nina", "Raj", "Emily", "Mohammed", "Sofia", "Kenji",
    "Aisha", "Lucas", "Mei", "David", "Grace", "Ahmed", "Anna", "Noah", "Zara",
    "Ethan", "Lin", "Maria", "Samuel", "Hannah", "Vikram", "Olivia", "Benjamin",
)

_LAST_NAMES = (
    "Vasquez", "Whitmore", "Okafor", "Tanaka", "Laurent", "Reid", "Sharma",
    "Kowalski", "Romero", "Berg", "Nguyen", "Grant", "Al-Hassan", "O'Connor",
    "Sato", "Chen", "Patel", "Silva", "Andersen", "Kim", "Williams", "Hassan",
    "Mueller", "Johnson", "Lee", "Garcia", "Brown", "Singh", "Martin", "Wong",
)

_NATIONALITIES = (
    "Singaporean", "British", "Japanese", "French", "Canadian",
    "Indian", "Polish", "Spanish", "German", "Australian", "American", "Emirati",
    "Irish", "Malaysian", "Brazilian", "Norwegian", "South Korean", "Italian",
    "Dutch", "Swedish", "Mexican", "Thai", "Indonesian", "New Zealander",
    # FATF grey-list nationalities (for realistic demo coverage)
    "Vietnamese", "Kenyan", "Lebanese", "Yemeni", "Venezuelan", "Syrian",
    "Kuwaiti", "Nepalese", "Angolan",
    # FATF EDD / black-list nationalities
    "Burmese", "Iranian", "North Korean",
)

_OCCUPATIONS = (
    "Software Engineer", "Accountant", "Teacher", "Nurse", "Sales Manager",
    "Operations Analyst", "Consultant", "Retail Manager", "Logistics Coordinator",
    "Marketing Manager", "Financial Analyst", "Architect", "Pharmacist",
    "Project Manager", "Data Analyst", "HR Specialist", "Legal Counsel",
)

_EMPLOYMENT = ("Employed", "Self-employed", "Retired", "Student", "Unemployed")

_PURPOSES = (
    "Personal savings and daily banking",
    "Salary crediting and bill payments",
    "Cross-border trade settlements",
    "Business operating account",
    "Investment and wealth management",
    "Family remittances",
    "Tuition and education fees",
)

_CITIES = (
    ("Singapore", "Singapore", "+65"),
    ("London", "UK", "+44"),
    ("Toronto", "Canada", "+1"),
    ("Sydney", "Australia", "+61"),
    ("Dubai", "UAE", "+971"),
    ("Mumbai", "India", "+91"),
    ("Berlin", "Germany", "+49"),
    ("Paris", "France", "+33"),
    ("Hanoi", "Vietnam", "+84"),
    ("Nairobi", "Kenya", "+254"),
    ("Yangon", "Myanmar", "+95"),
    ("Tehran", "Iran", "+98"),
)

_CORP_SUFFIXES = ("Pte Ltd", "Ltd", "GmbH", "Inc", "Holdings", "Group", "Trading")


def _normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _detect_account_column(df: pd.DataFrame) -> str | None:
    normalized = {_normalize_col(c): c for c in df.columns}
    for alias in ACCOUNT_COLUMN_ALIASES:
        if alias in normalized:
            return normalized[alias]
    if len(df.columns) == 1:
        return df.columns[0]
    for col in df.columns:
        if "account" in _normalize_col(col):
            return col
    return None


def _unique_account_ids(values: pd.Series) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values.astype(str).str.strip():
        if not raw or raw.lower() in {"nan", "none", "null"}:
            continue
        if raw.endswith(".0"):
            raw = raw[:-2]
        if raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
    return out


def load_account_ids_from_csv(path: Path, *, limit: int | None = None) -> list[str]:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    col = _detect_account_column(df)
    if col is None:
        raise ValueError(
            f"Could not detect an account-id column in {path.name}. "
            f"Expected one of: {', '.join(ACCOUNT_COLUMN_ALIASES)} or a single-column CSV."
        )
    ids = _unique_account_ids(df[col])
    if limit is not None:
        return ids[:limit]
    return ids


def load_account_ids_from_sender_receiver_csv(
    path: Path,
    *,
    limit: int | None = None,
) -> list[str]:
    """Collect unique account ids from Sender_account and Receiver_account columns."""
    df = pd.read_csv(path, dtype=str, low_memory=False)
    missing = [c for c in SENDER_RECEIVER_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path.name} is missing required columns: {missing}. "
            f"Expected {list(SENDER_RECEIVER_COLUMNS)}."
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for col in SENDER_RECEIVER_COLUMNS:
        for acct in _unique_account_ids(df[col]):
            if acct in seen:
                continue
            seen.add(acct)
            ordered.append(acct)
            if limit is not None and len(ordered) >= limit:
                return ordered
    return ordered


def load_account_ids_from_transactions(*, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in TRANSACTION_ACCOUNT_SOURCES:
        if not path.exists():
            continue
        try:
            batch = load_account_ids_from_sender_receiver_csv(path)
        except ValueError:
            continue
        for acct in batch:
            if acct in seen:
                continue
            seen.add(acct)
            ordered.append(acct)
            if limit is not None and len(ordered) >= limit:
                return ordered
    return ordered


def resolve_account_id_source() -> tuple[list[str], str]:
    """Return up to KYC_TARGET_ROW_COUNT account ids and a label describing the source."""
    if PRIMARY_TRANSACTION_DATASET.exists():
        ids = load_account_ids_from_sender_receiver_csv(
            PRIMARY_TRANSACTION_DATASET,
            limit=KYC_TARGET_ROW_COUNT,
        )
        if ids:
            return ids, f"{PRIMARY_TRANSACTION_DATASET} (Sender_account + Receiver_account)"

    for path in ROOT_ACCOUNT_ID_CSV_CANDIDATES:
        if path.exists():
            ids = load_account_ids_from_csv(path, limit=KYC_TARGET_ROW_COUNT)
            if ids:
                return ids, str(path)

    tx_ids = load_account_ids_from_transactions(limit=KYC_TARGET_ROW_COUNT)
    if tx_ids:
        return tx_ids, "transaction datasets (pilot + demo)"

    raise FileNotFoundError(
        "No account-id source found. Add Dataset.csv to the project root "
        "(with Sender_account and Receiver_account columns), kyc_account_ids.csv, "
        "or ensure data/pilot/aml_pilot_data.csv is present."
    )


def _random_dob(rng: random.Random) -> str:
    start = date(1955, 1, 1)
    end = date(2004, 12, 31)
    days = (end - start).days
    return (start + timedelta(days=rng.randint(0, days))).isoformat()


def _finalize_kyc_row(row: dict[str, str]) -> dict[str, str]:
    from utils.fatf_jurisdictions import apply_fatf_to_kyc_row

    row.setdefault("FATFJurisdiction", "")
    row.setdefault("FATFListCategory", "")
    return apply_fatf_to_kyc_row(row)


def _risk_profile(rng: random.Random) -> tuple[str, str]:
    roll = rng.random()
    if roll < 0.62:
        return RISK_LOW, CDD_SIMPLIFIED
    if roll < 0.85:
        return RISK_MEDIUM, CDD_STANDARD
    if roll < 0.97:
        return RISK_HIGH, CDD_ENHANCED
    return RISK_CRITICAL, CDD_ENHANCED


def _build_individual_row(account_no: str, customer_id: str, rng: random.Random) -> dict[str, str]:
    first = rng.choice(_FIRST_NAMES)
    last = rng.choice(_LAST_NAMES)
    nationality = rng.choice(_NATIONALITIES)
    city, country, dial = rng.choice(_CITIES)
    risk, cdd = _risk_profile(rng)
    email_slug = re.sub(r"[^a-z0-9]+", ".", f"{first}.{last}".lower()).strip(".")
    row = {
        "id": customer_id,
        "customer_type": CUSTOMER_TYPE_INDIVIDUAL,
        "FullName": f"{first} {last}",
        "Aliases": "",
        "DateOfBirth": _random_dob(rng),
        "Nationality": nationality,
        "NationalIdType": rng.choice(["NRIC", "Passport", "National ID"]),
        "NationalIdNumber": f"{rng.randint(10_000_000, 99_999_999)}",
        "Address": f"{rng.randint(1, 999)} {last} Street, {city}, {country}",
        "Email": f"{email_slug}{rng.randint(1, 999)}@email.com",
        "ContactNo": f"{dial} {rng.randint(7000, 9999)} {rng.randint(1000, 9999)}",
        "EmploymentStatus": rng.choice(_EMPLOYMENT),
        "Occupation": rng.choice(_OCCUPATIONS),
        "SourceOfWealth": rng.choice(
            ("Employment savings", "Family inheritance", "Business profits", "Property sale")
        ),
        "SourceOfIncome": rng.choice(
            ("Salary", "Business income", "Investments", "Pension", "Freelance fees")
        ),
        "PurposeOfAccount": rng.choice(_PURPOSES),
        "AccountNo": account_no,
        "RiskStatus": risk,
        "CDDLevel": cdd,
        "SanctionsReview": "",
        "LastCDDReviewAt": "",
        "Comments": "",
        "IsPEP": "Yes" if risk == RISK_CRITICAL and rng.random() < 0.35 else "No",
        "FlaggedBy": "",
        "FlaggedReason": "",
        "RiskIndicators": "",
        "SMApprovalStatus": "",
        "SMApprovedBy": "",
        "SMApprovedAt": "",
        "CompanyRegistrationNo": "",
        "RegisteredOperatingAddress": "",
        "UBOs": "",
        "CorporateDocuments": "",
        "FATFJurisdiction": "",
        "FATFListCategory": "",
    }
    return _finalize_kyc_row(row)


def _build_corporate_row(account_no: str, customer_id: str, rng: random.Random) -> dict[str, str]:
    stem = rng.choice(("Meridian", "Apex", "Global", "Pacific", "Summit", "Vertex", "Nexus"))
    sector = rng.choice(("Logistics", "Trading", "Energy", "Tech", "Manufacturing"))
    suffix = rng.choice(_CORP_SUFFIXES)
    name = f"{stem} {sector} {suffix}"
    city, country, dial = rng.choice(_CITIES)
    risk, cdd = _risk_profile(rng)
    reg = f"{rng.randint(2010, 2023)}{rng.randint(100000, 999999)}"
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())[:18]
    cdd_rank = {CDD_SIMPLIFIED: 0, CDD_STANDARD: 1, CDD_ENHANCED: 2}
    applied_cdd = max(cdd, CDD_STANDARD, key=lambda value: cdd_rank[value])
    row = {
        "id": customer_id,
        "customer_type": CUSTOMER_TYPE_CORPORATE,
        "FullName": name,
        "Aliases": "",
        "DateOfBirth": "",
        "Nationality": "",
        "NationalIdType": "Registration Number",
        "NationalIdNumber": reg,
        "Address": f"{rng.randint(1, 200)} Commerce Road, {city}, {country}",
        "Email": f"compliance@{slug}.com",
        "ContactNo": f"{dial} {rng.randint(6000, 6999)} {rng.randint(1000, 9999)}",
        "EmploymentStatus": "N/A",
        "Occupation": "N/A",
        "SourceOfWealth": "Business revenue and retained earnings",
        "SourceOfIncome": "Operating revenue",
        "PurposeOfAccount": rng.choice(
            ("Trade finance", "Treasury operations", "Supplier payments", "FX settlements")
        ),
        "AccountNo": account_no,
        "RiskStatus": risk,
        "CDDLevel": applied_cdd,
        "SanctionsReview": "",
        "LastCDDReviewAt": "",
        "Comments": f"Corporate client — {sector.lower()} sector",
        "IsPEP": "No",
        "FlaggedBy": "",
        "FlaggedReason": "",
        "RiskIndicators": "",
        "SMApprovalStatus": "",
        "SMApprovedBy": "",
        "SMApprovedAt": "",
        "CompanyRegistrationNo": reg,
        "RegisteredOperatingAddress": f"Industrial Park, {city}, {country}",
        "UBOs": (
            f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)} "
            f"({country}, {rng.randint(40, 85)}%, Director)"
        ),
        "CorporateDocuments": "Registry extract; Certificate of incorporation; UBO declaration",
        "FATFJurisdiction": "",
        "FATFListCategory": "",
    }
    return _finalize_kyc_row(row)


def generate_kyc_rows(
    account_ids: list[str],
    *,
    seed: int = 42,
    corporate_ratio: float = 0.05,
) -> list[dict[str, str]]:
    if not account_ids:
        raise ValueError("account_ids must not be empty")

    rng = random.Random(seed)
    existing_ids: set[str] = set()
    rows: list[dict[str, str]] = []

    for account_no in account_ids:
        customer_id = generate_customer_id(existing_ids)
        existing_ids.add(customer_id)
        if rng.random() < corporate_ratio:
            rows.append(_build_corporate_row(account_no, customer_id, rng))
        else:
            rows.append(_build_individual_row(account_no, customer_id, rng))

    from utils.kyc_store import apply_demo_sanctions_test_rows

    apply_demo_sanctions_test_rows(rows)
    return rows


def generate_kyc_database(
    *,
    row_count: int = KYC_TARGET_ROW_COUNT,
    seed: int = 42,
) -> tuple[pd.DataFrame, str]:
    account_ids, source = resolve_account_id_source()
    target = min(row_count, len(account_ids))
    if target < row_count:
        raise ValueError(
            f"Account source '{source}' only has {len(account_ids)} unique ids; "
            f"need at least {row_count}."
        )
    rows = generate_kyc_rows(account_ids[:target], seed=seed)
    return pd.DataFrame(rows, columns=KYC_COLUMNS), source
