from __future__ import annotations

from datetime import date

import streamlit as st

st.set_page_config(layout="wide")

from utils.sidebar import render_sidebar
from utils.aml_services import (
    archive_str_case,
    build_archive_search_view,
    build_str_case_from_record,
    get_all_str_records,
    get_str_subject,
    update_case_record,
    upsert_str_workflow,
)
from utils.audit_logger import log_action
from utils.constants import (
    CASE_STATUS_RESOLVED,
    INSTITUTION_NAME,
    STR_GATE_ROLE_LABEL,
    STR_REASON_CODES,
    STR_STATUS_APPROVED,
    STR_STATUS_ARCHIVED,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
    STR_STATUSES,
)
from utils.data_store import get_str_cases
from utils.session_utils import get_current_analyst
from utils.str_authz import authorize, gate_for_status
from utils.str_builder import build_default_grounds, build_str_document, make_reference_number

render_sidebar()

if "str_log" not in st.session_state:
    st.session_state["str_log"] = []

st.title("STR Generation")
st.caption("Draft, review, and approve Suspicious Transaction Reports with maker–checker controls.")

# ── Constants ─────────────────────────────────────────────────────────────────
_STAGES = [STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2, STR_STATUS_APPROVED]

_STATUS_BADGE = {
    STR_STATUS_DRAFT:    "⚪ Draft",
    STR_STATUS_L1:       "🟡 L1 Review",
    STR_STATUS_L2:       "🟠 L2 Review",
    STR_STATUS_APPROVED: "🔵 Approved",
    STR_STATUS_ARCHIVED: "🟢 Archived",
}

_STATUS_PILL_COLOR = {
    STR_STATUS_DRAFT:    "#888",
    STR_STATUS_L1:       "#fdd835",
    STR_STATUS_L2:       "#fb8c00",
    STR_STATUS_APPROVED: "#4da6ff",
    STR_STATUS_ARCHIVED: "#4caf50",
}

_TIER_COLOR = {"Critical": "#f44336", "High": "#fb8c00", "Medium": "#fdd835", "Low": "#64dd17"}

_SUBMIT_LABELS = {
    STR_STATUS_DRAFT: "Submit to L1 Review",
    STR_STATUS_L1:    "Approve to L2 Review",
    STR_STATUS_L2:    "Final Approve & Archive",
}

_AUTH_COLORS = {"ok": "#4caf50", "role": "#fb8c00", "sod": "#f44336", "lock": "#888"}
_AUTH_ICON = {"ok": "✓", "role": "⚠", "sod": "⛔", "lock": "🔒"}

_SUBJECT_FIELDS = [
    ("subject_name", "Full Name"),
    ("subject_dob", "Date of Birth"),
    ("subject_nationality", "Nationality"),
    ("subject_id_type", "ID Type"),
    ("subject_id_number", "ID Number"),
    ("subject_address", "Residential Address"),
]


# ── Shared HTML helpers ───────────────────────────────────────────────────────
def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _banner_item(label: str, value: str, color: str = "#e0e0e0") -> str:
    return (
        f"<div style='display:flex;flex-direction:column;gap:2px'>"
        f"<span style='font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.8px'>{label}</span>"
        f"<span style='font-size:14px;font-weight:700;color:{color}'>{value}</span>"
        f"</div>"
    )


def _section_label(text: str, accent: str = "", accent_color: str = "#4da6ff") -> None:
    accent_html = (
        f" <span style='color:{accent_color};font-size:10px;text-transform:none;letter-spacing:0'>{accent}</span>"
        if accent else ""
    )
    st.markdown(
        f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:1px;"
        f"color:#555;font-weight:600;margin:14px 0 10px'>{text}{accent_html}</div>",
        unsafe_allow_html=True,
    )


def _auth_banner(level: str, message: str) -> None:
    color = _AUTH_COLORS.get(level, "#888")
    icon = _AUTH_ICON.get(level, "•")
    st.markdown(
        f"<div style='display:flex;gap:10px;align-items:flex-start;border:1px solid {color};"
        f"background:{_hex_rgba(color, 0.07)};border-radius:8px;padding:11px 14px;margin:4px 0 10px'>"
        f"<span style='font-size:15px'>{icon}</span>"
        f"<span style='font-size:12.5px;color:{color};line-height:1.5'>{message}</span></div>",
        unsafe_allow_html=True,
    )


