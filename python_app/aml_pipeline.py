from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier


REQUIRED_COLUMNS = [
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


@dataclass
class TrainedModels:
    rf: RandomForestClassifier
    cart: DecisionTreeClassifier
    logit: LogisticRegression
    feature_columns: List[str]
    means: pd.Series


def validate_dataset(df: pd.DataFrame, require_target: bool) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    if require_target and "Is_laundering" not in df.columns:
        raise ValueError("Training dataset must include Is_laundering column")


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0)
    out["amount_log"] = np.log10(out["Amount"] + 1)

    out["cross_currency"] = (out["Payment_currency"].astype(str) != out["Received_currency"].astype(str)).astype(int)
    out["cross_border"] = (out["Sender_bank_location"].astype(str) != out["Receiver_bank_location"].astype(str)).astype(int)
    out["double_flag"] = ((out["cross_currency"] == 1) & (out["cross_border"] == 1)).astype(int)

    out["sender_txn_count"] = out.groupby("Sender_account")["Sender_account"].transform("count")
    out["receiver_txn_count"] = out.groupby("Receiver_account")["Receiver_account"].transform("count")

    out["sender_unique_receivers"] = out.groupby("Sender_account")["Receiver_account"].transform("nunique")
    out["receiver_unique_senders"] = out.groupby("Receiver_account")["Sender_account"].transform("nunique")

    out["sender_total_amount"] = out.groupby("Sender_account")["Amount"].transform("sum")
    out["receiver_total_amount"] = out.groupby("Receiver_account")["Amount"].transform("sum")

    out["Time"] = out["Time"].astype(str)
    parsed_time = pd.to_datetime(out["Time"], format="%H:%M:%S", errors="coerce")
    out["hour"] = parsed_time.dt.hour.fillna(0).astype(int)

    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["day_of_week"] = out["Date"].dt.dayofweek.fillna(0).astype(int)
    out["is_off_hours"] = ((out["hour"] < 6) | (out["hour"] >= 22)).astype(int)

    return out


def _to_model_matrix(df: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "amount_log",
        "cross_currency",
        "cross_border",
        "sender_txn_count",
        "receiver_txn_count",
        "sender_unique_receivers",
        "receiver_unique_senders",
        "hour",
        "day_of_week",
        "is_off_hours",
        "Payment_type",
        "Payment_currency",
        "Received_currency",
        "Sender_bank_location",
        "Receiver_bank_location",
    ]
    x = df[keep].copy()
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


def train_models(df: pd.DataFrame, random_state: int = 147) -> Tuple[TrainedModels, Dict[str, float]]:
    validate_dataset(df, require_target=True)
    feat = engineer_features(df)

    y = pd.to_numeric(feat["Is_laundering"], errors="coerce").fillna(0).astype(int)
    x = _to_model_matrix(feat)

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.3, random_state=random_state, stratify=y if y.nunique() > 1 else None
    )

    rf = RandomForestClassifier(n_estimators=200, random_state=random_state, class_weight="balanced")
    cart = DecisionTreeClassifier(max_depth=8, random_state=random_state, class_weight="balanced")
    logit = LogisticRegression(max_iter=600, class_weight="balanced")

    rf.fit(x_train, y_train)
    cart.fit(x_train, y_train)
    logit.fit(x_train, y_train)

    metrics = {
        "rf_test_accuracy": float(rf.score(x_test, y_test)),
        "cart_test_accuracy": float(cart.score(x_test, y_test)),
        "logit_test_accuracy": float(logit.score(x_test, y_test)),
    }

    models = TrainedModels(
        rf=rf,
        cart=cart,
        logit=logit,
        feature_columns=list(x.columns),
        means=x.mean(numeric_only=True),
    )
    return models, metrics


def score_transactions(df: pd.DataFrame, models: TrainedModels) -> pd.DataFrame:
    validate_dataset(df, require_target=False)
    feat = engineer_features(df)

    x = _to_model_matrix(feat)
    x = x.reindex(columns=models.feature_columns, fill_value=0)

    p_rf = models.rf.predict_proba(x)[:, 1]
    p_cart = models.cart.predict_proba(x)[:, 1]
    p_logit = models.logit.predict_proba(x)[:, 1]

    unified = (p_rf + p_cart + p_logit) / 3.0
    risk_band = np.where(unified >= 0.8, "HIGH", np.where(unified >= 0.5, "MEDIUM", "LOW"))
    flagged = risk_band != "LOW"

    out = df.copy()
    out["ai_risk_score"] = np.round(unified, 4)
    out["risk_band"] = risk_band
    out["flagged_case"] = flagged
    out["investigation_status"] = np.where(flagged, "OPEN", "DISMISSED")

    coefs = pd.Series(models.logit.coef_[0], index=models.feature_columns)
    top_features = []
    for i in range(len(x)):
        contrib = (x.iloc[i] * coefs).abs().sort_values(ascending=False).head(3)
        top_features.append(
            "; ".join([f"{k}={v:.3f}" for k, v in contrib.items()]) if len(contrib) > 0 else "N/A"
        )
    out["xai_rationale"] = top_features

    return out


def build_kyc_view(scored_df: pd.DataFrame) -> pd.DataFrame:
    # MVP heuristic KYC profile from transactional attributes.
    kyc = (
        scored_df.groupby("Sender_account", as_index=False)
        .agg(
            avg_score=("ai_risk_score", "mean"),
            tx_count=("Sender_account", "count"),
            main_country=("Sender_bank_location", lambda s: s.astype(str).mode().iloc[0] if not s.empty else "UNK"),
        )
    )
    kyc["kyc_risk_tier"] = np.where(kyc["avg_score"] >= 0.8, "HIGH", np.where(kyc["avg_score"] >= 0.5, "MEDIUM", "LOW"))
    return kyc


def build_cdd_cases(scored_df: pd.DataFrame) -> pd.DataFrame:
    flagged = scored_df[scored_df["flagged_case"]].copy()
    if flagged.empty:
        return flagged

    flagged["cdd_level"] = np.where(flagged["ai_risk_score"] >= 0.85, "ENHANCED", "STANDARD")
    flagged["str_required"] = flagged["ai_risk_score"] >= 0.85
    flagged["case_id"] = [f"CDD-{i+1:05d}" for i in range(len(flagged))]
    return flagged[["case_id", "Sender_account", "Receiver_account", "Amount", "ai_risk_score", "risk_band", "cdd_level", "str_required", "xai_rationale"]]


def build_dashboard(scored_df: pd.DataFrame, cdd_df: pd.DataFrame) -> pd.DataFrame:
    total = len(scored_df)
    flagged = int(scored_df["flagged_case"].sum())
    high = int((scored_df["risk_band"] == "HIGH").sum())
    medium = int((scored_df["risk_band"] == "MEDIUM").sum())
    str_count = int(cdd_df["str_required"].sum()) if not cdd_df.empty else 0
    str_rate = (str_count / flagged) if flagged else 0.0

    return pd.DataFrame(
        {
            "metric": [
                "transactions_scored",
                "flagged_cases",
                "high_risk_cases",
                "medium_risk_cases",
                "str_required_cases",
                "str_filing_rate",
            ],
            "value": [total, flagged, high, medium, str_count, round(str_rate, 4)],
        }
    )
