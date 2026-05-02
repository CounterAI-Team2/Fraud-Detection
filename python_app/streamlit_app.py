from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from aml_pipeline import (
    REQUIRED_COLUMNS,
    build_cdd_cases,
    build_dashboard,
    build_kyc_view,
    score_transactions,
    train_models,
    validate_dataset,
)

st.set_page_config(page_title="CounterAI MVP 0.1", layout="wide")
st.title("CounterAI MVP 0.1 - End-to-End AML Workflow")

st.markdown(
    "Upload training data (with `Is_laundering`) and monitoring data, then run the full flow: KYC -> Transaction Monitoring -> XAI -> CDD Investigation -> Dashboard."
)

with st.sidebar:
    st.header("Inputs")
    train_file = st.file_uploader("Training dataset CSV (must include Is_laundering)", type=["csv"])
    score_file = st.file_uploader("Scoring dataset CSV (for flagging cases)", type=["csv"])
    score_threshold_medium = st.slider("Medium risk threshold", 0.1, 0.9, 0.5, 0.01)
    score_threshold_high = st.slider("High risk threshold", 0.5, 0.99, 0.8, 0.01)
    run_btn = st.button("Run Full AML Flow", type="primary")


def _read_csv(uploaded) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(uploaded.getvalue()))


if run_btn:
    if train_file is None or score_file is None:
        st.error("Please upload both training and scoring CSV files.")
        st.stop()

    try:
        train_df = _read_csv(train_file)
        score_df = _read_csv(score_file)

        validate_dataset(train_df, require_target=True)
        validate_dataset(score_df, require_target=False)

        models, metrics = train_models(train_df)
        scored = score_transactions(score_df, models)

        # Apply user-selected thresholds for presentation flexibility.
        scored["risk_band"] = "LOW"
        scored.loc[scored["ai_risk_score"] >= score_threshold_medium, "risk_band"] = "MEDIUM"
        scored.loc[scored["ai_risk_score"] >= score_threshold_high, "risk_band"] = "HIGH"
        scored["flagged_case"] = scored["risk_band"].isin(["MEDIUM", "HIGH"])
        scored["investigation_status"] = scored["flagged_case"].map({True: "OPEN", False: "DISMISSED"})

        kyc_df = build_kyc_view(scored)
        cdd_df = build_cdd_cases(scored)
        dashboard_df = build_dashboard(scored, cdd_df)

        st.success("AML flow completed.")

        col1, col2, col3 = st.columns(3)
        col1.metric("Flagged Cases", int(scored["flagged_case"].sum()))
        col2.metric("High Risk", int((scored["risk_band"] == "HIGH").sum()))
        col3.metric("STR Required", int(cdd_df["str_required"].sum()) if not cdd_df.empty else 0)

        st.subheader("Model Training Summary")
        st.json(metrics)

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
    st.info("Upload files and click 'Run Full AML Flow' to start.")
    st.markdown("**Expected columns**")
    st.code("\n".join(REQUIRED_COLUMNS + ["Is_laundering (training only)"]))