def _trail_row(badge_label: str, badge_color: str, role_label: str, actor: str,
               decision: str, decision_color: str = "#888", last: bool = False) -> str:
    bg = _hex_rgba(badge_color, 0.15)
    border = "" if last else "border-bottom:1px solid #1e2130;"
    return (
        f"<div style='padding:10px 0;{border}'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px'>"
        f"<span style='font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;"
        f"background:{bg};color:{badge_color}'>{badge_label}</span>"
        f"<span style='font-size:12px;color:#888'>{actor or '—'}</span></div>"
        f"<div style='font-size:10px;color:#555;text-transform:uppercase;letter-spacing:0.5px'>{role_label}</div>"
        f"<div style='font-size:12px;color:{decision_color};margin-top:2px'>{decision}</div>"
        f"</div>"
    )


def _parse_reason_codes(raw: str) -> list[str]:
    return [c.strip() for c in str(raw or "").split(",") if c.strip()]


# ── STR Metrics (always visible above tabs) ───────────────────────────────────
_all_m_top  = get_all_str_records()
_total_top  = len(_all_m_top) if not _all_m_top.empty else 0
_inrev_top  = int(_all_m_top["status"].isin([STR_STATUS_L1, STR_STATUS_L2]).sum()) if not _all_m_top.empty else 0
_approv_top = int(_all_m_top["status"].isin([STR_STATUS_APPROVED, STR_STATUS_ARCHIVED]).sum()) if not _all_m_top.empty else 0
_draft_top  = int(_all_m_top["status"].eq(STR_STATUS_DRAFT).sum()) if not _all_m_top.empty else 0

_actor_id_top, _actor_role_top = get_current_analyst()
st.markdown(
    f"<div style='border:1px solid #1e2130;border-radius:10px;background:#13161f;"
    f"padding:10px 16px;margin-bottom:14px;font-size:12px;color:#888'>"
    f"<span style='text-transform:uppercase;letter-spacing:1px;color:#555;font-size:11px'>Acting as</span>"
    f"&nbsp;&nbsp;<b style='color:#4da6ff'>{_actor_role_top}</b> · {_actor_id_top}</div>",
    unsafe_allow_html=True,
)

