from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.aml_services import apply_sanctions_screening, clear_sanctions_flag, sync_customer_profiles
from utils.audit_logger import log_action
from utils.constants import CUSTOMER_RECENT_TXNS_LIMIT
from utils.data_store import get_customers
from utils.session_utils import get_current_analyst, require_scored_df

st.title("6. KYC & Screening")
st.caption("Customer profile review, KYC risk tiering, and sanctions screening workflow.")

require_scored_df()
scored_df = st.session_state["scored_df"]

customers = sync_customer_profiles(scored_df)
customers = apply_sanctions_screening(customers)
if customers.empty:
    st.info("No customer profiles are available yet.")
    st.stop()

customers = get_customers()
actor_id, actor_role = get_current_analyst()

filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    risk_filter = st.multiselect("Risk Tier", ["Low", "Medium", "High"], default=["Low", "Medium", "High"])
with filter_col2:
    sanctions_only = st.checkbox("Sanctions hits only", value=False)
with filter_col3:
    search_term = st.text_input("Customer or account search", value="")

view = customers[customers["kyc_risk_tier"].isin(risk_filter)].copy()
if sanctions_only:
    view = view[view["sanctions_flag"].astype(str).str.lower().isin(["true", "1"])]
if search_term.strip():
    needle = search_term.strip().lower()
    view = view[
        view["customer_name"].astype(str).str.lower().str.contains(needle)
        | view["account_id"].astype(str).str.lower().str.contains(needle)
        | view["customer_id"].astype(str).str.lower().str.contains(needle)
    ]

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Customer Profiles", len(view))
metric_col2.metric("High-Risk Customers", int(view["kyc_risk_tier"].astype(str).eq("High").sum()))
metric_col3.metric("Sanctions Hits", int(view["sanctions_flag"].astype(str).str.lower().isin(["true", "1"]).sum()))

st.dataframe(
    view[
        [
            "customer_id",
            "customer_name",
            "account_id",
            "kyc_status",
            "kyc_risk_tier",
            "cdd_level",
            "onboarding_date",
            "last_review_date",
            "sanctions_flag",
            "sanctions_reason",
        ]
    ],
    use_container_width=True,
)

customer_options = view["customer_id"].astype(str).tolist()
if not customer_options:
    st.info("No customers match the selected filters.")
    st.stop()

selected_customer_id = st.selectbox("Select customer profile", customer_options)
selected_row = customers[customers["customer_id"].astype(str) == str(selected_customer_id)].iloc[0]

st.subheader("Customer Profile")
profile_col1, profile_col2 = st.columns([2, 1])
with profile_col1:
    st.write(f"Customer ID: `{selected_row['customer_id']}`")
    st.write(f"Customer Name: `{selected_row['customer_name']}`")
    st.write(f"Account ID: `{selected_row['account_id']}`")
    st.write(f"KYC Status: `{selected_row['kyc_status']}`")
    st.write(f"Onboarding Date: `{selected_row['onboarding_date']}`")
    st.write(f"Last Review Date: `{selected_row['last_review_date']}`")
with profile_col2:
    st.metric("Risk Tier", selected_row["kyc_risk_tier"])
    st.metric("CDD Level", selected_row["cdd_level"])
    st.metric("Transaction Volume", f"{float(selected_row['transaction_volume']):,.2f}")

st.subheader("Risk Indicators")
st.write(
    {
        "cross_border_count": int(float(selected_row["cross_border_count"])),
        "cross_currency_count": int(float(selected_row["cross_currency_count"])),
        "unique_counterparties": int(float(selected_row["unique_counterparties"])),
        "high_value_count": int(float(selected_row["high_value_count"])),
    }
)

if str(selected_row["sanctions_flag"]).lower() in {"true", "1"}:
    st.warning(
        f"Sanctions warning: match source `{selected_row['sanctions_match_source']}`. Reason: {selected_row['sanctions_reason']}"
    )
    clear_reason = st.text_input("Clear sanctions reason", key="clear_sanctions_reason")
    if st.button("Clear Sanctions Flag"):
        if not clear_reason.strip():
            st.error("Provide a reason before clearing a sanctions flag.")
        else:
            clear_sanctions_flag(selected_customer_id, clear_reason, actor_id)
            log_action(
                action="sanctions_flag_cleared",
                details=f"customer_id={selected_customer_id}; reason={clear_reason}",
                analyst_id=actor_id,
                module="kyc_screening",
                event_type="sanctions_flag_cleared",
                entity_type="customer",
                entity_id=selected_customer_id,
                actor_role=actor_role,
                payload={"reason": clear_reason},
            )
            st.success("Sanctions flag cleared.")
            st.rerun()
else:
    st.success("No sanctions warning is active for this customer.")

st.subheader("Recent Customer Transactions")
scored = pd.DataFrame(scored_df)
scored["customer_id"] = scored["Sender_account"].astype(str).apply(lambda value: f"CUST-{value}")
customer_txns = scored[scored["customer_id"].astype(str) == str(selected_customer_id)].copy()
customer_txns["txn_dt"] = pd.to_datetime(customer_txns["Date"].astype(str) + " " + customer_txns["Time"].astype(str), errors="coerce")
customer_txns = customer_txns.sort_values("txn_dt", ascending=False)
st.dataframe(
    customer_txns[
        [
            "transaction_id",
            "Date",
            "Time",
            "Receiver_account",
            "Amount",
            "risk_score",
            "risk_tier",
        ]
    ].head(CUSTOMER_RECENT_TXNS_LIMIT),
    use_container_width=True,
)

log_action(
    action="kyc_profile_viewed",
    details=f"customer_id={selected_customer_id}",
    analyst_id=actor_id,
    module="kyc_screening",
    event_type="kyc_profile_viewed",
    entity_type="customer",
    entity_id=selected_customer_id,
    actor_role=actor_role,
    payload={"customer_id": selected_customer_id},
)
