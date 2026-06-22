from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

KYC_PATH = Path("data/kyc_customers.csv")
KYC_META_PATH = Path("data/kyc_generation_meta.json")
IRAN_NAMES_PATH = Path("iran_names.txt")

KYC_SEARCH_COLUMNS = [
    "FullName",
    "Aliases",
    "id",
    "AccountNo",
    "Email",
    "Nationality",
    "NationalIdNumber",
    "Occupation",
    "Address",
    "ContactNo",
    "PurposeOfAccount",
    "CompanyRegistrationNo",
    "FATFJurisdiction",
    "FATFListCategory",
    # Transaction monitoring linkage fields.
    "flagged_transaction_count",
    "last_reviewed",
    "review_notes",
]

KYC_PAGE_SIZE_DEFAULT = 50

CUSTOMER_TYPE_INDIVIDUAL = "Individual"
CUSTOMER_TYPE_CORPORATE = "Corporate"

# Persisted KYC schema. Older CSVs missing columns are migrated in ``get_kyc_customers``.
KYC_COLUMNS = [
    "id",
    "customer_type",
    # --- 1. CIP (Customer Identification Program) ---
    "FullName",
    "Aliases",
    "DateOfBirth",
    "Nationality",
    "NationalIdType",
    "NationalIdNumber",
    # --- 2. Contact & proof of residence ---
    "Address",
    "Email",
    "ContactNo",
    # --- 3. Financial profile & employment ---
    "EmploymentStatus",
    "Occupation",
    "SourceOfWealth",
    "SourceOfIncome",
    "PurposeOfAccount",
    # --- 4. Account & risk (operational) ---
    "AccountNo",
    "RiskStatus",
    "CDDLevel",
    "SanctionsReview",
    "SanctionsMatchedName",
    "SanctionsListKey",
    "SanctionsMatchScore",
    "SanctionsMatchType",
    "LastCDDReviewAt",
    "Comments",
    "flagged_transaction_count",
    "last_reviewed",
    "review_notes",
    "IsPEP",
    "FlaggedBy",
    "FlaggedReason",
    "RiskIndicators",
    "SMApprovalStatus",
    "SMApprovedBy",
    "SMApprovedAt",
    # --- 5. Corporate / business (when customer_type == Corporate) ---
    "CompanyRegistrationNo",
    "RegisteredOperatingAddress",
    "UBOs",
    "CorporateDocuments",
    # --- FATF jurisdiction screening (Feb 2026 lists) ---
    "FATFJurisdiction",
    "FATFListCategory",
]

# Overview table columns (summary only).
KYC_OVERVIEW_COLUMNS = [
    "FullName",
    "AccountNo",
    "customer_type",
    "RiskStatus",
    "CDDLevel",
    "SanctionsReview",
]

RISK_LOW = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH = "High"
RISK_CRITICAL = "Critical"

CUSTOMER_RISK_STATUSES = [RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL]

CDD_SIMPLIFIED = "Simplified"
CDD_ENHANCED = "Enhanced"

SANCTIONS_REVIEW_NONE = ""
SANCTIONS_REVIEW_PENDING = "Pending"
SANCTIONS_REVIEW_FUZZY = "Fuzzy — Review Required"
SANCTIONS_REVIEW_CONFIRMED = "Confirmed"
SANCTIONS_REVIEW_CLEARED = "Cleared"
SANCTIONS_REVIEW_ESCALATED = "Escalated"

SANCTIONS_ACTIVE_REVIEW_STATUSES = frozenset({
    SANCTIONS_REVIEW_PENDING,
    SANCTIONS_REVIEW_FUZZY,
    SANCTIONS_REVIEW_CONFIRMED,
    SANCTIONS_REVIEW_ESCALATED,
})

# First rows in the generated KYC database — used to demo exact/fuzzy sanctions hits.
DEMO_SANCTIONS_TEST_PROFILES: tuple[dict[str, str], ...] = (
    {
        "FullName": "Aiman Muhammed Rabi Al-Zawahiri",
        "Nationality": "Egyptian",
        "Occupation": "Demo — sanctions exact match",
        "Comments": "Demo account seeded for sanctions exact-match testing.",
    },
    {
        "FullName": "Agus Dwikarna",
        "Nationality": "Indonesian",
        "Occupation": "Demo — sanctions exact match",
        "Comments": "Demo account seeded for sanctions exact-match testing.",
    },
    {
        "FullName": "Ahmed Khalafan Ghailani",
        "Nationality": "Tanzanian",
        "Occupation": "Demo — sanctions fuzzy match",
        "Comments": "Demo account seeded for sanctions fuzzy-match testing.",
    },
    {
        "FullName": "Mohammed Reza Zahedi",
        "Nationality": "Iranian",
        "Occupation": "Demo — sanctions fuzzy match",
        "Comments": "Demo account seeded for sanctions fuzzy-match testing.",
    },
)

_DEMO_ENRICHMENT: dict[str, dict[str, str]] = {}


def _empty_kyc_fields() -> dict[str, str]:
    return {col: "" for col in KYC_COLUMNS if col != "id"}


def _seed_individual(
    customer_id: str,
    full_name: str,
    account_no: str,
    *,
    aliases: str = "",
    dob: str = "",
    nationality: str = "",
    id_type: str = "Passport",
    id_number: str = "",
    address: str = "",
    email: str = "",
    contact_no: str = "",
    employment: str = "Employed",
    occupation: str = "",
    source_of_wealth: str = "",
    source_of_income: str = "",
    purpose: str = "",
    comments: str = "",
    risk: str = RISK_LOW,
    cdd: str = CDD_SIMPLIFIED,
    is_pep: str = "No",
    sanctions: str = SANCTIONS_REVIEW_NONE,
) -> dict[str, str]:
    row = _empty_kyc_fields()
    row.update(
        {
            "id": customer_id,
            "customer_type": CUSTOMER_TYPE_INDIVIDUAL,
            "FullName": full_name,
            "Aliases": aliases,
            "DateOfBirth": dob,
            "Nationality": nationality,
            "NationalIdType": id_type,
            "NationalIdNumber": id_number,
            "Address": address,
            "Email": email,
            "ContactNo": contact_no,
            "EmploymentStatus": employment,
            "Occupation": occupation,
            "SourceOfWealth": source_of_wealth,
            "SourceOfIncome": source_of_income,
            "PurposeOfAccount": purpose,
            "AccountNo": account_no,
            "RiskStatus": risk,
            "CDDLevel": cdd,
            "SanctionsReview": sanctions,
            "Comments": comments,
            "IsPEP": is_pep,
        }
    )
    _DEMO_ENRICHMENT[customer_id] = {k: v for k, v in row.items() if k != "id"}
    return row


