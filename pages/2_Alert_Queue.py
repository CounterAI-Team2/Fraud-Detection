from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.audit_logger import log_action

st.title("2. Alert Queue")

scored_df = st.session_state.get("scored_df")
if scored_df is None:
    st.error("No scored dataset found. Please upload data in Page 1 first.")
    st.stop()

status_map = st.session_state.get("alert_status", {})

# Apply status from session state to dataframe view
view = scored_df.copy()
view["transaction_id"] = view["transaction_id"].astype(str)
view["Status"] = view["transaction_id"].map(lambda x: status_map.get(x, {}).get("status", "New"))
view["Dismiss_Reason"] = view["transaction_id"].map(lambda x: status_map.get(x, {}).get("reason", ""))

st.subheader("Filters")
colf1, colf2, colf3, colf4 = st.columns(4)
with colf1:
    tiers = st.multiselect("Risk Tier", ["Critical", "High", "Medium", "Low"], default=["Critical", "High", "Medium"])
with colf2:
    payment_types = sorted(view["Payment_type"].astype(str).unique().tolist())
    selected_pt = st.multiselect("Payment Type", payment_types, default=payment_types)
with colf3:
    dmin = pd.to_datetime(view["Date"], errors="coerce").min()
    dmax = pd.to_datetime(view["Date"], errors="coerce").max()
    dr = st.date_input("Date Range", value=(dmin.date() if pd.notna(dmin) else None, dmax.date() if pd.notna(dmax) else None))
with colf4:
    analyst_id = st.text_input("Analyst ID", value="Analyst")

if isinstance(dr, tuple) and len(dr) == 2 and dr[0] and dr[1]:
    start, end = pd.Timestamp(dr[0]), pd.Timestamp(dr[1])
    dser = pd.to_datetime(view["Date"], errors="coerce")
    view = view[(dser >= start) & (dser <= end)]

view = view[view["risk_tier"].isin(tiers)]
view = view[view["Payment_type"].astype(str).isin(selected_pt)]

# Priority sorting + dismissed to bottom
priority = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
status_rank = {"Dismissed": 1, "New": 0, "Escalated": 0}
view["_prio"] = view["risk_tier"].map(priority).fillna(99)
view["_status_rank"] = view["Status"].map(status_rank).fillna(0)
view = view.sort_values(["_status_rank", "_prio", "risk_score"], ascending=[True, True, False])

st.write(f"Alerts in current view: {len(view):,}")

if view.empty:
    st.info("No alerts match current filters.")
    st.stop()

reasons = [
    "Rule-based false positive",
    "Known legitimate counterparty",
    "Amount within normal range",
    "Other",
]

for _, row in view.head(200).iterrows():
    txid = str(row["transaction_id"])
    color = {"Critical": "#f44336", "High": "#fb8c00", "Medium": "#fdd835", "Low": "#cfd8dc"}.get(row["risk_tier"], "#e0e0e0")
    status = status_map.get(txid, {}).get("status", "New")

    with st.container(border=True):
        st.markdown(f"<div style='padding:6px;background:{color};border-radius:6px;color:black'><b>{row['risk_tier']}</b> | Txn {txid} | Status: {status}</div>", unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 3])
        c1.write(f"Sender: `{row['Sender_account']}`")
        c2.write(f"Receiver: `{row['Receiver_account']}`")
        c3.write(f"Amount: `{row['Amount']:,.2f}`")
        c4.write(f"Type: `{row['Payment_type']}`")
        c5.write(f"Risk Score: `{row['risk_score']:.4f}`")

        if status == "Dismissed":
            st.caption(f"Dismiss reason: {status_map.get(txid, {}).get('reason', '')}")

        a1, a2, a3 = st.columns([1, 1, 2])
        if a1.button("Investigate", key=f"inv_{txid}"):
            status_map[txid] = {"status": "Escalated", "reason": status_map.get(txid, {}).get("reason", "")}
            st.session_state["alert_status"] = status_map
            st.session_state["selected_txn_id"] = txid
            st.switch_page("pages/3_Case_Investigation.py")

        dismiss_reason = a3.selectbox("Dismiss reason", reasons, key=f"reason_{txid}")
        if a2.button("Dismiss", key=f"dis_{txid}"):
            status_map[txid] = {"status": "Dismissed", "reason": dismiss_reason}
            st.session_state["alert_status"] = status_map
            log_action(
                action="alert_dismissed",
                transaction_id=txid,
                details=f"risk_score={row['risk_score']:.4f}; reason={dismiss_reason}",
                analyst_id=analyst_id,
            )
            st.rerun()
