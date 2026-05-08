from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.aml_services import build_dashboard_metrics, ensure_scored_defaults
from utils.constants import TREND_HISTORICAL_DAYS
from utils.data_store import get_archive, get_cases, get_hitl_feedback
from utils.session_utils import require_scored_df

st.title("7. Management Dashboard")
st.caption("Operational KPIs for alerts, cases, STR throughput, and customer risk posture.")

require_scored_df()
scored_df = st.session_state["scored_df"]
scored_df = ensure_scored_defaults(scored_df)
metrics = build_dashboard_metrics(scored_df)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Avg Time To Action (hrs)", metrics["avg_time_to_action_hours"])
col2.metric("Alerts Cleared Today", metrics["alerts_cleared_today"])
col3.metric("STRs Filed This Week", metrics["strs_filed_this_week"])
col4.metric("High-Risk Customers", metrics["high_risk_customer_count"])

st.subheader("Open Alerts By Tier")
open_by_tier = pd.DataFrame(
    [{"tier": key, "count": value} for key, value in metrics["open_alerts_by_tier"].items()]
)
if open_by_tier.empty:
    st.info("No alert metrics available yet.")
else:
    st.bar_chart(open_by_tier.set_index("tier"))

st.subheader("High-Risk Customers By CDD Level")
cdd_breakdown = pd.DataFrame(
    [{"cdd_level": key, "count": value} for key, value in metrics["cdd_breakdown"].items()]
)
if cdd_breakdown.empty:
    st.info("No customer CDD metrics available yet.")
else:
    st.bar_chart(cdd_breakdown.set_index("cdd_level"))

st.subheader("30-Day STR And False Positive Trend")
archive = get_archive()
hitl = get_hitl_feedback()
trend_df = pd.DataFrame()

if not archive.empty:
    archive["archived_at"] = pd.to_datetime(archive["archived_at"], errors="coerce")
    str_trend = archive.groupby(archive["archived_at"].dt.date).size().rename("str_count")
    trend_df = str_trend.to_frame()

if not hitl.empty:
    hitl["timestamp_utc"] = pd.to_datetime(hitl["timestamp_utc"], errors="coerce")
    fp = hitl.assign(
        is_fp=hitl["corrected_label"].astype(str).eq("False Positive").astype(int)
    ).groupby(hitl["timestamp_utc"].dt.date)["is_fp"].mean().rename("fp_rate")
    trend_df = trend_df.join(fp, how="outer") if not trend_df.empty else fp.to_frame()

if trend_df.empty:
    st.info("Trend data will populate after STR archives and HITL feedback are recorded.")
else:
    trend_df = trend_df.fillna(0).sort_index().tail(TREND_HISTORICAL_DAYS)
    st.line_chart(trend_df)

st.subheader("Current Model Summary")
current_model = metrics.get("current_model", {})
if not current_model:
    st.info("No model registry entry available.")
else:
    st.write(current_model)

st.subheader("Drilldown Tables")
cases = get_cases()
if not cases.empty:
    selected_cdd = st.selectbox("Filter cases by CDD level", ["All"] + sorted(cases["cdd_level"].dropna().astype(str).unique().tolist()))
    filtered_cases = cases.copy()
    if selected_cdd != "All":
        filtered_cases = filtered_cases[filtered_cases["cdd_level"].astype(str) == selected_cdd]
    st.dataframe(filtered_cases.sort_values("updated_at", ascending=False), use_container_width=True)
