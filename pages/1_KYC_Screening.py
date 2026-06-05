from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.audit_logger import log_action
from utils.sidebar import render_sidebar
from utils.aml_services import ensure_scored_defaults, sync_customer_profiles
from utils.constants import (
    ALERT_STATUS_NEW,
    CUSTOMER_RISK_STATUSES,
    DATA_PREVIEW_LIMIT,
    FLAG_REASON_PEP,
    SM_APPROVAL_PENDING,
)
from utils.data_store import get_model_registry
from utils.feature_engineering import (
    CATEGORICAL_FEATURES,
    ENGINEERED_FEATURES,
    RED_FLAG_COLS,
    apply_risk_tier,
    SAML_REQUIRED_COLUMNS,
    engineer_features,
    prepare_model_matrix,
    validate_schema,
)
from utils.kyc_store import (
    CUSTOMER_RISK_STATUSES as KYC_RISK_STATUSES,
    CUSTOMER_TYPE_CORPORATE,
    CUSTOMER_TYPE_INDIVIDUAL,
    KYC_PAGE_SIZE_DEFAULT,
    RISK_CRITICAL,
    RISK_HIGH,
    SANCTIONS_REVIEW_PENDING,
    apply_cdd_escalation_from_transactions,
    enrol_customer,
    ensure_kyc_database,
    get_kyc_by_id,
    get_kyc_customers,
    paginate_kyc_customers,
    search_kyc_customers,
    set_customer_risk_status,
    update_kyc_record,
)
from utils.mas_sanctions_sync import (
    MAS_INDEX_URL,
    get_last_sync,
    import_uploaded_list,
    list_catalog_entries,
    screen_name,
    sync_mas_sanctions,
)
from utils.model_loader import load_models
from utils.session_utils import get_current_analyst

render_sidebar()
ensure_kyc_database()
actor_id, actor_role = get_current_analyst()

