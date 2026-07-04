from __future__ import annotations

from datetime import date

import streamlit as st

st.set_page_config(layout="wide")

from utils.sidebar import render_sidebar
from utils.audit_logger import log_action
from utils.session_utils import get_current_analyst
from utils.kyc_store import get_kyc_customers
from utils.cdd_review import (
    ADVERSE_MEDIA_RESULTS,
    CDD_STATUS_APPROVED,
    CDD_STATUS_COMPLETED,
    CDD_STATUS_DRAFT,
    CDD_STATUS_PENDING,
    CDD_STATUS_REJECTED,
    CDD_TYPE_ECDD,
    CDD_TYPE_SCDD,
    ECDD_BASIS,
    ECDD_CORP_ONLY_BASIS,
    ECDD_EVIDENCE_TYPES,
    ECDD_REVIEW_CYCLES,
    ECDD_TRIGGERS,
    PEP_TYPES,
    PRETXN_CHECK_OPTIONS,
    PURPOSE_BASES,
    SANCTIONS_RESULTS,
    SCDD_MEASURES,
    SCDD_REVIEW_CYCLES,
    SOF_CATEGORIES,
    can_approve,
    can_submit_for_approval,
    check_scdd_eligibility,
    get_latest_review,
    load_payload,
    save_review,
    sync_review_to_kyc,
)

render_sidebar()

st.title("Customer Due Diligence")
st.caption("Document SCDD / ECDD per MAS Notice 626 — Compliance Officer workspace.")

actor_id, actor_role = get_current_analyst()


def _safe_idx(options: list, value, default: int = 0) -> int:
    return options.index(value) if value in options else default


def _banner(level: str, msg: str) -> None:
    colors = {"ok": "#4caf50", "deny": "#f44336", "warn": "#fb8c00", "info": "#4da6ff"}
    icons = {"ok": "✓", "deny": "⛔", "warn": "⚠", "info": "ℹ"}
    c = colors.get(level, "#888")
    h = c.lstrip("#")
    rgba = f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},0.07)"
    st.markdown(
        f"<div style='display:flex;gap:10px;align-items:flex-start;border:1px solid {c};"
        f"background:{rgba};border-radius:8px;padding:11px 14px;margin:6px 0'>"
        f"<span style='font-size:15px'>{icons.get(level,'•')}</span>"
        f"<span style='font-size:12.5px;color:{c};line-height:1.5'>{msg}</span></div>",
        unsafe_allow_html=True,
    )


st.markdown(
    f"<div style='border:1px solid #1e2130;border-radius:10px;background:#13161f;padding:10px 16px;"
    f"margin-bottom:12px;font-size:12px;color:#888'><span style='text-transform:uppercase;"
    f"letter-spacing:1px;color:#555;font-size:11px'>Acting as</span>&nbsp;&nbsp;"
    f"<b style='color:#4da6ff'>{actor_role}</b> · {actor_id}</div>",
    unsafe_allow_html=True,
)

# ── Customer selector (+ handoff) ─────────────────────────────────────────────
customers = get_kyc_customers()
if customers.empty:
    st.warning("No KYC customers found. Enrol customers on the KYC page first.")
    st.stop()

_ids = customers["id"].astype(str).tolist()
_labels = {
    cid: f"{cid} — {customers.loc[customers['id'].astype(str) == cid, 'FullName'].iloc[0]}"
    for cid in _ids
}
_handoff_id = st.session_state.get("cdd_customer_id")
_default_idx = _ids.index(str(_handoff_id)) if str(_handoff_id) in _ids else 0

_sel_col, _mode_col = st.columns([2, 2])
selected_id = _sel_col.selectbox("Customer", _ids, index=_default_idx,
                                 format_func=lambda c: _labels.get(c, c), key="cdd_customer_sel")

kyc = customers.loc[customers["id"].astype(str) == str(selected_id)].iloc[0].to_dict()