def _seed_corporate(
    customer_id: str,
    company_name: str,
    account_no: str,
    *,
    reg_no: str,
    registered_address: str,
    operating_address: str,
    contact_no: str,
    email: str,
    ubos: str,
    documents: str,
    purpose: str = "",
    comments: str = "",
    risk: str = RISK_LOW,
    cdd: str = CDD_SIMPLIFIED,
) -> dict[str, str]:
    row = _empty_kyc_fields()
    row.update(
        {
            "id": customer_id,
            "customer_type": CUSTOMER_TYPE_CORPORATE,
            "FullName": company_name,
            "Aliases": "",
            "Nationality": "",
            "NationalIdType": "Registration Number",
            "NationalIdNumber": reg_no,
            "Address": registered_address,
            "Email": email,
            "ContactNo": contact_no,
            "EmploymentStatus": "N/A",
            "Occupation": "N/A",
            "SourceOfWealth": "Business revenue and retained earnings",
            "SourceOfIncome": "Operating revenue",
            "PurposeOfAccount": purpose,
            "AccountNo": account_no,
            "RiskStatus": risk,
            "CDDLevel": cdd,
            "CompanyRegistrationNo": reg_no,
            "RegisteredOperatingAddress": operating_address,
            "UBOs": ubos,
            "CorporateDocuments": documents,
            "Comments": comments,
            "IsPEP": "No",
        }
    )
    _DEMO_ENRICHMENT[customer_id] = {k: v for k, v in row.items() if k != "id"}
    return row


MOCK_KYC_ROWS: list[dict[str, str]] = [
    _seed_individual(
        "4624222122", "Elena Vasquez", "2512073279",
        aliases="E. Vasquez",
        dob="1988-03-14", nationality="Singaporean",
        id_type="NRIC", id_number="S8812345A",
        address="14 Marina View, Singapore 018961",
        email="elena.vasquez@email.sg", contact_no="+65 8123 4401",
        employment="Employed", occupation="Senior Marketing Manager",
        source_of_wealth="Salary savings; property sale 2019",
        source_of_income="Employment (TechCorp Pte Ltd)",
        purpose="Personal savings and daily banking",
        comments="Priority retail; verified passport 2024",
        risk=RISK_MEDIUM, cdd=CDD_SIMPLIFIED,
    ),
    _seed_individual(
        "1847293056", "James Whitmore", "685933721",
        aliases="J. Whitmore",
        dob="1975-11-02", nationality="British",
        id_type="Passport", id_number="GB123456789",
        address="88 Baker Street, London W1U 6RJ, UK",
        email="j.whitmore@ukmail.com", contact_no="+44 7700 900321",
        employment="Self-employed", occupation="Management Consultant",
        source_of_wealth="Consulting income; ISA investments",
        source_of_income="Professional fees",
        purpose="SME payroll and operating expenses",
        comments="SME payroll account",
    ),
    _seed_individual(
        "9031847265", "Amara Okafor", "6125211006",
        dob="1990-07-22", nationality="Nigerian",
        id_type="Passport", id_number="A12345678",
        address="22 Victoria Island, Lagos, Nigeria",
        email="amara.okafor@trade.ng", contact_no="+234 803 221 9988",
        employment="Employed", occupation="Import/Export Trader",
        source_of_wealth="Family business; trade profits",
        source_of_income="Okafor Trading Ltd dividends",
        purpose="Cross-border trade settlements",
        comments="Cross-border trade client",
    ),
    _seed_individual(
        "5519023847", "Hiroshi Tanaka", "566022042",
        dob="1982-01-30", nationality="Japanese",
        id_type="Passport", id_number="TR1234567",
        address="3-5-12 Shibuya, Tokyo 150-0002, Japan",
        email="hiroshi.tanaka@jp.ne.jp", contact_no="+81 90 1234 5678",
        employment="Contractor", occupation="Software Engineer",
        source_of_wealth="Employment history in fintech",
        source_of_income="Contract remittances",
        purpose="Personal remittances and savings",
        comments="Tech contractor remittances",
        risk=RISK_MEDIUM, cdd=CDD_SIMPLIFIED,
    ),
    _seed_individual(
        "7721049583", "Sophie Laurent", "3797478122",
        dob="1968-05-18", nationality="French",
        id_type="Passport", id_number="12AB34567",
        address="17 Rue de Rivoli, Paris 75001, France",
        email="s.laurent@banque-privee.fr", contact_no="+33 6 12 34 56 78",
        employment="Retired", occupation="Former Investment Banker",
        source_of_wealth="Career earnings; portfolio investments",
        source_of_income="Pension and investment returns",
        purpose="Private banking and wealth management",
        comments="Private banking referral",
    ),
    _seed_individual(
        "3384710295", "Marcus Reid", "5855075691",
        dob="2001-09-03", nationality="Canadian",
        id_type="Passport", id_number="CA9876543",
        address="401 King Street West, Toronto ON M5V 1K4",
        email="marcus.reid@student.ca", contact_no="+1 416 555 0192",
        employment="Student", occupation="University Student",
        source_of_wealth="Parental support",
        source_of_income="Family transfers; part-time work",
        purpose="Tuition and living expenses",
        comments="University tuition payments",
    ),
    _seed_individual(
        "6190384721", "Priya Sharma", "6590269298",
        dob="1985-12-08", nationality="Indian",
        id_type="Passport", id_number="Z1234567",
        address="9 MG Road, Bengaluru 560001, India",
        email="priya.sharma@inbox.in", contact_no="+91 98 7654 3210",
        employment="Employed", occupation="Healthcare Administrator",
        source_of_wealth="Salary; family property",
        source_of_income="Hospital salary",
        purpose="Family support transfers",
        comments="Family support transfers",
        risk=RISK_MEDIUM, cdd=CDD_SIMPLIFIED,
    ),
    _seed_individual(
        "2048571936", "Daniel Kowalski", "73806488",
        dob="1978-04-25", nationality="Polish",
        id_type="National ID", id_number="78042512345",
        address="55 Nowy Swiat, Warsaw 00-042, Poland",
        email="d.kowalski@logistics.pl", contact_no="+48 501 234 567",
        employment="Employed", occupation="Logistics Director",
        source_of_wealth="Business ownership (30% stake)",
        source_of_income="Salary and dividends",
        purpose="Import/export operating account",
        comments="Import/export operating account",
    ),
    _seed_individual(
        "8901234567", "Isabella Romero", "1631823864",
        dob="1993-06-11", nationality="Spanish",
        id_type="National ID", id_number="12345678Z",
        address="Calle Mayor 12, Madrid 28013, Spain",
        email="isabella.romero@hosp.es", contact_no="+34 600 111 222",
        employment="Employed", occupation="Hotel Operations Manager",
        source_of_wealth="Employment savings",
        source_of_income="Salary (hospitality group)",
        purpose="Operating account for hospitality business",
        comments="Hospitality sector",
    ),
    _seed_individual(
        "1273849506", "Thomas Berg", "2774166966",
        dob="1970-08-19", nationality="German",
        id_type="Passport", id_number="C01X00T47",
        address="Hauptstrasse 44, Berlin 10117, Germany",
        email="t.berg@manufacturing.de", contact_no="+49 151 9876 543",
        employment="Employed", occupation="Procurement Manager",
        source_of_wealth="Long-term employment; pension fund",
        source_of_income="Manufacturing group salary",
        purpose="Supplier payments",
        comments="Manufacturing supplier payments",
    ),
    _seed_individual(
        "4455667788", "Chloe Nguyen", "4918821034",
        dob="1995-02-27", nationality="Australian",
        id_type="Passport", id_number="PA1234567",
        address="220 Collins Street, Melbourne VIC 3000",
        email="chloe.nguyen@consult.au", contact_no="+61 4 1234 5678",
        employment="Self-employed", occupation="Management Consultant",
        source_of_wealth="Consulting practice",
        source_of_income="Client invoices",
        purpose="Business and personal mixed use",
        comments="Freelance consulting income",
    ),
    _seed_individual(
        "9988776655", "Oliver Grant", "3301948572",
        dob="1960-10-05", nationality="American",
        id_type="Passport", id_number="500123456",
        address="500 Fifth Avenue, New York NY 10110, USA",
        email="oliver.grant@trustlaw.com", contact_no="+1 212 555 0147",
        employment="Employed", occupation="Trust & Estates Attorney",
        source_of_wealth="Legal practice; trust distributions",
        source_of_income="Law firm partnership",
        purpose="Trust distributions and legal settlements",
        comments="Legal trust distributions",
    ),
    _seed_individual(
        "3344556677", "Fatima Al-Hassan", "7182930456",
        dob="1987-11-30", nationality="Emirati",
        id_type="Emirates ID", id_number="784-1987-1234567-1",
        address="Sheikh Zayed Road, Dubai, UAE",
        email="fatima.alhassan@re.ae", contact_no="+971 50 123 4567",
        employment="Employed", occupation="Real Estate Director",
        source_of_wealth="Property portfolio; family business",
        source_of_income="Salary and rental income",
        purpose="Real estate escrow and settlements",
        comments="Real estate escrow",
    ),
    _seed_individual(
        "5566778899", "Liam O'Connor", "9021345678",
        dob="1972-03-09", nationality="Irish",
        id_type="Passport", id_number="IE9876543",
        address="12 St Stephen's Green, Dublin 2, Ireland",
        email="liam.oconnor@charity.ie", contact_no="+353 87 123 4567",
        employment="Employed", occupation="Non-profit Treasurer",
        source_of_wealth="Employment; charitable grants oversight",
        source_of_income="NGO salary",
        purpose="Charity foundation operations",
        comments="Charity foundation treasurer",
    ),
    _seed_individual(
        "6677889900", "Yuki Sato", "1048572930",
        dob="1989-12-01", nationality="Japanese",
        id_type="Passport", id_number="TK7654321",
        address="2-8-1 Nishi-Shinjuku, Tokyo 163-8001, Japan",
        email="yuki.sato@corp.jp", contact_no="+81 80 9876 5432",
        employment="Employed", occupation="Corporate Finance Analyst",
        source_of_wealth="Employment savings",
        source_of_income="Corporate salary",
        purpose="Corporate travel card settlement",
        comments="Corporate travel card settlement",
    ),
    _seed_corporate(
        "8811223344", "Meridian Logistics Pte Ltd", "SG-CORP-4401",
        reg_no="201912345G",
        registered_address="10 Anson Road, #22-02, Singapore 079903",
        operating_address="Tuas South Avenue 3, Singapore 637025",
        contact_no="+65 6789 0011",
        email="compliance@meridianlogistics.sg",
        ubos="Tan Wei Ming (SG, 60%, Director) | Sarah Koh (SG, 25%, Shareholder) | Apex Holdings Ltd (15%, corporate shareholder)",
        documents="ACRA BizFile (2024); Certificate of Incorporation; Board resolution — account opening",
        purpose="Trade finance and supplier payments",
        comments="Regional freight forwarder",
        cdd=CDD_SIMPLIFIED,
    ),
    _seed_corporate(
        "9922334455", "Nordic Green Energy AS", "NO-CORP-5502",
        reg_no="NO 923 456 789",
        registered_address="Dronning Eufemias gate 16, 0191 Oslo, Norway",
        operating_address="Bergen Industrial Park, 5003 Bergen, Norway",
        contact_no="+47 22 33 44 55",
        email="kyc@nordicgreen.no",
        ubos="Erik Hansen (NO, 55%, CEO) | Ingrid Solberg (NO, 30%, CFO) | Green Future Fund (15%, institutional)",
        documents="Brønnøysund registry extract; Articles of association; UBO declaration (2025)",
        purpose="Renewable project treasury and FX hedging",
        comments="Energy sector corporate client",
        risk=RISK_MEDIUM,
        cdd=CDD_SIMPLIFIED,
    ),
]


