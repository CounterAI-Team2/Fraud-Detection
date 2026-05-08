from __future__ import annotations

from datetime import date

import streamlit as st

from utils.aml_services import archive_str_case, build_archive_search_view, upsert_str_workflow
from utils.audit_logger import log_action
from utils.data_store import get_str_cases
from utils.str_builder import build_default_grounds, make_reference_number

st.title("4. STR Generation")

if "str_case" not in st.session_state or st.session_state["str_case"] is None:
    st.error("No case loaded. Please escalate a case from the Case Investigation page.")
    st.stop()

str_case = st.session_state["str_case"]
actor_id = st.session_state.get("current_actor_id", "Analyst")
actor_role = st.session_state.get("current_actor_role", "Admin")

str_cases = get_str_cases()
existing_str = None
if not str_cases.empty:
    match = str_cases[str_cases["case_id"].astype(str) == str(str_case.get("case_id", ""))]
    if not match.empty:
        existing_str = match.iloc[0].to_dict()

starting_status = existing_str.get("status", "Draft") if existing_str else "Draft"
str_record = upsert_str_workflow(existing_str or str_case, build_default_grounds(str_case), starting_status)
st.session_state["current_str_id"] = str_record["str_id"]

st.write(f"Current Status: **{str_record['status']}**")

report_date = st.date_input("Report Date", value=date.today())
institution = st.text_input("Reporting Institution", value="Counter AI Demo Bank")
txn_ref = st.text_input("Transaction Reference", value=str_case["transaction_id"])
trx_date = st.text_input("Date of Suspicious Transaction", value=str_case.get("date", ""))
sender_details = st.text_input("Sender Details", value=f"Account {str_case['sender_account']}")
receiver_details = st.text_input("Receiver Details", value=f"Account {str_case['receiver_account']}")
amount = st.text_input("Transaction Amount", value=f"{str_case['amount']:,.2f}")
payment_method = st.text_input("Payment Method", value=str_case["payment_type"])
ai_summary = st.text_input(
    "AI Flagging Summary",
    value=f"RF score: {float(str_case['risk_score']):.3f} - {str_case['risk_tier']}",
)
cdd_level = st.text_input("CDD Level Applied", value=str_case["cdd_level"])

default_grounds = build_default_grounds(str_case)
grounds = st.text_area("Grounds for Suspicion", value=str_record.get("grounds", default_grounds), height=180)

confirm = st.checkbox("I confirm this STR is accurate to the best of my knowledge")
analyst_id = st.text_input("Analyst ID", value=str_case.get("escalated_by", actor_id))
l2_rejection_reason = st.text_input("L2 rejection reason", value="")

workflow_cols = st.columns(4)
if workflow_cols[0].button("Submit to L1 Review"):
    str_record = upsert_str_workflow(
        str_record,
        grounds,
        "L1Review",
        {"reference_number": str_record.get("reference_number", make_reference_number(str_case["transaction_id"]))},
    )
    log_action(
        action="str_submitted_l1",
        transaction_id=str_case["transaction_id"],
        details=f"str_id={str_record['str_id']}",
        analyst_id=analyst_id,
        module="str_workflow",
        event_type="str_submitted_l1",
        entity_type="str",
        entity_id=str_record["str_id"],
        actor_role=actor_role,
        payload={"status": "L1Review"},
    )
    st.success("STR moved to L1 Review.")
    st.rerun()

if workflow_cols[1].button("Approve L1"):
    str_record = upsert_str_workflow(
        str_record,
        grounds,
        "L2Review",
        {"l1_reviewer": analyst_id, "l1_reviewed_at": str(report_date), "l1_reason": "Approved by L1"},
    )
    log_action(
        action="str_approved_l1",
        transaction_id=str_case["transaction_id"],
        details=f"str_id={str_record['str_id']}",
        analyst_id=analyst_id,
        module="str_workflow",
        event_type="str_approved_l1",
        entity_type="str",
        entity_id=str_record["str_id"],
        actor_role=actor_role,
        payload={"status": "L2Review"},
    )
    st.success("STR moved to L2 Review.")
    st.rerun()