_mode_default = st.session_state.get("cdd_mode", CDD_TYPE_SCDD)
cdd_type = _mode_col.radio("CDD Type", [CDD_TYPE_SCDD, CDD_TYPE_ECDD],
                           index=0 if _mode_default == CDD_TYPE_SCDD else 1,
                           horizontal=True, key="cdd_mode_sel",
                           format_func=lambda m: "SCDD — Simplified" if m == CDD_TYPE_SCDD else "ECDD — Enhanced")
# Clear one-shot handoff so it doesn't pin the selector on every rerun.
st.session_state.pop("cdd_customer_id", None)
st.session_state.pop("cdd_mode", None)

_type_default = str(kyc.get("customer_type", "Individual")) or "Individual"
customer_type = st.radio("Customer type", ["Individual", "Corporate"],
                         index=0 if _type_default != "Corporate" else 1,
                         horizontal=True, key="cdd_ctype")
is_corp = customer_type == "Corporate"

# ── Customer header ───────────────────────────────────────────────────────────
_fatf = str(kyc.get("FATFListCategory", "") or "None") or "None"
_fatf_color = "#f44336" if _fatf and _fatf != "None" else "#4caf50"
_risk = str(kyc.get("RiskStatus", "—") or "—")
_div = "<div style='width:1px;align-self:stretch;background:#1e2130'></div>"
st.markdown(
    f"<div style='border:1px solid #1e2130;border-radius:10px;background:#13161f;padding:14px 18px;"
    f"display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin:10px 0 6px'>"
    + "".join(
        f"<div style='display:flex;flex-direction:column;gap:2px'>"
        f"<span style='font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.8px'>{lbl}</span>"
        f"<span style='font-size:14px;font-weight:700;color:{clr}'>{val}</span></div>" + (_div if i < 5 else "")
        for i, (lbl, val, clr) in enumerate([
            ("Customer", kyc.get("FullName", "—"), "#e0e0e0"),
            ("Customer ID", selected_id, "#4da6ff"),
            ("Type", customer_type, "#e0e0e0"),
            ("Nationality", kyc.get("Nationality", "—") or "—", "#e0e0e0"),
            ("Risk Rating", _risk, "#e0e0e0"),
            ("FATF Status", _fatf, _fatf_color),
        ])
    )
    + "</div>",
    unsafe_allow_html=True,
)

# ── Load existing review of this type ─────────────────────────────────────────
existing = get_latest_review(selected_id, cdd_type)
pl = load_payload(existing)
_status = str(existing.get("status", "")) if existing else ""