def apply_demo_sanctions_test_rows(rows: list[dict[str, str]]) -> None:
    """Overwrite the first demo rows with known sanctions test names."""
    sanctions_fields = (
        "SanctionsReview",
        "SanctionsMatchedName",
        "SanctionsListKey",
        "SanctionsMatchScore",
        "SanctionsMatchType",
    )
    for index, profile in enumerate(DEMO_SANCTIONS_TEST_PROFILES):
        if index >= len(rows):
            break
        rows[index].update(profile)
        for field in sanctions_fields:
            rows[index][field] = ""


def ensure_demo_sanctions_test_customers() -> bool:
    """
    Patch the first KYC rows with demo sanctions test names (idempotent).

    Clears the stored sanctions fingerprint so the next screen run picks up matches.
    """
    meta = _read_generation_meta()
    if meta.get("demo_sanctions_seeded_v1"):
        return False

    if not KYC_PATH.exists():
        return False

    customers = pd.read_csv(KYC_PATH, dtype=str)
    customers = _migrate_dataframe(customers)
    if len(customers) < len(DEMO_SANCTIONS_TEST_PROFILES):
        return False

    sanctions_fields = (
        "SanctionsReview",
        "SanctionsMatchedName",
        "SanctionsListKey",
        "SanctionsMatchScore",
        "SanctionsMatchType",
    )
    for index, profile in enumerate(DEMO_SANCTIONS_TEST_PROFILES):
        for key, value in profile.items():
            customers.at[customers.index[index], key] = value
        for field in sanctions_fields:
            customers.at[customers.index[index], field] = ""

    save_kyc_customers(customers)
    meta["demo_sanctions_seeded_v1"] = True
    meta.pop("sanctions_screen_fingerprint", None)
    KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    KYC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return True


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


