from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")

from utils.audit_logger import log_action
from utils.sidebar import render_sidebar
from utils.constants import (
    CUSTOMER_RISK_STATUSES,
    FLAG_REASON_PEP,
    KYC_ENROL_ROLES,
    KYC_RISK_MAKER_ROLES,
    REF_DATA_ROLES,
    SANCTIONS_DISPOSITION_ROLES,
    SM_APPROVAL_PENDING,
    display_role,
)
from utils.kyc_store import (
    CUSTOMER_RISK_STATUSES as KYC_RISK_STATUSES,
    CUSTOMER_TYPE_CORPORATE,
    CUSTOMER_TYPE_INDIVIDUAL,
    KYC_PAGE_SIZE_DEFAULT,
    RISK_CRITICAL,
    RISK_HIGH,
    SANCTIONS_ACTIVE_REVIEW_STATUSES,
    SANCTIONS_REVIEW_CONFIRMED,
    SANCTIONS_REVIEW_ESCALATED,
    SANCTIONS_REVIEW_FUZZY,
    SANCTIONS_REVIEW_PENDING,
    apply_confirmed_sanctions_match,
    clear_sanctions_match,
    enrol_customer,
    ensure_kyc_database,
    get_kyc_by_id,
    get_kyc_customers,
    paginate_kyc_customers,
    force_rescreen_kyc_sanctions,
    ensure_kyc_sanctions_screened,
    search_kyc_customers,
    set_customer_risk_status,
    update_kyc_record,
)
from utils.mas_sanctions_sync import (
    MAS_INDEX_URL,
    catalog_entry_status,
    get_last_sync,
    import_uploaded_list,
    list_catalog_entries,
    screen_name,
    sync_mas_sanctions,
)
from utils.session_utils import can_act, get_current_analyst, is_read_only

render_sidebar()
ensure_kyc_database()
actor_id, actor_role = get_current_analyst()
_can_enrol = can_act(actor_role, KYC_ENROL_ROLES)
_can_risk_edit = can_act(actor_role, KYC_RISK_MAKER_ROLES)
_can_sanctions_action = can_act(actor_role, SANCTIONS_DISPOSITION_ROLES)
_can_ref_data = can_act(actor_role, REF_DATA_ROLES)
_read_only = is_read_only(actor_role)

st.title("KYC Screening")
st.caption("Enrol and manage customers, screen against sanctions lists, and maintain KYC risk profiles.")

