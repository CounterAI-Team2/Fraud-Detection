from __future__ import annotations

import streamlit as st

from utils.audit_logger import log_action
from utils.kyc_store import (
    KYC_COLUMNS,
    enrol_customer,
    ensure_kyc_database,
    get_kyc_customers,
    name_on_un_sanctions_list,
)
from utils.session_utils import get_current_analyst

st.title("1. KYC & Customer Registry")
st.caption("Maintain enrolled customers before transaction upload. All new customers start at Low risk.")

ensure_kyc_database()
actor_id, actor_role = get_current_analyst()


def _complete_enrolment(pending: dict[str, str]) -> None:
    row, _ = enrol_customer(
        full_name=pending["FullName"],
        account_no=pending["AccountNo"],
        address=pending["Address"],
        contact_no=pending["ContactNo"],
        comments=pending.get("Comments", ""),
    )
    log_action(
        action="kyc_customer_enrolled",
        details=f"customer_id={row['id']}; account={row['AccountNo']}",
        analyst_id=actor_id,
        module="kyc_screening",
        event_type="kyc_customer_enrolled",
        entity_type="customer",
        entity_id=row["id"],
        actor_role=actor_role,
        payload={
            "id": row["id"],
            "FullName": row["FullName"],
            "AccountNo": row["AccountNo"],
            "sanctions_warning_ignored": pending.get("sanctions_warning_ignored", False),
        },
    )
    st.session_state.pop("kyc_pending_enrol", None)
    st.session_state["kyc_enrol_success"] = (
        f"Customer **{row['FullName']}** enrolled successfully (ID: `{row['id']}`)."
    )


@st.dialog("Enrol New Customer")
def enrol_customer_dialog() -> None:
    st.caption("Customer ID is assigned automatically (10 digits).")

    pending = st.session_state.get("kyc_pending_enrol")
    if pending:
        st.warning("Warning: This name is present on the 1737 UN Sanctions List")
        st.write(
            f"Pending enrolment: **{pending['FullName']}** · Account **{pending['AccountNo']}**"
        )
        col1, col2 = st.columns(2)
        if col1.button("Register anyway", type="primary", use_container_width=True):
            pending["sanctions_warning_ignored"] = True
            try:
                _complete_enrolment(pending)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if col2.button("Cancel", use_container_width=True):
            st.session_state.pop("kyc_pending_enrol", None)
            st.session_state.pop("kyc_open_enrol_dialog", None)
            st.rerun()
        return

    with st.form("enrol_customer_form", clear_on_submit=False):
        full_name = st.text_input("Full Name", placeholder="Legal name as on ID")
        account_no = st.text_input("Account Number", placeholder="Sender account used in transactions")
        address = st.text_input("Address")
        contact_no = st.text_input("Contact Number")
        comments = st.text_area("Comments", height=80, placeholder="Optional notes")
        submitted = st.form_submit_button("Enrol Customer", type="primary", use_container_width=True)

    if not submitted:
        return

    if not full_name.strip():
        st.error("Full Name is required.")
        return
    if not account_no.strip():
        st.error("Account Number is required.")
        return
    if not address.strip():
        st.error("Address is required.")
        return
    if not contact_no.strip():
        st.error("Contact Number is required.")
        return

    payload = {
        "FullName": full_name.strip(),
        "AccountNo": account_no.strip(),
        "Address": address.strip(),
        "ContactNo": contact_no.strip(),
        "Comments": comments.strip(),
    }

    if name_on_un_sanctions_list(full_name):
        st.session_state["kyc_pending_enrol"] = payload
        st.session_state["kyc_open_enrol_dialog"] = True
        st.rerun()
        return

    try:
        _complete_enrolment(payload)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


customers = get_kyc_customers()

success_msg = st.session_state.pop("kyc_enrol_success", None)
if success_msg:
    st.success(success_msg)

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Enrolled Customers", len(customers))
metric_col2.metric("Low Risk", int(customers["RiskStatus"].astype(str).str.lower().eq("low").sum()))
metric_col3.metric("Medium Risk", int(customers["RiskStatus"].astype(str).str.lower().eq("medium").sum()))

if st.button("Enrol New Customer", type="primary"):
    enrol_customer_dialog()

if st.session_state.pop("kyc_open_enrol_dialog", False):
    enrol_customer_dialog()

search = st.text_input("Search by name, ID, or account number", value="")
view = customers.copy()
if search.strip():
    needle = search.strip().lower()
    view = view[
        view["FullName"].astype(str).str.lower().str.contains(needle)
        | view["id"].astype(str).str.lower().str.contains(needle)
        | view["AccountNo"].astype(str).str.lower().str.contains(needle)
    ]

st.subheader("Customer Database")
if view.empty:
    st.info("No customers match your search.")
else:
    if search.strip():
        st.caption(f"Showing {len(view)} of {len(customers)} customers")
    st.dataframe(
        view.rename(
            columns={
                "id": "ID",
                "FullName": "Full Name",
                "AccountNo": "Account No",
                "ContactNo": "Contact No",
                "RiskStatus": "Risk Status",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
