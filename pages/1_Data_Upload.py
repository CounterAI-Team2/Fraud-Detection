from __future__ import annotations

import time
import pandas as pd
import streamlit as st

from utils.audit_logger import log_action
from utils.feature_engineering import ENGINEERED_FEATURES, SAML_REQUIRED_COLUMNS, engineer_features, validate_schema
from utils.model_loader import load_models

st.title("1. Data Upload")
st.caption("Upload SAML-D schema CSV and flag transactions predicted as money laundering by the pretrained RF model.")

uploaded = st.file_uploader("Upload CSV", type=["csv"])
cap_rows = st.number_input("Demo row cap (for speed)", min_value=1000, max_value=200000, value=50000, step=1000)


def _tier(score: float) -> str:
    if score >= 1.0:
        return "Critical"
    return "Low"


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

    base_features = ENGINEERED_FEATURES + [
        "Payment_type",
        "Payment_currency",
        "Received_currency",
        "Sender_bank_location",
        "Receiver_bank_location",
    ]

    x = pd.get_dummies(
        feat[base_features].copy(),
        columns=[
            "Payment_type",
            "Payment_currency",
            "Received_currency",
            "Sender_bank_location",
            "Receiver_bank_location",
        ],
        drop_first=False,
    )

    rf_cols = list(rf_model.feature_names_in_)
    x_rf = x.reindex(columns=rf_cols, fill_value=0)
    pred = rf_model.predict(x_rf).astype(int)

    feat["rf_prediction"] = pred
    feat["risk_score"] = pred  # compatibility field for downstream pages
    feat["risk_tier"] = feat["risk_score"].apply(_tier)

    # initialize alert status for this dataset
    statuses = {}
    for txid in feat["transaction_id"].astype(str).tolist():
        statuses[txid] = {"status": "New", "reason": ""}

    st.session_state["scored_df"] = feat
    st.session_state["alert_status"] = statuses

    elapsed = time.time() - t0

    tier_counts = feat["risk_tier"].value_counts().to_dict()
    flagged_count = int((feat["risk_score"] == 1).sum())

    st.success("Dataset processed successfully.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Transactions Scored", f"{len(feat):,}")
    c2.metric("Flagged by RF", f"{flagged_count:,}")
    c3.metric("Processing Time", f"{elapsed:.2f}s")

    st.write("Tier Counts", tier_counts)

    log_action(
        action="dataset_uploaded",
        details=(
            f"filename={uploaded.name}; row_count={len(feat)}; "
            f"flagged_count={flagged_count}; tiers={tier_counts}"
        ),
    )

    st.subheader("Preview")
    st.dataframe(feat.head(30), use_container_width=True)

else:
    st.info("Expected columns:\n" + ", ".join(SAML_REQUIRED_COLUMNS))
