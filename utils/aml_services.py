from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from utils.constants import (
    ALERT_THRESHOLDS,
    CASE_CLOSED_STATUSES,
    CASE_OPEN_STATUSES,
    CASE_STATUS_OPEN,
    CDD_LEVEL_STANDARD,
    HIGH_VALUE_THRESHOLD,
)
from utils.data_store import (
    CASE_COLUMNS,
    CUSTOMER_COLUMNS,
    append_hitl_feedback,
    append_archive_record,
    build_customer_profiles,
    get_archive,
    get_cases,
    get_customers,
    get_hitl_feedback,
    get_model_registry,
    get_str_cases,
    get_watchlist,
    make_case_id,
    make_customer_id,
    parse_payload,
    serialize_payload,
    upsert_case,
    upsert_customers,
    upsert_str_case,
    utc_now_iso,
)


def score_to_tier(score: float) -> str:
    if score >= ALERT_THRESHOLDS["Critical"]:
        return "Critical"
    if score >= ALERT_THRESHOLDS["High"]:
        return "High"
    if score >= ALERT_THRESHOLDS["Medium"]:
        return "Medium"
    return "Low"


def ensure_scored_defaults(scored_df: pd.DataFrame) -> pd.DataFrame:
    if scored_df is None:
        return pd.DataFrame()

    df = scored_df.copy()
    if "transaction_id" not in df.columns:
        df["transaction_id"] = df.index.astype(str)

    if "txn_dt" not in df.columns:
        df["txn_dt"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str), errors="coerce")

    df["risk_score"] = pd.to_numeric(df.get("risk_score", 0), errors="coerce").fillna(0.0)
    df["risk_score"] = df["risk_score"].clip(0, 1)
    if "rf_prediction" not in df.columns:
        df["rf_prediction"] = (df["risk_score"] >= ALERT_THRESHOLDS["Medium"]).astype(int)
    df["risk_tier"] = df["risk_score"].apply(score_to_tier)
    df["customer_id"] = df["Sender_account"].astype(str).apply(make_customer_id)
    df["amount_value"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["is_high_value"] = df["amount_value"] >= HIGH_VALUE_THRESHOLD
    return df


def sync_customer_profiles(scored_df: pd.DataFrame) -> pd.DataFrame:
    profiles = build_customer_profiles(ensure_scored_defaults(scored_df))
    if profiles.empty:
        return pd.DataFrame(columns=CUSTOMER_COLUMNS)

    existing = get_customers()
    if not existing.empty:
        preserved_columns = [
            "customer_id",
            "kyc_status",
            "cdd_level",
            "sanctions_flag",
            "sanctions_reason",
            "sanctions_match_source",
            "sanctions_cleared_reason",
            "sanctions_cleared_at",
            "sanctions_cleared_by",
            "created_at",
        ]
        preserved = existing[preserved_columns].copy().set_index("customer_id")
        profiles = profiles.set_index("customer_id")
        common_ids = profiles.index.intersection(preserved.index)
        for customer_id in common_ids:
            for column in preserved_columns:
                if column == "customer_id":
                    continue
                preserved_value = preserved.at[customer_id, column]
                if pd.notna(preserved_value) and str(preserved_value).strip() != "":
                    profiles.at[customer_id, column] = preserved_value
        profiles["updated_at"] = utc_now_iso()
        profiles = profiles.reset_index()[CUSTOMER_COLUMNS]

    return upsert_customers(profiles)


def screen_customer_against_watchlist(customer_row: pd.Series) -> dict[str, Any]:
    watchlist = get_watchlist()
    account_id = str(customer_row["account_id"])
    matches = watchlist[watchlist["account_id"].astype(str) == account_id]
    if matches.empty:
        return {"sanctions_flag": False, "sanctions_reason": "", "sanctions_match_source": ""}

    match = matches.iloc[0]
    return {
        "sanctions_flag": True,
        "sanctions_reason": str(match.get("reason", "Watchlist match")),
        "sanctions_match_source": str(match.get("watchlist_id", "")),
    }


def apply_sanctions_screening(customers_df: pd.DataFrame) -> pd.DataFrame:
    if customers_df.empty:
        return customers_df

    updated = customers_df.copy()
    screening = updated.apply(screen_customer_against_watchlist, axis=1, result_type="expand")
    updated["sanctions_flag"] = screening["sanctions_flag"]
    updated["sanctions_reason"] = screening["sanctions_reason"]
    updated["sanctions_match_source"] = screening["sanctions_match_source"]
    cleared_mask = updated["sanctions_cleared_reason"].astype(str).str.strip() != ""
    updated.loc[cleared_mask, "sanctions_flag"] = False
    updated["updated_at"] = utc_now_iso()
    return upsert_customers(updated[CUSTOMER_COLUMNS])


def clear_sanctions_flag(customer_id: str, reason: str, actor_id: str) -> pd.DataFrame:
    customers = get_customers()
    if customers.empty:
        return customers

    mask = customers["customer_id"].astype(str) == str(customer_id)
    customers.loc[mask, "sanctions_flag"] = False
    customers.loc[mask, "sanctions_cleared_reason"] = reason
    customers.loc[mask, "sanctions_cleared_at"] = utc_now_iso()
    customers.loc[mask, "sanctions_cleared_by"] = actor_id
    customers.loc[mask, "updated_at"] = utc_now_iso()
    upsert_customers(customers[CUSTOMER_COLUMNS])
    return customers


def ensure_case_for_transaction(txn: pd.Series, owner: str) -> dict[str, Any]:
    cases = get_cases()
    txid = str(txn["transaction_id"])
    if not cases.empty:
        matches = cases[cases["transaction_id"].astype(str) == txid]
        if not matches.empty:
            return matches.iloc[0].to_dict()

    row = {
        "case_id": make_case_id(),
        "transaction_id": txid,
        "customer_id": str(txn["customer_id"]),
        "account_id": str(txn["Sender_account"]),
        "alert_score": float(txn["risk_score"]),
        "alert_tier": str(txn["risk_tier"]),
        "status": CASE_STATUS_OPEN,
        "owner": owner,
        "cdd_level": CDD_LEVEL_STANDARD,
        "kyc_risk_tier": str(txn["risk_tier"]),
        "str_required": False,
        "opened_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "closed_at": "",
        "resolution": "",
        "notes": "",
        "attachment_count": 0,
        "attachment_names": "",
        "latest_attachment_at": "",
    }
    return upsert_case(row)


def update_case_record(case_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    cases = get_cases()
    if cases.empty:
        return {}

    matches = cases[cases["case_id"].astype(str) == str(case_id)]
    if matches.empty:
        return {}

    row = matches.iloc[0].to_dict()
    row.update(updates)
    row["updated_at"] = utc_now_iso()
    if row.get("status") in CASE_CLOSED_STATUSES and not row.get("closed_at"):
        row["closed_at"] = utc_now_iso()
    return upsert_case(row)


def attach_case_files(case_id: str, attachment_names: list[str]) -> dict[str, Any]:
    existing = update_case_record(
        case_id,
        {
            "attachment_count": len(attachment_names),
            "attachment_names": ", ".join(attachment_names),
            "latest_attachment_at": utc_now_iso() if attachment_names else "",
        },
    )
    return existing


def get_case_by_transaction(transaction_id: str) -> dict[str, Any] | None:
    cases = get_cases()
    if cases.empty:
        return None
    matches = cases[cases["transaction_id"].astype(str) == str(transaction_id)]
    if matches.empty:
        return None
    return matches.iloc[0].to_dict()


def get_related_transactions(scored_df: pd.DataFrame, txn_row: pd.Series, window_days: int = 30) -> pd.DataFrame:
    df = ensure_scored_defaults(scored_df)
    if df.empty:
        return df

    center = pd.to_datetime(txn_row["txn_dt"], errors="coerce")
    if pd.isna(center):
        return df.head(0)

    sender = str(txn_row["Sender_account"])
    customer_window = df[df["Sender_account"].astype(str) == sender].copy()
    start = center - timedelta(days=window_days)
    end = center + timedelta(days=window_days)
    customer_window = customer_window[(customer_window["txn_dt"] >= start) & (customer_window["txn_dt"] <= end)]
    customer_window["highlight_reason"] = ""
    customer_window.loc[customer_window["cross_currency"].astype(int) == 1, "highlight_reason"] += "Cross-currency "
    customer_window.loc[customer_window["cross_border"].astype(int) == 1, "highlight_reason"] += "Cross-border "
    customer_window.loc[customer_window["is_high_value"], "highlight_reason"] += "High-value"
    customer_window["highlight_reason"] = customer_window["highlight_reason"].str.strip()
    return customer_window.sort_values("txn_dt", ascending=False)


def record_hitl_feedback(transaction_id: str, customer_id: str, original_prediction: str, corrected_label: str, reason: str, actor_id: str) -> dict[str, Any]:
    return append_hitl_feedback(
        {
            "transaction_id": transaction_id,
            "customer_id": customer_id,
            "original_prediction": original_prediction,
            "corrected_label": corrected_label,
            "reason": reason,
            "actor_id": actor_id,
        }
    )


def get_all_str_records() -> pd.DataFrame:
    """Return all STR records from str_cases sorted by last update descending."""
    cases = get_str_cases()
    if cases.empty:
        return cases
    cases["updated_at"] = pd.to_datetime(cases["updated_at"], errors="coerce")
    return cases.sort_values("updated_at", ascending=False).reset_index(drop=True)


def upsert_str_workflow(case_row: dict[str, Any], grounds: str, status: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "str_id": case_row.get("str_id", ""),
        "case_id": case_row.get("case_id", ""),
        "transaction_id": case_row.get("transaction_id", ""),
        "customer_id": case_row.get("customer_id", ""),
        "status": status,
        "reference_number": case_row.get("reference_number", ""),
        "grounds": grounds,
    }
    if updates:
        payload.update(updates)
    return upsert_str_case(payload)


def archive_str_case(str_row: dict[str, Any], archived_by: str, summary: dict[str, Any]) -> dict[str, Any]:
    archive_summary = dict(summary)
    archive_summary["str_id"] = str_row.get("str_id", "")
    archive_summary["case_id"] = str_row.get("case_id", "")
    archive_summary["transaction_id"] = str_row.get("transaction_id", "")
    archive_summary["customer_id"] = str_row.get("customer_id", "")
    archive_summary["str_status"] = str_row.get("status", "")
    archive_summary["archived_by"] = archived_by
    return append_archive_record(archive_summary)


def build_dashboard_metrics(scored_df: pd.DataFrame) -> dict[str, Any]:
    df = ensure_scored_defaults(scored_df)
    cases = get_cases()
    archive = get_archive()
    now = pd.Timestamp.utcnow()

    open_by_tier = {}
    avg_time_to_action_hours = 0.0
    alerts_cleared_today = 0
    if not cases.empty:
        cases["opened_at_dt"] = pd.to_datetime(cases["opened_at"], errors="coerce", utc=True)
        cases["updated_at_dt"] = pd.to_datetime(cases["updated_at"], errors="coerce", utc=True)
        open_cases = cases[cases["status"].isin(CASE_OPEN_STATUSES)]
        open_by_tier = open_cases.groupby("alert_tier").size().to_dict()

        acted = cases[cases["updated_at_dt"].notna() & cases["opened_at_dt"].notna()].copy()
        if not acted.empty:
            avg_time_to_action_hours = float(
                ((acted["updated_at_dt"] - acted["opened_at_dt"]).dt.total_seconds().mean()) / 3600
            )

        alerts_cleared_today = int(
            cases[
                (cases["status"].isin(CASE_CLOSED_STATUSES))
                & (cases["updated_at_dt"].dt.date == now.date())
            ].shape[0]
        )

    archive_count_week = 0
    if not archive.empty:
        archive["archived_at_dt"] = pd.to_datetime(archive["archived_at"], errors="coerce", utc=True)
        week_start = now - pd.Timedelta(days=7)
        archive_count_week = int((archive["archived_at_dt"] >= week_start).sum())

    tier_series = df["risk_tier"].value_counts().to_dict() if not df.empty else {}
    high_risk_customers = get_customers()
    cdd_breakdown = {}
    if not high_risk_customers.empty:
        cdd_breakdown = high_risk_customers.groupby("cdd_level").size().to_dict()

    hitl = get_hitl_feedback()
    fp_rate = 0.0
    if not hitl.empty:
        fp_rate = float((hitl["corrected_label"].astype(str) == "False Positive").mean())

    registry = get_model_registry().get("models", [])
    current_model = registry[-1] if registry else {}

    return {
        "open_alerts_by_tier": open_by_tier or tier_series,
        "avg_time_to_action_hours": round(avg_time_to_action_hours, 2),
        "alerts_cleared_today": alerts_cleared_today,
        "strs_filed_this_week": archive_count_week,
        "high_risk_customer_count": int(
            high_risk_customers["kyc_risk_tier"].astype(str).eq("High").sum()
        )
        if not high_risk_customers.empty
        else 0,
        "cdd_breakdown": cdd_breakdown,
        "fp_rate": round(fp_rate, 4),
        "current_model": current_model,
    }


def build_governance_datasets() -> dict[str, pd.DataFrame]:
    hitl = get_hitl_feedback()
    cases = get_cases()
    registry = pd.DataFrame(get_model_registry().get("models", []))

    if not cases.empty:
        cases["updated_at_dt"] = pd.to_datetime(cases["updated_at"], errors="coerce", utc=True)
        cases["week"] = cases["updated_at_dt"].dt.tz_localize(None).dt.to_period("W").astype(str)
    if not hitl.empty:
        hitl["timestamp_dt"] = pd.to_datetime(hitl["timestamp_utc"], errors="coerce", utc=True)
        hitl["week"] = hitl["timestamp_dt"].dt.tz_localize(None).dt.to_period("W").astype(str)

    return {"hitl": hitl, "cases": cases, "registry": registry}


def build_archive_search_view() -> pd.DataFrame:
    archive = get_archive()
    if archive.empty:
        return archive
    archive["summary"] = archive["summary_json"].apply(parse_payload)
    archive["customer_name"] = archive["summary"].apply(lambda s: s.get("customer_name", ""))
    return archive


def merge_case_into_session_case(existing_case: dict[str, Any], str_case: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(existing_case)
    if str_case:
        merged.update(str_case)
    merged["customer_id"] = merged.get("customer_id") or make_customer_id(merged.get("sender_account", ""))
    return merged
