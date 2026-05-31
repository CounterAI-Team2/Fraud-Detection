from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.sidebar import render_sidebar
from utils.aml_services import build_dashboard_metrics, ensure_scored_defaults
from utils.audit_logger import log_action
from utils.constants import (
    RISK_TIER_COLORS,
    SM_APPROVAL_PENDING,
    STR_STATUS_APPROVED,
    STR_STATUS_ARCHIVED,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
    TREND_HISTORICAL_DAYS,
)
from utils.data_store import get_archive, get_cases, get_hitl_feedback, get_str_cases
from utils.kyc_store import (
    RISK_HIGH,
    approve_critical_customer,
    get_kyc_customers,
    reject_critical_flag,
)
from utils.session_utils import get_current_analyst

render_sidebar()

st.title("Management Dashboard")
st.caption("Operational KPIs for alerts, cases, STR throughput, and customer risk posture.")

actor_id, actor_role = get_current_analyst()
kyc_customers = get_kyc_customers()
pending_critical = kyc_customers[
    (kyc_customers["RiskStatus"].astype(str) == "Critical")
    & (kyc_customers["SMApprovalStatus"].astype(str) == SM_APPROVAL_PENDING)
]

_tab_overview, _tab_trends, _tab_cases = st.tabs(["Overview", "Trends", "Cases"])