def _migrate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for column in KYC_COLUMNS:
        if column not in df.columns:
            if column == "customer_type":
                df[column] = CUSTOMER_TYPE_INDIVIDUAL
            elif column == "CDDLevel":
                df[column] = CDD_SIMPLIFIED
            else:
                df[column] = ""
    # Backfill demo enrichment for bundled seed IDs where fields are still empty.
    for idx, row in df.iterrows():
        cid = str(row.get("id", "")).strip()
        template = _DEMO_ENRICHMENT.get(cid)
        if not template:
            if not str(row.get("customer_type", "")).strip():
                df.at[idx, "customer_type"] = CUSTOMER_TYPE_INDIVIDUAL
            continue
        for key, value in template.items():
            if key not in df.columns:
                continue
            current = str(row.get(key, "")).strip()
            if not current and value:
                df.at[idx, key] = value
    return df


def _account_source_fingerprint() -> str:
    """Stable content hash of the account-id source (not file mtime)."""
    from utils.kyc_generator import (
        KYC_TARGET_ROW_COUNT,
        PRIMARY_TRANSACTION_DATASET,
        ROOT_ACCOUNT_ID_CSV_CANDIDATES,
        TRANSACTION_ACCOUNT_SOURCES,
        load_account_ids_from_csv,
        load_account_ids_from_sender_receiver_csv,
        load_account_ids_from_transactions,
    )

    if PRIMARY_TRANSACTION_DATASET.exists():
        ids = load_account_ids_from_sender_receiver_csv(
            PRIMARY_TRANSACTION_DATASET,
            limit=KYC_TARGET_ROW_COUNT,
        )
        digest = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()[:16]
        return f"dataset:{len(ids)}:{digest}"

    for path in ROOT_ACCOUNT_ID_CSV_CANDIDATES:
        if path.exists():
            ids = load_account_ids_from_csv(path, limit=KYC_TARGET_ROW_COUNT)
            digest = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()[:16]
            return f"root:{path.name}:{len(ids)}:{digest}"

    ids = load_account_ids_from_transactions(limit=KYC_TARGET_ROW_COUNT)
    if ids:
        digest = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()[:16]
        return f"tx:{len(ids)}:{digest}"
    return "none"


def _read_generation_meta() -> dict:
    if not KYC_META_PATH.exists():
        return {}
    try:
        return json.loads(KYC_META_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_generation_meta(row_count: int, source: str, **extra: str | int) -> None:
    KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**_read_generation_meta(), **extra}
    payload.update(
        {
            "row_count": row_count,
            "source": source,
            "source_fingerprint": _account_source_fingerprint(),
            "generated_at": _utc_now_iso(),
        }
    )
    KYC_META_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _backfill_generation_meta(existing: pd.DataFrame, source: str = "existing kyc_customers.csv") -> None:
    """Record metadata for a bundled CSV without regenerating customer names."""
    if _read_generation_meta().get("source_fingerprint"):
        return
    _write_generation_meta(len(existing), source)


def _needs_bulk_regeneration(existing: pd.DataFrame) -> bool:
    """
    Only regenerate when there is no usable dataset yet.

    Existing 10k rows are preserved across deploys; schema gaps are migrated in place.
    """
    from utils.kyc_generator import KYC_TARGET_ROW_COUNT

    if existing.empty:
        return True
    if len(existing) >= KYC_TARGET_ROW_COUNT:
        _backfill_generation_meta(existing)
        return False
    meta = _read_generation_meta()
    if meta.get("row_count", 0) >= KYC_TARGET_ROW_COUNT:
        return False
    return len(existing) < KYC_TARGET_ROW_COUNT


def search_kyc_customers(
    customers: pd.DataFrame,
    query: str = "",
    *,
    risk_filter: str = "All",
    type_filter: str = "All",
    fatf_filter: str = "All",
) -> pd.DataFrame:
    """Filter customers by text query, risk tier, customer type, and FATF list."""
    df = customers.copy()
    if type_filter and type_filter != "All":
        df = df[df["customer_type"].astype(str) == type_filter]
    if risk_filter and risk_filter != "All":
        df = df[df["RiskStatus"].astype(str) == risk_filter]
    if fatf_filter and fatf_filter != "All":
        if fatf_filter == "Any FATF":
            df = df[df["FATFListCategory"].astype(str).str.strip() != ""]
        else:
            df = df[df["FATFListCategory"].astype(str) == fatf_filter]

    needle = query.strip().lower()
    if needle:
        mask = pd.Series(False, index=df.index)
        for column in KYC_SEARCH_COLUMNS:
            if column not in df.columns:
                continue
            mask |= df[column].astype(str).str.lower().str.contains(needle, na=False, regex=False)
        df = df[mask]
    return df.reset_index(drop=True)


def paginate_kyc_customers(
    customers: pd.DataFrame,
    page: int,
    page_size: int = KYC_PAGE_SIZE_DEFAULT,
) -> tuple[pd.DataFrame, int, int, int]:
    """Return (page_slice, current_page, total_pages, total_rows)."""
    total_rows = len(customers)
    if total_rows == 0:
        return customers.iloc[0:0], 1, 0, 0
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    current_page = max(1, min(int(page), total_pages))
    start = (current_page - 1) * page_size
    end = start + page_size
    return customers.iloc[start:end], current_page, total_pages, total_rows


def regenerate_kyc_database(
    *,
    row_count: int | None = None,
    seed: int = 42,
    force: bool = False,
) -> tuple[int, str]:
    from utils.fatf_jurisdictions import FATF_LIST_VERSION
    from utils.kyc_generator import KYC_TARGET_ROW_COUNT, generate_kyc_database

    target = row_count or KYC_TARGET_ROW_COUNT
    if KYC_PATH.exists() and not force:
        existing = pd.read_csv(KYC_PATH, dtype=str)
        if not existing.empty and len(existing) >= target and not _needs_bulk_regeneration(existing):
            source = str(_read_generation_meta().get("source", "existing kyc_customers.csv"))
            return len(existing), source

    bulk_df, source = generate_kyc_database(row_count=target, seed=seed)
    save_kyc_customers(bulk_df)
    _write_generation_meta(
        len(bulk_df),
        source,
        generator_seed=seed,
        fatf_list_version=FATF_LIST_VERSION,
    )
    return len(bulk_df), source


def ensure_kyc_database() -> None:
    _ensure_parent()
    if KYC_PATH.exists():
        df = pd.read_csv(KYC_PATH, dtype=str)
        if not df.empty and not _needs_bulk_regeneration(df):
            if any(col not in df.columns for col in KYC_COLUMNS):
                save_kyc_customers(_migrate_dataframe(df))
            ensure_demo_sanctions_test_customers()
            return

    try:
        regenerate_kyc_database()
        ensure_demo_sanctions_test_customers()
        return
    except (FileNotFoundError, ValueError):
        pass

    if KYC_PATH.exists():
        df = pd.read_csv(KYC_PATH, dtype=str)
        if not df.empty:
            migrated = _migrate_dataframe(df)
            save_kyc_customers(migrated)
            ensure_demo_sanctions_test_customers()
            return

    seed = pd.DataFrame(MOCK_KYC_ROWS, columns=KYC_COLUMNS)
    seed.to_csv(KYC_PATH, index=False)
    ensure_demo_sanctions_test_customers()


