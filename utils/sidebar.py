from __future__ import annotations

import streamlit as st

from utils.constants import ALERT_STATUS_NEW, CASE_OPEN_STATUSES, STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2
from utils.data_store import get_cases, get_str_cases
from utils.kyc_store import get_kyc_customers


def render_sidebar() -> None:
    for key, default in [("current_actor_id", "Analyst"), ("current_actor_role", "Admin"), ("alert_status", {})]:
        if key not in st.session_state:
            st.session_state[key] = default

    _scored = st.session_state.get("scored_df")
    _alert_map = st.session_state.get("alert_status", {})
    _pending_alerts = sum(1 for v in _alert_map.values() if v.get("status") == ALERT_STATUS_NEW)
    try:
        _cases_df = get_cases()
        _open_cases = int(_cases_df["status"].isin(CASE_OPEN_STATUSES).sum()) if not _cases_df.empty else 0
    except Exception:
        _open_cases = 0
    try:
        _strs_df = get_str_cases()
        _strs_review = int(_strs_df["status"].isin([STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2]).sum()) if not _strs_df.empty else 0
    except Exception:
        _strs_review = 0
    try:
        _kyc_df = get_kyc_customers()
        _critical = int((_kyc_df["RiskStatus"].astype(str) == "Critical").sum()) if not _kyc_df.empty else 0
    except Exception:
        _critical = 0

    with st.sidebar:
        st.session_state["current_actor_id"] = st.text_input("User ID", value=st.session_state["current_actor_id"])
        st.session_state["current_actor_role"] = st.selectbox(
            "Role",
            ["Admin", "Analyst", "Compliance Officer", "Senior Management"],
            index=["Admin", "Analyst", "Compliance Officer", "Senior Management"].index(st.session_state["current_actor_role"]),
        )
        st.divider()
        st.caption("Session Summary")
        with st.container(border=True):
            for label, value, color in [
                ("Pending Alerts",    str(_pending_alerts), "inherit"),
                ("Open Cases",        str(_open_cases),     "inherit"),
                ("STRs In Review",    str(_strs_review),    "inherit"),
                ("Critical Customers", str(_critical),      "inherit"),
            ]:
                c1, c2 = st.columns([2, 1])
                c1.markdown(label)
                c2.markdown(f"<div style='text-align:right;font-weight:bold;color:{color}'>{value}</div>", unsafe_allow_html=True)
            if _scored is not None:
                c1, c2 = st.columns([2, 1])
                c1.markdown("Dataset Loaded")
                c2.markdown(f"<div style='text-align:right;font-weight:bold;color:#00cc88'>{len(_scored):,} rows</div>", unsafe_allow_html=True)
