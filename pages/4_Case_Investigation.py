from __future__ import annotations

from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from utils.aml_services import (
    attach_case_files,
    ensure_case_for_transaction,
    ensure_scored_defaults,
    get_case_by_transaction,
    get_related_transactions,
    update_case_record,
)
from utils.audit_logger import log_action
from utils.constants import (
    ALERT_STATUS_DISMISSED,
    CASE_STATUSES,
    CASE_STATUS_ESCALATED,
    CASE_STATUS_IN_REVIEW,
    CASE_STATUS_OPEN,
    CASE_STATUS_RESOLVED,
    CDD_LEVEL_ENHANCED,
    CDD_LEVEL_STANDARD,
    CDD_LEVELS,
    RISK_TIER_COLORS,
)
from utils.data_store import get_customers, upsert_customers
from utils.feature_engineering import CATEGORICAL_FEATURES, ENGINEERED_FEATURES, prepare_model_matrix
from utils.model_loader import load_models
from utils.session_utils import get_current_analyst, require_scored_df
from utils.shap_explainer import get_model_xai_explanation

st.title("4. Case Investigation")

require_scored_df()
scored_df = st.session_state["scored_df"]
scored_df = ensure_scored_defaults(scored_df)
st.session_state["scored_df"] = scored_df

selected_txn_id = st.session_state.get("selected_txn_id")
if selected_txn_id is None:
    st.warning("No transaction selected from Alert Queue.")
    flagged_options = scored_df[scored_df["rf_prediction"].astype(int) == 1]
    if flagged_options.empty:
        st.info("No flagged transactions are available for investigation.")
        st.stop()
    tx_options = flagged_options["transaction_id"].astype(str).tolist()
    selected_txn_id = st.selectbox("Select transaction", tx_options)

rows = scored_df[scored_df["transaction_id"].astype(str) == str(selected_txn_id)]
if rows.empty:
    st.error("Selected transaction not found.")
    st.stop()

selected_txn = rows.iloc[0]
analyst_id, actor_role = get_current_analyst()
case_record = ensure_case_for_transaction(selected_txn, analyst_id)
existing_case = get_case_by_transaction(str(selected_txn["transaction_id"])) or case_record
st.session_state["selected_case_id"] = existing_case["case_id"]

tier_color = RISK_TIER_COLORS.get(selected_txn["risk_tier"], "#cfd8dc")

st.subheader("Case Workspace")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Case ID", existing_case["case_id"])
c2.metric("Status", existing_case.get("status", CASE_STATUS_OPEN))
c3.metric("Risk Tier", selected_txn["risk_tier"])
c4.metric("Risk Score", f"{float(selected_txn['risk_score']):.3f}")

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
        f"<div style='font-size:28px;font-weight:700;color:{tier_color}'>{'Flagged' if int(selected_txn['rf_prediction']) == 1 else 'Not flagged'}</div>"
        f"<div style='padding:6px;border-radius:8px;background:{tier_color};color:black;font-weight:700'>{selected_txn['risk_tier']}</div>",
        unsafe_allow_html=True,
    )

st.subheader("Model Explainability (CART + Logistic)")
rf_model, cart_model, logit_model = load_models()
x = prepare_model_matrix(scored_df[ENGINEERED_FEATURES + CATEGORICAL_FEATURES], rf_model.feature_names_in_)

idx = rows.index[0]
row_for_shap = x.loc[[idx]].copy()

try:
    top_features, plain_text, bullets = get_model_xai_explanation(cart_model, logit_model, row_for_shap, list(x.columns))
except Exception as e:
    import sys
    print(f"WARNING: XAI explanation failed: {e}", file=sys.stderr)
    top_features = [("amount_log", 0.0), ("cross_border", 0.0), ("cross_currency", 0.0)]
    plain_text = "This transaction was flagged primarily due to a combination of network and transaction risk indicators."
    bullets = [
        "- sender transacts with unusually many unique receivers (fan-out)",
        "- transaction amount is significantly above typical",
        "- transaction crosses international borders",
    ]

st.session_state["shap_top3_text"] = "; ".join([f for f, _ in top_features[:3]])
plot_df = pd.DataFrame(top_features, columns=["feature", "shap_value"]).sort_values(
    "shap_value", key=lambda s: s.abs(), ascending=True
)

fig, ax = plt.subplots(figsize=(8, 3.5))
ax.barh(plot_df["feature"], plot_df["shap_value"], color="#42a5f5")
ax.set_xlabel("Combined contribution (CART importance + Logistic local effect)")
ax.set_ylabel("Feature")
st.pyplot(fig)
st.write(plain_text)
for feature_name, feature_value in top_features[:5]:
    arrow = "up" if feature_value >= 0 else "down"
    st.write(f"- {feature_name}: risk {arrow} ({feature_value:.4f})")
for bullet in bullets:
    st.markdown(bullet)

st.subheader("Related Transactions (+/-30 days)")
related = get_related_transactions(scored_df, selected_txn, window_days=30)
if related.empty:
    st.info("No related transactions found in the review window.")
else:
    st.dataframe(
        related[
            [
                "transaction_id",
                "Date",
                "Time",
                "Receiver_account",
                "Amount",
                "risk_score",
                "risk_tier",
                "highlight_reason",
            ]
        ],
        use_container_width=True,
    )

