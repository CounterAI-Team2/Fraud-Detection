from __future__ import annotations

from datetime import date

import streamlit as st

from utils.sidebar import render_sidebar
from utils.aml_services import archive_str_case, build_archive_search_view, get_all_str_records, upsert_str_workflow
from utils.audit_logger import log_action
from utils.constants import (
    INSTITUTION_NAME,
    STR_STATUS_APPROVED,
    STR_STATUS_ARCHIVED,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
    STR_STATUSES,
)
from utils.data_store import get_str_cases
from utils.session_utils import get_current_analyst
from utils.str_builder import build_default_grounds, make_reference_number

render_sidebar()

if "str_log" not in st.session_state:
    st.session_state["str_log"] = []

st.title("STR Generation")
st.caption("Draft, review, and approve Suspicious Transaction Reports through the L1/L2 workflow.")

# ── Constants ─────────────────────────────────────────────────────────────────
_STAGES = [STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2, STR_STATUS_APPROVED]

_STAGE_META = {
    STR_STATUS_DRAFT:    ("#4caf50", "●", "Saved"),
    STR_STATUS_L1:       ("#4da6ff", "●", "In Progress"),
    STR_STATUS_L2:       ("#fb8c00", "●", "Pending"),
    STR_STATUS_APPROVED: ("#4caf50", "●", "Pending"),
    STR_STATUS_ARCHIVED: ("#888",    "●", "Archived"),
}

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

_TIER_COLOR = {
    "Critical": "#f44336",
    "High":     "#fb8c00",
    "Medium":   "#fdd835",
    "Low":      "#64dd17",
}

_SUBMIT_LABELS = {
    STR_STATUS_DRAFT: "Submit to L1 Review",
    STR_STATUS_L1:    "Approve to L2 Review",
    STR_STATUS_L2:    "Final Approve & Archive",
}


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


def _section_label(text: str, accent: str = "") -> None:
    accent_html = f" <span style='color:#4da6ff;font-size:10px;text-transform:none;letter-spacing:0'>{accent}</span>" if accent else ""
    st.markdown(
        f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:1px;"
        f"color:#555;font-weight:600;margin:14px 0 10px'>{text}{accent_html}</div>",
        unsafe_allow_html=True,
    )


def _review_row_html(badge_label: str, badge_color: str, reviewer: str, reason: str, reviewed_at: str, last: bool = False) -> str:
    reviewer_display = reviewer or "—"
    if not reviewer:
        decision_text  = "Awaiting reviewer"
        decision_color = "#555"
    else:
        decision_text  = f"{reason or '—'} · {reviewed_at or ''}"
        decision_color = "#888"
    bg = _hex_rgba(badge_color, 0.15)
    border = "" if last else "border-bottom:1px solid #1e2130;"
    return (
        f"<div style='padding:10px 0;{border}'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
        f"<span style='font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;"
        f"background:{bg};color:{badge_color}'>{badge_label}</span>"
        f"<span style='font-size:12px;color:#888'>{reviewer_display}</span>"
        f"</div>"
        f"<div style='font-size:12px;color:{decision_color};margin-top:2px'>{decision_text}</div>"
        f"</div>"
    )