def _base_meta(status: str, **extra) -> dict:
    meta = {
        "review_id": existing.get("review_id", "") if existing else "",
        "customer_id": selected_id,
        "account_no": str(kyc.get("AccountNo", "")),
        "customer_name": str(kyc.get("FullName", "")),
        "customer_type": customer_type,
        "cdd_type": cdd_type,
        "status": status,
        "created_at": existing.get("created_at", "") if existing else "",
    }
    meta.update(extra)
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# SCDD
# ══════════════════════════════════════════════════════════════════════════════
if cdd_type == CDD_TYPE_SCDD:
    eligible, reasons = check_scdd_eligibility(selected_id, kyc)

    st.subheader("Eligibility Validation")
    st.caption("MAS 626 — simplified measures are permitted only where ML/TF risk is assessed low.")
    if eligible:
        _banner("ok", "Eligible for Simplified CDD — no disqualifying factors detected.")
    else:
        _banner("deny", "SCDD <b>not permitted</b> — " + "; ".join(reasons) + ". Escalate to ECDD.")

    with st.container(border=True):
        st.markdown("**Risk Assessment Rationale** &nbsp;<span style='color:#f44336'>*</span>", unsafe_allow_html=True)
        risk_rationale = st.text_area("Risk rationale", value=pl.get("risk_rationale", ""),
                                      placeholder="e.g., Salaried resident; domestic-only activity; low volumes; transparent purpose...",
                                      label_visibility="collapsed", key="scdd_rationale")
        c1, c2, c3 = st.columns(3)
        risk_rating = c1.selectbox("Assessed Risk Rating", ["Low"], key="scdd_rating")
        product_channel = c2.text_input("Product / Channel", value=pl.get("product_channel", ""), key="scdd_product")
        expected_volume = c3.text_input("Expected Annual Volume (SGD)", value=pl.get("expected_volume", ""), key="scdd_volume")

    with st.container(border=True):
        st.markdown("**Nature of Simplified Measures Applied** &nbsp;<span style='color:#f44336'>*</span>", unsafe_allow_html=True)
        measures = st.multiselect("Simplified measures", SCDD_MEASURES,
                                  default=[m for m in pl.get("simplified_measures", []) if m in SCDD_MEASURES],
                                  label_visibility="collapsed", key="scdd_measures")
        measures_notes = st.text_area("Additional notes on measures", value=pl.get("measures_notes", ""), key="scdd_measures_notes")
        c1, c2 = st.columns(2)
        monitoring_threshold = c1.text_input("Monitoring threshold (SGD)", value=pl.get("monitoring_threshold", "10,000"), key="scdd_threshold")
        review_cycle = c2.selectbox("Periodic review cycle", SCDD_REVIEW_CYCLES,
                                    index=_safe_idx(SCDD_REVIEW_CYCLES, pl.get("review_cycle"), 0), key="scdd_cycle")

    with st.container(border=True):
        st.markdown("**Purpose & Intended Nature of Relationship** &nbsp;<span style='color:#4da6ff;font-size:11px'>· may be inferred</span>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        purpose_basis = c1.selectbox("Basis", PURPOSE_BASES, index=_safe_idx(PURPOSE_BASES, pl.get("purpose_basis"), 0), key="scdd_pbasis")
        inferred_purpose = c2.text_input("Inferred purpose", value=pl.get("inferred_purpose", ""), key="scdd_purpose")
        purpose_rationale = st.text_area("Rationale for inference", value=pl.get("purpose_rationale", ""), key="scdd_prationale")

    with st.container(border=True):
        st.markdown("**Eligibility Attestations** &nbsp;<span style='color:#f44336'>*</span>", unsafe_allow_html=True)
        att = pl.get("attestations", {})
        a1 = st.checkbox("Customer / beneficial owner is not from a FATF call-for-countermeasures country.", value=att.get("a1", eligible), key="scdd_a1")
        a2 = st.checkbox("There is no existing suspicion of money laundering or terrorism financing.", value=att.get("a2", eligible), key="scdd_a2")
        a3 = st.checkbox("Customer is not a PEP or otherwise higher-risk.", value=att.get("a3", eligible), key="scdd_a3")
        a4 = st.checkbox("The simplified measures applied are commensurate with the assessed low risk.", value=att.get("a4", False), key="scdd_a4")

    with st.container(border=True):
        st.markdown("**Sign-off**")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Completed by", value=actor_id, disabled=True, key="scdd_by")
        c2.date_input("Date", value=date.today(), key="scdd_date")
        next_review = c3.date_input("Next review date", value=date.today().replace(year=date.today().year + 3), key="scdd_next")

        _payload = {
            "risk_rationale": risk_rationale, "product_channel": product_channel, "expected_volume": expected_volume,
            "simplified_measures": measures, "measures_notes": measures_notes,
            "monitoring_threshold": monitoring_threshold, "review_cycle": review_cycle,
            "purpose_basis": purpose_basis, "inferred_purpose": inferred_purpose, "purpose_rationale": purpose_rationale,
            "attestations": {"a1": a1, "a2": a2, "a3": a3, "a4": a4},
        }
        _meta_common = dict(risk_rating=risk_rating, eligibility_status="Eligible" if eligible else "Blocked",
                            completed_by=actor_id, next_review_date=str(next_review))

        b1, b2 = st.columns([1, 1])
        if b1.button("Save Draft", use_container_width=True, key="scdd_save"):
            rec = save_review(_base_meta(CDD_STATUS_DRAFT, **_meta_common), _payload)
            log_action(action="scdd_draft_saved", transaction_id=str(selected_id),
                       details=f"review_id={rec['review_id']}", analyst_id=actor_id, module="cdd_review",
                       event_type="scdd_draft_saved", entity_type="cdd", entity_id=rec["review_id"], actor_role=actor_role)
            st.success("SCDD draft saved.")
            st.rerun()
        if b2.button("Complete SCDD", type="primary", use_container_width=True, disabled=not eligible, key="scdd_complete"):
            if not (a1 and a2 and a3 and a4):
                st.error("All eligibility attestations must be checked before completing.")
            elif not risk_rationale.strip() or not measures:
                st.error("Risk rationale and at least one simplified measure are required.")
            else:
                rec = save_review(_base_meta(CDD_STATUS_COMPLETED, completed_at=date.today().isoformat(), **_meta_common), _payload)
                sync_review_to_kyc(selected_id, CDD_TYPE_SCDD, _payload)
                log_action(action="scdd_completed", transaction_id=str(selected_id),
                           details=f"review_id={rec['review_id']}", analyst_id=actor_id, module="cdd_review",
                           event_type="scdd_completed", entity_type="cdd", entity_id=rec["review_id"],
                           actor_role=actor_role, payload={"cdd_type": "SCDD"})
                st.success("SCDD completed and synced to the customer record.")
                st.rerun()
        if not eligible:
            st.markdown("<div style='font-size:11px;color:#ff7a70'>Completion blocked — customer is not eligible for Simplified CDD.</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ECDD
# ══════════════════════════════════════════════════════════════════════════════
else:
    _locked = _status == CDD_STATUS_APPROVED
    _can_submit = can_submit_for_approval(actor_role)
    _approve_ok, _approve_msg = can_approve(actor_role, actor_id, existing or {})

    _banner("info", "ECDD: customer is on <b>Enhanced</b> due diligence. Starred fields are mandatory and "
                    "Senior Management approval is required before the relationship may proceed.")

    _basis_opts = [b for b in ECDD_BASIS if is_corp or b not in ECDD_CORP_ONLY_BASIS]
    with st.container(border=True):
        st.markdown("**Basis of Higher Risk** &nbsp;<span style='color:#f44336'>*</span>", unsafe_allow_html=True)
        basis = st.multiselect("Basis of higher risk", _basis_opts,
                              default=[b for b in pl.get("basis", []) if b in _basis_opts],
                              label_visibility="collapsed", disabled=_locked, key="ecdd_basis")
        basis_narrative = st.text_area("Narrative — basis of higher-risk determination",
                                       value=pl.get("basis_narrative", ""), disabled=_locked, key="ecdd_basis_narr")

    with st.container(border=True):
        st.markdown("**PEP & Screening Details**")
        c1, c2, c3 = st.columns(3)
        pep_type = c1.selectbox("PEP type", PEP_TYPES, index=_safe_idx(PEP_TYPES, pl.get("pep_type"), 0), disabled=_locked, key="ecdd_pep_type")
        pep_position = c2.text_input("Position / role", value=pl.get("pep_position", ""), disabled=_locked, key="ecdd_pep_pos")
        pep_country = c3.text_input("Country of prominence", value=pl.get("pep_country", ""), disabled=_locked, key="ecdd_pep_country")
        c1, c2 = st.columns(2)
        sanctions_result = c1.selectbox("Sanctions / watchlist screening result", SANCTIONS_RESULTS,
                                        index=_safe_idx(SANCTIONS_RESULTS, pl.get("sanctions_result"), 0), disabled=_locked, key="ecdd_sanctions")
        adverse_media = c2.selectbox("Adverse media result", ADVERSE_MEDIA_RESULTS,
                                     index=_safe_idx(ADVERSE_MEDIA_RESULTS, pl.get("adverse_media"), 0), disabled=_locked, key="ecdd_adverse")

    with st.container(border=True):
        st.markdown("**Source of Wealth (SoW)** &nbsp;<span style='color:#f44336'>*</span> "
                    "<span style='color:#fb8c00;font-size:11px'>· entire body of wealth</span>", unsafe_allow_html=True)
        source_of_wealth = st.text_area("Source of wealth", value=pl.get("source_of_wealth", ""),
                                        placeholder="Origin of total assets (customer + beneficial owner) and how accumulated over time.",
                                        label_visibility="collapsed", disabled=_locked, key="ecdd_sow")

    with st.container(border=True):
        st.markdown("**Source of Funds (SoF)** &nbsp;<span style='color:#f44336'>*</span> "
                    "<span style='color:#fb8c00;font-size:11px'>· this account / transaction</span>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        sof_category = c1.selectbox("Primary SoF category", SOF_CATEGORIES, index=_safe_idx(SOF_CATEGORIES, pl.get("sof_category"), 0), disabled=_locked, key="ecdd_sof_cat")
        funding_amount = c2.text_input("Expected funding amount (SGD)", value=pl.get("funding_amount", ""), disabled=_locked, key="ecdd_funding")
        source_of_funds = st.text_area("Details", value=pl.get("source_of_funds", ""), disabled=_locked, key="ecdd_sof")

    with st.container(border=True):
        st.markdown("**Third-Party / Gift Legitimacy**")
        gift_flag = st.checkbox("Wealth or funds (wholly/partly) derived from a gift or third party",
                                value=pl.get("gift_flag", False), disabled=_locked, key="ecdd_gift")
        third_party_name = third_party_rel = third_party_sow = ""
        if gift_flag:
            c1, c2 = st.columns(2)
            third_party_name = c1.text_input("Third-party name", value=pl.get("third_party_name", ""), disabled=_locked, key="ecdd_tp_name")
            third_party_rel = c2.text_input("Relationship to customer", value=pl.get("third_party_rel", ""), disabled=_locked, key="ecdd_tp_rel")
            third_party_sow = st.text_area("Assessment of third party's own SoW legitimacy", value=pl.get("third_party_sow", ""), disabled=_locked, key="ecdd_tp_sow")

    ubo_details = ownership_structure = ""
    if is_corp:
        with st.container(border=True):
            st.markdown("**Beneficial Ownership / UBOs** &nbsp;<span style='color:#f44336'>*</span> "
                        "<span style='color:#fb8c00;font-size:11px'>· corporate</span>", unsafe_allow_html=True)
            ubo_details = st.text_area("UBOs (name · % · role · SoW summary)", value=pl.get("ubo_details", ""), disabled=_locked, key="ecdd_ubo")
            ownership_structure = st.text_area("Ownership / control structure & economic purpose", value=pl.get("ownership_structure", ""), disabled=_locked, key="ecdd_structure")

    with st.container(border=True):
        st.markdown("**Corroboration Evidence** &nbsp;<span style='color:#f44336'>*</span> "
                    "<span style='color:#fb8c00;font-size:11px'>· reliable, independent sources</span>", unsafe_allow_html=True)
        evidence_types = st.multiselect("Source types provided", ECDD_EVIDENCE_TYPES,
                                       default=[e for e in pl.get("evidence_types", []) if e in ECDD_EVIDENCE_TYPES],
                                       disabled=_locked, key="ecdd_evidence")
        uploaded = st.file_uploader("Upload supporting documents", accept_multiple_files=True, disabled=_locked, key="ecdd_upload")
        existing_files = list(pl.get("evidence_files", []))
        new_files = [f.name for f in uploaded] if uploaded else []
        evidence_files = sorted(set(existing_files + new_files))
        if evidence_files:
            st.caption("Documents on file: " + ", ".join(evidence_files))

    with st.container(border=True):
        st.markdown("**Enhanced Monitoring Plan** &nbsp;<span style='color:#f44336'>*</span>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        monitoring_cycle = c1.selectbox("Periodic review cycle", ECDD_REVIEW_CYCLES, index=_safe_idx(ECDD_REVIEW_CYCLES, pl.get("monitoring_cycle"), 0), disabled=_locked, key="ecdd_cycle")
        monitoring_threshold = c2.text_input("Monitoring threshold (SGD)", value=pl.get("monitoring_threshold", "5,000"), disabled=_locked, key="ecdd_threshold")
        pretxn_checks = c3.selectbox("Pre-transaction checks", PRETXN_CHECK_OPTIONS, index=_safe_idx(PRETXN_CHECK_OPTIONS, pl.get("pretxn_checks"), 0), disabled=_locked, key="ecdd_pretxn")
        triggers = st.multiselect("Trigger events for re-review", ECDD_TRIGGERS,
                                 default=[t for t in pl.get("triggers", []) if t in ECDD_TRIGGERS], disabled=_locked, key="ecdd_triggers")

    # ── Senior Management approval ────────────────────────────────────────────
    _sm_status = str(existing.get("sm_status", "")) if existing else ""
    with st.container(border=True):
        _pill = {"Pending": ("#fdd835", "Pending"), "Approved": ("#4caf50", "Approved"),
                 "Rejected": ("#f44336", "Rejected")}.get(_sm_status, ("#888", "Not submitted"))
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<span style='font-size:15px;font-weight:700'>Senior Management Approval "
            f"<span style='color:#f44336'>*</span></span>"
            f"<span style='padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;"
            f"background:{_pill[0]}22;color:{_pill[0]}'>● {_pill[1]}</span></div>",
            unsafe_allow_html=True,
        )
        if _status == CDD_STATUS_PENDING:
            if _approve_ok:
                _banner("ok", "You are <b>Senior Management</b> — you may approve or reject this higher-risk relationship.")
            else:
                _banner("warn", _approve_msg)
        elif _sm_status == "Approved":
            _banner("ok", f"Approved by {existing.get('sm_approver','')} on {existing.get('sm_decision_at','')}.")
        elif _sm_status == "Rejected":
            _banner("deny", f"Rejected by {existing.get('sm_approver','')} on {existing.get('sm_decision_at','')}.")
        else:
            _banner("warn", "Not yet submitted. Compliance Officer must submit for Senior Management approval.")
        sm_remarks = st.text_area("Senior Management remarks", value=pl.get("sm_remarks", ""),
                                  disabled=not (_status == CDD_STATUS_PENDING and _approve_ok), key="ecdd_sm_remarks")

    def _ecdd_payload() -> dict:
        return {
            "basis": basis, "basis_narrative": basis_narrative,
            "pep_type": pep_type, "pep_position": pep_position, "pep_country": pep_country,
            "sanctions_result": sanctions_result, "adverse_media": adverse_media,
            "source_of_wealth": source_of_wealth, "sof_category": sof_category,
            "funding_amount": funding_amount, "source_of_funds": source_of_funds,
            "gift_flag": gift_flag, "third_party_name": third_party_name,
            "third_party_rel": third_party_rel, "third_party_sow": third_party_sow,
            "ubo_details": ubo_details, "ownership_structure": ownership_structure,
            "evidence_types": evidence_types, "evidence_files": evidence_files,
            "monitoring_cycle": monitoring_cycle, "monitoring_threshold": monitoring_threshold,
            "pretxn_checks": pretxn_checks, "triggers": triggers,
            "sm_remarks": sm_remarks,
            "sm_approver": existing.get("sm_approver", "") if existing else "",
            "sm_decision_at": existing.get("sm_decision_at", "") if existing else "",
        }

    with st.container(border=True):
        st.markdown("**Sign-off**")
        c1, c2 = st.columns(2)
        c1.text_input("Completed by (Compliance Officer)", value=actor_id, disabled=True, key="ecdd_by")
        next_review = c2.date_input("Next review date", value=date.today().replace(year=date.today().year + 1), key="ecdd_next")

        _meta_common = dict(risk_rating="High", completed_by=existing.get("completed_by", "") if existing else "",
                            next_review_date=str(next_review))

        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Save Draft", use_container_width=True, disabled=_locked, key="ecdd_save"):
            rec = save_review(_base_meta(_status or CDD_STATUS_DRAFT, sm_status=_sm_status, **_meta_common), _ecdd_payload())
            log_action(action="ecdd_draft_saved", transaction_id=str(selected_id), details=f"review_id={rec['review_id']}",
                       analyst_id=actor_id, module="cdd_review", event_type="ecdd_draft_saved", entity_type="cdd",
                       entity_id=rec["review_id"], actor_role=actor_role)
            st.success("ECDD draft saved.")
            st.rerun()

        if b2.button("Submit for SM Approval", use_container_width=True,
                     disabled=_locked or not _can_submit or _status == CDD_STATUS_PENDING, key="ecdd_submit"):
            if not _can_submit:
                st.error("Only a Compliance Officer can submit for approval.")
            elif not (basis and source_of_wealth.strip() and source_of_funds.strip() and evidence_types):
                st.error("Basis, Source of Wealth, Source of Funds, and at least one evidence type are required.")
            else:
                meta = _base_meta(CDD_STATUS_PENDING, sm_status="Pending",
                                  completed_by=actor_id, completed_at=date.today().isoformat(),
                                  risk_rating="High", next_review_date=str(next_review))
                rec = save_review(meta, _ecdd_payload())
                sync_review_to_kyc(selected_id, CDD_TYPE_ECDD, _ecdd_payload(), sm_status="Pending")
                log_action(action="ecdd_submitted", transaction_id=str(selected_id), details=f"review_id={rec['review_id']}",
                           analyst_id=actor_id, module="cdd_review", event_type="ecdd_submitted", entity_type="cdd",
                           entity_id=rec["review_id"], actor_role=actor_role, payload={"status": CDD_STATUS_PENDING})
                st.success("ECDD submitted for Senior Management approval.")
                st.rerun()

        if b3.button("Approve (SM)", type="primary", use_container_width=True,
                     disabled=not (_status == CDD_STATUS_PENDING and _approve_ok), key="ecdd_approve"):
            today = date.today().isoformat()
            pay = _ecdd_payload()
            pay["sm_approver"] = actor_id
            pay["sm_decision_at"] = today
            meta = _base_meta(CDD_STATUS_APPROVED, sm_status="Approved", sm_approver=actor_id, sm_role=actor_role,
                              sm_decision_at=today, completed_by=existing.get("completed_by", "") if existing else "",
                              completed_at=existing.get("completed_at", "") if existing else "",
                              risk_rating="High", next_review_date=str(next_review))
            rec = save_review(meta, pay)
            sync_review_to_kyc(selected_id, CDD_TYPE_ECDD, pay, sm_status="Approved")
            log_action(action="ecdd_approved", transaction_id=str(selected_id), details=f"review_id={rec['review_id']}",
                       analyst_id=actor_id, module="cdd_review", event_type="ecdd_approved", entity_type="cdd",
                       entity_id=rec["review_id"], actor_role=actor_role, payload={"status": CDD_STATUS_APPROVED})
            st.success("ECDD approved by Senior Management.")
            st.rerun()

        if b4.button("Reject (SM)", use_container_width=True,
                     disabled=not (_status == CDD_STATUS_PENDING and _approve_ok), key="ecdd_reject"):
            today = date.today().isoformat()
            pay = _ecdd_payload()
            pay["sm_approver"] = actor_id
            pay["sm_decision_at"] = today
            meta = _base_meta(CDD_STATUS_REJECTED, sm_status="Rejected", sm_approver=actor_id, sm_role=actor_role,
                              sm_decision_at=today, completed_by=existing.get("completed_by", "") if existing else "",
                              risk_rating="High", next_review_date=str(next_review))
            rec = save_review(meta, pay)
            log_action(action="ecdd_rejected", transaction_id=str(selected_id), details=f"review_id={rec['review_id']}",
                       analyst_id=actor_id, module="cdd_review", event_type="ecdd_rejected", entity_type="cdd",
                       entity_id=rec["review_id"], actor_role=actor_role, payload={"status": CDD_STATUS_REJECTED})
            st.warning("ECDD rejected — returned to Compliance Officer.")
            st.rerun()
