from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, train_test_split
from sklearn.tree import DecisionTreeClassifier


REQUIRED_COLUMNS = [
    "Time",
    "Date",
    "Sender_account",
    "Receiver_account",
    "Laundering_type",
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


def _engineer_row_features(df: pd.DataFrame) -> pd.DataFrame:
    """Row-level features only — no cross-row aggregations, safe to call on any subset."""
    out = df.copy()
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0)
    out["amount_log"] = np.log10(out["Amount"] + 1)
    out["cross_currency"] = (out["Payment_currency"].astype(str) != out["Received_currency"].astype(str)).astype(int)
    out["cross_border"] = (out["Sender_bank_location"].astype(str) != out["Receiver_bank_location"].astype(str)).astype(int)
    out["double_flag"] = ((out["cross_currency"] == 1) & (out["cross_border"] == 1)).astype(int)
    out["Time"] = out["Time"].astype(str)
    parsed_time = pd.to_datetime(out["Time"], format="%H:%M:%S", errors="coerce")
    out["hour"] = parsed_time.dt.hour.fillna(0).astype(int)
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["day_of_week"] = out["Date"].dt.dayofweek.fillna(0).astype(int)
    out["is_off_hours"] = ((out["hour"] < 6) | (out["hour"] >= 22)).astype(int)
    # Laundering_type is a post-hoc investigator label (target leak) — excluded from features.
    return out


def _compute_group_stats(df: pd.DataFrame) -> dict:
    """Compute aggregation lookup tables — must be called on training data only."""
    sender_stats = df.groupby("Sender_account", as_index=False).agg(
        sender_txn_count=("Sender_account", "count"),
        sender_unique_receivers=("Receiver_account", "nunique"),
        sender_total_amount=("Amount", "sum"),
    )
    receiver_stats = df.groupby("Receiver_account", as_index=False).agg(
        receiver_txn_count=("Receiver_account", "count"),
        receiver_unique_senders=("Sender_account", "nunique"),
        receiver_total_amount=("Amount", "sum"),
    )
    return {
        "sender_stats": sender_stats,
        "receiver_stats": receiver_stats,
        "sender_fallback": {
            "sender_txn_count": float(sender_stats["sender_txn_count"].mean()),
            "sender_unique_receivers": float(sender_stats["sender_unique_receivers"].mean()),
            "sender_total_amount": float(sender_stats["sender_total_amount"].mean()),
        },
        "receiver_fallback": {
            "receiver_txn_count": float(receiver_stats["receiver_txn_count"].mean()),
            "receiver_unique_senders": float(receiver_stats["receiver_unique_senders"].mean()),
            "receiver_total_amount": float(receiver_stats["receiver_total_amount"].mean()),
        },
    }


