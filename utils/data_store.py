from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path("data")
REFERENCE_DIR = DATA_DIR / "reference"
CUSTOMERS_PATH = DATA_DIR / "customers.csv"
CASES_PATH = DATA_DIR / "cases.csv"
SANCTIONS_PATH = REFERENCE_DIR / "sanctions_watchlist.csv"
AUDIT_V2_PATH = DATA_DIR / "audit_log_v2.csv"
HITL_PATH = DATA_DIR / "hitl_feedback.csv"
ARCHIVE_PATH = DATA_DIR / "str_archive.csv"
STR_CASES_PATH = DATA_DIR / "str_cases.csv"
REGISTRY_PATH = DATA_DIR / "model_registry.json"

CUSTOMER_COLUMNS = [
    "customer_id",
    "account_id",
    "customer_name",
    "customer_type",
    "kyc_status",
    "kyc_risk_tier",
    "cdd_level",
    "onboarding_date",
    "last_review_date",
    "home_country",
    "cross_border_count",
    "cross_currency_count",
    "transaction_volume",
    "unique_counterparties",
    "high_value_count",
    "sanctions_flag",
    "sanctions_reason",
    "sanctions_match_source",
    "sanctions_cleared_reason",
    "sanctions_cleared_at",
    "sanctions_cleared_by",
    "created_at",
    "updated_at",
]

CASE_COLUMNS = [
    "case_id",
    "transaction_id",
    "customer_id",
    "account_id",
    "alert_score",
    "alert_tier",
    "status",
    "owner",
    "cdd_level",
    "kyc_risk_tier",
    "str_required",
    "opened_at",
    "updated_at",
    "closed_at",
    "resolution",
    "notes",
    "attachment_count",
    "attachment_names",
    "latest_attachment_at",
]

AUDIT_COLUMNS = [
    "event_id",
    "timestamp_utc",
    "module",
    "event_type",
    "entity_type",
    "entity_id",
    "transaction_id",
    "actor_id",
    "actor_role",
    "payload_json",
]

HITL_COLUMNS = [
    "feedback_id",
    "timestamp_utc",
    "transaction_id",
    "customer_id",
    "original_prediction",
    "corrected_label",
    "reason",
    "actor_id",
]

STR_CASE_COLUMNS = [
    "str_id",
    "case_id",
    "transaction_id",
    "customer_id",
    "status",
    "l1_reviewer",
    "l1_reviewed_at",
    "l1_reason",
    "l2_reviewer",
    "l2_reviewed_at",
    "l2_reason",
    "reference_number",
    "grounds",
    "created_at",
    "updated_at",
]

ARCHIVE_COLUMNS = [
    "archive_id",
    "str_id",
    "case_id",
    "transaction_id",
    "customer_id",
    "risk_tier",
    "str_status",
    "archived_at",
    "archived_by",
    "summary_json",
]

