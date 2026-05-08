from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.aml_services import build_governance_datasets
from utils.data_store import get_audit_events

st.title("8. AI Governance")
st.caption("Drift monitoring, analyst override tracking, and model performance timeline.")

datasets = build_governance_datasets()
hitl = datasets["hitl"]
cases = datasets["cases"]
registry = datasets["registry"]

st.subheader("Drift Monitor")
if cases.empty:
    st.info("Case activity is required before drift indicators can be calculated.")
else:
    weekly_cases = cases.groupby("week").size().rename("case_count").to_frame()
    if not hitl.empty:
        weekly_fp = (
            hitl.assign(is_fp=hitl["corrected_label"].astype(str).eq("False Positive").astype(int))
            .groupby("week")["is_fp"]
            .mean()
            .rename("fp_rate")
        )
        weekly_cases = weekly_cases.join(weekly_fp, how="left")
    else:
        weekly_cases["fp_rate"] = 0.0

    weekly_cases["rolling_recall_proxy"] = 1 - weekly_cases["fp_rate"].fillna(0.0)
    weekly_cases["recall_drop_pp"] = weekly_cases["rolling_recall_proxy"].diff() * 100
    weekly_cases["fp_rise_pp"] = weekly_cases["fp_rate"].diff() * 100
    weekly_cases["recall_alert"] = weekly_cases["recall_drop_pp"] < -3
    weekly_cases["fp_alert"] = weekly_cases["fp_rise_pp"] > 5

    st.line_chart(weekly_cases[["rolling_recall_proxy", "fp_rate"]].fillna(0.0))
    alerts = weekly_cases[(weekly_cases["recall_alert"]) | (weekly_cases["fp_alert"])]
    if alerts.empty:
        st.success("No governance thresholds are currently breached.")
    else:
        st.warning("Governance threshold breach detected.")
        st.dataframe(alerts.reset_index(), use_container_width=True)

st.subheader("Override Tracker")
if hitl.empty:
    st.info("No HITL corrections logged yet.")
else:
    reason_breakdown = hitl.groupby("reason").size().rename("count").reset_index().sort_values("count", ascending=False)
    analyst_breakdown = hitl.groupby("actor_id").size().rename("override_count").reset_index()
    hitl["timestamp_dt"] = pd.to_datetime(hitl["timestamp_utc"], errors="coerce")

    override_rate = (
        hitl.groupby(hitl["timestamp_dt"].dt.date).size().rename("overrides_per_day").to_frame()
    )
    st.metric("Override Rate", round(len(hitl) / max(len(cases), 1), 4))
    st.line_chart(override_rate)
    st.write("Overrides by analyst")
    st.dataframe(analyst_breakdown, use_container_width=True)
    st.write("Top override reasons")
    st.dataframe(reason_breakdown, use_container_width=True)

st.subheader("Model Performance Over Time")
if registry.empty:
    st.info("No model registry history found.")
else:
    for metric in ["precision", "recall", "f1", "error_rate"]:
        registry[metric] = pd.to_numeric(registry[metric], errors="coerce")
    timeline = registry.copy()
    timeline["trained_on"] = pd.to_datetime(timeline["trained_on"], errors="coerce", unit="s").fillna(
        pd.to_datetime(timeline["trained_on"], errors="coerce")
    )
    st.dataframe(timeline.sort_values("trained_on", ascending=False), use_container_width=True)
    chart_df = timeline.set_index("version")[["precision", "recall", "f1", "error_rate"]].fillna(0)
    st.line_chart(chart_df)

st.subheader("Governance Evidence Export")
audit_events = get_audit_events()
if audit_events.empty:
    st.info("No v2 audit events available for export yet.")
else:
    export_df = audit_events.copy()
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Governance Evidence CSV",
        data=csv_bytes,
        file_name="governance_evidence.csv",
        mime="text/csv",
    )
