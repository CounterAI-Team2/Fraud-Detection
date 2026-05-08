from __future__ import annotations

import streamlit as st

from utils.data_store import ensure_reference_data
from utils.model_loader import ensure_model_registry_entry

st.set_page_config(page_title="CounterAI AML Platform", layout="wide")
ensure_reference_data()
ensure_model_registry_entry()

st.title("CounterAI AML Platform - Roadmap Build")

_DEFAULTS = {
    "scored_df": None, "alert_status": {}, "selected_txn_id": None,
    "str_case": None,  "str_log": [],     "selected_case_id": None,
    "current_actor_id": "Analyst", "current_actor_role": "Admin",
    "current_str_id": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

with st.sidebar:
    st.subheader("Session Controls")
    st.session_state["current_actor_id"] = st.text_input("User ID", value=st.session_state["current_actor_id"])
    st.session_state["current_actor_role"] = st.selectbox(
        "Role",
        ["Admin", "Analyst", "Compliance Officer", "Senior Management"],
        index=["Admin", "Analyst", "Compliance Officer", "Senior Management"].index(st.session_state["current_actor_role"]),
    )
    st.caption("Use the sidebar page navigation to access Upload, Queue, KYC, CDD, STR, Audit, Dashboard, and Governance modules.")

st.markdown(
    "Use the sidebar to navigate: **Data Upload -> Alert Queue -> Case Investigation -> KYC & Screening -> STR Generation -> Audit Log -> Management Dashboard -> AI Governance**"
)
st.info("Models are pre-trained and loaded from `models/rf_model.pkl`, `models/cart_model.pkl`, and `models/logit_model.pkl`.")
