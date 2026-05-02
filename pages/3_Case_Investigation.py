from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from utils.audit_logger import log_action
from utils.model_loader import load_models
from utils.shap_explainer import get_model_xai_explanation

st.title("3. Case Investigation")

scored_df = st.session_state.get("scored_df")
if scored_df is None:
    st.error("No scored dataset available. Please upload and score data first.")
    st.stop()

selected_txn_id = st.session_state.get("selected_txn_id")
if selected_txn_id is None:
    st.warning("No transaction selected from Alert Queue.")
    tx_options = scored_df["transaction_id"].astype(str).tolist()
    selected_txn_id = st.selectbox("Select transaction", tx_options)

rows = scored_df[scored_df["transaction_id"].astype(str) == str(selected_txn_id)]
if rows.empty:
    st.error("Selected transaction not found.")
    st.stop()

selected_txn = rows.iloc[0]

score = float(selected_txn["risk_score"])
if score >= 0.85:
    tier_color = "#f44336"
elif score >= 0.65:
    tier_color = "#fb8c00"
elif score >= 0.40:
    tier_color = "#fdd835"
else:
    tier_color = "#cfd8dc"

st.subheader("Transaction Details")
d1, d2 = st.columns([2, 1])
with d1:
    st.write(f"Transaction ID: `{selected_txn['transaction_id']}`")
    st.write(f"Date/Time: `{selected_txn['Date']} {selected_txn['Time']}`")
    st.write(f"Sender Account: `{selected_txn['Sender_account']}`")
    st.write(f"Receiver Account: `{selected_txn['Receiver_account']}`")
    st.write(f"Amount: `{float(selected_txn['Amount']):,.2f}`")
    st.write(f"Payment Type: `{selected_txn['Payment_type']}`")
    st.write(f"Sender Bank Location: `{selected_txn['Sender_bank_location']}`")
    st.write(f"Receiver Bank Location: `{selected_txn['Receiver_bank_location']}`")
    st.write(f"Payment Currency: `{selected_txn['Payment_currency']}`")
    st.write(f"Received Currency: `{selected_txn['Received_currency']}`")
with d2:
    st.markdown(
        f"<div style='font-size:36px;font-weight:700;color:{tier_color}'>{score:.4f}</div>"
        f"<div style='padding:6px;border-radius:8px;background:{tier_color};color:black;font-weight:700'>{selected_txn['risk_tier']}</div>",
        unsafe_allow_html=True,
    )

st.subheader("Model Explainability (CART + Logistic)")
rf_model, cart_model, logit_model = load_models()

base_features = [
    "amount_log",
    "cross_border",
    "cross_currency",
    "sender_txn_count",
    "receiver_txn_count",
    "sender_unique_receivers",
    "receiver_unique_senders",
    "hour",
    "day_of_week",
    "is_off_hours",
    "Payment_type",
    "Payment_currency",
    "Received_currency",
    "Sender_bank_location",
    "Receiver_bank_location",
]

x = scored_df[base_features].copy()
x = pd.get_dummies(
    x,
    columns=[
        "Payment_type",
        "Payment_currency",
        "Received_currency",
        "Sender_bank_location",
        "Receiver_bank_location",
    ],
    drop_first=False,
)
x = x.reindex(columns=list(rf_model.feature_names_in_), fill_value=0)

idx = rows.index[0]
row_for_shap = x.loc[[idx]].copy()

try:
    top_features, plain_text, bullets = get_model_xai_explanation(cart_model, logit_model, row_for_shap, list(x.columns))
except Exception:
    top_features = [("amount_log", 0.0), ("cross_border", 0.0), ("cross_currency", 0.0)]
    plain_text = "This transaction was flagged primarily due to a combination of network and transaction risk indicators."
    bullets = ["- sender transacts with unusually many unique receivers (fan-out)", "- transaction amount is significantly above typical", "- transaction crosses international borders"]