def _apply_group_stats(df: pd.DataFrame, group_stats: dict) -> pd.DataFrame:
    """Merge pre-computed group stats onto df; unseen accounts receive training-set means."""
    out = df.merge(group_stats["sender_stats"], on="Sender_account", how="left")
    out = out.merge(group_stats["receiver_stats"], on="Receiver_account", how="left")
    for col, val in group_stats["sender_fallback"].items():
        out[col] = out[col].fillna(val)
    for col, val in group_stats["receiver_fallback"].items():
        out[col] = out[col].fillna(val)
    return out


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Full feature engineering for inference — group stats derived from the scoring batch itself."""
    out = _engineer_row_features(df)
    group_stats = _compute_group_stats(out)
    out = _apply_group_stats(out, group_stats)
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
        # "Laundering_type",  # target leak — excluded
    ]
    available = [c for c in keep if c in df.columns]
    x = df[available].copy()
    cat_cols = [
        c for c in [
            "Payment_type",
            "Payment_currency",
            "Received_currency",
            "Sender_bank_location",
            "Receiver_bank_location",
            # "Laundering_type",  # target leak — excluded
        ]
        if c in x.columns
    ]
    x = pd.get_dummies(x, columns=cat_cols, drop_first=False)
    return x


def _clf_metrics(y_true: pd.Series, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, int(cm[0, 0]))
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "tp": int(tp),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
    }


def tune_rf_hyperparameters(
    df: pd.DataFrame,
    random_state: int = 147,
    n_iter: int = 40,
    cv_folds: int = 5,
    scoring: str = "f1",
    n_jobs: int = 1,
) -> tuple[dict[str, Any], float]:
    validate_dataset(df, require_target=True)
    feat = engineer_features(df)
    y = pd.to_numeric(feat["Is_laundering"], errors="coerce").fillna(0).astype(int)
    x = _to_model_matrix(feat)

    param_dist = {
        "n_estimators": [200, 400, 600, 800],
        "max_depth": [None, 8, 12, 16, 24],
        "min_samples_split": [2, 5, 10, 20],
        "min_samples_leaf": [1, 2, 4, 8],
        "max_features": ["sqrt", "log2", 0.3, 0.5, 0.8],
        "class_weight": ["balanced", "balanced_subsample", None],
    }

    rf = RandomForestClassifier(random_state=random_state)
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    search = RandomizedSearchCV(
        rf,
        param_distributions=param_dist,
        n_iter=n_iter,
        scoring=scoring,
        cv=cv,
        n_jobs=n_jobs,
        verbose=1,
        random_state=random_state,
    )
    search.fit(x, y)
    return search.best_params_, float(search.best_score_)


def train_models(
    df: pd.DataFrame,
    random_state: int = 147,
    rf_overrides: dict[str, Any] | None = None,
) -> Tuple[TrainedModels, Dict]:
    validate_dataset(df, require_target=True)

    # 1. Split raw data FIRST to prevent group-by aggregation and encoding leakage
    y_full = pd.to_numeric(df["Is_laundering"], errors="coerce").fillna(0).astype(int)
    df_train_raw, df_test_raw, y_train, y_test = train_test_split(
        df, y_full, test_size=0.3, random_state=random_state,
        stratify=y_full if y_full.nunique() > 1 else None,
    )
    df_train_raw = df_train_raw.reset_index(drop=True)
    df_test_raw  = df_test_raw.reset_index(drop=True)
    y_train      = y_train.reset_index(drop=True)
    y_test       = y_test.reset_index(drop=True)

    # 2. Engineer features — group stats from train only, then applied to test
    feat_train = _engineer_row_features(df_train_raw)
    group_stats = _compute_group_stats(feat_train)
    feat_train = _apply_group_stats(feat_train, group_stats)

    feat_test = _engineer_row_features(df_test_raw)
    feat_test = _apply_group_stats(feat_test, group_stats)

    # 3. Dummy encoding fit on train, reindexed for test (no category leakage)
    x_train = _to_model_matrix(feat_train)
    feature_columns = list(x_train.columns)
    x_test = _to_model_matrix(feat_test).reindex(columns=feature_columns, fill_value=0)

    # 4. Balance training set by downsampling majority class
    train_bal = pd.concat([x_train, y_train.rename("target")], axis=1)
    minority = train_bal[train_bal["target"] == 1]
    majority = train_bal[train_bal["target"] == 0]
    if not minority.empty and len(majority) > len(minority):
        majority = majority.sample(n=len(minority), random_state=random_state)
        train_bal = pd.concat([majority, minority], axis=0).sample(frac=1, random_state=random_state)
    y_train_bal = train_bal["target"].astype(int)
    x_train_bal = train_bal.drop(columns=["target"])

    # 5. Train
    rf_params = {"n_estimators": 200, "class_weight": "balanced"}
    if rf_overrides:
        rf_params.update(rf_overrides)
    rf = RandomForestClassifier(random_state=random_state, **rf_params)
    cart = DecisionTreeClassifier(max_depth=8, random_state=random_state, class_weight="balanced")
    logit = LogisticRegression(max_iter=2000, class_weight="balanced")
    rf.fit(x_train_bal, y_train_bal)
    cart.fit(x_train_bal, y_train_bal)
    logit.fit(x_train_bal, y_train_bal)

    # 6. Evaluate on held-out test set
    rf_pred = rf.predict(x_test)
    cart_pred = cart.predict(x_test)
    logit_pred = logit.predict(x_test)
    rf_prob = rf.predict_proba(x_test)[:, 1]
    cart_prob = cart.predict_proba(x_test)[:, 1]
    logit_prob = logit.predict_proba(x_test)[:, 1]

    metrics = {
        "test_size": int(len(y_test)),
        "test_positives": int((y_test == 1).sum()),
        "balanced_train_rows": int(len(x_train_bal)),
        "balanced_train_positives": int((y_train_bal == 1).sum()),
        "rf": _clf_metrics(y_test, rf_pred, rf_prob),
        "cart": _clf_metrics(y_test, cart_pred, cart_prob),
        "logit": _clf_metrics(y_test, logit_pred, logit_prob),
        "rf_params": rf.get_params(),
    }

    models = TrainedModels(
        rf=rf,
        cart=cart,
        logit=logit,
        feature_columns=feature_columns,
        means=x_train.mean(numeric_only=True),
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