from __future__ import annotations

import streamlit as st

from utils.constants import ALERT_STATUS_NEW, CASE_OPEN_STATUSES, STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2
from utils.data_store import ensure_reference_data, get_cases, get_str_cases
from utils.kyc_store import ensure_kyc_database, get_kyc_customers
from utils.mas_sanctions_sync import sync_mas_sanctions
from utils.model_loader import ensure_model_registry_entry

st.set_page_config(page_title="CounterAI AML Platform", layout="wide")
ensure_reference_data()
ensure_kyc_database()
ensure_model_registry_entry()

# Sync MAS sanctions lists once per session at launch. Failures degrade to
# the cached/bundled name list and are surfaced on the KYC page.
if not st.session_state.get("mas_sync_done"):
    st.session_state["mas_sync_result"] = sync_mas_sanctions().to_dict()
    st.session_state["mas_sync_done"] = True

st.title("CounterAI AML Platform")
st.caption("Anti-money-laundering detection and reporting — pre-trained RF model, inference-only at runtime.")

_DEFAULTS = {
    "scored_df": None, "alert_status": {}, "selected_txn_id": None,
    "str_case": None,  "str_log": [],     "selected_case_id": None,
    "current_actor_id": "Analyst", "current_actor_role": "Admin",
    "current_str_id": None, "selected_str_record": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# --- Live session stats (computed once, used in sidebar + homepage) ---
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
    st.subheader("Session Controls")
    st.session_state["current_actor_id"] = st.text_input("User ID", value=st.session_state["current_actor_id"])
    st.session_state["current_actor_role"] = st.selectbox(
        "Role",
        ["Admin", "Analyst", "Compliance Officer", "Senior Management"],
        index=["Admin", "Analyst", "Compliance Officer", "Senior Management"].index(st.session_state["current_actor_role"]),
    )
    st.divider()
    st.caption("Session Summary")
    _s1, _s2 = st.columns(2)
    _s1.metric("Alerts", _pending_alerts)
    _s2.metric("Cases", _open_cases)
    _s1.metric("STRs", _strs_review)
    _s2.metric("Critical", _critical)
    if _scored is not None:
        st.caption(f"Dataset: {len(_scored):,} rows")

_h1, _h2, _h3, _h4 = st.columns(4)
_h1.metric("Pending Alerts", _pending_alerts)
_h2.metric("Open Cases", _open_cases)
_h3.metric("STRs In Review", _strs_review)
_h4.metric("Critical Customers", _critical)

st.info("Models are pre-trained and loaded from `models/rf_model.pkl`, `models/cart_model.pkl`, and `models/logit_model.pkl`.")

st.subheader("Workflow")
_wf_cols = st.columns(6)
_wf_steps = [
    ("1. KYC Screening", "pages/1_KYC_Screening.py"),
    ("2. Data Upload", "pages/2_Data_Upload.py"),
    ("3. Alert Queue", "pages/3_Alert_Queue.py"),
    ("4. Case Investigation", "pages/4_Case_Investigation.py"),
    ("5. STR Generation", "pages/5_STR_Generation.py"),
    ("6. Audit Log", "pages/6_Audit_Log.py"),
]
for _col, (_label, _path) in zip(_wf_cols, _wf_steps):
    with _col:
        st.page_link(_path, label=_label, use_container_width=True)