def _apply_fatf_screening_to_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    from utils.fatf_jurisdictions import FATF_LIST_VERSION, apply_fatf_to_kyc_row

    meta = _read_generation_meta()
    if meta.get("fatf_list_version") == FATF_LIST_VERSION:
        return df, False

    out = df.copy()
    for idx, row in out.iterrows():
        updated = apply_fatf_to_kyc_row(row.to_dict())
        for key in KYC_COLUMNS:
            if key in updated:
                out.at[idx, key] = updated[key]

    meta = {**meta, "fatf_list_version": FATF_LIST_VERSION}
    KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    KYC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out, True


def get_kyc_customers() -> pd.DataFrame:
    ensure_kyc_database()
    df = pd.read_csv(KYC_PATH, dtype=str)
    df = _migrate_dataframe(df)
    df = df[KYC_COLUMNS].fillna("")
    df.loc[df["CDDLevel"].astype(str).str.strip() == "", "CDDLevel"] = CDD_SIMPLIFIED
    df.loc[df["customer_type"].astype(str).str.strip() == "", "customer_type"] = CUSTOMER_TYPE_INDIVIDUAL
    df, fatf_changed = _apply_fatf_screening_to_dataframe(df)
    if fatf_changed:
        save_kyc_customers(df)
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


def get_customer_by_account(account_no: str) -> dict[str, str] | None:
    """Return a KYC customer by AccountNo using string-safe comparison."""
    return get_kyc_by_account(str(account_no).strip() if account_no is not None else "")


def escalate_customer_risk(account_no: str, new_risk_status: str, new_cdd_level: str, reason: str) -> bool:
    """
    Promote a KYC customer from transaction monitoring without downgrading risk.

    Returns False when no KYC row exists for the account.
    """
    if not account_no:
        return False

    customers = get_kyc_customers()
    needle = str(account_no).strip()
    mask = customers["AccountNo"].astype(str).str.strip() == needle
    if not mask.any():
        return False

    idx = customers.index[mask][0]
    current_risk = str(customers.at[idx, "RiskStatus"] or RISK_LOW)
    requested_risk = str(new_risk_status or RISK_LOW)
    rank = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}

    count_raw = str(customers.at[idx, "flagged_transaction_count"]).strip()
    try:
        flag_count = int(float(count_raw)) if count_raw else 0
    except ValueError:
        flag_count = 0

    today = datetime.now(UTC).date().isoformat()
    note = str(reason or "").strip()[:200]
    prior_notes = str(customers.at[idx, "review_notes"]).strip()
    updated_notes = f"{today}: {note}" if note else f"{today}: Transaction monitoring review"
    if prior_notes:
        updated_notes = f"{prior_notes}\n{updated_notes}"

    customers.at[idx, "flagged_transaction_count"] = str(flag_count + 1)
    customers.at[idx, "last_reviewed"] = today
    customers.at[idx, "review_notes"] = updated_notes
    customers.at[idx, "LastCDDReviewAt"] = today
    customers.at[idx, "Comments"] = updated_notes

    if rank.get(requested_risk, 0) > rank.get(current_risk, 0):
        customers.at[idx, "RiskStatus"] = requested_risk
        customers.at[idx, "CDDLevel"] = new_cdd_level

    save_kyc_customers(customers)
    return True


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


def _screen_customer_names(full_name: str, aliases: str = "") -> dict:
    from utils.mas_sanctions_sync import screen_name

    best = screen_name(full_name)
    for alias in (a.strip() for a in aliases.split(";") if a.strip()):
        hit = screen_name(alias)
        if hit.get("matched") and (
            not best.get("matched")
            or hit.get("confidence", 0) > best.get("confidence", 0)
        ):
            best = hit
    return best


def _append_comment(existing: str, line: str) -> str:
    prior = str(existing or "").strip()
    if not prior:
        return line
    if line in prior:
        return prior
    return f"{prior}\n{line}"


def _append_indicator(existing: str, indicator: str) -> str:
    parts = [p.strip() for p in str(existing or "").split(";") if p.strip()]
    if indicator not in parts:
        parts.append(indicator)
    return "; ".join(parts)


def _sanctions_comment(match_info: dict, *, confirmed: bool) -> str:
    matched_name = match_info.get("matched_name", "")
    list_key = match_info.get("list_key") or "MAS Sanctions"
    confidence = float(match_info.get("confidence", 0) or 0) * 100
    match_type = match_info.get("match_type", "")
    if confirmed:
        return (
            f"[MAS Sanctions — Confirmed] Designated list match: '{matched_name}' "
            f"on {list_key} ({confidence:.0f}% {match_type} match). "
            "Customer flagged for Enhanced CDD and sanctions monitoring."
        )
    return (
        f"[MAS Sanctions — Fuzzy match pending] Possible match: '{matched_name}' "
        f"on {list_key} ({confidence:.0f}% {match_type}). "
        "Awaiting analyst confirmation."
    )


def _risk_rank(value: str) -> int:
    return {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}.get(str(value), 0)


def apply_confirmed_sanctions_match(
    customer_id: str,
    match_info: dict,
    *,
    actor_id: str = "system",
) -> dict[str, str] | None:
    """Elevate CDD/risk and annotate a confirmed sanctions list match."""
    customers = get_kyc_customers()
    mask = customers["id"].astype(str) == str(customer_id)
    if not mask.any():
        return None

    idx = customers.index[mask][0]
    row = customers.loc[idx]
    current_risk = str(row.get("RiskStatus", RISK_LOW))
    new_risk = current_risk
    if _risk_rank(current_risk) < _risk_rank(RISK_HIGH):
        new_risk = RISK_HIGH

    current_cdd = str(row.get("CDDLevel", CDD_SIMPLIFIED))
    new_cdd = CDD_ENHANCED if current_cdd != CDD_ENHANCED else current_cdd
    confidence_pct = int(round(float(match_info.get("confidence", 0) or 0) * 100))

    updates = {
        "SanctionsReview": SANCTIONS_REVIEW_CONFIRMED,
        "SanctionsMatchedName": str(match_info.get("matched_name", "")),
        "SanctionsListKey": str(match_info.get("list_key") or "MAS Sanctions"),
        "SanctionsMatchScore": str(confidence_pct),
        "SanctionsMatchType": str(match_info.get("match_type", "exact")),
        "CDDLevel": new_cdd,
        "RiskStatus": new_risk,
        "Comments": _append_comment(row.get("Comments", ""), _sanctions_comment(match_info, confirmed=True)),
        "FlaggedReason": "Sanctions List Match",
        "FlaggedBy": actor_id,
        "RiskIndicators": _append_indicator(row.get("RiskIndicators", ""), "MAS Sanctions — confirmed list match"),
        "LastCDDReviewAt": _utc_now_iso(),
    }
    return update_kyc_record(customer_id, updates)