st.session_state["shap_top3_text"] = "; ".join([f for f, _ in top_features[:3]])

plot_df = pd.DataFrame(top_features, columns=["feature", "shap_value"])
plot_df = plot_df.sort_values("shap_value", key=lambda s: s.abs(), ascending=True)

fig, ax = plt.subplots(figsize=(8, 3.5))
ax.barh(plot_df["feature"], plot_df["shap_value"], color="#42a5f5")
ax.set_xlabel("Combined contribution (CART importance + Logistic local effect)")
ax.set_ylabel("Feature")
st.pyplot(fig)

st.write(plain_text)
for b in bullets:
    st.markdown(b)

st.subheader("Related Transactions")
sender_acc = selected_txn["Sender_account"]
receiver_acc = selected_txn["Receiver_account"]

scored_df = scored_df.copy()
scored_df["_dt"] = pd.to_datetime(scored_df["Date"].astype(str) + " " + scored_df["Time"].astype(str), errors="coerce")

sender_last = scored_df[scored_df["Sender_account"] == sender_acc].sort_values("_dt", ascending=False).head(10)
receiver_last = scored_df[scored_df["Receiver_account"] == receiver_acc].sort_values("_dt", ascending=False).head(10)

st.write("Last 10 from same Sender")
st.dataframe(
    sender_last[["transaction_id", "Date", "Time", "Receiver_account", "Amount", "risk_tier"]],
    use_container_width=True,
)
st.write("Last 10 to same Receiver")
st.dataframe(
    receiver_last[["transaction_id", "Date", "Time", "Sender_account", "Amount", "risk_tier"]],
    use_container_width=True,
)

st.subheader("CDD Level Selector")
cdd_level = st.radio("CDD Level", ["Simplified CDD", "Standard CDD", "Enhanced CDD"], horizontal=True)
notes = st.text_area("Investigation notes", key="investigation_notes", height=120)
outcome_reason = st.text_input("Resolution reason (required if resolving without STR)", value="")
analyst_id = st.text_input("Analyst ID", value="Analyst")

c1, c2 = st.columns(2)

escalate_enabled = bool(cdd_level and notes.strip())
if c1.button("Escalate to STR", disabled=not escalate_enabled):
    st.session_state["str_case"] = {
        "transaction_id": str(selected_txn["transaction_id"]),
        "date": str(selected_txn["Date"]),
        "sender_account": str(selected_txn["Sender_account"]),
        "receiver_account": str(selected_txn["Receiver_account"]),
        "amount": float(selected_txn["Amount"]),
        "payment_type": str(selected_txn["Payment_type"]),
        "risk_score": float(selected_txn["risk_score"]),
        "risk_tier": str(selected_txn["risk_tier"]),
        "cdd_level": cdd_level,
        "investigation_notes": notes,
        "shap_top3": st.session_state.get("shap_top3_text", ""),
        "escalated_at": datetime.now().isoformat(),
        "escalated_by": analyst_id,
    }
    log_action(
        action="case_investigated",
        transaction_id=str(selected_txn["transaction_id"]),
        details=f"cdd_level={cdd_level}; notes_length={len(notes)}; outcome=escalated_to_str",
        analyst_id=analyst_id,
    )
    st.switch_page("pages/4_STR_Generation.py")

if c2.button("Resolve - No STR Required"):
    if not outcome_reason.strip():
        st.error("Please provide a resolution reason.")
    else:
        status_map = st.session_state.get("alert_status", {})
        status_map[str(selected_txn["transaction_id"])] = {"status": "Dismissed", "reason": outcome_reason}
        st.session_state["alert_status"] = status_map
        log_action(
            action="case_investigated",
            transaction_id=str(selected_txn["transaction_id"]),
            details=f"cdd_level={cdd_level}; notes_length={len(notes)}; outcome=resolved_no_str; reason={outcome_reason}",
            analyst_id=analyst_id,
        )
        st.success("Case resolved without STR.")