DEFAULT_WATCHLIST = [
    {
        "watchlist_id": "WL-001",
        "name": "Global Risk Trading LLC",
        "account_id": "1631823864",
        "country": "UK",
        "reason": "Synthetic sanctioned counterparty for demo flows",
    },
    {
        "watchlist_id": "WL-002",
        "name": "Zeta Holdings",
        "account_id": "6125211006",
        "country": "Nigeria",
        "reason": "Synthetic politically exposed counterparty for demo flows",
    },
    {
        "watchlist_id": "WL-003",
        "name": "Nova Imports",
        "account_id": "2774166966",
        "country": "Germany",
        "reason": "Synthetic restricted remitter for demo flows",
    },
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_csv_store(path: Path, columns: list[str]) -> None:
    _ensure_parent(path)
    if path.exists():
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def ensure_json_store(path: Path, default_data: Any) -> None:
    _ensure_parent(path)
    if path.exists():
        return
    path.write_text(json.dumps(default_data, indent=2), encoding="utf-8")


def ensure_reference_data() -> None:
    ensure_csv_store(CUSTOMERS_PATH, CUSTOMER_COLUMNS)
    ensure_csv_store(CASES_PATH, CASE_COLUMNS)
    ensure_csv_store(AUDIT_V2_PATH, AUDIT_COLUMNS)
    ensure_csv_store(HITL_PATH, HITL_COLUMNS)
    ensure_csv_store(STR_CASES_PATH, STR_CASE_COLUMNS)
    ensure_csv_store(ARCHIVE_PATH, ARCHIVE_COLUMNS)
    ensure_json_store(REGISTRY_PATH, {"models": []})

    _ensure_parent(SANCTIONS_PATH)
    if not SANCTIONS_PATH.exists():
        pd.DataFrame(DEFAULT_WATCHLIST).to_csv(SANCTIONS_PATH, index=False)


def read_csv_store(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    ensure_reference_data()
    if not path.exists():
        if columns is None:
            return pd.DataFrame()
        return pd.DataFrame(columns=columns)

    df = pd.read_csv(path)
    if columns is not None:
        for column in columns:
            if column not in df.columns:
                df[column] = ""
        df = df[columns]
    return df


def write_csv_store(path: Path, df: pd.DataFrame, columns: list[str] | None = None) -> None:
    ensure_reference_data()
    if columns is not None:
        for column in columns:
            if column not in df.columns:
                df[column] = ""
        df = df[columns]
    df.to_csv(path, index=False)


def append_csv_row(path: Path, row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    df = read_csv_store(path, columns)
    normalized_row = {column: row.get(column, "") for column in columns}
    df = pd.concat([df, pd.DataFrame([normalized_row])], ignore_index=True)
    write_csv_store(path, df, columns)
    return normalized_row


def load_json_store(path: Path, default_data: Any) -> Any:
    ensure_json_store(path, default_data)
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_store(path: Path, data: Any) -> None:
    ensure_json_store(path, data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def make_case_id() -> str:
    return f"CDD-{uuid.uuid4().hex[:8].upper()}"


def make_str_id() -> str:
    return f"STR-{uuid.uuid4().hex[:8].upper()}"


def make_archive_id() -> str:
    return f"ARC-{uuid.uuid4().hex[:8].upper()}"


def make_customer_id(account_id: str | int) -> str:
    return f"CUST-{str(account_id)}"


def normalize_account_id(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def serialize_payload(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    return json.dumps(payload, sort_keys=True, default=str)


def parse_payload(value: str | float | None) -> dict[str, Any]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    text = str(value).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def get_customer_name(account_id: str) -> str:
    suffix = account_id[-4:] if account_id else "0000"
    return f"Customer {suffix}"


def upsert_customers(customer_df: pd.DataFrame) -> pd.DataFrame:
    customer_df = customer_df.copy()
    for column in CUSTOMER_COLUMNS:
        if column not in customer_df.columns:
            customer_df[column] = ""
    customer_df = customer_df[CUSTOMER_COLUMNS].fillna("")
    string_like_columns = [
        "customer_id",
        "account_id",
        "customer_name",
        "customer_type",
        "kyc_status",
        "kyc_risk_tier",
        "cdd_level",
        "onboarding_date",
        "last_review_date",
        "home_country",
        "sanctions_reason",
        "sanctions_match_source",
        "sanctions_cleared_reason",
        "sanctions_cleared_at",
        "sanctions_cleared_by",
        "created_at",
        "updated_at",
    ]
    for column in string_like_columns:
        customer_df[column] = customer_df[column].astype(str)

    current = read_csv_store(CUSTOMERS_PATH, CUSTOMER_COLUMNS)
    if current.empty:
        write_csv_store(CUSTOMERS_PATH, customer_df, CUSTOMER_COLUMNS)
        return customer_df

    current = current.fillna("")
    for column in string_like_columns:
        current[column] = current[column].astype(str)

    merged = current.set_index("customer_id")
    incoming = customer_df.set_index("customer_id")
    merged.update(incoming)

    missing = incoming.index.difference(merged.index)
    if len(missing) > 0:
        merged = pd.concat([merged, incoming.loc[missing]])

    result = merged.reset_index()
    write_csv_store(CUSTOMERS_PATH, result, CUSTOMER_COLUMNS)
    return result


def build_customer_profiles(scored_df: pd.DataFrame) -> pd.DataFrame:
    if scored_df is None or scored_df.empty:
        return pd.DataFrame(columns=CUSTOMER_COLUMNS)

    df = scored_df.copy()
    df["account_id"] = df["Sender_account"].astype(str)
    df["counterparty_id"] = df["Receiver_account"].astype(str)
    df["amount_value"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["cross_border_flag"] = pd.to_numeric(df["cross_border"], errors="coerce").fillna(0).astype(int)
    df["cross_currency_flag"] = pd.to_numeric(df["cross_currency"], errors="coerce").fillna(0).astype(int)
    df["risk_score_num"] = pd.to_numeric(df.get("risk_score", 0), errors="coerce").fillna(0.0)
    df["txn_date"] = pd.to_datetime(df["Date"], errors="coerce")

    grouped = (
        df.groupby("account_id", as_index=False)
        .agg(
            transaction_volume=("amount_value", "sum"),
            unique_counterparties=("counterparty_id", "nunique"),
            cross_border_count=("cross_border_flag", "sum"),
            cross_currency_count=("cross_currency_flag", "sum"),
            high_value_count=("amount_value", lambda s: int((s >= 10000).sum())),
            onboarding_date=("txn_date", "min"),
            last_review_date=("txn_date", "max"),
            home_country=("Sender_bank_location", lambda s: s.astype(str).mode().iloc[0] if not s.empty else "Unknown"),
        )
    )

    def _risk_tier(row: pd.Series) -> str:
        if row["cross_border_count"] >= 3 or row["transaction_volume"] >= 50000 or row["unique_counterparties"] >= 10:
            return "High"
        if row["cross_border_count"] >= 1 or row["transaction_volume"] >= 20000 or row["unique_counterparties"] >= 5:
            return "Medium"
        return "Low"

    grouped["customer_id"] = grouped["account_id"].apply(make_customer_id)
    grouped["customer_name"] = grouped["account_id"].apply(get_customer_name)
    grouped["customer_type"] = "Individual"
    grouped["kyc_status"] = "Pending Review"
    grouped["kyc_risk_tier"] = grouped.apply(_risk_tier, axis=1)
    grouped["cdd_level"] = grouped["kyc_risk_tier"].map({"High": "Enhanced", "Medium": "Standard"}).fillna("Simplified")
    grouped["sanctions_flag"] = False
    grouped["sanctions_reason"] = ""
    grouped["sanctions_match_source"] = ""
    grouped["sanctions_cleared_reason"] = ""
    grouped["sanctions_cleared_at"] = ""
    grouped["sanctions_cleared_by"] = ""
    grouped["created_at"] = utc_now_iso()
    grouped["updated_at"] = utc_now_iso()
    grouped["onboarding_date"] = grouped["onboarding_date"].dt.date.astype(str)
    grouped["last_review_date"] = grouped["last_review_date"].dt.date.astype(str)
    return grouped[CUSTOMER_COLUMNS]


def get_customers() -> pd.DataFrame:
    return read_csv_store(CUSTOMERS_PATH, CUSTOMER_COLUMNS)


def get_cases() -> pd.DataFrame:
    return read_csv_store(CASES_PATH, CASE_COLUMNS)


def get_audit_events() -> pd.DataFrame:
    return read_csv_store(AUDIT_V2_PATH, AUDIT_COLUMNS)


def get_hitl_feedback() -> pd.DataFrame:
    return read_csv_store(HITL_PATH, HITL_COLUMNS)


def get_str_cases() -> pd.DataFrame:
    return read_csv_store(STR_CASES_PATH, STR_CASE_COLUMNS)


def get_archive() -> pd.DataFrame:
    return read_csv_store(ARCHIVE_PATH, ARCHIVE_COLUMNS)


def get_watchlist() -> pd.DataFrame:
    ensure_reference_data()
    return pd.read_csv(SANCTIONS_PATH)


def upsert_case(case_row: dict[str, Any]) -> dict[str, Any]:
    cases = get_cases()
    now = utc_now_iso()
    row = {column: case_row.get(column, "") for column in CASE_COLUMNS}
    row["updated_at"] = row.get("updated_at") or now
    row["opened_at"] = row.get("opened_at") or now

    if not row["case_id"]:
        row["case_id"] = make_case_id()

    if cases.empty:
        write_csv_store(CASES_PATH, pd.DataFrame([row]), CASE_COLUMNS)
        return row

    match_idx = cases.index[cases["case_id"].astype(str) == str(row["case_id"])].tolist()
    if match_idx:
        cases.loc[match_idx[0], CASE_COLUMNS] = [row.get(column, "") for column in CASE_COLUMNS]
    else:
        cases = pd.concat([cases, pd.DataFrame([row])], ignore_index=True)
    write_csv_store(CASES_PATH, cases, CASE_COLUMNS)
    return row


def upsert_str_case(str_row: dict[str, Any]) -> dict[str, Any]:
    cases = get_str_cases()
    now = utc_now_iso()
    row = {column: str_row.get(column, "") for column in STR_CASE_COLUMNS}
    row["updated_at"] = row.get("updated_at") or now
    row["created_at"] = row.get("created_at") or now

    if not row["str_id"]:
        row["str_id"] = make_str_id()

    if cases.empty:
        write_csv_store(STR_CASES_PATH, pd.DataFrame([row]), STR_CASE_COLUMNS)
        return row

    match_idx = cases.index[cases["str_id"].astype(str) == str(row["str_id"])].tolist()
    if match_idx:
        cases.loc[match_idx[0], STR_CASE_COLUMNS] = [row.get(column, "") for column in STR_CASE_COLUMNS]
    else:
        cases = pd.concat([cases, pd.DataFrame([row])], ignore_index=True)
    write_csv_store(STR_CASES_PATH, cases, STR_CASE_COLUMNS)
    return row


def append_archive_record(summary: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    row = {
        "archive_id": make_archive_id(),
        "str_id": summary.get("str_id", ""),
        "case_id": summary.get("case_id", ""),
        "transaction_id": summary.get("transaction_id", ""),
        "customer_id": summary.get("customer_id", ""),
        "risk_tier": summary.get("risk_tier", ""),
        "str_status": summary.get("str_status", ""),
        "archived_at": now,
        "archived_by": summary.get("archived_by", ""),
        "summary_json": serialize_payload(summary),
    }
    return append_csv_row(ARCHIVE_PATH, row, ARCHIVE_COLUMNS)


def append_hitl_feedback(feedback_row: dict[str, Any]) -> dict[str, Any]:
    row = {
        "feedback_id": f"fb_{uuid.uuid4().hex[:12]}",
        "timestamp_utc": utc_now_iso(),
        "transaction_id": feedback_row.get("transaction_id", ""),
        "customer_id": feedback_row.get("customer_id", ""),
        "original_prediction": feedback_row.get("original_prediction", ""),
        "corrected_label": feedback_row.get("corrected_label", ""),
        "reason": feedback_row.get("reason", ""),
        "actor_id": feedback_row.get("actor_id", "Analyst"),
    }
    return append_csv_row(HITL_PATH, row, HITL_COLUMNS)


def get_model_registry() -> dict[str, Any]:
    return load_json_store(REGISTRY_PATH, {"models": []})


def upsert_model_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    registry = get_model_registry()
    models = registry.get("models", [])
    model_id = entry.get("model_id") or f"model_{uuid.uuid4().hex[:8]}"
    normalized = {
        "model_id": model_id,
        "version": entry.get("version", "v0.1"),
        "trained_on": entry.get("trained_on", utc_now_iso()),
        "precision": entry.get("precision", ""),
        "recall": entry.get("recall", ""),
        "f1": entry.get("f1", ""),
        "error_rate": entry.get("error_rate", ""),
        "notes": entry.get("notes", ""),
    }

    updated = False
    for idx, existing in enumerate(models):
        if existing.get("model_id") == model_id:
            models[idx] = normalized
            updated = True
            break
    if not updated:
        models.append(normalized)

    registry["models"] = models
    save_json_store(REGISTRY_PATH, registry)
    return normalized
