from __future__ import annotations

from datetime import date

import streamlit as st

from utils.audit_logger import log_action
from utils.str_builder import build_default_grounds, make_reference_number

st.title("4. STR Generation")

if "str_case" not in st.session_state or st.session_state["str_case"] is None:
    st.error("No case loaded. Please escalate a case from the Case Investigation page.")
    st.stop()

str_case = st.session_state["str_case"]

status_key = f"str_status_{str_case['transaction_id']}"
if status_key not in st.session_state:
    st.session_state[status_key] = "Draft"

st.write(f"Current Status: **{st.session_state[status_key]}**")

report_date = st.date_input("Report Date", value=date.today())
institution = st.text_input("Reporting Institution", value="Counter AI Demo Bank")
txn_ref = st.text_input("Transaction Reference", value=str_case["transaction_id"])
trx_date = st.text_input("Date of Suspicious Transaction", value=str_case.get("date", ""))
sender_details = st.text_input("Sender Details", value=f"Account {str_case['sender_account']}")
receiver_details = st.text_input("Receiver Details", value=f"Account {str_case['receiver_account']}")
amount = st.text_input("Transaction Amount", value=f"{str_case['amount']:,.2f}")
payment_method = st.text_input("Payment Method", value=str_case["payment_type"])
ai_summary = st.text_input("AI Flagging Summary", value=f"RF decision: {'Flagged' if int(str_case['risk_score']) == 1 else 'Not flagged'} - {str_case['risk_tier']}")
cdd_level = st.text_input("CDD Level Applied", value=str_case["cdd_level"])

default_grounds = build_default_grounds(str_case)
grounds = st.text_area("Grounds for Suspicion", value=default_grounds, height=180)

confirm = st.checkbox("I confirm this STR is accurate to the best of my knowledge")
analyst_id = st.text_input("Analyst ID", value=str_case.get("escalated_by", "Analyst"))

c1, c2 = st.columns(2)
if c1.button("Submit for Review"):
    st.session_state[status_key] = "Pending Approval"
    st.success("STR moved to Pending Approval.")

if c2.button("Approve and File"):
    if not confirm:
        st.error("Please confirm analyst declaration before filing.")
    else:
        st.session_state[status_key] = "Filed"
        ref_no = make_reference_number(str_case["transaction_id"])
        st.success(f"STR filed successfully. Reference Number: {ref_no}")

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
            action="str_filed",
            transaction_id=str_case["transaction_id"],
            details=f"reference_number={ref_no}; rf_prediction={int(str_case['risk_score'])}; cdd_level={str_case['cdd_level']}",
            analyst_id=analyst_id,
        )

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