def apply_fuzzy_sanctions_match(customer_id: str, match_info: dict) -> dict[str, str] | None:
    """Flag a possible sanctions match for analyst confirmation (no CDD elevation yet)."""
    customers = get_kyc_customers()
    mask = customers["id"].astype(str) == str(customer_id)
    if not mask.any():
        return None

    row = customers.loc[mask].iloc[0]
    confidence_pct = int(round(float(match_info.get("confidence", 0) or 0) * 100))
    updates = {
        "SanctionsReview": SANCTIONS_REVIEW_FUZZY,
        "SanctionsMatchedName": str(match_info.get("matched_name", "")),
        "SanctionsListKey": str(match_info.get("list_key") or "MAS Sanctions"),
        "SanctionsMatchScore": str(confidence_pct),
        "SanctionsMatchType": "fuzzy",
        "Comments": _append_comment(row.get("Comments", ""), _sanctions_comment(match_info, confirmed=False)),
        "LastCDDReviewAt": _utc_now_iso(),
    }
    return update_kyc_record(customer_id, updates)


def clear_sanctions_match(customer_id: str, *, actor_id: str = "system", reason: str = "") -> dict[str, str] | None:
    """Analyst cleared a fuzzy or pending sanctions hit as a false positive."""
    customers = get_kyc_customers()
    mask = customers["id"].astype(str) == str(customer_id)
    if not mask.any():
        return None

    row = customers.loc[mask].iloc[0]
    note = reason.strip() or "Analyst determined no true sanctions list match."
    updates = {
        "SanctionsReview": SANCTIONS_REVIEW_CLEARED,
        "SanctionsMatchedName": "",
        "SanctionsListKey": "",
        "SanctionsMatchScore": "",
        "SanctionsMatchType": "cleared",
        "Comments": _append_comment(
            row.get("Comments", ""),
            f"[MAS Sanctions — Cleared] {note} (reviewed by {actor_id})",
        ),
        "LastCDDReviewAt": _utc_now_iso(),
    }
    return update_kyc_record(customer_id, updates)


def rescreen_all_kyc_customers() -> dict:
    """
    Screen every enrolled customer against consolidated sanctions names.

    Exact matches are auto-confirmed with Enhanced CDD. Fuzzy matches are queued
    for analyst confirmation in the UI.
    """
    customers = get_kyc_customers()
    exact_count = 0
    fuzzy_count = 0
    skipped_count = 0
    fuzzy_queue: list[dict] = []

    for _, row in customers.iterrows():
        customer_id = str(row["id"])
        review = str(row.get("SanctionsReview", "")).strip()
        if review == SANCTIONS_REVIEW_CONFIRMED:
            match_info = _screen_customer_names(
                str(row.get("FullName", "")),
                str(row.get("Aliases", "")),
            )
            if match_info.get("matched"):
                new_key = str(match_info.get("list_key") or "")
                current_key = str(row.get("SanctionsListKey", "")).strip()
                if new_key and new_key != current_key:
                    update_kyc_record(
                        customer_id,
                        {
                            "SanctionsMatchedName": str(match_info.get("matched_name", "")),
                            "SanctionsListKey": new_key,
                            "SanctionsMatchScore": str(match_info.get("confidence", "")),
                            "SanctionsMatchType": str(match_info.get("match_type", "")),
                        },
                    )
            skipped_count += 1
            continue
        if review == SANCTIONS_REVIEW_CLEARED:
            skipped_count += 1
            continue

        match_info = _screen_customer_names(
            str(row.get("FullName", "")),
            str(row.get("Aliases", "")),
        )
        if not match_info.get("matched"):
            if review in {SANCTIONS_REVIEW_FUZZY, SANCTIONS_REVIEW_PENDING}:
                clear_sanctions_match(customer_id, reason="No match on latest sanctions rescreen.")
            continue

        if match_info.get("match_type") == "exact":
            apply_confirmed_sanctions_match(customer_id, match_info)
            exact_count += 1
        else:
            apply_fuzzy_sanctions_match(customer_id, match_info)
            fuzzy_queue.append({"customer_id": customer_id, **match_info})
            fuzzy_count += 1

    return {
        "exact": exact_count,
        "fuzzy": fuzzy_count,
        "skipped": skipped_count,
        "fuzzy_queue": fuzzy_queue,
    }


def _sanctions_screen_fingerprint() -> str:
    from utils.mas_sanctions_sync import _load_consolidated_names

    names = "\n".join(sorted(_load_consolidated_names()))
    return hashlib.sha256(names.encode("utf-8")).hexdigest()[:16]


def ensure_kyc_sanctions_screened() -> dict | None:
    """
    Rescreen all enrolled customers when the consolidated sanctions list changes.

    Returns rescreen stats when a new screen runs, otherwise None.
    """
    meta = _read_generation_meta()
    fingerprint = _sanctions_screen_fingerprint()
    if meta.get("sanctions_screen_fingerprint") == fingerprint:
        return None

    result = rescreen_all_kyc_customers()
    meta.update(
        {
            "sanctions_screen_fingerprint": fingerprint,
            "sanctions_screen_at": _utc_now_iso(),
            "sanctions_screen_exact": result["exact"],
            "sanctions_screen_fuzzy": result["fuzzy"],
        }
    )
    KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    KYC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result


def force_rescreen_kyc_sanctions() -> dict:
    """Always rescreen enrolled customers and refresh the stored sanctions fingerprint."""
    result = rescreen_all_kyc_customers()
    meta = _read_generation_meta()
    meta.update(
        {
            "sanctions_screen_fingerprint": _sanctions_screen_fingerprint(),
            "sanctions_screen_at": _utc_now_iso(),
            "sanctions_screen_exact": result["exact"],
            "sanctions_screen_fuzzy": result["fuzzy"],
        }
    )
    KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    KYC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result