st.title("KYC & Transaction Scoring")
st.caption("Enrol and manage customers, screen against sanctions lists, upload transaction data, and score AML risk.")

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
    /* Customer list row buttons (keys prefixed kyc_row_) */
    [class*="st-key-kyc_row_"] button {
        width: 100% !important;
        min-height: 52px !important;
        height: auto !important;
        padding: 10px 14px !important;
        margin: 0 0 6px 0 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        background: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 8px !important;
    }
    [class*="st-key-kyc_row_"] button:hover {
        background: rgba(77, 166, 255, 0.14) !important;
        border-color: rgba(77, 166, 255, 0.45) !important;
    }
    [class*="st-key-kyc_row_"] button p {
        text-align: left !important;
        white-space: pre !important;
        font-family: "Source Sans Pro", sans-serif !important;
        font-size: 13px !important;
        line-height: 1.5 !important;
        margin: 0 !important;
        width: 100% !important;
    }
    [class*="st-key-kyc_row_"] button svg,
    [class*="st-key-kyc_row_"] button [data-testid="stIconMaterial"] {
        display: none !important;
    }
    .kyc-col-header {
        font-size: 11px;
        font-weight: 700;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        padding: 0 4px 8px 4px;
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
    if status == SANCTIONS_REVIEW_PENDING:
        return _badge("Pending", "background:rgba(77,166,255,0.15);color:#4da6ff")
    return f"<span style='color:#555'>—</span>"

def _detail_line(label: str, value: str) -> None:
    display = str(value or "").strip() or "—"
    st.markdown(f"**{label}**  \n{display}")


def _open_customer_profile(customer_id: str) -> None:
    st.session_state["kyc_view_customer_id"] = str(customer_id)


KYC_TABLE_COL_WEIGHTS = [3.2, 2.0, 0.85, 1.05, 1.05, 0.9]


def _customer_row_label(row: pd.Series) -> str:
    """Two-line label for a full-width row button (aligned with header columns)."""
    _name = str(row.get("FullName", ""))
    _cid = str(row.get("id", ""))
    _acct = str(row.get("AccountNo", ""))
    _ctype = "Corp" if str(row.get("customer_type", "")) == CUSTOMER_TYPE_CORPORATE else "Ind"
    _risk = str(row.get("RiskStatus", "Low"))
    _cdd = str(row.get("CDDLevel", "—")) or "—"
    _sanc = str(row.get("SanctionsReview", ""))
    _sanc_d = "Pending" if _sanc == SANCTIONS_REVIEW_PENDING else "—"
    return (
        f"{_name}\n"
        f"{_cid:<28}{_acct:<18}{_ctype:^8}{_risk:^10}{_cdd:^12}{_sanc_d:^8}"
    )


def _complete_enrolment(pending: dict) -> None:
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
    if match_info.get("matched"):
        msg += " Sanctions review flagged as **Pending**."
    if is_pep:
        msg += " Risk set to **Critical** (PEP) — pending SM approval."
    elif indicators:
        msg += f" Risk set to **High** ({', '.join(indicators)})."
    st.session_state["kyc_enrol_success"] = msg


@st.dialog("Enrol New Customer", width="large")
def _enrol_dialog() -> None:
    st.caption("Customer Identification Program (CIP) — all required fields are screened against sanctions lists.")

    _pending = st.session_state.get("kyc_pending_enrol")
    if _pending and _pending.get("sanctions_match"):
        _match = _pending["sanctions_match"]
        _list_key = _match.get("list_key") or "MAS Targeted Financial Sanctions list"
        st.warning(
            f"Potential match on **{_list_key}** "
            f"(matched: `{_match.get('matched_name', '')}`). "
            "Additional CDD required before proceeding."
        )
        st.write(f"Pending: **{_pending.get('FullName', '')}** · Account **{_pending.get('AccountNo', '')}**")
        _wc1, _wc2 = st.columns(2)
        if _wc1.button("Register with Pending Review", type="primary", use_container_width=True):
            _pending["sanctions_warning_acknowledged"] = True
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

        _submitted = st.form_submit_button("Submit enrolment", type="primary", use_container_width=True)

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
        if _sanc == SANCTIONS_REVIEW_PENDING:
            st.markdown(_sanctions_badge(_sanc), unsafe_allow_html=True)

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
            st.warning("Pending Senior Management approval.")

        _rmc1, _rmc2 = st.columns(2)
        _new_risk = _rmc1.selectbox(
            "Risk status",
            CUSTOMER_RISK_STATUSES,
            index=CUSTOMER_RISK_STATUSES.index(_risk) if _risk in CUSTOMER_RISK_STATUSES else 0,
            key=f"detail_risk_{customer_id}",
        )
        _reason_opts = ["Manual", "PEP", "High-risk jurisdiction", "Complex profile", "Other"]
        _reason = _rmc2.selectbox("Reason", _reason_opts, key=f"detail_reason_{customer_id}")
        _custom_reason = ""
        if _reason == "Other":
            _custom_reason = st.text_input("Specify reason", key=f"detail_custom_{customer_id}")
        _is_pep = st.checkbox("Flag as PEP", value=_cur_pep, key=f"detail_pep_{customer_id}")

        _final_risk = RISK_CRITICAL if _is_pep else _new_risk
        _final_reason = FLAG_REASON_PEP if _is_pep else (_custom_reason.strip() if _reason == "Other" else _reason)
        if _is_pep and _new_risk != RISK_CRITICAL:
            st.info("PEP flag sets risk to Critical.")

        if st.button("Save risk changes", type="primary", key=f"detail_save_{customer_id}"):
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
    if _b4.button("Refresh", key="banner_refresh"):
        st.session_state["mas_sync_result"] = sync_mas_sanctions(force=True).to_dict()
        st.rerun()


# ── Tabs ──────────────────────────────────────────────────────────────────────
_tab_registry, _tab_scoring, _tab_sanctions = st.tabs(
    ["Customer Registry", "Transaction Scoring", "Sanctions Lists"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Customer Registry
# ══════════════════════════════════════════════════════════════════════════════
with _tab_registry:
    customers = get_kyc_customers()

    # KPI row
    _m1, _m2, _m3, _m4, _m5, _m6 = st.columns(6)
    _kpi_data = [
        (_m1, "Enrolled",          len(customers),                                                                                   "#4da6ff"),
        (_m2, "Low",               int(customers["RiskStatus"].astype(str).str.lower().eq("low").sum()),                             "#64dd17"),
        (_m3, "Medium",            int(customers["RiskStatus"].astype(str).str.lower().eq("medium").sum()),                          "#fdd835"),
        (_m4, "High",              int(customers["RiskStatus"].astype(str).str.lower().eq("high").sum()),                            "#fb8c00"),
        (_m5, "Critical",          int(customers["RiskStatus"].astype(str).str.lower().eq("critical").sum()),                        "#f44336"),
        (_m6, "Sanc. Pending", int(customers["SanctionsReview"].astype(str).eq(SANCTIONS_REVIEW_PENDING).sum()), "#888"),
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

    _toolbar_l, _toolbar_r = st.columns([2, 1])
    with _toolbar_l:
        st.text_input(
            "Search",
            placeholder="Search",
            label_visibility="collapsed",
            key="kyc_search_input",
        )
    with _toolbar_r:
        if st.button("+ Enrol new customer", type="primary", use_container_width=True):
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
            _hdr = st.columns(KYC_TABLE_COL_WEIGHTS)
            for _hcol, _htext in zip(
                _hdr,
                ["Name / ID", "Account", "Type", "Risk", "CDD", "Sanc."],
            ):
                _hcol.markdown(f"<div class='kyc-col-header'>{_htext}</div>", unsafe_allow_html=True)

            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            for _, _row in _page_df.iterrows():
                _cid = str(_row["id"])
                st.button(
                    _customer_row_label(_row),
                    key=f"kyc_row_{_cid}",
                    use_container_width=True,
                    type="secondary",
                    on_click=_open_customer_profile,
                    args=(_cid,),
                )

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

    if st.session_state.get("kyc_view_customer_id"):
        _customer_detail_dialog(st.session_state["kyc_view_customer_id"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Transaction Scoring
# ══════════════════════════════════════════════════════════════════════════════
with _tab_scoring:
    _col_upload, _col_results = st.columns(2, gap="medium")

    with _col_upload:
        with st.container(border=True):
            st.markdown("**Upload Transaction Dataset**")
            st.caption("SAML-D format CSV. Schema is validated before scoring begins.")
            _uploaded = st.file_uploader("", type=["csv"], label_visibility="collapsed")
            with st.expander("Expected CSV columns"):
                st.code(", ".join(SAML_REQUIRED_COLUMNS))

            st.divider()

            st.markdown("**Scoring Options**")
            _oc1, _oc2 = st.columns(2)
            _cap_rows  = _oc1.number_input("Row cap", min_value=1000, max_value=200_000, value=50_000, step=1000)
            _threshold = _oc2.slider("Risk threshold", min_value=0.05, max_value=0.95, value=0.50, step=0.05)
            _score_btn = st.button(
                "Score Dataset", type="primary", use_container_width=True,
                disabled=_uploaded is None,
            )

    with _col_results:
        with st.container(border=True, height=420):
            st.markdown("**Scoring Results**")

            # Process on button click
            if _score_btn and _uploaded is not None:
                _t0  = time.time()
                _raw = pd.read_csv(_uploaded)
                _ok, _missing = validate_schema(_raw)
                if not _ok:
                    st.error(f"Schema mismatch. Missing columns: {_missing}")
                    st.stop()
                if len(_raw) > _cap_rows:
                    _raw = _raw.head(int(_cap_rows)).copy()
                    st.warning(f"Dataset capped to {_cap_rows:,} rows.")
                _feat = engineer_features(_raw)
                _rf_model, _, _ = load_models()
                _x_rf = prepare_model_matrix(
                    _feat[ENGINEERED_FEATURES + CATEGORICAL_FEATURES],
                    _rf_model.feature_names_in_,
                )
                _risk_prob = (
                    _rf_model.predict_proba(_x_rf)[:, 1]
                    if hasattr(_rf_model, "predict_proba")
                    else _rf_model.predict(_x_rf).astype(float)
                )
                _pred = (_risk_prob >= _threshold).astype(int)
                _feat["rf_prediction"]            = _pred
                _feat["risk_score"]               = _risk_prob
                _feat["risk_threshold"]           = _threshold
                _feat = apply_risk_tier(_feat)
                _feat["prediction_wrong"]         = ""
                _feat["prediction_feedback_reason"] = ""
                _feat = ensure_scored_defaults(_feat)
                _aid3, _arole3 = get_current_analyst()
                _statuses = {
                    _txid: {"status": ALERT_STATUS_NEW, "reason": ""}
                    for _txid in _feat["transaction_id"].astype(str)
                }
                st.session_state["scored_df"]    = _feat
                st.session_state["alert_status"] = _statuses
                _customer_profiles = sync_customer_profiles(_feat)
                _cdd_changes       = apply_cdd_escalation_from_transactions(_feat)
                _elapsed           = time.time() - _t0
                _registry          = get_model_registry().get("models", [])
                _cur_model         = _registry[-1] if _registry else {}
                st.session_state["_scoring_meta"] = {
                    "elapsed":      _elapsed,
                    "profiles":     len(_customer_profiles),
                    "cdd_changes":  _cdd_changes,
                    "filename":     _uploaded.name,
                    "flagged":      int((_feat["rf_prediction"] == 1).sum()),
                    "tier_counts":  _feat["risk_tier"].value_counts().to_dict(),
                    "threshold":    _threshold,
                    "model_label":  f"{_cur_model.get('model_id', 'rf_model')} {_cur_model.get('version', '')}".strip(),
                }
                log_action(
                    action="dataset_uploaded",
                    details=f"filename={_uploaded.name}; row_count={len(_feat)}; flagged={int((_feat['rf_prediction']==1).sum())}",
                    analyst_id=_aid3, module="data_upload",
                    event_type="dataset_uploaded", entity_type="dataset",
                    entity_id=_uploaded.name, actor_role=_arole3,
                    payload={
                        "filename": _uploaded.name, "row_count": len(_feat),
                        "flagged_count": int((_feat["rf_prediction"] == 1).sum()),
                        "tiers": _feat["risk_tier"].value_counts().to_dict(), "threshold": _threshold,
                    },
                )
                for _, _txrow in _feat.iterrows():
                    log_action(
                        action="prediction_generated",
                        transaction_id=str(_txrow["transaction_id"]),
                        details=f"risk_score={float(_txrow['risk_score']):.4f}; risk_tier={_txrow['risk_tier']}",
                        analyst_id=_aid3, module="risk_scoring",
                        event_type="prediction_generated", entity_type="transaction",
                        entity_id=str(_txrow["transaction_id"]), actor_role=_arole3,
                        payload={
                            "risk_score": round(float(_txrow["risk_score"]), 4),
                            "risk_tier": _txrow["risk_tier"], "threshold": _threshold,
                            "prediction": int(_txrow["rf_prediction"]),
                        },
                    )

            # Display results
            _feat_display = st.session_state.get("scored_df")
            _meta         = st.session_state.get("_scoring_meta", {})

            if _feat_display is None and _uploaded is None:
                st.markdown(
                    "<div style='text-align:center;padding:48px 0;color:#444'>"
                    "<div style='font-size:32px;margin-bottom:8px'>📂</div>"
                    "<div>Upload a CSV to see results</div></div>",
                    unsafe_allow_html=True,
                )
            elif _feat_display is None and _uploaded is not None:
                st.info("File ready. Configure options and click **Score Dataset**.")
            else:
                _model_label = _meta.get("model_label", "rf_model")
                st.caption(
                    f"Processed in {_meta.get('elapsed', 0):.2f}s"
                    f" &nbsp;·&nbsp; Model: {_model_label}"
                    f" &nbsp;·&nbsp; Threshold: {_meta.get('threshold', _threshold)}"
                )
                st.caption(
                    "MAS red-flag features active: "
                    + ", ".join(RED_FLAG_COLS)
                )

                # Summary metrics
                _sm1, _sm2, _sm3, _sm4 = st.columns(4)
                with _sm1:
                    with st.container(border=True):
                        st.metric("Transactions Scored", f"{len(_feat_display):,}")
                with _sm2:
                    with st.container(border=True):
                        st.metric("Flagged",             f"{_meta.get('flagged', 0):,}")
                with _sm3:
                    with st.container(border=True):
                        st.metric("Profiles Synced",     f"{_meta.get('profiles', 0):,}")
                with _sm4:
                    with st.container(border=True):
                        st.metric("Processing Time",     f"{_meta.get('elapsed', 0):.2f}s")

                # Risk tier bars
                st.markdown("**Risk Tier Breakdown**")
                _tier_counts = _meta.get("tier_counts", _feat_display["risk_tier"].value_counts().to_dict())
                _max_count   = max(_tier_counts.values(), default=1) or 1
                _tier_colors = {"High": "#f44336", "Medium": "#fb8c00", "Low": "#64dd17"}
                _bars_html   = ""
                for _tier, _color in _tier_colors.items():
                    _cnt = _tier_counts.get(_tier, 0)
                    _pct = int(_cnt / _max_count * 100)
                    _bars_html += (
                        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>"
                        f"<span style='color:#888;font-size:12px;width:60px;text-align:right'>{_tier}</span>"
                        f"<div style='flex:1;background:#1e2130;border-radius:4px;height:12px'>"
                        f"<div style='width:{_pct}%;background:{_color};height:100%;border-radius:4px'></div>"
                        f"</div>"
                        f"<span style='color:{_color};font-weight:700;font-size:13px;width:40px'>{_cnt:,}</span>"
                        f"</div>"
                    )
                st.markdown(_bars_html, unsafe_allow_html=True)

                # KYC auto-escalations
                _cdd_ch = _meta.get("cdd_changes", [])
                if _cdd_ch:
                    _lines = "".join(
                        f"· <code>{c['id']}</code> {c['FullName']}: Risk {c['old_risk']} → "
                        f"<strong style='color:#fb8c00'>{c['new_risk']}</strong>, "
                        f"CDD {c['old_cdd']} → <strong style='color:#fb8c00'>{c['new_cdd']}</strong><br>"
                        for c in _cdd_ch
                    )
                    st.markdown(
                        f"<div style='border:1px solid #fb8c00;border-left:4px solid #fb8c00;"
                        f"border-radius:8px;padding:12px 16px;background:rgba(251,140,0,0.05);"
                        f"font-size:12.5px;margin:12px 0'>"
                        f"<strong style='color:#fb8c00'>KYC Auto-Escalations ({len(_cdd_ch)})</strong>"
                        f"<p style='margin-top:8px;color:#ccc;line-height:1.8'>{_lines}</p></div>",
                        unsafe_allow_html=True,
                    )

    if _feat_display is not None:
        with st.container(border=True):
            st.markdown("**Transaction Preview**")
            st.dataframe(
                _feat_display[[
                    "transaction_id", "Date", "Sender_account",
                    "Amount", "risk_score", "risk_tier", "rf_prediction",
                ]].head(DATA_PREVIEW_LIMIT),
                use_container_width=True,
                hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Sanctions Lists
# ══════════════════════════════════════════════════════════════════════════════
with _tab_sanctions:
    _catalog      = list_catalog_entries()
    _needs_upload = [e for e in _catalog if e["needs_manual_upload"]]

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
                        "Status":       "Needs upload" if e["needs_manual_upload"] else "Synced",
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
                "Download the HTML page from MAS or UN directly and drop it here. "
                "Names are parsed and merged automatically."
            )
            _uploaded_html = st.file_uploader(
                "HTML file(s)", type=["html", "htm"],
                accept_multiple_files=True, key="mas_manual_upload",
            )
            _existing_keys  = [e["key"] for e in _catalog]
            _target_options = ["Auto from filename", "New custom list", *_existing_keys]
            _target = st.selectbox("Assign to catalog entry", _target_options)

            _custom_key = _custom_label = _custom_category = _custom_lu = ""
            if _target == "New custom list":
                _custom_label    = st.text_input("List label",    placeholder="e.g. UN 1737 (Iran) - manual")
                _custom_key      = st.text_input("List key",      placeholder="e.g. un-1737-list")
                _custom_category = st.text_input("Category",      placeholder="e.g. Iran")
                _custom_lu       = st.text_input("Last Updated",  placeholder="e.g. 27 Sep 2025")

            if _uploaded_html and st.button("Import Files", type="primary", use_container_width=True):
                _aid4, _arole4 = get_current_analyst()
                _results, _errors = [], []
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
                    _result = import_uploaded_list(html=_raw_html, key=_kh, label=_lh, category=_ch, last_updated=_luh)
                    _results.append({"filename": _upl.name, **_result})
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
                    st.rerun()