st.markdown(
    """
    <style>
    .kyc-risk-badge {
        display: inline-block;
        white-space: nowrap;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
        line-height: 1.4;
    }
    /* Bordered KYC data table */
    [data-testid="stHorizontalBlock"]:has(.kyc-th),
    [data-testid="stHorizontalBlock"]:has([class*="st-key-kycrow_"]) {
        gap: 0 !important;
    }
    [data-testid="stHorizontalBlock"]:has(.kyc-th) [data-testid="column"],
    [data-testid="stHorizontalBlock"]:has([class*="st-key-kycrow_"]) [data-testid="column"] {
        padding: 0 !important;
    }
    .kyc-th {
        padding: 10px 10px;
        font-size: 11px;
        font-weight: 700;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        background: rgba(255, 255, 255, 0.06);
        border-top: 1px solid rgba(255, 255, 255, 0.14);
        border-bottom: 1px solid rgba(255, 255, 255, 0.14);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        min-height: 40px;
        display: flex;
        align-items: center;
        box-sizing: border-box;
    }
    .kyc-th-0 { border-left: 1px solid rgba(255, 255, 255, 0.14); }
    .kyc-th-5 { border-right: 1px solid rgba(255, 255, 255, 0.14); }
    [class*="st-key-kycrow_"] {
        margin-bottom: 0 !important;
    }
    [class*="st-key-kycrow_"] button {
        width: 100% !important;
        min-height: 50px !important;
        height: auto !important;
        padding: 8px 10px !important;
        margin: 0 !important;
        border-radius: 0 !important;
        border: none !important;
        border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
        background: rgba(255, 255, 255, 0.02) !important;
        box-shadow: none !important;
    }
    [class*="st-key-kycrow_"][class*="_0"] button {
        border-left: 1px solid rgba(255, 255, 255, 0.14) !important;
    }
    [class*="st-key-kycrow_"][class*="_5"] button {
        border-right: 1px solid rgba(255, 255, 255, 0.14) !important;
    }
    [class*="st-key-kycrow_"] button:hover {
        background: rgba(77, 166, 255, 0.12) !important;
    }
    [class*="st-key-kycrow_"] button p {
        font-size: 13px !important;
        line-height: 1.35 !important;
        margin: 0 !important;
        width: 100% !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [class*="st-key-kycrow_"][class*="_0"] button p {
        white-space: pre-line !important;
        text-align: left !important;
    }
    [class*="st-key-kycrow_"][class*="_1"] button p {
        white-space: nowrap !important;
        text-align: left !important;
    }
    [class*="st-key-kycrow_"][class*="_2"] button p,
    [class*="st-key-kycrow_"][class*="_3"] button p,
    [class*="st-key-kycrow_"][class*="_4"] button p,
    [class*="st-key-kycrow_"][class*="_5"] button p {
        white-space: nowrap !important;
        text-align: center !important;
    }
    [class*="st-key-kycrow_"] button svg,
    [class*="st-key-kycrow_"] button [data-testid="stIconMaterial"] {
        display: none !important;
    }
    .kyc-kpi-card {
        text-align: center;
        width: 100%;
        padding: 12px 6px;
        min-height: 92px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
    }
    .kyc-kpi-label {
        font-size: 10px;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 6px;
        min-height: 28px;
        line-height: 1.2;
        width: 100%;
        text-align: center;
    }
    .kyc-kpi-value {
        font-size: 28px;
        font-weight: 700;
        line-height: 1;
        width: 100%;
        text-align: center !important;
    }
    [class*="st-key-banner_refresh"] button {
        white-space: nowrap !important;
        min-width: 92px !important;
    }
    [class*="st-key-banner_refresh"] button p {
        white-space: nowrap !important;
    }
    .kyc-filter-label {
        font-size: 11px;
        font-weight: 600;
        color: #888;
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _badge(text: str, style: str) -> str:
    return (
        f"<span class='kyc-risk-badge' style='{style}'>{text}</span>"
    )

def _risk_badge(risk: str) -> str:
    styles = {
        "Critical": "background:rgba(244,67,54,0.15);color:#f44336",
        "High":     "background:rgba(251,140,0,0.15);color:#fb8c00",
        "Medium":   "background:rgba(253,216,53,0.15);color:#fdd835",
        "Low":      "background:rgba(100,221,23,0.15);color:#64dd17",
    }
    return _badge(risk, styles.get(risk, "background:#2a2a2a;color:#888"))

def _sanctions_badge(status: str) -> str:
    styles = {
        SANCTIONS_REVIEW_PENDING: ("Pending", "background:rgba(77,166,255,0.15);color:#4da6ff"),
        SANCTIONS_REVIEW_FUZZY: ("Fuzzy", "background:rgba(253,216,53,0.15);color:#fdd835"),
        SANCTIONS_REVIEW_CONFIRMED: ("Confirmed", "background:rgba(244,67,54,0.15);color:#f44336"),
    }
    if status in styles:
        label, style = styles[status]
        return _badge(label, style)
    return f"<span style='color:#555'>—</span>"


def _sanctions_table_label(status: str, list_key: str = "") -> str:
    if status == SANCTIONS_REVIEW_PENDING:
        base = "Pending"
    elif status == SANCTIONS_REVIEW_FUZZY:
        base = "Fuzzy"
    elif status == SANCTIONS_REVIEW_CONFIRMED:
        base = "Confirmed"
    else:
        return "—"
    if list_key:
        short = list_key if len(list_key) <= 18 else f"{list_key[:17]}…"
        return f"{base}\n{short}"
    return base

def _detail_line(label: str, value: str) -> None:
    display = str(value or "").strip() or "—"
    st.markdown(f"**{label}**  \n{display}")


def _open_customer_profile(customer_id: str) -> None:
    st.session_state["kyc_view_customer_id"] = str(customer_id)


def _sanctions_match_queue_item(row: pd.Series) -> dict:
    score_raw = row.get("SanctionsMatchScore", "")
    match_type = str(row.get("SanctionsMatchType", "") or "").strip().lower()
    try:
        score = float(score_raw or 0)
        confidence = score / 100 if score > 1 else score
    except (TypeError, ValueError):
        confidence = 1.0 if match_type == "exact" else 0.0
    if not match_type and str(row.get("SanctionsReview", "")) == SANCTIONS_REVIEW_CONFIRMED:
        match_type = "exact"
    return {
        "customer_id": str(row["id"]),
        "matched_name": str(row.get("SanctionsMatchedName", "")),
        "list_key": str(row.get("SanctionsListKey", "")),
        "confidence": confidence,
        "match_type": match_type or "fuzzy",
    }


def _open_sanctions_review(customer_id: str) -> None:
    row = get_kyc_by_id(customer_id)
    if row is None:
        return
    item = _sanctions_match_queue_item(row)
    rest = [
        q
        for q in st.session_state.get("kyc_fuzzy_sanctions_queue", [])
        if str(q.get("customer_id")) != str(customer_id)
    ]
    st.session_state["kyc_fuzzy_sanctions_queue"] = [item] + rest


def _flagged_sanctions_customers(customers: pd.DataFrame) -> pd.DataFrame:
    flagged = customers[
        customers["SanctionsReview"].astype(str).isin(SANCTIONS_ACTIVE_REVIEW_STATUSES)
    ].copy()
    if flagged.empty:
        return flagged
    _status_rank = {
        SANCTIONS_REVIEW_FUZZY: 0,
        SANCTIONS_REVIEW_PENDING: 1,
        SANCTIONS_REVIEW_ESCALATED: 2,
        SANCTIONS_REVIEW_CONFIRMED: 3,
    }
    flagged["_sanc_sort"] = flagged["SanctionsReview"].astype(str).map(
        lambda s: _status_rank.get(s, 9)
    )
    return flagged.sort_values(["_sanc_sort", "FullName"], kind="stable").drop(
        columns=["_sanc_sort"]
    )


def _catalog_label_for_key(list_key: str, labels: dict[str, str]) -> str:
    key = str(list_key or "").strip()
    if not key:
        return "—"
    return labels.get(key, key)


KYC_TABLE_COL_WEIGHTS = [3.2, 2.0, 0.85, 1.05, 1.05, 0.9]
FLAGS_TABLE_COL_WEIGHTS = [2.6, 1.4, 0.95, 2.0, 1.6, 0.65, 0.75]


def _render_kyc_table_row(row: pd.Series) -> None:
    """One clickable table row — columns match the header grid."""
    _cid = str(row["id"])
    _name = str(row.get("FullName", ""))
    _acct = str(row.get("AccountNo", ""))
    _ctype = "Corp" if str(row.get("customer_type", "")) == CUSTOMER_TYPE_CORPORATE else "Ind"
    _risk = str(row.get("RiskStatus", "Low"))
    _cdd = str(row.get("CDDLevel", "—")) or "—"
    _sanc = str(row.get("SanctionsReview", ""))
    _sanc_key = str(row.get("SanctionsListKey", "")).strip()
    _sanc_d = _sanctions_table_label(_sanc, _sanc_key)

    _cells = [
        f"{_name}\n{_cid}",
        _acct,
        _ctype,
        _risk,
        _cdd,
        _sanc_d,
    ]
    _cols = st.columns(KYC_TABLE_COL_WEIGHTS, gap="small")
    for _i, (_col, _label) in enumerate(zip(_cols, _cells)):
        with _col:
            st.button(
                _label,
                key=f"kycrow_{_cid}_{_i}",
                use_container_width=True,
                type="secondary",
                on_click=_open_customer_profile,
                args=(_cid,),
            )


def _complete_enrolment(pending: dict) -> None:
    if pending.get("sanctions_match") and not pending.get("sanctions_rejected"):
        pending["sanctions_confirmed"] = True
    row, match_info = enrol_customer(
        pending,
        sanctions_match=pending.get("sanctions_match"),
    )
    indicators = pending.get("risk_indicators", [])
    flag_reason = pending.get("flag_reason", "") or "; ".join(indicators)
    is_pep = "PEP (Politically Exposed Person)" in indicators
    if is_pep:
        set_customer_risk_status(row["id"], RISK_CRITICAL, actor_id, reason=flag_reason, is_pep=True)
    elif indicators:
        set_customer_risk_status(row["id"], RISK_HIGH, actor_id, reason=flag_reason)
    if indicators:
        update_kyc_record(row["id"], {"RiskIndicators": "; ".join(indicators)})
    log_action(
        action="kyc_customer_enrolled",
        details=(
            f"customer_id={row['id']}; account={row['AccountNo']}; "
            f"sanctions_match={match_info.get('matched', False)}; risk_indicators={indicators}"
        ),
        analyst_id=actor_id, module="kyc_screening",
        event_type="kyc_customer_enrolled", entity_type="customer",
        entity_id=row["id"], actor_role=actor_role,
        payload={
            "id": row["id"], "FullName": row["FullName"], "AccountNo": row["AccountNo"],
            "sanctions_match": match_info,
            "sanctions_warning_acknowledged": pending.get("sanctions_warning_acknowledged", False),
            "risk_indicators": indicators,
        },
    )
    st.session_state.pop("kyc_pending_enrol", None)
    msg = f"Customer **{row['FullName']}** enrolled (ID: `{row['id']}`)."
    if match_info.get("matched") and not pending.get("sanctions_rejected"):
        if match_info.get("match_type") == "fuzzy":
            msg += " Fuzzy sanctions match flagged — **Enhanced CDD** applied after confirmation."
        else:
            msg += " Sanctions list match **confirmed** — **Enhanced CDD** applied."
    if is_pep:
        msg += " Risk set to **Critical** (PEP) — pending SM approval."
    elif indicators:
        msg += f" Risk set to **High** ({', '.join(indicators)})."
    st.session_state["kyc_enrol_success"] = msg
    st.session_state["kyc_enrolled_id"] = row["id"]


@st.dialog("Enrol New Customer", width="large")
def _enrol_dialog() -> None:
    st.caption("Customer Identification Program (CIP) — all required fields are screened against sanctions lists.")

    _pending = st.session_state.get("kyc_pending_enrol")
    if _pending and _pending.get("sanctions_match"):
        _match = _pending["sanctions_match"]
        _list_key = _match.get("list_key") or "MAS Targeted Financial Sanctions list"
        _confidence = float(_match.get("confidence", 0) or 0) * 100
        _is_fuzzy = _match.get("match_type") == "fuzzy"

        if _is_fuzzy:
            st.warning(
                f"**Possible sanctions match** on **{_list_key}** "
                f"({_confidence:.0f}% similarity)."
            )
            st.caption("Fuzzy matches require analyst confirmation before sanctions controls are applied.")
        else:
            st.error(
                f"**Exact sanctions list match** on **{_list_key}**."
            )
            st.caption("This customer matches a designated name on the sanctions list.")

        st.markdown(
            f"- **Customer name:** {_pending.get('FullName', '')}  \n"
            f"- **Matched list name:** `{_match.get('matched_name', '')}`  \n"
            f"- **Account:** {_pending.get('AccountNo', '')}"
        )

        if _is_fuzzy:
            _wc1, _wc2, _wc3 = st.columns(3)
            if _wc1.button("Confirm match & enrol", type="primary", use_container_width=True):
                _pending["sanctions_confirmed"] = True
                try:
                    _complete_enrolment(_pending)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if _wc2.button("Enrol — not a match", use_container_width=True):
                _pending.pop("sanctions_match", None)
                _pending["sanctions_rejected"] = True
                try:
                    _complete_enrolment(_pending)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if _wc3.button("Cancel", use_container_width=True):
                st.session_state.pop("kyc_pending_enrol", None)
                st.rerun()
        else:
            _wc1, _wc2 = st.columns(2)
            if _wc1.button("Confirm match & enrol", type="primary", use_container_width=True):
                _pending["sanctions_confirmed"] = True
                try:
                    _complete_enrolment(_pending)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if _wc2.button("Cancel", use_container_width=True):
                st.session_state.pop("kyc_pending_enrol", None)
                st.rerun()
        return

    _ctype = st.radio(
        "Customer type",
        [CUSTOMER_TYPE_INDIVIDUAL, CUSTOMER_TYPE_CORPORATE],
        horizontal=True,
        key="enrol_customer_type",
    )
    _is_corp = _ctype == CUSTOMER_TYPE_CORPORATE

    with st.form("enrol_kyc_form", clear_on_submit=False):
        st.markdown("##### 1. Basic identification (CIP)")
        _c1, _c2 = st.columns(2)
        _full_name = _c1.text_input(
            "Full legal name *" if not _is_corp else "Registered company name *",
            placeholder="As on government ID or ACRA register",
        )
        _aliases = _c2.text_input("Aliases", placeholder="Semicolon-separated alternate names")
        if _is_corp:
            _reg_no = _c1.text_input("Company registration number *", placeholder="e.g. 201912345G")
            _dob = _nationality = _id_type = _id_number = ""
        else:
            _reg_no = ""
            _dob = _c1.text_input("Date of birth *", placeholder="YYYY-MM-DD")
            _nationality = _c2.text_input("Nationality *", placeholder="e.g. Singaporean")
            _id_type = _c1.selectbox("ID type *", ["NRIC", "Passport", "National ID", "Emirates ID", "Other"])
            _id_number = _c2.text_input("Government ID number *", placeholder="NRIC / passport / SSN")

        st.markdown("##### 2. Contact & proof of residence")
        _c3, _c4 = st.columns(2)
        _address = _c3.text_input("Residential / registered address *")
        _email = _c4.text_input("Email address *", placeholder="name@domain.com")
        _contact_no = _c3.text_input("Telephone *", placeholder="+65 9000 0000")
        _account_no = _c4.text_input("Account number *", placeholder="e.g. SG-0041-8812")

        st.markdown("##### 3. Financial profile & employment")
        if _is_corp:
            _employment = _occupation = "N/A"
            _sow = _c3.text_input("Source of wealth", placeholder="Business revenue, investors, etc.")
            _soi = _c4.text_input("Source of income", placeholder="Operating revenue")
        else:
            _employment = _c3.selectbox(
                "Employment status *",
                ["Employed", "Self-employed", "Unemployed", "Retired", "Student"],
            )
            _occupation = _c4.text_input("Occupation *", placeholder="Job title or role")
            _sow = _c3.text_input("Source of wealth *", placeholder="Savings, inheritance, property sale…")
            _soi = _c4.text_input("Source of income *", placeholder="Salary, business profits…")
        _purpose = st.text_input(
            "Purpose of account *",
            placeholder="Personal savings, payroll, trade finance…",
        )

        if _is_corp:
            st.markdown("##### 4. Corporate / business")
            _op_addr = st.text_input("Principal operating address *")
            _ubos = st.text_area(
                "Ultimate beneficial owners (UBOs) *",
                height=68,
                placeholder="Name; nationality; % ownership; role — one per line",
            )
            _corp_docs = st.text_area(
                "Corporate documents on file *",
                height=68,
                placeholder="ACRA BizFile, certificate of incorporation, board resolution…",
            )
        else:
            _op_addr = _ubos = _corp_docs = ""

        st.markdown("##### Risk indicators")
        _risk_indicators = st.multiselect(
            "Risk indicators",
            [
                "PEP (Politically Exposed Person)",
                "High-risk jurisdiction",
                "Adverse media",
                "Complex ownership structure",
                "Cash-intensive business",
                "Non-profit / NGO",
            ],
            help="PEP → Critical; any other indicator → High.",
        )
        _flag_reason = st.text_input("Flagging reason", placeholder="Required if indicator selected")
        _comments = st.text_area("Internal comments", height=60, placeholder="Optional analyst notes")

        _submitted = st.form_submit_button(
            "Submit enrolment", type="primary", use_container_width=True,
            disabled=not _can_enrol,
        )

    if _submitted:
        _errors: list[str] = []
        if not _full_name.strip():
            _errors.append("Full legal name is required.")
        if not _account_no.strip():
            _errors.append("Account number is required.")
        if not _address.strip():
            _errors.append("Address is required.")
        if not _email.strip():
            _errors.append("Email is required.")
        if not _contact_no.strip():
            _errors.append("Telephone is required.")
        if not _purpose.strip():
            _errors.append("Purpose of account is required.")
        if _is_corp:
            if not _reg_no.strip():
                _errors.append("Company registration number is required.")
            if not _op_addr.strip():
                _errors.append("Operating address is required.")
            if not _ubos.strip():
                _errors.append("UBO details are required.")
            if not _corp_docs.strip():
                _errors.append("Corporate documents are required.")
        else:
            if not _dob.strip():
                _errors.append("Date of birth is required.")
            if not _nationality.strip():
                _errors.append("Nationality is required.")
            if not _id_number.strip():
                _errors.append("Government ID number is required.")
            if not _occupation.strip():
                _errors.append("Occupation is required.")
            if not _sow.strip():
                _errors.append("Source of wealth is required.")
            if not _soi.strip():
                _errors.append("Source of income is required.")
        if _errors:
            for _err in _errors:
                st.error(_err)
            return

        _payload: dict = {
            "customer_type": _ctype,
            "FullName": _full_name.strip(),
            "Aliases": _aliases.strip(),
            "DateOfBirth": _dob.strip(),
            "Nationality": _nationality.strip(),
            "NationalIdType": _id_type if not _is_corp else "Registration Number",
            "NationalIdNumber": (_reg_no if _is_corp else _id_number).strip(),
            "Address": _address.strip(),
            "Email": _email.strip(),
            "ContactNo": _contact_no.strip(),
            "AccountNo": _account_no.strip(),
            "EmploymentStatus": _employment,
            "Occupation": _occupation.strip() if not _is_corp else "N/A",
            "SourceOfWealth": _sow.strip(),
            "SourceOfIncome": _soi.strip(),
            "PurposeOfAccount": _purpose.strip(),
            "CompanyRegistrationNo": _reg_no.strip() if _is_corp else "",
            "RegisteredOperatingAddress": _op_addr.strip() if _is_corp else "",
            "UBOs": _ubos.strip() if _is_corp else "",
            "CorporateDocuments": _corp_docs.strip() if _is_corp else "",
            "Comments": _comments.strip(),
            "risk_indicators": _risk_indicators,
            "flag_reason": _flag_reason.strip(),
            "IsPEP": "Yes" if "PEP (Politically Exposed Person)" in _risk_indicators else "No",
        }
        _match_info = screen_name(_full_name)
        if not _match_info.get("matched") and _aliases.strip():
            for _alias in (a.strip() for a in _aliases.split(";") if a.strip()):
                _match_info = screen_name(_alias)
                if _match_info.get("matched"):
                    break
        if _match_info.get("matched"):
            _payload["sanctions_match"] = _match_info
            st.session_state["kyc_pending_enrol"] = _payload
            st.rerun()
        try:
            _complete_enrolment(_payload)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("Customer KYC Profile", width="large")
def _customer_detail_dialog(customer_id: str) -> None:
    row = get_kyc_by_id(customer_id)
    if not row:
        st.error("Customer not found.")
        if st.button("Close"):
            st.rerun()
        return

    _ctype = str(row.get("customer_type", CUSTOMER_TYPE_INDIVIDUAL))
    _is_corp = _ctype == CUSTOMER_TYPE_CORPORATE
    _risk = str(row.get("RiskStatus", "Low"))
    _sanc = str(row.get("SanctionsReview", ""))

    _hdr_l, _hdr_r = st.columns([3, 1])
    with _hdr_l:
        st.markdown(f"### {row.get('FullName', '—')}")
        st.caption(f"Customer ID `{customer_id}` · {_ctype} · Account `{row.get('AccountNo', '—')}`")
    with _hdr_r:
        st.markdown(_risk_badge(_risk), unsafe_allow_html=True)
        if _sanc in {SANCTIONS_REVIEW_PENDING, SANCTIONS_REVIEW_FUZZY, SANCTIONS_REVIEW_CONFIRMED}:
            st.markdown(_sanctions_badge(_sanc), unsafe_allow_html=True)

    if _sanc in {SANCTIONS_REVIEW_FUZZY, SANCTIONS_REVIEW_CONFIRMED, SANCTIONS_REVIEW_PENDING}:
        with st.container(border=True):
            st.markdown("**Sanctions screening**")
            _detail_line("Review status", _sanc)
            _detail_line("Matched list name", row.get("SanctionsMatchedName", ""))
            _detail_line("List", row.get("SanctionsListKey", ""))
            _detail_line("Match score", f"{row.get('SanctionsMatchScore', '')}%")
            if _sanc == SANCTIONS_REVIEW_FUZZY:
                _fc1, _fc2 = st.columns(2)
                if _fc1.button("Confirm sanctions match", key=f"sanc_confirm_{customer_id}", type="primary"):
                    apply_confirmed_sanctions_match(
                        customer_id,
                        {
                            "matched_name": row.get("SanctionsMatchedName", ""),
                            "list_key": row.get("SanctionsListKey", ""),
                            "confidence": float(row.get("SanctionsMatchScore", 0) or 0) / 100,
                            "match_type": "fuzzy",
                        },
                        actor_id=actor_id,
                    )
                    st.rerun()
                if _fc2.button("Clear — not a match", key=f"sanc_clear_{customer_id}"):
                    clear_sanctions_match(customer_id, actor_id=actor_id)
                    st.rerun()

    _t1, _t2 = st.tabs(["KYC file", "Risk management"])

    with _t1:
        with st.container(border=True):
            st.markdown("**1. Basic identification (CIP)**")
            _g1, _g2, _g3 = st.columns(3)
            with _g1:
                _detail_line("Full legal name", row.get("FullName", ""))
                _detail_line("Aliases", row.get("Aliases", ""))
            with _g2:
                if not _is_corp:
                    _detail_line("Date of birth", row.get("DateOfBirth", ""))
                    _detail_line("Nationality", row.get("Nationality", ""))
            with _g3:
                _detail_line("ID type", row.get("NationalIdType", ""))
                _detail_line("Government ID", row.get("NationalIdNumber", ""))

        with st.container(border=True):
            st.markdown("**2. Contact & proof of residence**")
            _c1, _c2 = st.columns(2)
            with _c1:
                _detail_line("Residential / registered address", row.get("Address", ""))
                _detail_line("Telephone", row.get("ContactNo", ""))
            with _c2:
                _detail_line("Email", row.get("Email", ""))

        with st.container(border=True):
            st.markdown("**3. Financial profile & employment**")
            _f1, _f2 = st.columns(2)
            with _f1:
                _detail_line("Employment status", row.get("EmploymentStatus", ""))
                _detail_line("Occupation", row.get("Occupation", ""))
                _detail_line("Source of wealth", row.get("SourceOfWealth", ""))
            with _f2:
                _detail_line("Source of income", row.get("SourceOfIncome", ""))
                _detail_line("Purpose of account", row.get("PurposeOfAccount", ""))

        with st.container(border=True):
            st.markdown("**4. Risk assessment**")
            _r1, _r2, _r3 = st.columns(3)
            with _r1:
                _detail_line("PEP status", row.get("IsPEP", "No") or "No")
                _detail_line("Risk status", _risk)
            with _r2:
                _detail_line("CDD level", row.get("CDDLevel", ""))
                _detail_line("Sanctions review", _sanc or "Clear")
            with _r3:
                _detail_line("Risk indicators", row.get("RiskIndicators", ""))
                _detail_line("SM approval", row.get("SMApprovalStatus", "") or "—")
            _fatf_cat = str(row.get("FATFListCategory", "")).strip()
            if _fatf_cat:
                from utils.fatf_jurisdictions import fatf_category_label

                st.warning(
                    f"**FATF exposure:** {row.get('FATFJurisdiction', '—')} "
                    f"({fatf_category_label(_fatf_cat)})"
                )

        if _is_corp:
            with st.container(border=True):
                st.markdown("**5. Corporate / business**")
                _detail_line("Registration number", row.get("CompanyRegistrationNo", ""))
                _detail_line("Operating address", row.get("RegisteredOperatingAddress", ""))
                _detail_line("Ultimate beneficial owners", row.get("UBOs", ""))
                _detail_line("Documents on file", row.get("CorporateDocuments", ""))

        if str(row.get("Comments", "")).strip():
            with st.container(border=True):
                st.markdown("**Internal comments**")
                st.write(row.get("Comments", ""))

    with _t2:
        _cur_pep = str(row.get("IsPEP", "")).strip().lower() == "yes"
        _cur_sm = str(row.get("SMApprovalStatus", ""))
        if _cur_sm == SM_APPROVAL_PENDING:
            st.warning("Pending MLRO approval.")
        if not _can_risk_edit:
            st.caption(
                f"Risk changes require AML Analyst or Senior Investigator role. "
                f"Current role: {display_role(actor_role)}."
            )

        _rmc1, _rmc2 = st.columns(2)
        _new_risk = _rmc1.selectbox(
            "Risk status",
            CUSTOMER_RISK_STATUSES,
            index=CUSTOMER_RISK_STATUSES.index(_risk) if _risk in CUSTOMER_RISK_STATUSES else 0,
            key=f"detail_risk_{customer_id}",
            disabled=not _can_risk_edit,
        )
        _reason_opts = ["Manual", "PEP", "High-risk jurisdiction", "Complex profile", "Other"]
        _reason = _rmc2.selectbox(
            "Reason", _reason_opts, key=f"detail_reason_{customer_id}",
            disabled=not _can_risk_edit,
        )
        _custom_reason = ""
        if _reason == "Other":
            _custom_reason = st.text_input(
                "Specify reason", key=f"detail_custom_{customer_id}",
                disabled=not _can_risk_edit,
            )
        _is_pep = st.checkbox(
            "Flag as PEP", value=_cur_pep, key=f"detail_pep_{customer_id}",
            disabled=not _can_risk_edit,
        )

        _final_risk = RISK_CRITICAL if _is_pep else _new_risk
        _final_reason = FLAG_REASON_PEP if _is_pep else (_custom_reason.strip() if _reason == "Other" else _reason)
        if _is_pep and _new_risk != RISK_CRITICAL:
            st.info("PEP flag sets risk to Critical.")

        if st.button(
            "Save risk changes", type="primary", key=f"detail_save_{customer_id}",
            disabled=not _can_risk_edit,
        ):
            _aid2, _arole2 = get_current_analyst()
            _updated = set_customer_risk_status(
                customer_id=customer_id,
                new_status=_final_risk,
                actor_id=_aid2,
                reason=_final_reason,
                is_pep=True if _is_pep else (False if not _cur_pep else None),
            )
            if _updated:
                log_action(
                    action="customer_risk_status_changed",
                    details=f"customer_id={customer_id}; new={_final_risk}; pep={_is_pep}",
                    analyst_id=_aid2,
                    module="kyc_screening",
                    event_type="customer_risk_status_changed",
                    entity_type="customer",
                    entity_id=customer_id,
                    actor_role=_arole2,
                    payload={"new_risk": _final_risk, "is_pep": _is_pep, "reason": _final_reason},
                )
                st.rerun()
            st.error("Update failed.")

    if st.button("Close", key=f"detail_close_{customer_id}"):
        st.session_state.pop("kyc_view_customer_id", None)
        st.rerun()


@st.dialog("Sanctions Match — Analyst Review", width="large")
def _fuzzy_sanctions_review_dialog() -> None:
    queue = st.session_state.get("kyc_fuzzy_sanctions_queue") or []
    if not queue:
        return

    item = queue[0]
    customer_id = str(item.get("customer_id", ""))
    row = get_kyc_by_id(customer_id)
    if not row:
        st.session_state["kyc_fuzzy_sanctions_queue"] = queue[1:]
        st.rerun()
        return

    _confidence = float(item.get("confidence", 0) or 0) * 100
    _review_status = str(row.get("SanctionsReview", ""))
    _list_labels = {e.get("key"): e.get("label", e.get("key")) for e in list_catalog_entries()}
    _list_disp = _catalog_label_for_key(str(item.get("list_key", "")), _list_labels)
    if _review_status == SANCTIONS_REVIEW_CONFIRMED:
        st.warning(
            f"Relitigate confirmed sanctions match for **{row.get('FullName', '—')}**."
        )
    elif item.get("match_type") == "exact":
        st.warning(f"Exact sanctions match for **{row.get('FullName', '—')}**.")
    else:
        st.warning(
            f"Possible sanctions match for **{row.get('FullName', '—')}** "
            f"({_confidence:.0f}% similarity)."
        )
    st.markdown(
        f"- **Customer ID:** `{customer_id}`  \n"
        f"- **Account:** `{row.get('AccountNo', '—')}`  \n"
        f"- **Matched list name:** `{item.get('matched_name', '')}`  \n"
        f"- **List:** {_list_disp}"
    )
    st.caption(f"{len(queue)} customer(s) awaiting sanctions confirmation.")
    if not _can_sanctions_action:
        st.caption(
            f"Your role ({display_role(actor_role)}) cannot dispose of sanctions matches. "
            "Confirm and Clear are disabled; you may still defer with Review later."
        )

    _c1, _c2, _c3 = st.columns(3)
    if _c1.button(
        "Confirm sanctions match", type="primary", use_container_width=True, key="fuzzy_confirm",
        disabled=not _can_sanctions_action,
    ):
        apply_confirmed_sanctions_match(customer_id, item, actor_id=actor_id)
        log_action(
            action="sanctions_match_confirmed",
            details=f"customer_id={customer_id}; matched={item.get('matched_name', '')}",
            analyst_id=actor_id,
            module="kyc_screening",
            event_type="sanctions_match_confirmed",
            entity_type="customer",
            entity_id=customer_id,
            actor_role=actor_role,
            payload=item,
        )
        st.session_state["kyc_fuzzy_sanctions_queue"] = queue[1:]
        st.rerun()
    if _c2.button(
        "Not a match — clear flag", use_container_width=True, key="fuzzy_clear",
        disabled=not _can_sanctions_action,
    ):
        clear_sanctions_match(customer_id, actor_id=actor_id)
        log_action(
            action="sanctions_match_cleared",
            details=f"customer_id={customer_id}; cleared fuzzy hit",
            analyst_id=actor_id,
            module="kyc_screening",
            event_type="sanctions_match_cleared",
            entity_type="customer",
            entity_id=customer_id,
            actor_role=actor_role,
            payload=item,
        )
        st.session_state["kyc_fuzzy_sanctions_queue"] = queue[1:]
        st.rerun()
    if _c3.button("Review later", use_container_width=True, key="fuzzy_later"):
        st.session_state["kyc_fuzzy_sanctions_queue"] = queue[1:] + [queue[0]]
        st.rerun()


# ── Sanctions Banner ──────────────────────────────────────────────────────────
_sync = st.session_state.get("mas_sync_result") or get_last_sync() or {}
_sync_status = _sync.get("status", "unknown")
_sync_count  = _sync.get("name_count", 0)
_sync_at     = _sync.get("fetched_at", "—")
_STATUS_META = {
    "ok":           ("#4caf50", "Up to date",  "All sanctions lists synced successfully."),
    "skipped":      ("#4da6ff", "Skipped",     "Lists already up to date — no changes pulled."),
    "partial":      ("#fb8c00", "Partial",     "Some lists synced; others failed. Screening continues against cached names."),
    "needs_upload": ("#fb8c00", "Needs upload","One or more lists require a manual HTML upload — automatic fetch unavailable."),
    "failed":       ("#f44336", "Sync failed", "All list fetches failed. Screening continues against cached names."),
}
_b_color, _b_label, _b_desc = _STATUS_META.get(_sync_status, ("#888", "Unknown", "Sync status could not be determined."))

with st.container(border=True):
    _b1, _b2, _b3, _b4 = st.columns([0.4, 4.8, 1.2, 1.0])
    _b1.markdown(
        f"<div style='width:12px;height:12px;border-radius:50%;background:{_b_color};margin-top:8px'></div>",
        unsafe_allow_html=True,
    )
    _b2.markdown(
        f"**MAS Sanctions Lists** &nbsp;"
        f"<span style='color:#888;font-size:12px'>Last synced: {_sync_at}"
        f" &nbsp;·&nbsp; {_sync_count:,} screened names</span>  \n"
        f"<span style='color:#666;font-size:12px'>{_b_desc}</span>",
        unsafe_allow_html=True,
    )
    _b3.markdown(
        f"<span style='background:rgba(76,175,80,0.12);color:{_b_color};border-radius:20px;"
        f"padding:3px 10px;font-size:12px;font-weight:600'>{_b_label}</span>",
        unsafe_allow_html=True,
    )
    if _b4.button("Refresh", key="banner_refresh", disabled=not _can_ref_data):
        st.session_state["mas_sync_result"] = sync_mas_sanctions(force=True).to_dict()
        st.rerun()


# ── Tabs ──────────────────────────────────────────────────────────────────────
_tab_registry, _tab_flags, _tab_sanctions = st.tabs(
    ["Customer Registry", "Sanctions Flags", "Sanctions Lists"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Customer Registry
# ══════════════════════════════════════════════════════════════════════════════
with _tab_registry:
    customers = get_kyc_customers()

    if not st.session_state.get("kyc_bulk_screen_done"):
        with st.spinner("Screening enrolled customers against sanctions lists…"):
            _rescreen = ensure_kyc_sanctions_screened()
            st.session_state["kyc_bulk_screen_done"] = True
            if _rescreen:
                st.session_state["kyc_rescreen_summary"] = _rescreen
                if _rescreen.get("fuzzy_queue"):
                    st.session_state["kyc_fuzzy_sanctions_queue"] = _rescreen["fuzzy_queue"]
        customers = get_kyc_customers()

    _rescreen_summary = st.session_state.pop("kyc_rescreen_summary", None)
    if _rescreen_summary:
        _parts = []
        if _rescreen_summary.get("exact"):
            _parts.append(f"**{_rescreen_summary['exact']:,}** exact match(es) confirmed with Enhanced CDD")
        if _rescreen_summary.get("fuzzy"):
            _parts.append(f"**{_rescreen_summary['fuzzy']:,}** fuzzy match(es) need analyst review")
        if _parts:
            st.info("Sanctions rescreen complete: " + " · ".join(_parts) + ".")

    _fuzzy_queue = st.session_state.get("kyc_fuzzy_sanctions_queue") or []
    if not _fuzzy_queue:
        _db_fuzzy = customers[
            customers["SanctionsReview"].astype(str) == SANCTIONS_REVIEW_FUZZY
        ]
        if not _db_fuzzy.empty:
            st.session_state["kyc_fuzzy_sanctions_queue"] = [
                _sanctions_match_queue_item(row) for _, row in _db_fuzzy.iterrows()
            ]

    # KPI row
    _m1, _m2, _m3, _m4, _m5, _m6 = st.columns(6)
    _kpi_data = [
        (_m1, "Enrolled",          len(customers),                                                                                   "#4da6ff"),
        (_m2, "Low",               int(customers["RiskStatus"].astype(str).str.lower().eq("low").sum()),                             "#64dd17"),
        (_m3, "Medium",            int(customers["RiskStatus"].astype(str).str.lower().eq("medium").sum()),                          "#fdd835"),
        (_m4, "High",              int(customers["RiskStatus"].astype(str).str.lower().eq("high").sum()),                            "#fb8c00"),
        (_m5, "Critical",          int(customers["RiskStatus"].astype(str).str.lower().eq("critical").sum()),                        "#f44336"),
        (_m6, "Sanc. Flags", int(customers["SanctionsReview"].astype(str).isin(SANCTIONS_ACTIVE_REVIEW_STATUSES).sum()), "#888"),
    ]
    for _mcol, _mlabel, _mval, _mcolor in _kpi_data:
        with _mcol:
            with st.container(border=True):
                st.markdown(
                    f"<div class='kyc-kpi-card'>"
                    f"<div class='kyc-kpi-label'>{_mlabel}</div>"
                    f"<div class='kyc-kpi-value' style='color:{_mcolor}'>{_mval:,}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    _success = st.session_state.pop("kyc_enrol_success", None)
    if _success:
        st.success(_success)
        _enrolled_id = st.session_state.pop("kyc_enrolled_id", None)
        if _enrolled_id and st.button("Complete SCDD for this customer", key="kyc_to_scdd"):
            st.session_state["cdd_customer_id"] = str(_enrolled_id)
            st.session_state["cdd_mode"] = "SCDD"
            st.switch_page("pages/9_CDD_Review.py")

    if "kyc_applied_filters" not in st.session_state:
        st.session_state["kyc_applied_filters"] = {
            "search": "",
            "risk": "All",
            "type": "All",
            "fatf": "All",
            "page_size": KYC_PAGE_SIZE_DEFAULT,
        }
    if "kyc_page" not in st.session_state:
        st.session_state["kyc_page"] = 1

    _applied = st.session_state["kyc_applied_filters"]
    if "kyc_search_input" not in st.session_state:
        st.session_state["kyc_search_input"] = _applied["search"]
    if "kyc_filter_risk_input" not in st.session_state:
        st.session_state["kyc_filter_risk_input"] = _applied["risk"]
    if "kyc_filter_type_input" not in st.session_state:
        st.session_state["kyc_filter_type_input"] = _applied["type"]
    if "kyc_filter_fatf_input" not in st.session_state:
        st.session_state["kyc_filter_fatf_input"] = _applied["fatf"]
    if "kyc_page_size_input" not in st.session_state:
        st.session_state["kyc_page_size_input"] = int(_applied["page_size"])

    _toolbar_l, _toolbar_m, _toolbar_r = st.columns([2, 1, 1])
    with _toolbar_l:
        st.text_input(
            "Search",
            placeholder="Search",
            label_visibility="collapsed",
            key="kyc_search_input",
        )
    with _toolbar_m:
        if st.button(
            "Rescreen sanctions", use_container_width=True,
            disabled=not _can_sanctions_action,
        ):
            with st.spinner("Rescreening all customers…"):
                _manual = force_rescreen_kyc_sanctions()
                st.session_state["kyc_rescreen_summary"] = _manual
                if _manual.get("fuzzy_queue"):
                    st.session_state["kyc_fuzzy_sanctions_queue"] = _manual["fuzzy_queue"]
            st.rerun()
    with _toolbar_r:
        if st.button(
            "+ Enrol new customer", type="primary", use_container_width=True,
            disabled=not _can_enrol,
        ):
            st.session_state.pop("kyc_pending_enrol", None)
            _enrol_dialog()

    _filter_risk, _filter_type, _filter_fatf, _page_size_col, _filter_btn = st.columns([1, 1, 1, 1, 0.7])
    with _filter_risk:
        st.markdown("<div class='kyc-filter-label'>Risk level</div>", unsafe_allow_html=True)
        st.selectbox(
            "Risk level",
            ["All", *CUSTOMER_RISK_STATUSES],
            label_visibility="collapsed",
            key="kyc_filter_risk_input",
        )
    with _filter_type:
        st.markdown("<div class='kyc-filter-label'>Customer type</div>", unsafe_allow_html=True)
        st.selectbox(
            "Customer type",
            ["All", CUSTOMER_TYPE_INDIVIDUAL, CUSTOMER_TYPE_CORPORATE],
            label_visibility="collapsed",
            key="kyc_filter_type_input",
        )
    with _filter_fatf:
        st.markdown("<div class='kyc-filter-label'>FATF list</div>", unsafe_allow_html=True)
        st.selectbox(
            "FATF list",
            ["All", "Any FATF", "Black", "EDD", "Grey"],
            label_visibility="collapsed",
            key="kyc_filter_fatf_input",
        )
    with _page_size_col:
        st.markdown("<div class='kyc-filter-label'>Rows per page</div>", unsafe_allow_html=True)
        st.selectbox(
            "Rows per page",
            [25, 50, 100, 200],
            label_visibility="collapsed",
            key="kyc_page_size_input",
        )
    with _filter_btn:
        st.markdown("<div class='kyc-filter-label'>&nbsp;</div>", unsafe_allow_html=True)
        if st.button("Apply filters", type="primary", use_container_width=True):
            st.session_state["kyc_applied_filters"] = {
                "search": st.session_state.get("kyc_search_input", "").strip(),
                "risk": st.session_state.get("kyc_filter_risk_input", "All"),
                "type": st.session_state.get("kyc_filter_type_input", "All"),
                "fatf": st.session_state.get("kyc_filter_fatf_input", "All"),
                "page_size": int(st.session_state.get("kyc_page_size_input", KYC_PAGE_SIZE_DEFAULT)),
            }
            st.session_state["kyc_page"] = 1
            st.rerun()

    _applied = st.session_state["kyc_applied_filters"]
    _search = _applied["search"]
    _risk_filter = _applied["risk"]
    _type_filter = _applied["type"]
    _fatf_filter = _applied["fatf"]
    _page_size = int(_applied["page_size"])

    with st.container(border=True):
        _th1, _th2 = st.columns([4, 1])
        _th1.markdown("**Customer database**")
        _th2.markdown(
            f"<div style='text-align:right;color:#555;font-size:12px;padding-top:6px'>"
            f"{len(customers):,} enrolled</div>",
            unsafe_allow_html=True,
        )

        _filtered = search_kyc_customers(
            customers,
            _search,
            risk_filter=_risk_filter,
            type_filter=_type_filter,
            fatf_filter=_fatf_filter,
        )
        _page_df, _page_num, _total_pages, _total_matches = paginate_kyc_customers(
            _filtered,
            st.session_state["kyc_page"],
            page_size=_page_size,
        )
        st.session_state["kyc_page"] = _page_num

        _filters_active = (
            _search.strip()
            or _risk_filter != "All"
            or _type_filter != "All"
            or _fatf_filter != "All"
        )
        if _filters_active:
            st.caption(
                f"**{_total_matches:,}** match"
                f"{'es' if _total_matches != 1 else ''}"
                + (f" · page **{_page_num}** of **{_total_pages}**" if _total_pages else "")
            )
        else:
            st.caption(
                f"Showing page **{_page_num}** of **{_total_pages}** "
                f"({min(_page_size, _total_matches):,} of {_total_matches:,} customers)"
            )

        st.caption("Click anywhere on a row to open the full KYC profile.")

        if _total_matches == 0:
            st.info("No customers match your search or filters.")
        else:
            _hdr = st.columns(KYC_TABLE_COL_WEIGHTS, gap="small")
            _header_labels = ["Name / ID", "Account", "Type", "Risk", "CDD", "Sanc."]
            for _i, (_hcol, _htext) in enumerate(zip(_hdr, _header_labels)):
                _align = "center" if _i >= 2 else "flex-start"
                _hcol.markdown(
                    f"<div class='kyc-th kyc-th-{_i}' style='justify-content:{_align}'>"
                    f"{_htext}</div>",
                    unsafe_allow_html=True,
                )

            for _, _row in _page_df.iterrows():
                _render_kyc_table_row(_row)

            _nav1, _nav2, _nav3, _nav4, _nav5 = st.columns([1, 1, 2, 1, 1])
            with _nav1:
                if st.button("⏮ First", disabled=_page_num <= 1, use_container_width=True):
                    st.session_state["kyc_page"] = 1
                    st.rerun()
            with _nav2:
                if st.button("◀ Prev", disabled=_page_num <= 1, use_container_width=True):
                    st.session_state["kyc_page"] = max(1, _page_num - 1)
                    st.rerun()
            with _nav3:
                st.markdown(
                    f"<div style='text-align:center;padding-top:8px;color:#888;font-size:13px'>"
                    f"Page {_page_num} of {_total_pages}</div>",
                    unsafe_allow_html=True,
                )
            with _nav4:
                if st.button("Next ▶", disabled=_page_num >= _total_pages, use_container_width=True):
                    st.session_state["kyc_page"] = min(_total_pages, _page_num + 1)
                    st.rerun()
            with _nav5:
                if st.button("Last ⏭", disabled=_page_num >= _total_pages, use_container_width=True):
                    st.session_state["kyc_page"] = _total_pages
                    st.rerun()

def _catalog_row_status(entry: dict) -> str:
    return str(
        entry.get("status")
        or catalog_entry_status(entry)
        or ("Needs upload" if entry.get("needs_manual_upload") else "Synced")
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Sanctions Flags
# ══════════════════════════════════════════════════════════════════════════════
with _tab_flags:
    _flag_customers = get_kyc_customers()
    _flagged = _flagged_sanctions_customers(_flag_customers)
    _list_labels = {
        e.get("key"): e.get("label", e.get("key")) for e in list_catalog_entries()
    }

    with st.container(border=True):
        st.markdown("**Sanctions flags**")
        st.caption(
            "All customers with an active sanctions hit. "
            "Use **Review** to relitigate any flag in the analyst review dialog."
        )
        if _flagged.empty:
            st.info("No active sanctions flags in the customer database.")
        else:
            _fuzzy_n = int(
                (_flagged["SanctionsReview"].astype(str) == SANCTIONS_REVIEW_FUZZY).sum()
            )
            _confirmed_n = int(
                (_flagged["SanctionsReview"].astype(str) == SANCTIONS_REVIEW_CONFIRMED).sum()
            )
            st.caption(
                f"**{len(_flagged):,}** flagged"
                f" · **{_fuzzy_n:,}** fuzzy review"
                f" · **{_confirmed_n:,}** confirmed"
            )

            _fhdr = st.columns(FLAGS_TABLE_COL_WEIGHTS, gap="small")
            _fheader_labels = [
                "Name / ID",
                "Account",
                "Status",
                "Matched name",
                "List",
                "Score",
                "Review",
            ]
            for _i, (_fhcol, _fhtext) in enumerate(zip(_fhdr, _fheader_labels)):
                _falign = "center" if _i >= 2 else "flex-start"
                _fhcol.markdown(
                    f"<div class='kyc-th kyc-th-{_i}' style='justify-content:{_falign}'>"
                    f"{_fhtext}</div>",
                    unsafe_allow_html=True,
                )

            for _, _frow in _flagged.iterrows():
                _fcid = str(_frow["id"])
                _fname = str(_frow.get("FullName", ""))
                _facct = str(_frow.get("AccountNo", ""))
                _fstatus = str(_frow.get("SanctionsReview", ""))
                _fmatched = str(_frow.get("SanctionsMatchedName", "")) or "—"
                _flist = _catalog_label_for_key(
                    str(_frow.get("SanctionsListKey", "")), _list_labels
                )
                _fscore_raw = _frow.get("SanctionsMatchScore", "")
                _fmatch_type = str(_frow.get("SanctionsMatchType", "") or "").lower()
                if _fmatch_type == "exact" or _fstatus == SANCTIONS_REVIEW_CONFIRMED:
                    _fscore = "Exact"
                else:
                    try:
                        _fs = float(_fscore_raw or 0)
                        _fscore = f"{_fs:.0f}%" if _fs > 1 else f"{_fs * 100:.0f}%"
                    except (TypeError, ValueError):
                        _fscore = "—"

                if _fstatus == SANCTIONS_REVIEW_FUZZY:
                    _fstatus_d = "Fuzzy"
                elif _fstatus == SANCTIONS_REVIEW_CONFIRMED:
                    _fstatus_d = "Confirmed"
                elif _fstatus == SANCTIONS_REVIEW_PENDING:
                    _fstatus_d = "Pending"
                else:
                    _fstatus_d = _fstatus or "—"

                _fcols = st.columns(FLAGS_TABLE_COL_WEIGHTS, gap="small")
                _fcells = [
                    f"{_fname}\n{_fcid}",
                    _facct,
                    _fstatus_d,
                    _fmatched,
                    _flist,
                    _fscore,
                ]
                for _fi, (_fcol, _ftext) in enumerate(zip(_fcols[:-1], _fcells)):
                    _falign = "center" if _fi >= 2 else "flex-start"
                    _fcol.markdown(
                        f"<div class='kyc-td' style='justify-content:{_falign}'>"
                        f"{_ftext}</div>",
                        unsafe_allow_html=True,
                    )
                with _fcols[-1]:
                    st.button(
                        "Review",
                        key=f"flag_review_{_fcid}",
                        use_container_width=True,
                        on_click=_open_sanctions_review,
                        args=(_fcid,),
                        disabled=not _can_sanctions_action,
                    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Sanctions Lists
# ══════════════════════════════════════════════════════════════════════════════
with _tab_sanctions:
    _catalog      = list_catalog_entries()
    _needs_upload = [e for e in _catalog if _catalog_row_status(e) == "Needs upload"]

    _sc_left, _sc_right = st.columns(2, gap="medium")

    with _sc_left:
        with st.container(border=True):
            st.markdown("**MAS Sanctions Catalog**")
            st.caption(
                f"Source: [{MAS_INDEX_URL}]({MAS_INDEX_URL})  \n"
                "Lists marked 'Needs upload' require manual HTML download from source."
            )
            if _needs_upload:
                st.warning(f"{len(_needs_upload)} list(s) need manual upload.")
            if _catalog:
                _catalog_view = [
                    {
                        "List":         e["label"] or e["key"],
                        "Category":     e["category"],
                        "Names":        e["name_count"],
                        "Last Updated": e["last_updated"],
                        "Status":       _catalog_row_status(e),
                    }
                    for e in _catalog
                ]
                st.dataframe(_catalog_view, use_container_width=True, hide_index=True)
            else:
                st.info("No catalog entries available.")

    with _sc_right:
        with st.container(border=True):
            st.markdown("**Manual Upload**")
            st.caption(
                "Upload HTML exports from MAS/UN, or plain text / CSV name lists (one name per line). "
                "Names are parsed, saved, merged into the consolidated list, and customers are rescreened."
            )
            if not _can_ref_data:
                st.info(
                    f"Reference-data uploads are restricted to System Administrator. "
                    f"Current role: {display_role(actor_role)}."
                )
            _uploaded_html = st.file_uploader(
                "Name list file(s)",
                type=["html", "htm", "txt", "csv", "tsv"],
                accept_multiple_files=True,
                key="mas_manual_upload",
                disabled=not _can_ref_data,
            )
            _existing_keys  = [e["key"] for e in _catalog]
            _target_options = ["Auto from filename", "New custom list", *_existing_keys]
            _target = st.selectbox(
                "Assign to catalog entry", _target_options,
                disabled=not _can_ref_data,
            )

            _custom_key = _custom_label = _custom_category = _custom_lu = ""
            if _target == "New custom list":
                _custom_label    = st.text_input("List label",    placeholder="e.g. UN 1737 (Iran) - manual", disabled=not _can_ref_data)
                _custom_key      = st.text_input("List key",      placeholder="e.g. un-1737-list", disabled=not _can_ref_data)
                _custom_category = st.text_input("Category",      placeholder="e.g. Iran", disabled=not _can_ref_data)
                _custom_lu       = st.text_input("Last Updated",  placeholder="e.g. 27 Sep 2025", disabled=not _can_ref_data)

            if _uploaded_html and st.button(
                "Import Files", type="primary", use_container_width=True,
                disabled=not _can_ref_data,
            ):
                _aid4, _arole4 = get_current_analyst()
                _results, _errors = [], []
                _rescreen_exact = 0
                _rescreen_fuzzy = 0
                _fuzzy_queue: list[dict] = []
                for _upl in _uploaded_html:
                    try:
                        _raw_html = _upl.read().decode("utf-8", errors="replace")
                    except Exception as exc:
                        _errors.append(f"{_upl.name}: decode failed ({exc})")
                        continue
                    if _target == "Auto from filename":
                        _kh = Path(_upl.name).stem
                        _lh, _ch, _luh = _kh.replace("-", " ").title(), "", ""
                    elif _target == "New custom list":
                        _kh  = _custom_key or Path(_upl.name).stem
                        _lh, _ch, _luh = _custom_label, _custom_category, _custom_lu
                    else:
                        _kh = _target
                        _me = next((e for e in _catalog if e["key"] == _target), {})
                        _lh, _ch, _luh = _me.get("label", ""), _me.get("category", ""), _me.get("last_updated", "")
                    _result = import_uploaded_list(
                        html=_raw_html,
                        key=_kh,
                        label=_lh,
                        category=_ch,
                        last_updated=_luh,
                        filename=_upl.name,
                    )
                    _results.append({"filename": _upl.name, **_result})
                    _rescreen = _result.get("rescreen") or {}
                    _rescreen_exact += int(_rescreen.get("exact", 0))
                    _rescreen_fuzzy += int(_rescreen.get("fuzzy", 0))
                    _fuzzy_queue.extend(_rescreen.get("fuzzy_queue", []))
                    log_action(
                        action="mas_list_manual_upload",
                        details=f"key={_result['key']}; file={_upl.name}; name_count={_result['name_count']}",
                        analyst_id=_aid4, module="kyc_screening",
                        event_type="mas_list_manual_upload", entity_type="sanctions_list",
                        entity_id=_result["key"], actor_role=_arole4,
                        payload={
                            "filename": _upl.name,
                            "name_count": _result["name_count"],
                            "total_names": _result["total_names"],
                            "label": _lh, "category": _ch,
                            "rescreen_exact": _rescreen.get("exact", 0),
                            "rescreen_fuzzy": _rescreen.get("fuzzy", 0),
                        },
                    )
                for _r in _results:
                    st.success(
                        f"Imported `{_r['filename']}` → `{_r['key']}` "
                        f"({_r['name_count']} names; total: {_r['total_names']:,})"
                    )
                for _err in _errors:
                    st.error(_err)
                if _results:
                    if _rescreen_exact or _rescreen_fuzzy:
                        _parts = []
                        if _rescreen_exact:
                            _parts.append(f"**{_rescreen_exact:,}** exact match(es) confirmed")
                        if _rescreen_fuzzy:
                            _parts.append(f"**{_rescreen_fuzzy:,}** fuzzy match(es) queued for review")
                        st.session_state["kyc_rescreen_summary"] = {
                            "exact": _rescreen_exact,
                            "fuzzy": _rescreen_fuzzy,
                        }
                        if _fuzzy_queue:
                            st.session_state["kyc_fuzzy_sanctions_queue"] = _fuzzy_queue
                        st.info("Sanctions rescreen after upload: " + " · ".join(_parts) + ".")
                    st.rerun()


if st.session_state.get("kyc_view_customer_id"):
    _customer_detail_dialog(st.session_state["kyc_view_customer_id"])

if st.session_state.get("kyc_fuzzy_sanctions_queue"):
    _fuzzy_sanctions_review_dialog()