def enrol_customer(
    data: dict[str, str],
    *,
    sanctions_match: dict | None = None,
    # Backward-compatible keyword args
    full_name: str | None = None,
    account_no: str | None = None,
    address: str | None = None,
    contact_no: str | None = None,
    comments: str = "",
) -> tuple[dict[str, str], dict]:
    """Register a customer. Returns (row, sanctions_match_info)."""
    if full_name is not None:
        data = {
            **data,
            "FullName": full_name,
            "AccountNo": account_no or data.get("AccountNo", ""),
            "Address": address or data.get("Address", ""),
            "ContactNo": contact_no or data.get("ContactNo", ""),
            "Comments": comments or data.get("Comments", ""),
        }

    customers = get_kyc_customers()
    existing_ids = set(customers["id"].astype(str))
    account_no_val = str(data.get("AccountNo", "")).strip()
    if not account_no_val:
        raise ValueError("Account number is required.")
    if account_no_val in set(customers["AccountNo"].astype(str).str.strip()):
        raise ValueError(f"Account number {account_no_val} is already registered.")

    name = str(data.get("FullName", "")).strip()
    if not name:
        raise ValueError("Full name is required.")

    aliases = str(data.get("Aliases", "")).strip()
    sanctions_confirmed = bool(data.get("sanctions_confirmed"))
    sanctions_rejected = bool(data.get("sanctions_rejected"))
    match_info = sanctions_match if sanctions_match is not None else _screen_customer_names(name, aliases)
    if sanctions_rejected or not match_info.get("matched"):
        match_info = {**match_info, "matched": False}
        sanctions_review = SANCTIONS_REVIEW_NONE
    elif sanctions_confirmed or match_info.get("match_type") == "exact":
        sanctions_review = SANCTIONS_REVIEW_CONFIRMED
    elif match_info.get("match_type") == "fuzzy":
        sanctions_review = SANCTIONS_REVIEW_FUZZY
    else:
        sanctions_review = SANCTIONS_REVIEW_PENDING

    customer_type = str(data.get("customer_type", CUSTOMER_TYPE_INDIVIDUAL)).strip() or CUSTOMER_TYPE_INDIVIDUAL
    row = _empty_kyc_fields()
    row.update({k: str(v).strip() if v is not None else "" for k, v in data.items() if k in KYC_COLUMNS})
    row["id"] = generate_customer_id(existing_ids)
    row["customer_type"] = customer_type
    row["FullName"] = name
    row["AccountNo"] = account_no_val
    row["RiskStatus"] = row.get("RiskStatus") or RISK_LOW
    row["CDDLevel"] = row.get("CDDLevel") or CDD_SIMPLIFIED
    row["SanctionsReview"] = sanctions_review
    row["LastCDDReviewAt"] = _utc_now_iso()
    row["IsPEP"] = row.get("IsPEP") or "No"

    if match_info.get("matched") and sanctions_review == SANCTIONS_REVIEW_CONFIRMED:
        row["SanctionsMatchedName"] = str(match_info.get("matched_name", ""))
        row["SanctionsListKey"] = str(match_info.get("list_key") or "MAS Sanctions")
        row["SanctionsMatchScore"] = str(int(round(float(match_info.get("confidence", 0) or 0) * 100)))
        row["SanctionsMatchType"] = str(match_info.get("match_type", "exact"))
        row["CDDLevel"] = CDD_ENHANCED
        row["Comments"] = _append_comment(row.get("Comments", ""), _sanctions_comment(match_info, confirmed=True))
        row["FlaggedReason"] = "Sanctions List Match"
        row["RiskIndicators"] = _append_indicator(row.get("RiskIndicators", ""), "MAS Sanctions — confirmed list match")
        if _risk_rank(str(row.get("RiskStatus", RISK_LOW))) < _risk_rank(RISK_HIGH):
            row["RiskStatus"] = RISK_HIGH
    elif match_info.get("matched") and sanctions_review == SANCTIONS_REVIEW_FUZZY:
        row["SanctionsMatchedName"] = str(match_info.get("matched_name", ""))
        row["SanctionsListKey"] = str(match_info.get("list_key") or "MAS Sanctions")
        row["SanctionsMatchScore"] = str(int(round(float(match_info.get("confidence", 0) or 0) * 100)))
        row["SanctionsMatchType"] = "fuzzy"
        row["Comments"] = _append_comment(row.get("Comments", ""), _sanctions_comment(match_info, confirmed=False))

    from utils.fatf_jurisdictions import apply_fatf_to_kyc_row

    row = apply_fatf_to_kyc_row(row)

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