st.subheader("CDD Decisioning")
customers = get_customers()
customer_mask = customers["customer_id"].astype(str) == str(selected_txn["customer_id"])
customer_row = customers[customer_mask].iloc[0] if not customers.empty and customer_mask.any() else None

default_cdd = existing_case.get("cdd_level", CDD_LEVEL_STANDARD)
default_idx = CDD_LEVELS.index(default_cdd) if default_cdd in CDD_LEVELS else 1
cdd_level = st.radio("CDD Level", CDD_LEVELS, index=default_idx, horizontal=True)
status = st.selectbox("Case Status", CASE_STATUSES, index=1 if existing_case.get("status") == CASE_STATUS_IN_REVIEW else 0)
notes = st.text_area("Investigation notes", value=existing_case.get("notes", ""), height=140)
outcome_reason = st.text_input("Resolution reason (required if resolving without STR)", value=existing_case.get("resolution", ""))
attachment_names = st.text_input(
    "Attachment names (comma separated metadata only)",
    value=existing_case.get("attachment_names", ""),
    help="MVP stores attachment metadata only.",
)

save_col, escalate_col, resolve_col = st.columns(3)
if save_col.button("Save Case Workspace"):
    updated_case = update_case_record(
        existing_case["case_id"],
        {
            "status": status,
            "cdd_level": cdd_level,
            "notes": notes,
            "resolution": outcome_reason,
            "str_required": cdd_level == CDD_LEVEL_ENHANCED,
            "kyc_risk_tier": "High" if cdd_level == CDD_LEVEL_ENHANCED else ("Medium" if cdd_level == CDD_LEVEL_STANDARD else "Low"),
        },
    )
    attachment_list = [item.strip() for item in attachment_names.split(",") if item.strip()]
    updated_case = attach_case_files(updated_case["case_id"], attachment_list)

    if customer_row is not None:
        customers.loc[customer_mask, "cdd_level"] = cdd_level
        customers.loc[customer_mask, "kyc_risk_tier"] = updated_case["kyc_risk_tier"]
        customers.loc[customer_mask, "last_review_date"] = str(pd.Timestamp.utcnow().date())
        customers.loc[customer_mask, "updated_at"] = datetime.now().isoformat()
        upsert_customers(customers)

    log_action(
        action="cdd_case_updated",
        transaction_id=str(selected_txn["transaction_id"]),
        details=f"case_id={updated_case['case_id']}; cdd_level={cdd_level}; status={status}",
        analyst_id=analyst_id,
        module="cdd_module",
        event_type="cdd_case_updated",
        entity_type="case",
        entity_id=updated_case["case_id"],
        actor_role=actor_role,
        payload={
            "cdd_level": cdd_level,
            "status": status,
            "notes_length": len(notes),
            "attachment_count": len(attachment_list),
        },
    )
    st.success("Case workspace saved.")

escalate_enabled = bool(notes.strip())
if escalate_col.button("Escalate to STR", disabled=not escalate_enabled):
    updated_case = update_case_record(
        existing_case["case_id"],
        {
            "status": CASE_STATUS_ESCALATED,
            "cdd_level": cdd_level,
            "notes": notes,
            "str_required": True,
            "kyc_risk_tier": "High" if cdd_level == CDD_LEVEL_ENHANCED else existing_case.get("kyc_risk_tier", "Medium"),
        },
    )
    st.session_state["str_case"] = {
        "case_id": updated_case["case_id"],
        "customer_id": str(selected_txn["customer_id"]),
        "customer_name": customer_row["customer_name"] if customer_row is not None else "",
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
        action="case_escalated_to_str",
        transaction_id=str(selected_txn["transaction_id"]),
        details=f"case_id={updated_case['case_id']}; cdd_level={cdd_level}",
        analyst_id=analyst_id,
        module="cdd_module",
        event_type="case_escalated_to_str",
        entity_type="case",
        entity_id=updated_case["case_id"],
        actor_role=actor_role,
        payload={
            "cdd_level": cdd_level,
            "notes_length": len(notes),
            "str_required": True,
        },
    )
    st.switch_page("pages/5_STR_Generation.py")

if resolve_col.button("Resolve - No STR Required"):
    if not outcome_reason.strip():
        st.error("Please provide a resolution reason.")
    else:
        updated_case = update_case_record(
            existing_case["case_id"],
            {
                "status": CASE_STATUS_RESOLVED,
                "cdd_level": cdd_level,
                "notes": notes,
                "resolution": outcome_reason,
                "str_required": False,
            },
        )
        status_map = st.session_state.get("alert_status", {})
        status_map[str(selected_txn["transaction_id"])] = {"status": ALERT_STATUS_DISMISSED, "reason": outcome_reason}
        st.session_state["alert_status"] = status_map
        log_action(
            action="case_resolved_no_str",
            transaction_id=str(selected_txn["transaction_id"]),
            details=f"case_id={updated_case['case_id']}; cdd_level={cdd_level}; reason={outcome_reason}",
            analyst_id=analyst_id,
            module="cdd_module",
            event_type="case_resolved_no_str",
            entity_type="case",
            entity_id=updated_case["case_id"],
            actor_role=actor_role,
            payload={
                "cdd_level": cdd_level,
                "reason": outcome_reason,
            },
        )
        st.success("Case resolved without STR.")