if workflow_cols[2].button("Reject at L2"):
    if not l2_rejection_reason.strip():
        st.error("Provide an L2 rejection reason.")
    else:
        str_record = upsert_str_workflow(
            str_record,
            grounds,
            "Draft",
            {"l2_reviewer": analyst_id, "l2_reviewed_at": str(report_date), "l2_reason": l2_rejection_reason},
        )
        log_action(
            action="str_rejected_l2",
            transaction_id=str_case["transaction_id"],
            details=f"str_id={str_record['str_id']}; reason={l2_rejection_reason}",
            analyst_id=analyst_id,
            module="str_workflow",
            event_type="str_rejected_l2",
            entity_type="str",
            entity_id=str_record["str_id"],
            actor_role=actor_role,
            payload={"reason": l2_rejection_reason},
        )
        st.warning("STR sent back to Draft after L2 rejection.")
        st.rerun()

if workflow_cols[3].button("Approve and Archive"):
    if not confirm:
        st.error("Please confirm analyst declaration before archiving.")
    else:
        ref_no = str_record.get("reference_number") or make_reference_number(str_case["transaction_id"])
        str_record = upsert_str_workflow(
            str_record,
            grounds,
            "Approved",
            {
                "reference_number": ref_no,
                "l2_reviewer": analyst_id,
                "l2_reviewed_at": str(report_date),
                "l2_reason": "Approved at L2",
            },
        )
        archive_str_case(
            str_record,
            analyst_id,
            {
                "customer_name": str_case.get("customer_name", ""),
                "risk_tier": str_case.get("risk_tier", ""),
                "report_date": str(report_date),
                "reference_number": ref_no,
                "grounds": grounds,
            },
        )
        upsert_str_workflow(str_record, grounds, "Archived", {"reference_number": ref_no})
        st.success(f"STR approved and archived. Reference Number: {ref_no}")
        st.session_state["str_log"].append(
            {
                "reference_number": ref_no,
                "transaction_id": str_case["transaction_id"],
                "rf_prediction": str_case["risk_score"],
                "cdd_level": str_case["cdd_level"],
                "filed_by": analyst_id,
                "report_date": str(report_date),
            }
        )
        log_action(
            action="str_archived",
            transaction_id=str_case["transaction_id"],
            details=f"reference_number={ref_no}; cdd_level={str_case['cdd_level']}",
            analyst_id=analyst_id,
            module="str_workflow",
            event_type="str_archived",
            entity_type="str",
            entity_id=str_record["str_id"],
            actor_role=actor_role,
            payload={"reference_number": ref_no, "status": "Archived"},
        )
        st.rerun()

st.subheader("STR Preview")
st.markdown(
    f"""
- **Report Date:** {report_date}
- **Institution:** {institution}
- **Transaction Reference:** {txn_ref}
- **Date of Suspicious Transaction:** {trx_date}
- **Sender:** {sender_details}
- **Receiver:** {receiver_details}
- **Amount:** {amount}
- **Payment Method:** {payment_method}
- **AI Flagging:** {ai_summary}
- **CDD Level:** {cdd_level}

**Grounds for Suspicion**

{grounds}
"""
)

st.subheader("Archived STR Cases")
archive_view = build_archive_search_view()
if archive_view.empty:
    st.info("No archived STR cases yet.")
else:
    search_col1, search_col2, search_col3 = st.columns(3)
    with search_col1:
        customer_search = st.text_input("Archive search by customer", value="")
    with search_col2:
        risk_search = st.selectbox("Risk Tier", ["All"] + sorted(archive_view["risk_tier"].dropna().astype(str).unique().tolist()))
    with search_col3:
        status_search = st.selectbox("STR Status", ["All"] + sorted(archive_view["str_status"].dropna().astype(str).unique().tolist()))

    archive_filtered = archive_view.copy()
    if customer_search.strip():
        archive_filtered = archive_filtered[
            archive_filtered["customer_name"].astype(str).str.contains(customer_search.strip(), case=False, na=False)
        ]
    if risk_search != "All":
        archive_filtered = archive_filtered[archive_filtered["risk_tier"].astype(str) == risk_search]
    if status_search != "All":
        archive_filtered = archive_filtered[archive_filtered["str_status"].astype(str) == status_search]

    st.dataframe(
        archive_filtered[
            [
                "archive_id",
                "str_id",
                "case_id",
                "transaction_id",
                "customer_id",
                "customer_name",
                "risk_tier",
                "str_status",
                "archived_at",
                "archived_by",
            ]
        ],
        use_container_width=True,
    )
