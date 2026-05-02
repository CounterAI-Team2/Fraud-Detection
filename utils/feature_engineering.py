from __future__ import annotations

import pandas as pd
import numpy as np

SAML_REQUIRED_COLUMNS = [
    "Time",
    "Date",
    "Sender_account",
    "Receiver_account",
    "Amount",
    "Payment_currency",
    "Received_currency",
    "Sender_bank_location",
    "Receiver_bank_location",
    "Payment_type",
]

ENGINEERED_FEATURES = [
    "amount_log",
    "cross_border",
    "cross_currency",
    "sender_txn_count",
    "receiver_txn_count",
    "sender_unique_receivers",
    "receiver_unique_senders",
    "hour",
    "day_of_week",
    "is_off_hours",
]


def validate_schema(df: pd.DataFrame) -> tuple[bool, list[str]]:
    missing = [c for c in SAML_REQUIRED_COLUMNS if c not in df.columns]
    return (len(missing) == 0, missing)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0)
    out["amount_log"] = np.log10(out["Amount"] + 1)

    out["cross_currency"] = (out["Payment_currency"].astype(str) != out["Received_currency"].astype(str)).astype(int)
    out["cross_border"] = (out["Sender_bank_location"].astype(str) != out["Receiver_bank_location"].astype(str)).astype(int)

    out["sender_txn_count"] = out.groupby("Sender_account")["Sender_account"].transform("count")
    out["receiver_txn_count"] = out.groupby("Receiver_account")["Receiver_account"].transform("count")

    out["sender_unique_receivers"] = out.groupby("Sender_account")["Receiver_account"].transform("nunique")
    out["receiver_unique_senders"] = out.groupby("Receiver_account")["Sender_account"].transform("nunique")

    parsed_time = pd.to_datetime(out["Time"].astype(str), format="%H:%M:%S", errors="coerce")
    out["hour"] = parsed_time.dt.hour.fillna(0).astype(int)

    parsed_date = pd.to_datetime(out["Date"], errors="coerce")
    out["day_of_week"] = parsed_date.dt.dayofweek.fillna(0).astype(int)
    out["is_off_hours"] = ((out["hour"] < 6) | (out["hour"] >= 22)).astype(int)

    # Convenience fields for UX and filtering
    out["transaction_id"] = out.index.astype(str)
    if "transaction_id" in df.columns:
        out["transaction_id"] = df["transaction_id"].astype(str)

    out["txn_dt"] = pd.to_datetime(out["Date"].astype(str) + " " + out["Time"].astype(str), errors="coerce")

    return out


def build_model_matrix(df_feat: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    x = df_feat[feature_columns].copy()
    x = pd.get_dummies(
        x,
        columns=[
            "Payment_type",
            "Payment_currency",
            "Received_currency",
            "Sender_bank_location",
            "Receiver_bank_location",
        ],
        drop_first=False,
    )
    return x