def _fatf_exposure_from_transactions(scored_df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Map account number -> (canonical jurisdiction, FATF category) from bank locations."""
    from utils.fatf_jurisdictions import FATF_CATEGORY_RANK, evaluate_text_fields

    if scored_df is None or scored_df.empty:
        return {}

    exposure: dict[str, tuple[str, str]] = {}
    for _, txn in scored_df.iterrows():
        hit = evaluate_text_fields(
            str(txn.get("Sender_bank_location", "")),
            str(txn.get("Receiver_bank_location", "")),
        )
        if not hit:
            continue
        for col in ("Sender_account", "Receiver_account"):
            if col not in scored_df.columns:
                continue
            account = str(txn.get(col, "")).strip()
            if not account:
                continue
            prior = exposure.get(account)
            if prior is None or FATF_CATEGORY_RANK[hit[1]] > FATF_CATEGORY_RANK[prior[1]]:
                exposure[account] = hit
    return exposure


def apply_cdd_escalation_from_transactions(scored_df: pd.DataFrame) -> list[dict[str, str]]:
    """
    Walk each KYC customer and upgrade RiskStatus + CDDLevel based on:
    - highest ML risk tier on flagged transactions, and
    - FATF jurisdiction exposure via transaction bank locations.

    Returns the list of changed rows (id, old/new RiskStatus, old/new CDDLevel).
    """
    from utils.cdd_rules import recommend_cdd_level, recommend_risk_status  # avoid cycle
    from utils.fatf_jurisdictions import apply_fatf_to_kyc_row

    involved = _suspicious_accounts(scored_df)
    fatf_by_account = _fatf_exposure_from_transactions(scored_df)
    if not involved and not fatf_by_account:
        return []

    customers = get_kyc_customers()
    changes: list[dict[str, str]] = []
    now = _utc_now_iso()

    for idx, row in customers.iterrows():
        customer_id = str(row["id"]).strip()
        account_no = str(row["AccountNo"]).strip()
        hit_tier = involved.get(customer_id) or involved.get(account_no)

        row_dict = row.to_dict()
        fatf_hit = fatf_by_account.get(account_no)
        if fatf_hit:
            row_dict["FATFJurisdiction"] = fatf_hit[0]
            row_dict["FATFListCategory"] = fatf_hit[1]
            row_dict = apply_fatf_to_kyc_row(row_dict)

        if not hit_tier and not fatf_hit:
            continue

        sanctions_pending = str(row_dict.get("SanctionsReview", "")).strip() in {
            SANCTIONS_REVIEW_PENDING,
            SANCTIONS_REVIEW_FUZZY,
            SANCTIONS_REVIEW_CONFIRMED,
            SANCTIONS_REVIEW_ESCALATED,
        }
        fatf_category = str(row_dict.get("FATFListCategory", ""))
        txn_tier = hit_tier or "Low"
        new_risk = recommend_risk_status(
            row_dict.get("RiskStatus", row["RiskStatus"]),
            txn_tier,
            fatf_category=fatf_category,
        )
        new_cdd = recommend_cdd_level(
            current_cdd=row_dict.get("CDDLevel", row["CDDLevel"]),
            risk_status=new_risk,
            top_txn_tier=txn_tier,
            sanctions_pending=sanctions_pending,
            fatf_category=fatf_category,
        )

        old_risk = str(row["RiskStatus"])
        old_cdd = str(row["CDDLevel"])
        if new_risk == old_risk and new_cdd == old_cdd and not fatf_hit:
            continue

        change = {
            "id": customer_id,
            "FullName": str(row["FullName"]),
            "old_risk": old_risk,
            "new_risk": new_risk,
            "old_cdd": old_cdd,
            "new_cdd": new_cdd,
            "trigger_tier": hit_tier or f"FATF:{fatf_category}",
        }
        for key in ("RiskStatus", "CDDLevel", "FATFJurisdiction", "FATFListCategory",
                    "RiskIndicators", "FlaggedReason", "SMApprovalStatus", "Comments"):
            if key in row_dict and key in KYC_COLUMNS:
                customers.at[idx, key] = row_dict[key]
        customers.at[idx, "RiskStatus"] = new_risk
        customers.at[idx, "CDDLevel"] = new_cdd
        customers.at[idx, "LastCDDReviewAt"] = now
        changes.append(change)

    if changes:
        save_kyc_customers(customers)
    return changes


# ---------------------------------------------------------------------------
# 4-level risk management
# ---------------------------------------------------------------------------

_RISK_RANK: dict[str, int] = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}
_RISK_TO_CDD: dict[str, str] = {
    RISK_LOW: CDD_SIMPLIFIED,
    RISK_MEDIUM: CDD_SIMPLIFIED,
    RISK_HIGH: CDD_ENHANCED,
    RISK_CRITICAL: CDD_ENHANCED,
}


def set_customer_risk_status(
    customer_id: str,
    new_status: str,
    actor_id: str,
    reason: str = "",
    is_pep: bool | None = None,
) -> dict[str, str] | None:
    """
    Manually promote or demote a customer's RiskStatus to any of the 4 levels.

    - Promotes CDDLevel to match the new risk (never auto-demotes CDD when demoting risk,
      so an analyst must explicitly lower CDD via Case Investigation).
    - When new_status == RISK_CRITICAL, sets SMApprovalStatus = "Pending".
    - When demoting away from Critical, clears the SM approval fields.
    - is_pep=True/False explicitly sets IsPEP; None leaves it unchanged.

    Returns the updated row dict, or None if the customer was not found.
    """
    from utils.constants import SM_APPROVAL_PENDING  # avoid circular at module level

    customers = get_kyc_customers()
    mask = customers["id"].astype(str) == str(customer_id)
    if not mask.any():
        return None

    row = customers.loc[mask].iloc[0]
    old_status = str(row["RiskStatus"])
    new_cdd = _RISK_TO_CDD.get(new_status, CDD_SIMPLIFIED)

    old_cdd_rank = {CDD_SIMPLIFIED: 0, CDD_ENHANCED: 1}.get(str(row["CDDLevel"]), 0)
    new_cdd_rank = {CDD_SIMPLIFIED: 0, CDD_ENHANCED: 1}.get(new_cdd, 0)
    applied_cdd = new_cdd if new_cdd_rank >= old_cdd_rank else str(row["CDDLevel"])

    updates: dict[str, str] = {
        "RiskStatus": new_status,
        "CDDLevel": applied_cdd,
        "FlaggedBy": actor_id,
        "FlaggedReason": reason or "Manual",
    }

    if new_status == RISK_CRITICAL:
        updates["SMApprovalStatus"] = SM_APPROVAL_PENDING
        updates["SMApprovedBy"] = ""
        updates["SMApprovedAt"] = ""
    elif old_status == RISK_CRITICAL:
        updates["SMApprovalStatus"] = ""
        updates["SMApprovedBy"] = ""
        updates["SMApprovedAt"] = ""

    if is_pep is True:
        updates["IsPEP"] = "Yes"
    elif is_pep is False:
        updates["IsPEP"] = "No"

    return update_kyc_record(customer_id, updates)


def approve_critical_customer(customer_id: str, sm_actor_id: str) -> dict[str, str] | None:
    """Senior Management approves a Critical-flagged customer."""
    from utils.constants import SM_APPROVAL_APPROVED

    return update_kyc_record(customer_id, {
        "SMApprovalStatus": SM_APPROVAL_APPROVED,
        "SMApprovedBy": sm_actor_id,
        "SMApprovedAt": _utc_now_iso(),
    })


def reject_critical_flag(customer_id: str, sm_actor_id: str, reason: str = "") -> dict[str, str] | None:
    """
    Senior Management rejects the Critical flag.  RiskStatus is stepped back to High
    so the customer retains Enhanced CDD but no longer requires SM sign-off.
    """
    from utils.constants import SM_APPROVAL_REJECTED

    return update_kyc_record(customer_id, {
        "RiskStatus": RISK_HIGH,
        "CDDLevel": CDD_ENHANCED,
        "SMApprovalStatus": SM_APPROVAL_REJECTED,
        "SMApprovedBy": sm_actor_id,
        "SMApprovedAt": _utc_now_iso(),
        "FlaggedReason": reason or "Rejected by SM",
    })


def scan_pep_column(upload_df: pd.DataFrame) -> list[dict[str, str]]:
    """
    Template hook: scan an uploaded DataFrame for a PEP indicator column.

    Looks for columns named IsPEP / is_pep / PEP / pep (case-insensitive).
    Rows where the value is truthy ("yes", "true", "1", "y") are promoted to
    Critical in the KYC database if their AccountNo is already registered.

    Returns a list of change dicts for audit logging:
        [{"id", "FullName", "AccountNo", "old_risk", "new_risk"}, ...]
    """
    from utils.constants import FLAG_REASON_PEP

    pep_col = next(
        (c for c in upload_df.columns if c.strip().lower() in {"ispep", "is_pep", "pep"}),
        None,
    )
    if pep_col is None:
        return []

    _truthy = {"yes", "true", "1", "y"}
    pep_accounts = set(
        upload_df.loc[
            upload_df[pep_col].astype(str).str.strip().str.lower().isin(_truthy),
            "Sender_account",
        ].astype(str).str.strip().tolist()
    ) if "Sender_account" in upload_df.columns else set()

    if not pep_accounts:
        return []

    customers = get_kyc_customers()
    changes: list[dict[str, str]] = []

    for _, row in customers.iterrows():
        account = str(row["AccountNo"]).strip()
        if account not in pep_accounts:
            continue
        if str(row.get("IsPEP", "")).strip().lower() == "yes":
            continue

        old_risk = str(row["RiskStatus"])
        set_customer_risk_status(
            customer_id=str(row["id"]),
            new_status=RISK_CRITICAL,
            actor_id="system",
            reason=FLAG_REASON_PEP,
            is_pep=True,
        )
        changes.append({
            "id": str(row["id"]),
            "FullName": str(row["FullName"]),
            "AccountNo": account,
            "old_risk": old_risk,
            "new_risk": RISK_CRITICAL,
        })

    return changes
