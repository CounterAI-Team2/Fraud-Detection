from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.sidebar import render_sidebar
from utils.audit_helpers import log_alert_dismissed, log_alert_escalated, log_prediction_feedback
from utils.aml_services import ensure_case_for_transaction, ensure_scored_defaults, record_hitl_feedback
from utils.constants import (
    ALERT_QUEUE_DISPLAY_LIMIT,
    ALERT_STATUS_DISMISSED,
    ALERT_STATUS_ESCALATED,
    ALERT_STATUS_NEW,
)
from utils.session_utils import get_current_analyst, require_scored_df

render_sidebar()

st.title("Alert Queue")
st.caption("Review scored transactions, dismiss false positives, or escalate to case investigation.")

require_scored_df()
scored_df = st.session_state["scored_df"]
analyst_id, actor_role = get_current_analyst()

scored_df = ensure_scored_defaults(scored_df)
st.session_state["scored_df"] = scored_df
status_map = st.session_state.get("alert_status", {})

view = scored_df.copy()
view["transaction_id"] = view["transaction_id"].astype(str)
view["_status"] = view["transaction_id"].map(lambda x: status_map.get(x, {}).get("status", ALERT_STATUS_NEW))

_threshold = float(scored_df["risk_threshold"].iloc[0]) if "risk_threshold" in scored_df.columns else 0.5
_total_alerts = int((view["_status"] != ALERT_STATUS_DISMISSED).sum())

# ── Status info bar ───────────────────────────────────────────────────────────
with st.container(border=True):
    _ib1, _ib2, _ib3, _ib4 = st.columns(4)
    _ib1.markdown(f"Scored dataset: **{len(scored_df):,} rows**")
    _ib2.markdown(f"Threshold: **{_threshold}**")
    _ib3.markdown(f"Showing: **{_total_alerts} alerts**")
    _ib4.markdown(f"Analyst: **{analyst_id}**")

# ── Filters ───────────────────────────────────────────────────────────────────
with st.container(border=True):
    _fc1, _fc2, _fc3, _fc4 = st.columns(4)
    _tiers = _fc1.multiselect(
        "Risk Tier", ["Critical", "High", "Medium", "Low"],
        default=["Critical", "High", "Medium"],
    )
    _payment_types = sorted(view["Payment_type"].astype(str).unique().tolist())
    _sel_pt = _fc2.multiselect("Payment Type", _payment_types, default=_payment_types)
    _dmin = pd.to_datetime(view["Date"], errors="coerce").min()
    _dmax = pd.to_datetime(view["Date"], errors="coerce").max()
    _dr = _fc3.date_input(
        "Date Range",
        value=(_dmin.date() if pd.notna(_dmin) else None, _dmax.date() if pd.notna(_dmax) else None),
    )
    _sel_statuses = _fc4.multiselect(
        "Status",
        [ALERT_STATUS_NEW, ALERT_STATUS_ESCALATED, ALERT_STATUS_DISMISSED],
        default=[ALERT_STATUS_NEW, ALERT_STATUS_ESCALATED],
    )

# Apply filters
if isinstance(_dr, tuple) and len(_dr) == 2 and _dr[0] and _dr[1]:
    _dser = pd.to_datetime(view["Date"], errors="coerce")
    view = view[(_dser >= pd.Timestamp(_dr[0])) & (_dser <= pd.Timestamp(_dr[1]))]

view = view[view["risk_tier"].isin(_tiers)]
view = view[view["Payment_type"].astype(str).isin(_sel_pt)]
if _sel_statuses:
    view = view[view["_status"].isin(_sel_statuses)]

# Sort: dismissed to bottom, then by tier + score
_priority = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
_status_rank = {ALERT_STATUS_DISMISSED: 1, ALERT_STATUS_NEW: 0, ALERT_STATUS_ESCALATED: 0}
view["_prio"]        = view["risk_tier"].map(_priority).fillna(99)
view["_status_rank"] = view["_status"].map(_status_rank).fillna(0)
view = view.sort_values(["_status_rank", "_prio", "risk_score"], ascending=[True, True, False])

