from __future__ import annotations

import io
from pathlib import Path

import joblib
import pandas as pd
import streamlit as st

from aml_pipeline import (
    REQUIRED_COLUMNS,
    build_cdd_cases,
    build_dashboard,
    build_kyc_view,
    score_transactions,
    validate_dataset,
)

MODEL_PATH = Path("models/aml_models.joblib")

st.set_page_config(page_title="CounterAI MVP 0.1", layout="wide")
st.title("CounterAI MVP 0.1 - End-to-End AML Workflow")

st.markdown(
    "Upload a new dataset and flag possible money laundering cases using pretrained models from Assignment 2 data."
)

with st.sidebar:
    st.header("Inputs")
    score_file = st.file_uploader("Scoring dataset CSV", type=["csv"])
    score_threshold_medium = st.slider("Medium risk threshold", 0.1, 0.9, 0.5, 0.01)
    score_threshold_high = st.slider("High risk threshold", 0.5, 0.99, 0.8, 0.01)
    run_btn = st.button("Run Full AML Flow", type="primary")


@st.cache_resource
def load_models():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Pretrained model bundle not found at {MODEL_PATH}. "
            "Run: python python_app/train_pretrained_models.py"
        )
    return joblib.load(MODEL_PATH)


def _read_csv(uploaded) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(uploaded.getvalue()))


if run_btn:
    if score_file is None:
        st.error("Please upload a scoring CSV file.")
        st.stop()

    try:
        score_df = _read_csv(score_file)
        validate_dataset(score_df, require_target=False)

        models = load_models()
        scored = score_transactions(score_df, models)

        scored["risk_band"] = "LOW"
        scored.loc[scored["ai_risk_score"] >= score_threshold_medium, "risk_band"] = "MEDIUM"
        scored.loc[scored["ai_risk_score"] >= score_threshold_high, "risk_band"] = "HIGH"
        scored["flagged_case"] = scored["risk_band"].isin(["MEDIUM", "HIGH"])
        scored["investigation_status"] = scored["flagged_case"].map({True: "OPEN", False: "DISMISSED"})

        kyc_df = build_kyc_view(scored)
        cdd_df = build_cdd_cases(scored)
        dashboard_df = build_dashboard(scored, cdd_df)

        st.success("AML flow completed with pretrained models.")

        col1, col2, col3 = st.columns(3)
        col1.metric("Flagged Cases", int(scored["flagged_case"].sum()))
        col2.metric("High Risk", int((scored["risk_band"] == "HIGH").sum()))
        col3.metric("STR Required", int(cdd_df["str_required"].sum()) if not cdd_df.empty else 0)

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            [
                "KYC",
                "Transaction Monitoring",
                "Explainable AI",
                "Investigations (CDD)",
                "Dashboard",
                "Downloads",
            ]
        )

        with tab1:
            st.dataframe(kyc_df, use_container_width=True)

        with tab2:
            cols = [
                "Sender_account",
                "Receiver_account",
                "Amount",
                "ai_risk_score",
                "risk_band",
                "flagged_case",
                "investigation_status",
            ]
            st.dataframe(scored[cols], use_container_width=True)

        with tab3:
            xai_cols = [
                "Sender_account",
                "Receiver_account",
                "Amount",
                "ai_risk_score",
                "risk_band",
                "xai_rationale",
            ]
            st.dataframe(scored[xai_cols], use_container_width=True)

        with tab4:
            if cdd_df.empty:
                st.info("No flagged cases requiring CDD in this run.")
            else:
                st.dataframe(cdd_df, use_container_width=True)

        with tab5:
            st.dataframe(dashboard_df, use_container_width=True)

        with tab6:
            st.download_button(
                "Download Scored Cases CSV",
                data=scored.to_csv(index=False).encode("utf-8"),
                file_name="scored_cases.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download CDD Cases CSV",
                data=cdd_df.to_csv(index=False).encode("utf-8"),
                file_name="cdd_cases.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download Dashboard Metrics CSV",
                data=dashboard_df.to_csv(index=False).encode("utf-8"),
                file_name="dashboard_metrics.csv",
                mime="text/csv",
            )

    except Exception as exc:
        st.error(f"Run failed: {exc}")

else:
    st.info("Upload a dataset and click 'Run Full AML Flow' to start.")
    st.markdown("**Expected columns**")
    st.code("\n".join(REQUIRED_COLUMNS))
    st.caption("Model source: pretrained bundle from Assignment 2 dataset in project folder.")
