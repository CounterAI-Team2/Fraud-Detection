from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.audit_logger import read_audit_log

st.title("5. Audit Log")

rows = read_audit_log()
if not rows:
    st.info("No audit events recorded yet.")
    st.stop()

log_df = pd.DataFrame(rows)
log_df["timestamp"] = pd.to_datetime(log_df["timestamp"], errors="coerce")

st.metric("Total Audit Rows", len(log_df))

actions = ["All"] + sorted(log_df["action"].dropna().unique().tolist())
selected_action = st.selectbox("Action Type", actions)

min_d = log_df["timestamp"].min()
max_d = log_df["timestamp"].max()
range_val = st.date_input("Date Range", value=(min_d.date(), max_d.date()))

view = log_df.copy()
if selected_action != "All":
    view = view[view["action"] == selected_action]

if isinstance(range_val, tuple) and len(range_val) == 2:
    start = pd.Timestamp(range_val[0])
    end = pd.Timestamp(range_val[1]) + pd.Timedelta(days=1)
    view = view[(view["timestamp"] >= start) & (view["timestamp"] < end)]

view = view.rename(
    columns={
        "timestamp": "Timestamp",
        "action": "Action Type",
        "transaction_id": "Transaction ID",
        "details": "Details",
        "analyst_id": "Analyst ID",
    }
)

st.dataframe(view.sort_values("Timestamp", ascending=False), use_container_width=True)

csv_data = view.to_csv(index=False).encode("utf-8")
st.download_button("Download Audit Log CSV", data=csv_data, file_name="audit_log_export.csv", mime="text/csv")
