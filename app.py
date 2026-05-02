from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CounterAI AML Platform", layout="wide")
st.title("CounterAI AML Platform - MVP 0.1")

if "scored_df" not in st.session_state:
    st.session_state["scored_df"] = None
if "alert_status" not in st.session_state:
    st.session_state["alert_status"] = {}
if "selected_txn_id" not in st.session_state:
    st.session_state["selected_txn_id"] = None
if "str_case" not in st.session_state:
    st.session_state["str_case"] = None
if "str_log" not in st.session_state:
    st.session_state["str_log"] = []

st.markdown("Use the sidebar to navigate: **Data Upload -> Alert Queue -> Case Investigation -> STR Generation -> Audit Log**")
st.info("Models are pre-trained and loaded from `models/rf_model.pkl` and `models/cart_model.pkl`.")
