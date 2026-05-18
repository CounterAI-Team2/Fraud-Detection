from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from utils.audit_logger import log_action
from utils.aml_services import ensure_scored_defaults, sync_customer_profiles
from utils.kyc_store import ensure_kyc_database, upgrade_kyc_risk_from_transactions
from utils.constants import ALERT_STATUS_NEW, DATA_PREVIEW_LIMIT
from utils.data_store import get_model_registry
from utils.feature_engineering import CATEGORICAL_FEATURES, ENGINEERED_FEATURES, SAML_REQUIRED_COLUMNS, engineer_features, prepare_model_matrix, validate_schema
from utils.model_loader import load_models
from utils.session_utils import get_current_analyst

st.title("2. Data Upload")

ensure_kyc_database()
st.caption("Upload a transaction CSV, validate schema, engineer AML features, score risk, and persist customer profiles for downstream review.")

uploaded = st.file_uploader("Upload CSV", type=["csv"])
cap_rows = st.number_input("Demo row cap (for speed)", min_value=1000, max_value=200000, value=50000, step=1000)
threshold = st.slider("Risk threshold", min_value=0.05, max_value=0.95, value=0.50, step=0.05)


if uploaded is not None:
    t0 = time.time()
    raw = pd.read_csv(uploaded)

    ok, missing = validate_schema(raw)
    if not ok:
        st.error(f"Schema mismatch. Missing columns: {missing}")
        st.stop()

    if len(raw) > cap_rows:
        raw = raw.head(int(cap_rows)).copy()
        st.warning(f"Dataset capped to first {cap_rows:,} rows for MVP performance.")

    feat = engineer_features(raw)
    rf_model, _, _ = load_models()

    x_rf = prepare_model_matrix(feat[ENGINEERED_FEATURES + CATEGORICAL_FEATURES], rf_model.feature_names_in_)
    if hasattr(rf_model, "predict_proba"):
        risk_probability = rf_model.predict_proba(x_rf)[:, 1]
    else:
        risk_probability = rf_model.predict(x_rf).astype(float)
    pred = (risk_probability >= threshold).astype(int)

    feat["rf_prediction"] = pred
    feat["risk_score"] = risk_probability
    feat["risk_threshold"] = threshold
    feat["prediction_wrong"] = ""
    feat["prediction_feedback_reason"] = ""
    feat = ensure_scored_defaults(feat)
    analyst_id, actor_role = get_current_analyst()

    # initialize alert status for this dataset
    statuses = {}
    for txid in feat["transaction_id"].astype(str).tolist():
        statuses[txid] = {"status": ALERT_STATUS_NEW, "reason": ""}

    st.session_state["scored_df"] = feat
    st.session_state["alert_status"] = statuses
    customer_profiles = sync_customer_profiles(feat)
    upgraded_kyc_ids = upgrade_kyc_risk_from_transactions(feat)

    elapsed = time.time() - t0

    tier_counts = feat["risk_tier"].value_counts().to_dict()
    flagged_count = int((feat["rf_prediction"] == 1).sum())
    registry = get_model_registry().get("models", [])
    current_model = registry[-1] if registry else {}

    st.success("Dataset processed successfully.")
    if upgraded_kyc_ids:
        st.warning(
            "KYC risk upgraded to **Medium** for customer ID(s) linked to suspicious transactions: "
            + ", ".join(f"`{cid}`" for cid in upgraded_kyc_ids)
        )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Transactions Scored", f"{len(feat):,}")
    c2.metric("Flagged Above Threshold", f"{flagged_count:,}")
    c3.metric("Processing Time", f"{elapsed:.2f}s")
    c4.metric("Customer Profiles Synced", f"{len(customer_profiles):,}")

    st.write("Tier Counts", tier_counts)
    if current_model:
        st.caption(
            "Current model registry entry: "
            f"{current_model.get('model_id', '')} / version {current_model.get('version', '')}"
        )

    log_action(
        action="dataset_uploaded",
        details=f"filename={uploaded.name}; row_count={len(feat)}; flagged_count={flagged_count}",
        analyst_id=analyst_id,
        module="data_upload",
        event_type="dataset_uploaded",
        entity_type="dataset",
        entity_id=uploaded.name,
        actor_role=actor_role,
        payload={
            "filename": uploaded.name,
            "row_count": len(feat),
            "flagged_count": flagged_count,
            "tiers": tier_counts,
            "threshold": threshold,
        },
    )

    for _, row in feat.iterrows():
        log_action(
            action="prediction_generated",
            transaction_id=str(row["transaction_id"]),
            details=f"risk_score={float(row['risk_score']):.4f}; risk_tier={row['risk_tier']}",
            analyst_id=analyst_id,
            module="risk_scoring",
            event_type="prediction_generated",
            entity_type="transaction",
            entity_id=str(row["transaction_id"]),
            actor_role=actor_role,
            payload={
                "risk_score": round(float(row["risk_score"]), 4),
                "risk_tier": row["risk_tier"],
                "threshold": threshold,
                "prediction": int(row["rf_prediction"]),
            },
        )

    st.subheader("Preview")
    st.dataframe(
        feat[
            [
                "transaction_id",
                "Date",
                "Time",
                "Sender_account",
                "Receiver_account",
                "Amount",
                "risk_score",
                "risk_tier",
                "rf_prediction",
            ]
        ].head(DATA_PREVIEW_LIMIT),
        use_container_width=True,
    )

else:
    st.info("Expected columns:\n" + ", ".join(SAML_REQUIRED_COLUMNS))