# ── Tab 1: Overview ───────────────────────────────────────────────────────────
with _tab_overview:
    scored = st.session_state.get("scored_df")
    metrics: dict = {}
    if scored is not None:
        scored = ensure_scored_defaults(scored)
        metrics = build_dashboard_metrics(scored)

    # --- Compute KPI values ---
    detection_rate = (
        round(float(scored["rf_prediction"].eq(1).mean()) * 100, 1)
        if scored is not None and "rf_prediction" in scored.columns
        else 0.0
    )
    avg_resolution_days = round(metrics.get("avg_time_to_action_hours", 0.0) / 24, 1)
    fp_rate = round(metrics.get("fp_rate", 0.0) * 100, 1)

    str_df = get_str_cases()
    if not str_df.empty:
        _total = len(str_df)
        _approved = int(str_df["status"].isin([STR_STATUS_APPROVED, STR_STATUS_ARCHIVED]).sum())
        str_approval_rate = round(_approved / _total * 100, 1) if _total > 0 else 0.0
        str_status_counts = str_df["status"].value_counts().to_dict()
    else:
        str_approval_rate = 0.0
        str_status_counts = {}

    # --- Delta tracking ---
    _prev_det = st.session_state.get("_dash_prev_det", detection_rate)
    _prev_res = st.session_state.get("_dash_prev_res", avg_resolution_days)
    _prev_str = st.session_state.get("_dash_prev_str", str_approval_rate)
    _prev_fp  = st.session_state.get("_dash_prev_fp",  fp_rate)

    # --- KPI card helper ---
    def _kpi_card(label: str, value_str: str, color: str, delta: float, suffix: str = "") -> str:
        if delta > 0:
            arrow = f"▲ {abs(round(delta, 1))}{suffix}"
            d_color = "#ff4b4b"
        elif delta < 0:
            arrow = f"▼ {abs(round(delta, 1))}{suffix}"
            d_color = "#00cc88"
        else:
            arrow, d_color = "—", "#888"
        return f"""
        <div style="border:1px solid #444;border-top:4px solid {color};border-radius:10px;
            background:rgba(255,255,255,0.05);padding:20px 16px;min-height:160px;">
            <p style="color:#aaa;font-size:11px;text-transform:uppercase;
                letter-spacing:1.5px;margin:0 0 10px 0;line-height:1.4">{label}</p>
            <p style="color:{color};font-size:52px;font-weight:bold;
                margin:0 0 8px 0;line-height:1">{value_str}</p>
            <p style="font-size:13px;margin:0;color:{d_color}">{arrow}</p>
        </div>"""

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi_card("Alert Detection Rate", f"{detection_rate}%",      "#f44336", detection_rate    - _prev_det, "%"), unsafe_allow_html=True)
    k2.markdown(_kpi_card("Avg Case Resolution",  f"{avg_resolution_days}d", "#fb8c00", avg_resolution_days - _prev_res, "d"), unsafe_allow_html=True)
    k3.markdown(_kpi_card("STR Approval Rate",    f"{str_approval_rate}%",   "#4caf50", str_approval_rate  - _prev_str, "%"), unsafe_allow_html=True)
    k4.markdown(_kpi_card("False Positive Rate",  f"{fp_rate}%",             "#4da6ff", fp_rate            - _prev_fp,  "%"), unsafe_allow_html=True)

    st.session_state["_dash_prev_det"] = detection_rate
    st.session_state["_dash_prev_res"] = avg_resolution_days
    st.session_state["_dash_prev_str"] = str_approval_rate
    st.session_state["_dash_prev_fp"]  = fp_rate

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Horizontal bar chart helper ---
    def _hbar_chart(items: list[tuple[str, int, str]]) -> str:
        max_val = max((v for _, v, _ in items), default=1) or 1
        rows = ""
        for label, count, color in items:
            pct = int(count / max_val * 100)
            rows += f"""
            <div style="display:flex;align-items:center;margin-bottom:12px;gap:10px">
                <span style="color:#aaa;font-size:13px;width:85px;text-align:right;flex-shrink:0">{label}</span>
                <div style="flex:1;background:#2a2a2a;border-radius:4px;height:14px">
                    <div style="width:{pct}%;background:{color};height:100%;border-radius:4px"></div>
                </div>
                <span style="color:{color};font-weight:bold;font-size:14px;width:28px;flex-shrink:0">{count}</span>
            </div>"""
        return rows

    chart_l, chart_r = st.columns(2)

    with chart_l:
        with st.container(border=True):
            st.markdown("**Alerts by Risk Tier (last 30 days)**")
            tier_data = (
                scored["risk_tier"].value_counts().to_dict()
                if scored is not None and "risk_tier" in scored.columns
                else metrics.get("open_alerts_by_tier", {})
            )
            tier_items = [
                (tier, tier_data.get(tier, 0), RISK_TIER_COLORS.get(tier, "#888"))
                for tier in ["Critical", "High", "Medium", "Low"]
            ]
            st.markdown(_hbar_chart(tier_items), unsafe_allow_html=True)

    with chart_r:
        with st.container(border=True):
            st.markdown("**STR Status Breakdown**")
            str_items = [
                ("Draft",     str_status_counts.get(STR_STATUS_DRAFT,    0), "#888888"),
                ("L1 Review", str_status_counts.get(STR_STATUS_L1,       0), "#4da6ff"),
                ("L2 Review", str_status_counts.get(STR_STATUS_L2,       0), "#ab47bc"),
                ("Approved",  str_status_counts.get(STR_STATUS_APPROVED, 0), "#4caf50"),
                ("Archived",  str_status_counts.get(STR_STATUS_ARCHIVED, 0), "#546e7a"),
            ]
            st.markdown(_hbar_chart(str_items), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Critical Customer Approval Queue ---
    with st.container(border=True):
        st.markdown("**Critical Customer Approval Queue**")
        st.divider()
        if pending_critical.empty:
            st.success("No Critical customers pending Senior Management approval.")
        else:
            can_approve = actor_role in {"Senior Management", "Admin"}
            h1, h2, h3, h4, h5 = st.columns([2, 2, 1.5, 2, 2])
            for col, lbl in zip([h1, h2, h3, h4, h5], ["CUSTOMER", "ACCOUNT", "CDD LEVEL", "FLAGGED REASON", "ACTIONS"]):
                col.markdown(f"<span style='color:#aaa;font-size:11px;font-weight:bold;letter-spacing:1px'>{lbl}</span>", unsafe_allow_html=True)
            st.divider()
            for _, crit_row in pending_critical.iterrows():
                cid = str(crit_row["id"])
                r1, r2, r3, r4, r5 = st.columns([2, 2, 1.5, 2, 2])
                r1.markdown(str(crit_row["FullName"]))
                r2.markdown(f"`{crit_row['AccountNo']}`")
                r3.markdown(str(crit_row.get("CDDLevel", "—")))
                r4.markdown(str(crit_row.get("FlaggedReason", "—") or "—"))
                if can_approve:
                    if r5.button("Approve", key=f"approve_{cid}", type="primary", use_container_width=True):
                        approve_critical_customer(cid, actor_id)
                        log_action(
                            action="critical_customer_approved",
                            details=f"customer_id={cid}; approved_by={actor_id}",
                            analyst_id=actor_id, module="management_dashboard",
                            event_type="critical_customer_approved", entity_type="customer",
                            entity_id=cid, actor_role=actor_role,
                            payload={"customer_id": cid, "approved_by": actor_id},
                        )
                        st.rerun()
                    if r5.button("Reject", key=f"reject_{cid}", use_container_width=True):
                        reject_critical_flag(cid, actor_id)
                        log_action(
                            action="critical_customer_rejected",
                            details=f"customer_id={cid}; rejected_by={actor_id}; demoted to High",
                            analyst_id=actor_id, module="management_dashboard",
                            event_type="critical_customer_rejected", entity_type="customer",
                            entity_id=cid, actor_role=actor_role,
                            payload={"customer_id": cid, "rejected_by": actor_id, "new_risk": RISK_HIGH},
                        )
                        st.rerun()
                else:
                    r5.caption("Requires SM / Admin role.")

# ── Tab 2: Trends ─────────────────────────────────────────────────────────────
with _tab_trends:
    _scored_t = st.session_state.get("scored_df")
    if _scored_t is not None:
        _scored_t = ensure_scored_defaults(_scored_t)
        _metrics_t = build_dashboard_metrics(_scored_t)

        st.subheader("Open Alerts By Tier")
        open_by_tier = pd.DataFrame(
            [{"tier": key, "count": value} for key, value in _metrics_t["open_alerts_by_tier"].items()]
        )
        if open_by_tier.empty:
            st.info("No alert metrics available yet.")
        else:
            st.bar_chart(open_by_tier.set_index("tier"))

        st.subheader("High-Risk Customers By CDD Level")
        cdd_breakdown = pd.DataFrame(
            [{"cdd_level": key, "count": value} for key, value in _metrics_t["cdd_breakdown"].items()]
        )
        if cdd_breakdown.empty:
            st.info("No customer CDD metrics available yet.")
        else:
            st.bar_chart(cdd_breakdown.set_index("cdd_level"))
    else:
        st.info("Upload a dataset on the Data Upload page to see alert and CDD charts.")

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
    if _scored_t is not None:
        current_model = _metrics_t.get("current_model", {})
        if not current_model:
            st.info("No model registry entry available.")
        else:
            st.write(current_model)
    else:
        st.info("Upload a dataset to see the current model summary.")

# ── Tab 3: Cases ──────────────────────────────────────────────────────────────
with _tab_cases:
    st.subheader("Drilldown Tables")
    cases = get_cases()
    if not cases.empty:
        selected_cdd = st.selectbox("Filter cases by CDD level", ["All"] + sorted(cases["cdd_level"].dropna().astype(str).unique().tolist()))
        filtered_cases = cases.copy()
        if selected_cdd != "All":
            filtered_cases = filtered_cases[filtered_cases["cdd_level"].astype(str) == selected_cdd]
        st.dataframe(filtered_cases.sort_values("updated_at", ascending=False), use_container_width=True)
    else:
        st.info("No cases available yet.")