if view.empty:
    st.info("No alerts match current filters.")
    st.stop()


def _reason_text(row: pd.Series) -> str:
    """Build a short plain-English reason from engineered features."""
    parts = []
    if row.get("off_hours", 0):
        parts.append("Off-hours transfer")
    if row.get("cross_border", 0):
        parts.append("Cross-border transaction")
    if row.get("cross_currency", 0):
        parts.append("Cross-currency exchange")
    if row.get("is_high_value", 0):
        parts.append(f"High-value amount (${float(row['Amount']):,.0f})")
    if not parts:
        parts.append("Flagged by risk model")
    return ". ".join(parts) + "."


_TIER_BORDER = {
    "Critical": "#f44336",
    "High":     "#fb8c00",
    "Medium":   "#fdd835",
    "Low":      "#64dd17",
}

_dismiss_reasons = ["False positive", "Investigated — no concern", "Duplicate"]
_feedback_options = ["False Positive", "False Negative", "Needs retraining", "Other"]

# ── Alert cards ───────────────────────────────────────────────────────────────
for _, row in view.head(ALERT_QUEUE_DISPLAY_LIMIT).iterrows():
    txid     = str(row["transaction_id"])
    tier     = str(row["risk_tier"])
    score    = float(row["risk_score"])
    status   = status_map.get(txid, {}).get("status", ALERT_STATUS_NEW)
    color    = _TIER_BORDER.get(tier, "#888")
    reason   = _reason_text(row)
    dim      = status == ALERT_STATUS_DISMISSED
    _dismiss_key = f"_dismiss_open_{txid}"

    with st.container(border=True):
        _c1, _c2, _c3, _c4, _c5 = st.columns([1.2, 2.5, 2.5, 1.2, 2])

        # Risk tier badge
        _c1.markdown(
            f"<div style='border:2px solid {color};border-radius:6px;padding:5px 10px;"
            f"text-align:center;font-weight:700;color:{color};"
            f"opacity:{'0.4' if dim else '1'}'>{tier}</div>",
            unsafe_allow_html=True,
        )

        # Transaction info
        _txt_color = "#555" if dim else "#ccc"
        _id_color  = "#555" if dim else "#fff"
        _c2.markdown(
            f"<div style='opacity:{'0.5' if dim else '1'}'>"
            f"<strong style='color:{_id_color};font-size:15px'>ID: {txid}</strong><br>"
            f"<span style='color:{_txt_color};font-size:12px'>"
            f"{row.get('Sender_account','—')} · {row.get('Payment_type','—')} · "
            f"${float(row['Amount']):,.0f}</span><br>"
            f"<span style='color:#555;font-size:12px'>{row.get('Date','—')} {row.get('Time','')}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Reason
        _c3.markdown(
            f"<div style='color:{'#444' if dim else '#888'};font-size:13px;padding-top:4px'>"
            f"{reason}</div>",
            unsafe_allow_html=True,
        )

        # Risk score
        _c4.markdown(
            f"<div style='text-align:center;opacity:{'0.4' if dim else '1'}'>"
            f"<span style='font-size:30px;font-weight:700;color:{color}'>{score:.2f}</span><br>"
            f"<span style='font-size:11px;color:#555'>Risk Score</span></div>",
            unsafe_allow_html=True,
        )

        # Actions
        if dim:
            _c5.markdown(
                "<div style='text-align:center;padding-top:8px;"
                "color:#555;font-size:13px'>Dismissed</div>",
                unsafe_allow_html=True,
            )
        elif status == ALERT_STATUS_ESCALATED:
            _c5.markdown(
                "<div style='text-align:center;padding-top:8px;"
                "color:#4da6ff;font-size:13px;font-weight:600'>Escalated</div>",
                unsafe_allow_html=True,
            )
        else:
            _ac1, _ac2 = _c5.columns(2)
            if _ac1.button("Escalate", key=f"esc_{txid}", type="primary", use_container_width=True):
                status_map[txid] = {"status": ALERT_STATUS_ESCALATED, "reason": status_map.get(txid, {}).get("reason", "")}
                st.session_state["alert_status"] = status_map
                st.session_state["selected_txn_id"] = txid
                _case = ensure_case_for_transaction(row, analyst_id)
                st.session_state["selected_case_id"] = _case["case_id"]
                log_alert_escalated(txid, _case["case_id"], analyst_id, actor_role, tier, score)
                st.switch_page("pages/4_Case_Investigation.py")
            if _ac2.button("Dismiss", key=f"dis_{txid}", use_container_width=True):
                st.session_state[_dismiss_key] = not st.session_state.get(_dismiss_key, False)
                st.rerun()

        # Inline dismiss panel
        if st.session_state.get(_dismiss_key):
            _dr1, _dr2 = st.columns([3, 1])
            _dismiss_reason = _dr1.selectbox(
                "Reason", _dismiss_reasons, key=f"reason_{txid}", label_visibility="collapsed"
            )
            if _dr2.button("Confirm", key=f"confirm_dis_{txid}", type="primary", use_container_width=True):
                status_map[txid] = {"status": ALERT_STATUS_DISMISSED, "reason": _dismiss_reason}
                st.session_state["alert_status"] = status_map
                st.session_state[_dismiss_key] = False
                log_alert_dismissed(txid, analyst_id, actor_role, _dismiss_reason, score)
                st.rerun()

        # Explainability & feedback expander
        with st.expander("Explainability & Prediction Feedback"):
            _xe1, _xe2, _xe3, _xe4, _xe5 = st.columns(5)
            _xmetrics = [
                (_xe1, "Risk Score",     f"{round(score, 4)}",                          color),
                (_xe2, "Risk Tier",      tier,                                           color),
                (_xe3, "Cross Border",   "Yes" if row.get("cross_border", 0) else "No",  "#f44336" if row.get("cross_border", 0) else "#4caf50"),
                (_xe4, "Cross Currency", "Yes" if row.get("cross_currency", 0) else "No","#f44336" if row.get("cross_currency", 0) else "#4caf50"),
                (_xe5, "High Value",     "Yes" if row.get("is_high_value", False) else "No", "#fb8c00" if row.get("is_high_value", False) else "#4caf50"),
            ]
            for _xcol, _xlabel, _xval, _xcolor in _xmetrics:
                with _xcol:
                    with st.container(border=True):
                        st.markdown(
                            f"<div style='text-align:center;padding:10px 0'>"
                            f"<div style='font-size:11px;color:#666;text-transform:uppercase;"
                            f"letter-spacing:1px;margin-bottom:8px'>{_xlabel}</div>"
                            f"<div style='font-size:20px;font-weight:700;color:{_xcolor};margin-bottom:6px'>{_xval}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
            st.divider()
            _fb_label  = st.selectbox("Prediction correction", _feedback_options, key=f"feedback_{txid}")
            _fb_reason = st.text_input("Correction reason", key=f"feedback_reason_{txid}")
            if st.button("Log HITL Feedback", key=f"feedback_btn_{txid}"):
                record_hitl_feedback(
                    transaction_id=txid,
                    customer_id=str(row.get("customer_id", "")),
                    original_prediction="Flagged" if int(row["rf_prediction"]) == 1 else "Not flagged",
                    corrected_label=_fb_label,
                    reason=_fb_reason or "No reason provided",
                    actor_id=analyst_id,
                )
                log_prediction_feedback(txid, analyst_id, actor_role, _fb_label, _fb_reason, int(row["rf_prediction"]))
                st.success("HITL feedback captured.")