from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.audit_logger import read_audit_events, read_audit_log

st.title("5. Audit Log")

actor_role = st.session_state.get("current_actor_role", "Admin")
events = pd.DataFrame(read_audit_events())
legacy_rows = pd.DataFrame(read_audit_log())

tab1, tab2 = st.tabs(["Audit v2", "Legacy Audit"])

with tab1:
    if events.empty:
        st.info("No v2 audit events recorded yet.")
    else:
        events["timestamp_utc"] = pd.to_datetime(events["timestamp_utc"], errors="coerce", utc=True)
        st.metric("Total Audit Rows", len(events))

        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            selected_module = st.selectbox("Module", ["All"] + sorted(events["module"].dropna().unique().tolist()))
        with filter_col2:
            selected_event = st.selectbox("Event Type", ["All"] + sorted(events["event_type"].dropna().unique().tolist()))
        with filter_col3:
            selected_actor = st.selectbox("User", ["All"] + sorted(events["actor_id"].dropna().unique().tolist()))
        with filter_col4:
            min_d = events["timestamp_utc"].min()
            max_d = events["timestamp_utc"].max()
            range_val = st.date_input("Date Range", value=(min_d.date(), max_d.date()))

        view = events.copy()
        if actor_role != "Admin":
            current_actor = st.session_state.get("current_actor_id", "Analyst")
            view = view[view["actor_id"].astype(str) == current_actor]
            st.caption("Non-admin roles only see their own audit events.")

        if selected_module != "All":
            view = view[view["module"] == selected_module]
        if selected_event != "All":
            view = view[view["event_type"] == selected_event]
        if selected_actor != "All" and actor_role == "Admin":
            view = view[view["actor_id"] == selected_actor]

        if isinstance(range_val, tuple) and len(range_val) == 2:
            start = pd.Timestamp(range_val[0], tz="UTC")
            end = pd.Timestamp(range_val[1], tz="UTC") + pd.Timedelta(days=1)
            view = view[(view["timestamp_utc"] >= start) & (view["timestamp_utc"] < end)]

        display = view.rename(
            columns={
                "timestamp_utc": "Timestamp",
                "module": "Module",
                "event_type": "Event Type",
                "entity_type": "Entity Type",
                "entity_id": "Entity ID",
                "transaction_id": "Transaction ID",
                "actor_id": "User ID",
                "actor_role": "Role",
                "payload_json": "Payload",
            }
        )
        st.dataframe(display.sort_values("Timestamp", ascending=False), use_container_width=True)
        csv_data = display.to_csv(index=False).encode("utf-8")
        st.download_button("Download Audit v2 CSV", data=csv_data, file_name="audit_log_v2_export.csv", mime="text/csv")

with tab2:
    if legacy_rows.empty:
        st.info("No legacy audit events recorded yet.")
    else:
        legacy_rows["timestamp"] = pd.to_datetime(legacy_rows["timestamp"], errors="coerce")
        st.dataframe(legacy_rows.sort_values("timestamp", ascending=False), use_container_width=True)
