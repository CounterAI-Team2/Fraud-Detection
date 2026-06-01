from __future__ import annotations

import random
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

KYC_PATH = Path("data/kyc_customers.csv")
IRAN_NAMES_PATH = Path("iran_names.txt")

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
    "LastCDDReviewAt",
    "Comments",
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
CDD_STANDARD = "Standard"
CDD_ENHANCED = "Enhanced"

SANCTIONS_REVIEW_NONE = ""
SANCTIONS_REVIEW_PENDING = "Pending"
SANCTIONS_REVIEW_CLEARED = "Cleared"
SANCTIONS_REVIEW_ESCALATED = "Escalated"

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
    cdd: str = CDD_STANDARD,
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
        risk=RISK_MEDIUM, cdd=CDD_STANDARD,
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
        risk=RISK_MEDIUM, cdd=CDD_STANDARD,
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
        risk=RISK_MEDIUM, cdd=CDD_STANDARD,
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
        cdd=CDD_STANDARD,
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
        cdd=CDD_STANDARD,
    ),
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


def ensure_kyc_database() -> None:
    _ensure_parent()
    if KYC_PATH.exists():
        df = pd.read_csv(KYC_PATH, dtype=str)
        if not df.empty:
            needs_save = any(col not in df.columns for col in KYC_COLUMNS)
            migrated = _migrate_dataframe(df)
            if not needs_save and "4624222122" in migrated["id"].astype(str).values:
                sample = migrated[migrated["id"].astype(str) == "4624222122"].iloc[0]
                needs_save = not str(sample.get("Email", "")).strip()
            if needs_save:
                save_kyc_customers(migrated)
            return

    seed = pd.DataFrame(MOCK_KYC_ROWS, columns=KYC_COLUMNS)
    seed.to_csv(KYC_PATH, index=False)


def get_kyc_customers() -> pd.DataFrame:
    ensure_kyc_database()
    df = pd.read_csv(KYC_PATH, dtype=str)
    df = _migrate_dataframe(df)
    df = df[KYC_COLUMNS].fillna("")
    df.loc[df["CDDLevel"].astype(str).str.strip() == "", "CDDLevel"] = CDD_SIMPLIFIED
    df.loc[df["customer_type"].astype(str).str.strip() == "", "customer_type"] = CUSTOMER_TYPE_INDIVIDUAL
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


def _screen_customer_names(full_name: str, aliases: str = "") -> dict:
    from utils.mas_sanctions_sync import screen_name

    primary = screen_name(full_name)
    if primary.get("matched"):
        return primary
    for alias in (a.strip() for a in aliases.split(";") if a.strip()):
        hit = screen_name(alias)
        if hit.get("matched"):
            return hit
    return primary


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
    match_info = sanctions_match if sanctions_match is not None else _screen_customer_names(name, aliases)
    sanctions_review = SANCTIONS_REVIEW_PENDING if match_info.get("matched") else SANCTIONS_REVIEW_NONE

    customer_type = str(data.get("customer_type", CUSTOMER_TYPE_INDIVIDUAL)).strip() or CUSTOMER_TYPE_INDIVIDUAL
    row = _empty_kyc_fields()
    row.update({k: str(v).strip() if v is not None else "" for k, v in data.items() if k in KYC_COLUMNS})
    row["id"] = generate_customer_id(existing_ids)
    row["customer_type"] = customer_type
    row["FullName"] = name
    row["AccountNo"] = account_no_val
    row["RiskStatus"] = row.get("RiskStatus") or RISK_LOW
    row["CDDLevel"] = row.get("CDDLevel") or (CDD_STANDARD if customer_type == CUSTOMER_TYPE_CORPORATE else CDD_SIMPLIFIED)
    row["SanctionsReview"] = sanctions_review
    row["LastCDDReviewAt"] = _utc_now_iso()
    row["IsPEP"] = row.get("IsPEP") or "No"

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


# ---------------------------------------------------------------------------
# 4-level risk management
# ---------------------------------------------------------------------------

_RISK_RANK: dict[str, int] = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}
_RISK_TO_CDD: dict[str, str] = {
    RISK_LOW: CDD_SIMPLIFIED,
    RISK_MEDIUM: CDD_STANDARD,
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

    old_cdd_rank = {CDD_SIMPLIFIED: 0, CDD_STANDARD: 1, CDD_ENHANCED: 2}.get(str(row["CDDLevel"]), 0)
    new_cdd_rank = {CDD_SIMPLIFIED: 0, CDD_STANDARD: 1, CDD_ENHANCED: 2}.get(new_cdd, 0)
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