# ── STR Metrics (always visible above tabs) ───────────────────────────────────
_all_m_top  = get_all_str_records()
_total_top  = len(_all_m_top) if not _all_m_top.empty else 0
_inrev_top  = int(_all_m_top["status"].isin([STR_STATUS_L1, STR_STATUS_L2]).sum()) if not _all_m_top.empty else 0
_approv_top = int(_all_m_top["status"].isin([STR_STATUS_APPROVED, STR_STATUS_ARCHIVED]).sum()) if not _all_m_top.empty else 0
_draft_top  = int(_all_m_top["status"].eq(STR_STATUS_DRAFT).sum()) if not _all_m_top.empty else 0

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
        st.info("No case loaded. Escalate a case from Case Investigation to begin an STR workflow.")
    else:
        str_case = st.session_state["str_case"]
        actor_id, actor_role = get_current_analyst()

        str_cases = get_str_cases()
        existing_str = None
        if not str_cases.empty:
            _match = str_cases[str_cases["case_id"].astype(str) == str(str_case.get("case_id", ""))]
            if not _match.empty:
                existing_str = _match.iloc[0].to_dict()

        starting_status = existing_str.get("status", STR_STATUS_DRAFT) if existing_str else STR_STATUS_DRAFT
        str_record      = upsert_str_workflow(existing_str or str_case, build_default_grounds(str_case), starting_status)
        st.session_state["current_str_id"] = str_record["str_id"]
        current_status = str_record["status"]
        _cur_idx = _STAGES.index(current_status) if current_status in _STAGES else 0

        # ── Workflow stage cards ──────────────────────────────────────────────
        _wf_cols = st.columns(len(_STAGES))
        for _i, (_col, _stage) in enumerate(zip(_wf_cols, _STAGES)):
            _color, _icon, _sub = _STAGE_META.get(_stage, ("#888", "●", ""))
            _is_current   = _i == _cur_idx
            _is_done      = _i < _cur_idx
            _border_color = _color if (_is_current or _is_done) else "#2a2a2a"
            _bg           = _hex_rgba(_color, 0.08) if (_is_current or _is_done) else "#13161f"
            _label_color  = "#fff" if (_is_current or _is_done) else "#555"
            _sub_text     = "Saved" if _is_done else ("In Progress" if _is_current else "Pending")
            _sub_color    = "#4caf50" if _is_done else (_color if _is_current else "#444")
            _icon_inner   = "✅" if _is_done else f"<span style='color:{_color}'>{_icon}</span>"
            _col.markdown(
                f"<div style='border:2px solid {_border_color};border-radius:10px;background:{_bg};"
                f"padding:16px 12px;text-align:center'>"
                f"<div style='font-size:28px;margin-bottom:6px'>{_icon_inner}</div>"
                f"<div style='font-weight:700;color:{_label_color};font-size:14px'>{_stage}</div>"
                f"<div style='font-size:12px;color:{_sub_color};margin-top:4px'>{_sub_text}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Case summary banner ───────────────────────────────────────────────
        _tier     = str(str_case.get("risk_tier", "—"))
        _tier_clr = _TIER_COLOR.get(_tier, "#888")
        _customer = str(str_case.get("customer_name") or str_case.get("customer_id") or "—")
        _amount   = float(str_case.get("amount", 0))
        _score    = float(str_case.get("risk_score", 0))
        _div_html = "<div style='width:1px;background:#1e2130;align-self:stretch;'></div>"

        st.markdown(
            f"<div style='border:1px solid #1e2130;border-radius:10px;background:#13161f;"
            f"padding:14px 18px;display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-bottom:16px'>"
            + _banner_item("Case ID", str(str_case.get("case_id", "—")), "#4da6ff")
            + _div_html
            + _banner_item("Transaction ID", str(str_case.get("transaction_id", "—")))
            + _div_html
            + _banner_item("Customer", _customer)
            + _div_html
            + _banner_item("Amount", f"${_amount:,.0f}", "#f44336")
            + _div_html
            + _banner_item("Risk Tier", _tier, _tier_clr)
            + _div_html
            + _banner_item("RF Score", f"{_score:.3f}", "#fb8c00")
            + _div_html
            + _banner_item("CDD Level", str(str_case.get("cdd_level", "—")))
            + "</div>",
            unsafe_allow_html=True,
        )

        # ── Main layout: Form (left) | Metrics + History (right) ─────────────
        _form_col, _right_col = st.columns([3, 2], gap="medium")

        # ─────────────────────────────── LEFT: STR Form ──────────────────────
        with _form_col:
            with st.container(border=True):
                # Header: title + status pill
                _pill_color = _STATUS_PILL_COLOR.get(current_status, "#888")
                _pill_label = _STATUS_BADGE.get(current_status, current_status)
                _pill_bg    = _hex_rgba(_pill_color, 0.15)
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                    f"<span style='font-size:15px;font-weight:700'>STR Form</span>"
                    f"<span style='display:inline-flex;align-items:center;gap:6px;padding:4px 12px;"
                    f"border-radius:20px;font-size:12px;font-weight:600;background:{_pill_bg};color:{_pill_color}'>"
                    f"<span style='width:7px;height:7px;border-radius:50%;background:{_pill_color};"
                    f"display:inline-block'></span>{_pill_label}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.divider()

                _is_locked = current_status in (STR_STATUS_APPROVED, STR_STATUS_ARCHIVED)

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
                _td8.text_input(
                    "AI Flagging Summary",
                    value=f"RF score: {float(str_case.get('risk_score', 0)):.3f} — {str_case.get('risk_tier', '')}",
                    disabled=True, key="str_ai_summary",
                )

                # ── Grounds for Suspicion (editable) ─────────────────────────
                _section_label("Grounds for Suspicion", "● editable")
                default_grounds = build_default_grounds(str_case)
                grounds = st.text_area(
                    "Grounds",
                    value=str_record.get("grounds", default_grounds),
                    height=120,
                    disabled=_is_locked,
                    label_visibility="collapsed",
                    key="str_grounds",
                )

                # ── Filing Details ────────────────────────────────────────────
                _section_label("Filing Details")
                _fd1, _fd2 = st.columns(2)
                analyst_field = actor_id
                _fd1.text_input("Analyst ID", value=analyst_field, disabled=True, key="str_analyst")
                _fd2.text_input(
                    "Reference Number",
                    value=str(str_record.get("reference_number") or "—"),
                    disabled=True,
                    key="str_ref_num",
                )

                # ── L2-only: Rejection reason ─────────────────────────────────
                l2_reject_reason = ""
                if current_status == STR_STATUS_L2:
                    st.markdown(
                        f"<div style='border:1px solid #f44336;border-radius:8px;"
                        f"background:{_hex_rgba('#f44336', 0.05)};padding:12px 14px;margin-top:12px'>"
                        f"<div style='font-size:12px;color:#f44336;margin-bottom:8px;font-weight:600'>"
                        f"L2 Rejection — if rejecting</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    l2_reject_reason = st.text_input(
                        "Rejection Reason",
                        placeholder="Provide reason for returning STR to Draft...",
                        key="str_l2_reject",
                    )

                # ── L2-only: Analyst declaration ──────────────────────────────
                confirm = False
                if current_status == STR_STATUS_L2:
                    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                    confirm = st.checkbox(
                        "I confirm this STR is accurate and complete to the best of my knowledge, "
                        "and I am authorised to file this report.",
                        key="str_confirm",
                    )

                st.divider()

                # ── Action buttons ────────────────────────────────────────────
                _submit_label    = _SUBMIT_LABELS.get(current_status, "Already Approved")
                _submit_disabled = _is_locked

                if st.button(_submit_label, type="primary", use_container_width=True, disabled=_submit_disabled, key="str_submit"):
                    if current_status == STR_STATUS_DRAFT:
                        str_record = upsert_str_workflow(
                            str_record, grounds, STR_STATUS_L1,
                            {"reference_number": str_record.get("reference_number") or make_reference_number(str_case["transaction_id"])},
                        )
                        log_action(action="str_submitted_l1", transaction_id=str_case["transaction_id"],
                                   details=f"str_id={str_record['str_id']}", analyst_id=analyst_field,
                                   module="str_workflow", event_type="str_submitted_l1", entity_type="str",
                                   entity_id=str_record["str_id"], actor_role=actor_role, payload={"status": STR_STATUS_L1})
                        st.success("STR submitted to L1 Review.")
                        st.rerun()
                    elif current_status == STR_STATUS_L1:
                        str_record = upsert_str_workflow(
                            str_record, grounds, STR_STATUS_L2,
                            {"l1_reviewer": analyst_field, "l1_reviewed_at": str(report_date), "l1_reason": "Approved by L1"},
                        )
                        log_action(action="str_approved_l1", transaction_id=str_case["transaction_id"],
                                   details=f"str_id={str_record['str_id']}", analyst_id=analyst_field,
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
                                {"reference_number": ref_no, "l2_reviewer": analyst_field,
                                 "l2_reviewed_at": str(report_date), "l2_reason": "Approved at L2"},
                            )
                            archive_str_case(str_record, analyst_field, {
                                "customer_name": str_case.get("customer_name", ""),
                                "risk_tier": str_case.get("risk_tier", ""),
                                "report_date": str(report_date),
                                "reference_number": ref_no, "grounds": grounds,
                            })
                            upsert_str_workflow(str_record, grounds, STR_STATUS_ARCHIVED, {"reference_number": ref_no})
                            st.session_state["str_log"].append({
                                "reference_number": ref_no, "transaction_id": str_case["transaction_id"],
                                "rf_prediction": str_case["risk_score"], "cdd_level": str_case["cdd_level"],
                                "filed_by": analyst_field, "report_date": str(report_date),
                            })
                            log_action(action="str_archived", transaction_id=str_case["transaction_id"],
                                       details=f"reference_number={ref_no}", analyst_id=analyst_field,
                                       module="str_workflow", event_type="str_archived", entity_type="str",
                                       entity_id=str_record["str_id"], actor_role=actor_role,
                                       payload={"reference_number": ref_no, "status": STR_STATUS_ARCHIVED})
                            st.success(f"STR approved and archived. Reference: {ref_no}")
                            st.rerun()

                if not _is_locked:
                    if st.button("Save Draft", use_container_width=True, key="str_save_draft"):
                        upsert_str_workflow(str_record, grounds, STR_STATUS_DRAFT)
                        st.success("Draft saved.")
                        st.rerun()

                    if current_status == STR_STATUS_L2:
                        if st.button("Reject at L2", use_container_width=True, key="str_reject_l2"):
                            if not l2_reject_reason.strip():
                                st.error("Provide an L2 rejection reason in the field above.")
                            else:
                                str_record = upsert_str_workflow(
                                    str_record, grounds, STR_STATUS_DRAFT,
                                    {"l2_reviewer": analyst_field, "l2_reviewed_at": str(report_date), "l2_reason": l2_reject_reason},
                                )
                                log_action(action="str_rejected_l2", transaction_id=str_case["transaction_id"],
                                           details=f"str_id={str_record['str_id']}; reason={l2_reject_reason}",
                                           analyst_id=analyst_field, module="str_workflow", event_type="str_rejected_l2",
                                           entity_type="str", entity_id=str_record["str_id"], actor_role=actor_role,
                                           payload={"reason": l2_reject_reason})
                                st.warning("STR returned to Draft after L2 rejection.")
                                st.rerun()

        # ─────────────────────────── RIGHT: Review History ───────────────────
        with _right_col:

            # Review History
            with st.container(border=True):
                st.markdown("**Review History**")
                st.divider()
                st.markdown(
                    _review_row_html(
                        "L1 Review", "#4da6ff",
                        str(str_record.get("l1_reviewer", "") or ""),
                        str(str_record.get("l1_reason", "") or ""),
                        str(str_record.get("l1_reviewed_at", "") or ""),
                        last=False,
                    )
                    + _review_row_html(
                        "L2 Review", "#fb8c00",
                        str(str_record.get("l2_reviewer", "") or ""),
                        str(str_record.get("l2_reason", "") or ""),
                        str(str_record.get("l2_reviewed_at", "") or ""),
                        last=True,
                    ),
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — All STRs
# ══════════════════════════════════════════════════════════════════════════════
with tab_all:
    all_strs = get_all_str_records()

    # Filters
    _frow1, _frow2 = st.columns([2, 1])
    _search_term   = _frow1.text_input("Search by STR ID / Case ID / Transaction ID", value="", key="tracker_search")
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
            _view["Status"] = _view["status"].map(_STATUS_BADGE).fillna(_view["status"])
            st.dataframe(
                _view[[
                    "Status", "str_id", "case_id", "transaction_id",
                    "reference_number", "l1_reviewer", "l2_reviewer", "updated_at",
                ]].rename(columns={
                    "str_id": "STR ID", "case_id": "Case ID", "transaction_id": "Txn ID",
                    "reference_number": "Reference No.", "l1_reviewer": "L1 Reviewer",
                    "l2_reviewer": "L2 Reviewer", "updated_at": "Last Updated",
                }).sort_values("Last Updated", ascending=False),
                use_container_width=True, hide_index=True,
            )

            st.divider()
            _sc, _bc = st.columns([4, 1])
            _str_id_options  = _view["str_id"].astype(str).tolist()
            _selected_str_id = _sc.selectbox("Select STR to view", _str_id_options, key="tracker_select_str")
            _bc.write("")
            if _bc.button("View →", key="tracker_view_btn"):
                _rec = all_strs[all_strs["str_id"].astype(str) == _selected_str_id].iloc[0].to_dict()
                st.session_state["selected_str_record"] = _rec

            # Inline STR viewer
            _record = st.session_state.get("selected_str_record")
            if _record:
                st.divider()
                _rs = _record.get("status", "")
                st.subheader(f"{_record.get('str_id', '—')}  {_STATUS_BADGE.get(_rs, _rs)}")
                _vc1, _vc2, _vc3 = st.columns(3)
                _vc1.metric("Case ID",       _record.get("case_id", "—") or "—")
                _vc2.metric("Transaction ID", _record.get("transaction_id", "—") or "—")
                _vc3.metric("Reference No.",  _record.get("reference_number", "—") or "—")
                st.markdown("**Grounds for Suspicion**")
                st.text_area("", value=_record.get("grounds", ""), height=120, disabled=True, key="view_str_grounds")
                _rl, _rr = st.columns(2)
                with _rl:
                    with st.container(border=True):
                        st.markdown("**L1 Review**")
                        st.write(f"Reviewer: {_record.get('l1_reviewer', '') or '—'}")
                        st.write(f"Date: {_record.get('l1_reviewed_at', '') or '—'}")
                        st.write(f"Decision: {_record.get('l1_reason', '') or '—'}")
                with _rr:
                    with st.container(border=True):
                        st.markdown("**L2 Review**")
                        st.write(f"Reviewer: {_record.get('l2_reviewer', '') or '—'}")
                        st.write(f"Date: {_record.get('l2_reviewed_at', '') or '—'}")
                        st.write(f"Decision: {_record.get('l2_reason', '') or '—'}")

    # Archived STRs
    st.divider()
    st.subheader("Archived STRs")
    archive_view = build_archive_search_view()
    if archive_view.empty:
        st.info("No archived STR cases yet.")
    else:
        _as1, _as2, _as3 = st.columns(3)
        _cust_search   = _as1.text_input("Search by customer", value="", key="arch_cust")
        _risk_search   = _as2.selectbox("Risk Tier", ["All"] + sorted(archive_view["risk_tier"].dropna().astype(str).unique().tolist()), key="arch_risk")
        _status_search = _as3.selectbox("STR Status", ["All"] + sorted(archive_view["str_status"].dropna().astype(str).unique().tolist()), key="arch_status")

        _arch_filt = archive_view.copy()
        if _cust_search.strip():
            _arch_filt = _arch_filt[_arch_filt["customer_name"].astype(str).str.contains(_cust_search.strip(), case=False, na=False)]
        if _risk_search != "All":
            _arch_filt = _arch_filt[_arch_filt["risk_tier"].astype(str) == _risk_search]
        if _status_search != "All":
            _arch_filt = _arch_filt[_arch_filt["str_status"].astype(str) == _status_search]

        st.dataframe(
            _arch_filt[[
                "archive_id", "str_id", "case_id", "transaction_id",
                "customer_id", "customer_name", "risk_tier", "str_status",
                "archived_at", "archived_by",
            ]],
            use_container_width=True,
        )