_hm1, _hm2, _hm3, _hm4 = st.columns(4)
for _hmcol, _hmlabel, _hmval, _hmcolor in [
    (_hm1, "TOTAL STRS", _total_top,  "#4da6ff"),
    (_hm2, "IN REVIEW",  _inrev_top,  "#fb8c00"),
    (_hm3, "APPROVED",   _approv_top, "#4caf50"),
    (_hm4, "DRAFT",      _draft_top,  "#fdd835"),
]:
    with _hmcol:
        with st.container(border=True):
            st.markdown(
                f"<div style='text-align:center;padding:8px 0'>"
                f"<div style='font-size:11px;color:#666;text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:6px'>{_hmlabel}</div>"
                f"<div style='font-size:36px;font-weight:700;color:{_hmcolor}'>{_hmval}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_workflow, tab_all = st.tabs(["Current Case Workflow", "All STRs"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Current Case Workflow
# ══════════════════════════════════════════════════════════════════════════════
with tab_workflow:
    if "str_case" not in st.session_state or st.session_state["str_case"] is None:
        st.info("No case loaded. Escalate a case from Case Investigation, or open an in-progress STR from the All STRs tab.")
    else:
        str_case = st.session_state["str_case"]
        actor_id, actor_role = get_current_analyst()

        str_cases = get_str_cases()
        existing_str = None
        if not str_cases.empty:
            _match = str_cases[str_cases["case_id"].astype(str) == str(str_case.get("case_id", ""))]
            if not _match.empty:
                existing_str = _match.iloc[0].to_dict()

        # Seed the working record: existing row if present, else the escalated case.
        base = dict(existing_str) if existing_str else dict(str_case)

        # Subject particulars — seed any blank field from the KYC store.
        _subject_seed = get_str_subject(str_case)
        for _k, _v in _subject_seed.items():
            if not base.get(_k):
                base[_k] = _v
        # Drafter identity — captured once, on first creation.
        if not base.get("drafted_by"):
            base["drafted_by"] = actor_id
            base["drafted_role"] = actor_role
        if not base.get("currency"):
            base["currency"] = str(str_case.get("currency", "") or "")

        starting_status = base.get("status", STR_STATUS_DRAFT) or STR_STATUS_DRAFT
        grounds_seed = base.get("grounds") or build_default_grounds(str_case)
        str_record = upsert_str_workflow(base, grounds_seed, starting_status)
        st.session_state["current_str_id"] = str_record["str_id"]
        current_status = str_record["status"]
        _cur_idx = _STAGES.index(current_status) if current_status in _STAGES else 0

        _is_locked = current_status in (STR_STATUS_APPROVED, STR_STATUS_ARCHIVED)
        _action = gate_for_status(current_status)
        if _is_locked:
            _allowed, _auth_level, _auth_msg = False, "lock", "This STR is approved and locked — read-only."
        else:
            _allowed, _auth_level, _auth_msg = authorize(_action, actor_id, actor_role, str_record)

        # ── Workflow stage cards (annotated with the role that owns each gate) ──
        _wf_cols = st.columns(len(_STAGES))
        for _i, (_col, _stage) in enumerate(zip(_wf_cols, _STAGES)):
            _color = _STATUS_PILL_COLOR.get(_stage, "#888")
            _is_current = _i == _cur_idx
            _is_done = _i < _cur_idx
            _border_color = _color if (_is_current or _is_done) else "#2a2a2a"
            _bg = _hex_rgba(_color, 0.08) if (_is_current or _is_done) else "#13161f"
            _label_color = "#fff" if (_is_current or _is_done) else "#555"
            _sub_text = "Saved" if _is_done else ("In Progress" if _is_current else "Pending")
            _sub_color = "#4caf50" if _is_done else (_color if _is_current else "#444")
            _icon_inner = "✅" if _is_done else f"<span style='color:{_color}'>●</span>"
            _role_lbl = STR_GATE_ROLE_LABEL.get(_stage, "Filed")
            _col.markdown(
                f"<div style='border:2px solid {_border_color};border-radius:10px;background:{_bg};"
                f"padding:16px 12px;text-align:center'>"
                f"<div style='font-size:26px;margin-bottom:6px'>{_icon_inner}</div>"
                f"<div style='font-weight:700;color:{_label_color};font-size:14px'>{_stage}</div>"
                f"<div style='font-size:12px;color:{_sub_color};margin-top:4px'>{_sub_text}</div>"
                f"<div style='font-size:10px;color:#555;margin-top:6px;text-transform:uppercase;"
                f"letter-spacing:0.5px'>{_role_lbl}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Case summary banner ───────────────────────────────────────────────
        _tier = str(str_case.get("risk_tier", "—"))
        _tier_clr = _TIER_COLOR.get(_tier, "#888")
        _customer = str(str_record.get("subject_name") or str_case.get("customer_name") or str_case.get("customer_id") or "—")
        _amount = float(str_case.get("amount", 0) or 0)
        _score = float(str_case.get("risk_score", 0) or 0)
        _div_html = "<div style='width:1px;background:#1e2130;align-self:stretch;'></div>"
        st.markdown(
            f"<div style='border:1px solid #1e2130;border-radius:10px;background:#13161f;"
            f"padding:14px 18px;display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-bottom:16px'>"
            + _banner_item("Case ID", str(str_case.get("case_id", "—")), "#4da6ff") + _div_html
            + _banner_item("Transaction ID", str(str_case.get("transaction_id", "—"))) + _div_html
            + _banner_item("Customer", _customer) + _div_html
            + _banner_item("Amount", f"${_amount:,.0f}", "#f44336") + _div_html
            + _banner_item("Risk Tier", _tier, _tier_clr) + _div_html
            + _banner_item("RF Score", f"{_score:.3f}", "#fb8c00") + _div_html
            + _banner_item("CDD Level", str(str_case.get("cdd_level", "—")))
            + "</div>",
            unsafe_allow_html=True,
        )

        # ── Main layout: Form (left) | Trail (right) ──────────────────────────
        _form_col, _right_col = st.columns([3, 2], gap="medium")

        with _form_col:
            with st.container(border=True):
                _pill_color = _STATUS_PILL_COLOR.get(current_status, "#888")
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                    f"<span style='font-size:15px;font-weight:700'>STR Form</span>"
                    f"<span style='display:inline-flex;align-items:center;gap:6px;padding:4px 12px;"
                    f"border-radius:20px;font-size:12px;font-weight:600;"
                    f"background:{_hex_rgba(_pill_color, 0.15)};color:{_pill_color}'>"
                    f"<span style='width:7px;height:7px;border-radius:50%;background:{_pill_color};"
                    f"display:inline-block'></span>{_STATUS_BADGE.get(current_status, current_status)}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.divider()

                # ── Authorization / SoD banner ────────────────────────────────
                _auth_banner(_auth_level, _auth_msg)

                # ── Subject Particulars (editable, pre-filled from KYC) ────────
                _section_label("Subject Particulars", "● pre-filled from KYC", "#4caf50")
                _sp1, _sp2 = st.columns(2)
                subject_name = _sp1.text_input("Full Name", value=str_record.get("subject_name", ""), disabled=_is_locked, key="str_subj_name")
                subject_dob = _sp2.text_input("Date of Birth", value=str_record.get("subject_dob", ""), disabled=_is_locked, key="str_subj_dob")
                _sp3, _sp4 = st.columns(2)
                subject_nationality = _sp3.text_input("Nationality", value=str_record.get("subject_nationality", ""), disabled=_is_locked, key="str_subj_nat")
                subject_id_type = _sp4.text_input("ID Type", value=str_record.get("subject_id_type", ""), disabled=_is_locked, key="str_subj_idtype")
                _sp5, _sp6 = st.columns(2)
                subject_id_number = _sp5.text_input("ID Number", value=str_record.get("subject_id_number", ""), disabled=_is_locked, key="str_subj_idnum")
                _sp6.text_input("Customer ID", value=str(str_case.get("customer_id", "")), disabled=True, key="str_subj_custid")
                subject_address = st.text_input("Residential Address", value=str_record.get("subject_address", ""), disabled=_is_locked, key="str_subj_addr")

                # ── Transaction Details (read-only) ───────────────────────────
                _section_label("Transaction Details")
                _td1, _td2 = st.columns(2)
                _td1.text_input("Reporting Institution", value=INSTITUTION_NAME, disabled=True, key="str_institution")
                report_date = _td2.date_input("Report Date", value=date.today(), disabled=_is_locked, key="str_report_date")
                _td3, _td4 = st.columns(2)
                _td3.text_input("Transaction Reference", value=str(str_case.get("transaction_id", "")), disabled=True, key="str_txn_ref")
                _td4.text_input("Date of Suspicious Transaction", value=str(str_case.get("date", "")), disabled=True, key="str_txn_date")
                _td5, _td6 = st.columns(2)
                _td5.text_input("Sender Account", value=f"Account {str_case.get('sender_account', '')}", disabled=True, key="str_sender")
                _td6.text_input("Receiver Account", value=f"Account {str_case.get('receiver_account', '')}", disabled=True, key="str_receiver")
                _td7, _td8 = st.columns(2)
                _td7.text_input("Payment Method", value=str(str_case.get("payment_type", "")), disabled=True, key="str_payment")
                _td8.text_input("AI Flagging Summary",
                                value=f"RF score: {float(str_case.get('risk_score', 0) or 0):.3f} — {str_case.get('risk_tier', '')}",
                                disabled=True, key="str_ai_summary")

                # ── Reason Codes (multiselect) ────────────────────────────────
                _section_label("Reason Codes", "● select all that apply")
                reason_codes = st.multiselect(
                    "Reason Codes",
                    options=STR_REASON_CODES,
                    default=[c for c in _parse_reason_codes(str_record.get("reason_codes", "")) if c in STR_REASON_CODES],
                    disabled=_is_locked,
                    label_visibility="collapsed",
                    key="str_reason_codes",
                )

                # ── Grounds for Suspicion (editable) ──────────────────────────
                _section_label("Grounds for Suspicion", "● editable")
                grounds = st.text_area(
                    "Grounds",
                    value=str_record.get("grounds", grounds_seed),
                    height=120, disabled=_is_locked, label_visibility="collapsed", key="str_grounds",
                )

                # ── Filing Details ────────────────────────────────────────────
                _section_label("Filing Details")
                _fd1, _fd2 = st.columns(2)
                _fd1.text_input("Reviewer (you)", value=actor_id, disabled=True, key="str_reviewer")
                _fd2.text_input("Reference Number", value=str(str_record.get("reference_number") or "—"), disabled=True, key="str_ref_num")

                # Collected form field updates (persisted on every save / transition).
                _form_updates = {
                    "subject_name": subject_name, "subject_dob": subject_dob,
                    "subject_nationality": subject_nationality, "subject_id_type": subject_id_type,
                    "subject_id_number": subject_id_number, "subject_address": subject_address,
                    "reason_codes": ", ".join(reason_codes),
                    "currency": str_record.get("currency", ""),
                }

                # ── L2-only: return reason + declaration ──────────────────────
                return_reason = ""
                confirm = False
                if current_status in (STR_STATUS_L1, STR_STATUS_L2) and not _is_locked:
                    return_reason = st.text_input(
                        "Return-to-drafter reason (if returning)",
                        placeholder="Provide a reason for returning this STR to Draft...",
                        key="str_return_reason",
                    )
                if current_status == STR_STATUS_L2 and not _is_locked:
                    confirm = st.checkbox(
                        "I confirm this STR is accurate and complete to the best of my knowledge, "
                        "and I am authorised to file this report.",
                        key="str_confirm",
                    )

                st.divider()

                # ── Action buttons (role + SoD gated) ─────────────────────────
                _submit_label = _SUBMIT_LABELS.get(current_status, "Already Approved")
                if st.button(_submit_label, type="primary", use_container_width=True,
                             disabled=_is_locked or not _allowed, key="str_submit"):
                    if not _allowed:
                        st.error(_auth_msg)
                    elif current_status == STR_STATUS_DRAFT:
                        str_record = upsert_str_workflow(
                            str_record, grounds, STR_STATUS_L1,
                            {**_form_updates,
                             "reference_number": str_record.get("reference_number") or make_reference_number(str_case["transaction_id"])},
                        )
                        log_action(action="str_submitted_l1", transaction_id=str_case["transaction_id"],
                                   details=f"str_id={str_record['str_id']}", analyst_id=actor_id,
                                   module="str_workflow", event_type="str_submitted_l1", entity_type="str",
                                   entity_id=str_record["str_id"], actor_role=actor_role, payload={"status": STR_STATUS_L1})
                        st.success("STR submitted to L1 Review.")
                        st.rerun()
                    elif current_status == STR_STATUS_L1:
                        str_record = upsert_str_workflow(
                            str_record, grounds, STR_STATUS_L2,
                            {**_form_updates, "l1_reviewer": actor_id, "l1_role": actor_role,
                             "l1_reviewed_at": str(report_date), "l1_reason": "Approved by L1"},
                        )
                        log_action(action="str_approved_l1", transaction_id=str_case["transaction_id"],
                                   details=f"str_id={str_record['str_id']}", analyst_id=actor_id,
                                   module="str_workflow", event_type="str_approved_l1", entity_type="str",
                                   entity_id=str_record["str_id"], actor_role=actor_role, payload={"status": STR_STATUS_L2})
                        st.success("STR moved to L2 Review.")
                        st.rerun()
                    elif current_status == STR_STATUS_L2:
                        if not confirm:
                            st.error("Please confirm the analyst declaration before approving.")
                        else:
                            ref_no = str_record.get("reference_number") or make_reference_number(str_case["transaction_id"])
                            str_record = upsert_str_workflow(
                                str_record, grounds, STR_STATUS_APPROVED,
                                {**_form_updates, "reference_number": ref_no, "l2_reviewer": actor_id,
                                 "l2_role": actor_role, "l2_reviewed_at": str(report_date), "l2_reason": "Approved at L2"},
                            )
                            archive_str_case(str_record, actor_id, {
                                "customer_name": str_case.get("customer_name", ""),
                                "subject_name": subject_name,
                                "risk_tier": str_case.get("risk_tier", ""),
                                "report_date": str(report_date),
                                "reference_number": ref_no, "grounds": grounds,
                            })
                            upsert_str_workflow(str_record, grounds, STR_STATUS_ARCHIVED, {**_form_updates, "reference_number": ref_no})
                            # Close the loop: resolve the originating case now that the STR is filed,
                            # so it stops counting as an open case on the dashboard.
                            _case_id = str(str_case.get("case_id", ""))
                            if _case_id:
                                update_case_record(_case_id, {
                                    "status": CASE_STATUS_RESOLVED,
                                    "resolution": f"STR filed — {ref_no}",
                                    "str_required": True,
                                })
                                log_action(action="case_resolved_str_filed", transaction_id=str_case["transaction_id"],
                                           details=f"case_id={_case_id}; reference_number={ref_no}", analyst_id=actor_id,
                                           module="cdd_module", event_type="case_resolved_str_filed", entity_type="case",
                                           entity_id=_case_id, actor_role=actor_role,
                                           payload={"reference_number": ref_no, "status": CASE_STATUS_RESOLVED})
                            st.session_state["str_log"].append({
                                "reference_number": ref_no, "transaction_id": str_case["transaction_id"],
                                "rf_prediction": str_case.get("risk_score", ""), "cdd_level": str_case.get("cdd_level", ""),
                                "filed_by": actor_id, "report_date": str(report_date),
                            })
                            log_action(action="str_archived", transaction_id=str_case["transaction_id"],
                                       details=f"reference_number={ref_no}", analyst_id=actor_id,
                                       module="str_workflow", event_type="str_archived", entity_type="str",
                                       entity_id=str_record["str_id"], actor_role=actor_role,
                                       payload={"reference_number": ref_no, "status": STR_STATUS_ARCHIVED})
                            st.success(f"STR approved and archived. Reference: {ref_no}")
                            st.rerun()

                if not _is_locked:
                    if st.button("Save Draft", use_container_width=True, key="str_save_draft"):
                        upsert_str_workflow(str_record, grounds, current_status, _form_updates)
                        st.success("Draft saved.")
                        st.rerun()

                    if current_status in (STR_STATUS_L1, STR_STATUS_L2):
                        if st.button("Return to Drafter", use_container_width=True, key="str_return"):
                            if not _allowed:
                                st.error(_auth_msg)
                            elif not return_reason.strip():
                                st.error("Provide a return-to-drafter reason in the field above.")
                            else:
                                _rkey = "l2" if current_status == STR_STATUS_L2 else "l1"
                                str_record = upsert_str_workflow(
                                    str_record, grounds, STR_STATUS_DRAFT,
                                    {**_form_updates, f"{_rkey}_reviewer": actor_id, f"{_rkey}_role": actor_role,
                                     f"{_rkey}_reviewed_at": str(report_date), f"{_rkey}_reason": return_reason},
                                )
                                log_action(action="str_returned", transaction_id=str_case["transaction_id"],
                                           details=f"str_id={str_record['str_id']}; reason={return_reason}",
                                           analyst_id=actor_id, module="str_workflow", event_type="str_returned",
                                           entity_type="str", entity_id=str_record["str_id"], actor_role=actor_role,
                                           payload={"reason": return_reason})
                                st.warning("STR returned to Draft.")
                                st.rerun()

        # ─────────────────────────── RIGHT: Maker–Checker Trail + SoD ─────────
        with _right_col:
            with st.container(border=True):
                st.markdown("**Maker–Checker Trail**")
                st.divider()
                _l1_actor = str(str_record.get("l1_reviewer", "") or "")
                _l2_actor = str(str_record.get("l2_reviewer", "") or "")
                st.markdown(
                    _trail_row("Drafted", "#4caf50", "Analyst",
                               str(str_record.get("drafted_by", "") or ""),
                               f"Drafted · {str(str_record.get('created_at', '') or '')[:10]}", "#888")
                    + _trail_row("L1 Review", "#4da6ff", "Compliance Officer", _l1_actor,
                                 (f"{str_record.get('l1_reason', '')} · {str_record.get('l1_reviewed_at', '')}"
                                  if _l1_actor else "Awaiting L1 reviewer"),
                                 "#888" if _l1_actor else "#444")
                    + _trail_row("L2 Review", "#fb8c00", "Senior Management", _l2_actor,
                                 (f"{str_record.get('l2_reason', '')} · {str_record.get('l2_reviewed_at', '')}"
                                  if _l2_actor else "Awaiting L2 reviewer"),
                                 "#888" if _l2_actor else "#444", last=True),
                    unsafe_allow_html=True,
                )

            with st.container(border=True):
                st.markdown("**Segregation of Duties**")
                st.divider()
                st.markdown(
                    f"<div style='font-size:11.5px;color:#777;line-height:1.6'>"
                    f"Each gate must be cleared by a <b style='color:#aaa'>different</b> person:<br>"
                    f"• L1 reviewer ≠ drafter<br>"
                    f"• L2 reviewer ≠ L1 reviewer and ≠ drafter<br><br>"
                    f"Drafter of this STR: <b style='color:#aaa'>{str_record.get('drafted_by', '') or '—'}</b></div>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — All STRs (actionable: open in workflow + per-row download)
# ══════════════════════════════════════════════════════════════════════════════
with tab_all:
    all_strs = get_all_str_records()

    _frow1, _frow2 = st.columns([2, 1])
    _search_term = _frow1.text_input("Search by STR ID / Case ID / Transaction ID", value="", key="tracker_search")
    _status_filter = _frow2.multiselect("Filter by Status", STR_STATUSES, default=STR_STATUSES, key="tracker_status_filter")

    if all_strs.empty:
        st.info("No STRs have been created yet.")
    else:
        _view = all_strs[all_strs["status"].isin(_status_filter)].copy() if _status_filter else all_strs.copy()
        if _search_term.strip():
            _needle = _search_term.strip().lower()
            _view = _view[
                _view["str_id"].astype(str).str.lower().str.contains(_needle)
                | _view["case_id"].astype(str).str.lower().str.contains(_needle)
                | _view["transaction_id"].astype(str).str.lower().str.contains(_needle)
            ]

        if _view.empty:
            st.info("No STRs match the current filters.")
        else:
            # Header row
            _hcols = st.columns([1.3, 1.1, 1.1, 1.1, 1.0, 1.0, 1.0, 1.8])
            for _hc, _ht in zip(_hcols, ["Status", "STR ID", "Case ID", "Txn ID", "Drafter", "L1", "L2", "Action"]):
                _hc.markdown(f"<span style='font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.8px'>{_ht}</span>",
                             unsafe_allow_html=True)
            st.divider()

            for _, _r in _view.iterrows():
                _rec = _r.to_dict()
                _rid = str(_rec.get("str_id", ""))
                _status = str(_rec.get("status", ""))
                _c = st.columns([1.3, 1.1, 1.1, 1.1, 1.0, 1.0, 1.0, 1.8])
                _c[0].markdown(_STATUS_BADGE.get(_status, _status))
                _c[1].write(_rid)
                _c[2].write(str(_rec.get("case_id", "") or "—"))
                _c[3].write(str(_rec.get("transaction_id", "") or "—"))
                _c[4].write(str(_rec.get("drafted_by", "") or "—"))
                _c[5].write(str(_rec.get("l1_reviewer", "") or "—"))
                _c[6].write(str(_rec.get("l2_reviewer", "") or "—"))
                with _c[7]:
                    _a1, _a2 = st.columns(2)
                    if _a1.button("Open →", key=f"open_{_rid}", use_container_width=True):
                        st.session_state["str_case"] = build_str_case_from_record(_rec)
                        st.success(f"{_rid} loaded — switch to the Current Case Workflow tab.")
                    if _status in (STR_STATUS_APPROVED, STR_STATUS_ARCHIVED):
                        _a2.download_button(
                            "⬇ STR",
                            data=build_str_document(_rec),
                            file_name=f"{_rec.get('reference_number') or _rid}.html",
                            mime="text/html",
                            key=f"dl_{_rid}",
                            use_container_width=True,
                        )
                    else:
                        _a2.button("⬇ STR", key=f"dl_disabled_{_rid}", disabled=True,
                                   help="Available once Approved", use_container_width=True)

    # Archived STRs
    st.divider()
    st.subheader("Archived STRs")
    archive_view = build_archive_search_view()
    if archive_view.empty:
        st.info("No archived STR cases yet.")
    else:
        _as1, _as2, _as3 = st.columns(3)
        _cust_search = _as1.text_input("Search by customer", value="", key="arch_cust")
        _risk_search = _as2.selectbox("Risk Tier", ["All"] + sorted(archive_view["risk_tier"].dropna().astype(str).unique().tolist()), key="arch_risk")
        _status_search = _as3.selectbox("STR Status", ["All"] + sorted(archive_view["str_status"].dropna().astype(str).unique().tolist()), key="arch_status")

        _arch_filt = archive_view.copy()
        if _cust_search.strip():
            _arch_filt = _arch_filt[_arch_filt["customer_name"].astype(str).str.contains(_cust_search.strip(), case=False, na=False)]
        if _risk_search != "All":
            _arch_filt = _arch_filt[_arch_filt["risk_tier"].astype(str) == _risk_search]
        if _status_search != "All":
            _arch_filt = _arch_filt[_arch_filt["str_status"].astype(str) == _status_search]

        _arch_cols = [c for c in [
            "archive_id", "str_id", "case_id", "transaction_id",
            "customer_id", "customer_name", "risk_tier", "str_status",
            "archived_at", "archived_by",
        ] if c in _arch_filt.columns]
        st.dataframe(_arch_filt[_arch_cols], use_container_width=True)