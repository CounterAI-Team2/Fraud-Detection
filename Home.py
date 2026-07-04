from __future__ import annotations

import streamlit as st

from utils.constants import (
    ALERT_STATUS_NEW,
    CASE_OPEN_STATUSES,
    DEFAULT_ACTOR_ID,
    DEFAULT_ACTOR_ROLE,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
    display_role,
)
from utils.data_store import ensure_reference_data, get_cases, get_str_cases
from utils.kyc_store import ensure_kyc_database, get_kyc_customers
from utils.mas_sanctions_sync import sync_mas_sanctions
from utils.model_loader import CART_PATH, LOGIT_PATH, RF_PATH, ensure_model_registry_entry
from utils.sidebar import render_sidebar

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
    "current_actor_id": DEFAULT_ACTOR_ID, "current_actor_role": DEFAULT_ACTOR_ROLE,
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

render_sidebar()

_threshold = float(_scored["risk_threshold"].iloc[0]) if _scored is not None else None
_threshold_display = str(_threshold) if _threshold is not None else "—"
_actor_id = st.session_state.get("current_actor_id", DEFAULT_ACTOR_ID)
_actor_role = st.session_state.get("current_actor_role", DEFAULT_ACTOR_ROLE)
_models = " · ".join(p.stem for p in [RF_PATH, CART_PATH, LOGIT_PATH] if p.exists())

with st.container(border=True):
    _sc1, _sc2, _sc3, _sc4 = st.columns([1, 2.5, 1, 1.5])
    _sc1.markdown("🟢 System Online")
    _sc2.markdown(f"Models: **{_models}**")
    _sc3.markdown(f"Threshold:  \n**{_threshold_display}**")
    _sc4.markdown(f"Session:  \n**{_actor_id} / {display_role(_actor_role)}**")

def _card(label: str, value: int, color: str, delta: int) -> str:
    arrow = f"▲ {delta}" if delta > 0 else (f"▼ {abs(delta)}" if delta < 0 else "—")
    d_color = "#ff4b4b" if delta > 0 else ("#00cc88" if delta < 0 else "#888")
    return f"""
    <div style="border:1px solid #555;border-top:4px solid {color};
        border-radius:10px;background:rgba(255,255,255,0.05);padding:20px 16px;min-height:150px;">
        <p style="color:#aaa;font-size:11px;text-transform:uppercase;
            letter-spacing:1.5px;margin:0 0 10px 0;line-height:1.4">{label}</p>
        <p style="color:{color};font-size:52px;font-weight:bold;
            margin:0 0 8px 0;line-height:1">{value}</p>
        <p style="font-size:13px;margin:0;color:{d_color}">{arrow}</p>
    </div>"""

_prev_alerts   = st.session_state.get("_home_prev_alerts", _pending_alerts)
_prev_cases    = st.session_state.get("_home_prev_cases", _open_cases)
_prev_strs     = st.session_state.get("_home_prev_strs", _strs_review)
_prev_critical = st.session_state.get("_home_prev_critical", _critical)

_h1, _h2, _h3, _h4 = st.columns(4)
_h1.markdown(_card("Pending Alerts",     _pending_alerts, "#ff4b4b", _pending_alerts - _prev_alerts),   unsafe_allow_html=True)
_h2.markdown(_card("Open Cases",         _open_cases,     "#ffa500", _open_cases     - _prev_cases),    unsafe_allow_html=True)
_h3.markdown(_card("STRs In Review",     _strs_review,    "#4da6ff", _strs_review    - _prev_strs),     unsafe_allow_html=True)
_h4.markdown(_card("Critical Customers", _critical,       "#00cc88", _critical       - _prev_critical), unsafe_allow_html=True)

st.session_state["_home_prev_alerts"]   = _pending_alerts
st.session_state["_home_prev_cases"]    = _open_cases
st.session_state["_home_prev_strs"]     = _strs_review
st.session_state["_home_prev_critical"] = _critical

# st.info("Models are pre-trained and loaded from `models/rf_model.pkl`, `models/cart_model.pkl`, and `models/logit_model.pkl`.")

# st.subheader("Workflow")
# _wf_cols = st.columns(6)
# _wf_steps = [
#     ("1. KYC Screening", "pages/1_KYC_Screening.py"),
#     ("2. Data Upload", "pages/2_Data_Upload.py"),
#     ("3. Alert Queue", "pages/3_Alert_Queue.py"),
#     ("4. Case Investigation", "pages/4_Case_Investigation.py"),
#     ("5. STR Generation", "pages/5_STR_Generation.py"),
#     ("6. Audit Log", "pages/6_Audit_Log.py"),
# ]
# for _col, (_label, _path) in zip(_wf_cols, _wf_steps):
#     with _col:
#         st.page_link(_path, label=_label, use_container_width=True)
