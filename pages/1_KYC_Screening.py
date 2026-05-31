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
    SAML_REQUIRED_COLUMNS,
    engineer_features,
    prepare_model_matrix,
    validate_schema,
)
from utils.kyc_store import (
    CUSTOMER_RISK_STATUSES as KYC_RISK_STATUSES,
    RISK_CRITICAL,
    RISK_HIGH,
    SANCTIONS_REVIEW_PENDING,
    apply_cdd_escalation_from_transactions,
    enrol_customer,
    ensure_kyc_database,
    get_kyc_customers,
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _badge(text: str, style: str) -> str:
    return (
        f"<span style='display:inline-block;padding:2px 10px;border-radius:20px;"
        f"font-size:11px;font-weight:700;{style}'>{text}</span>"
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

def _complete_enrolment(pending: dict) -> None:
    row, match_info = enrol_customer(
        full_name=pending["FullName"],
        account_no=pending["AccountNo"],
        address=pending["Address"],
        contact_no=pending["ContactNo"],
        comments=pending.get("Comments", ""),
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
    _b1, _b2, _b3, _b4 = st.columns([0.4, 5, 1.2, 0.8])
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
        (_m6, "Sanctions Pending", int(customers["SanctionsReview"].astype(str).eq(SANCTIONS_REVIEW_PENDING).sum()),                 "#888"),
    ]
    for _mcol, _mlabel, _mval, _mcolor in _kpi_data:
        with _mcol:
            with st.container(border=True):
                st.markdown(
                    f"<div style='text-align:center;padding:6px 0'>"
                    f"<div style='font-size:11px;color:#666;text-transform:uppercase;"
                    f"letter-spacing:1px;margin-bottom:6px'>{_mlabel}</div>"
                    f"<div style='font-size:28px;font-weight:700;color:{_mcolor}'>{_mval}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    _col_enrol, _col_table = st.columns([2, 3], gap="medium")

    # ── Left: Enrolment form ──────────────────────────────────────────────────
    with _col_enrol:
        with st.container(border=True):
            st.markdown("**Enrol New Customer**")
            st.caption("Customer ID is auto-assigned. Sanctions screening runs on submission.")

            _success = st.session_state.pop("kyc_enrol_success", None)
            if _success:
                st.success(_success)

            # Sanctions match warning state
            _pending = st.session_state.get("kyc_pending_enrol")
            if _pending and _pending.get("sanctions_match"):
                _match = _pending["sanctions_match"]
                _list_key = _match.get("list_key") or "MAS Targeted Financial Sanctions list"
                st.warning(
                    f"**⚠ Potential Sanctions Match**  \n"
                    f"Match to **{_list_key}** (matched name: `{_match.get('matched_name', '')}`).  \n"
                    f"Additional CDD is required before this relationship can proceed."
                )
                st.write(f"Pending enrolment: **{_pending['FullName']}** — Account **{_pending['AccountNo']}**")
                _wc1, _wc2 = st.columns(2)
                if _wc1.button("Register with Pending Review", type="primary", use_container_width=True):
                    _pending["sanctions_warning_acknowledged"] = True
                    try:
                        _complete_enrolment(_pending)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if _wc2.button("Cancel Enrolment", use_container_width=True):
                    st.session_state.pop("kyc_pending_enrol", None)
                    st.rerun()
            else:
                with st.form("enrol_form", clear_on_submit=False):
                    _fc1, _fc2 = st.columns(2)
                    _full_name  = _fc1.text_input("Full Name *",      placeholder="Legal name as on ID")
                    _account_no = _fc2.text_input("Account Number *", placeholder="e.g. SG-0041-8812")
                    _address    = _fc1.text_input("Address *",        placeholder="Residential address")
                    _contact_no = _fc2.text_input("Contact Number *", placeholder="+65 9000 0000")
                    _risk_indicators = st.multiselect(
                        "Risk Indicators",
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
                    _flag_reason = st.text_input(
                        "Flagging Reason",
                        placeholder="Required if indicator selected",
                    )
                    _comments = st.text_area("Comments", height=70, placeholder="Optional notes")
                    _submitted = st.form_submit_button("Enrol Customer", type="primary", use_container_width=True)

                if _submitted:
                    if not _full_name.strip():
                        st.error("Full Name is required.")
                    elif not _account_no.strip():
                        st.error("Account Number is required.")
                    elif not _address.strip():
                        st.error("Address is required.")
                    elif not _contact_no.strip():
                        st.error("Contact Number is required.")
                    else:
                        _payload = {
                            "FullName": _full_name.strip(),
                            "AccountNo": _account_no.strip(),
                            "Address": _address.strip(),
                            "ContactNo": _contact_no.strip(),
                            "Comments": _comments.strip(),
                            "risk_indicators": _risk_indicators,
                            "flag_reason": _flag_reason.strip(),
                        }
                        _match_info = screen_name(_full_name)
                        if _match_info.get("matched"):
                            _payload["sanctions_match"] = _match_info
                            st.session_state["kyc_pending_enrol"] = _payload
                            st.rerun()
                        else:
                            try:
                                _complete_enrolment(_payload)
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))

    # ── Right: Customer table + inline risk manager ───────────────────────────
    with _col_table:
        with st.container(border=True):
            _th1, _th2 = st.columns([3, 1])
            _th1.markdown("**Customer Database**")
            _th2.markdown(
                f"<div style='text-align:right;color:#555;font-size:12px;padding-top:4px'>"
                f"{len(customers)} customers</div>",
                unsafe_allow_html=True,
            )

            _search = st.text_input(
                "", placeholder="🔍  Search by name, ID, or account…",
                label_visibility="collapsed",
            )
            _view = customers.copy()
            if _search.strip():
                _needle = _search.strip().lower()
                _view = _view[
                    _view["FullName"].astype(str).str.lower().str.contains(_needle)
                    | _view["id"].astype(str).str.lower().str.contains(_needle)
                    | _view["AccountNo"].astype(str).str.lower().str.contains(_needle)
                ]

            # Table header
            _hc = st.columns([2.2, 1.8, 1, 1, 1.5, 1.5])
            for _hcol, _hlabel in zip(_hc, ["NAME", "ACCOUNT", "RISK", "CDD", "SANCTIONS", "ACTIONS"]):
                _hcol.markdown(
                    f"<span style='font-size:11px;font-weight:700;color:#555;"
                    f"text-transform:uppercase;letter-spacing:0.8px'>{_hlabel}</span>",
                    unsafe_allow_html=True,
                )
            st.markdown("<hr style='border-color:#1e2130;margin:4px 0 8px 0'>", unsafe_allow_html=True)

            if _view.empty:
                st.info("No customers match your search.")
            else:
                for _, _row in _view.iterrows():
                    _cid     = str(_row["id"])
                    _risk    = str(_row.get("RiskStatus", "Low"))
                    _sanc    = str(_row.get("SanctionsReview", "—"))
                    _open_key = f"risk_open_{_cid}"

                    _rc = st.columns([2.2, 1.8, 1, 1, 1.5, 1.5])
                    _rc[0].markdown(
                        f"**{_row['FullName']}**  \n"
                        f"<span style='font-size:11px;color:#555'>{_cid}</span>",
                        unsafe_allow_html=True,
                    )
                    _rc[1].markdown(
                        f"<span style='font-size:12px;color:#ccc'>`{_row['AccountNo']}`</span>",
                        unsafe_allow_html=True,
                    )
                    _rc[2].markdown(_risk_badge(_risk), unsafe_allow_html=True)
                    _rc[3].markdown(
                        f"<span style='font-size:12px;color:#aaa'>{_row.get('CDDLevel', '—')}</span>",
                        unsafe_allow_html=True,
                    )
                    _rc[4].markdown(_sanctions_badge(_sanc), unsafe_allow_html=True)

                    _btn_label = "▲ Close" if st.session_state.get(_open_key) else "Manage Risk"
                    if _rc[5].button(_btn_label, key=f"btn_{_cid}", use_container_width=True):
                        st.session_state[_open_key] = not st.session_state.get(_open_key, False)
                        st.rerun()

                    # Inline risk manager
                    if st.session_state.get(_open_key):
                        with st.container(border=True):
                            st.markdown(
                                f"<span style='font-size:11px;font-weight:700;color:#aaa;"
                                f"text-transform:uppercase;letter-spacing:1px'>"
                                f"Manage Risk — {_row['FullName']}</span>",
                                unsafe_allow_html=True,
                            )
                            _cur_risk = str(_row.get("RiskStatus", "Low"))
                            _cur_pep  = str(_row.get("IsPEP", "")).strip().lower() == "yes"
                            _cur_sm   = str(_row.get("SMApprovalStatus", ""))

                            if _cur_sm == SM_APPROVAL_PENDING:
                                st.warning("Pending Senior Management approval.")

                            _rmc1, _rmc2 = st.columns(2)
                            _new_risk = _rmc1.selectbox(
                                "Risk Status", CUSTOMER_RISK_STATUSES,
                                index=CUSTOMER_RISK_STATUSES.index(_cur_risk) if _cur_risk in CUSTOMER_RISK_STATUSES else 0,
                                key=f"risk_sel_{_cid}",
                            )
                            _reason_opts = ["Manual", "PEP", "High-risk jurisdiction", "Complex profile", "Other"]
                            _reason = _rmc2.selectbox("Reason", _reason_opts, key=f"reason_{_cid}")
                            _custom_reason = ""
                            if _reason == "Other":
                                _custom_reason = st.text_input("Specify reason", key=f"custom_reason_{_cid}")
                            _is_pep = st.checkbox(
                                "Flag as PEP (Politically Exposed Person)",
                                value=_cur_pep, key=f"pep_{_cid}",
                            )

                            _final_risk   = RISK_CRITICAL if _is_pep else _new_risk
                            _final_reason = FLAG_REASON_PEP if _is_pep else (_custom_reason.strip() if _reason == "Other" else _reason)

                            if _is_pep and _new_risk != RISK_CRITICAL:
                                st.info("Flagging as PEP will set risk to Critical.")

                            _sv, _cl = st.columns(2)
                            if _sv.button("Save", key=f"save_{_cid}", type="primary", use_container_width=True):
                                _aid2, _arole2 = get_current_analyst()
                                _updated = set_customer_risk_status(
                                    customer_id=_cid, new_status=_final_risk,
                                    actor_id=_aid2, reason=_final_reason,
                                    is_pep=True if _is_pep else (False if not _cur_pep else None),
                                )
                                if _updated:
                                    log_action(
                                        action="customer_risk_status_changed",
                                        details=f"customer_id={_cid}; old={_cur_risk}; new={_final_risk}; pep={_is_pep}",
                                        analyst_id=_aid2, module="kyc_screening",
                                        event_type="customer_risk_status_changed", entity_type="customer",
                                        entity_id=_cid, actor_role=_arole2,
                                        payload={"old_risk": _cur_risk, "new_risk": _final_risk,
                                                 "is_pep": _is_pep, "reason": _final_reason},
                                    )
                                    st.session_state[_open_key] = False
                                    st.rerun()
                                else:
                                    st.error("Update failed.")
                            if _cl.button("Cancel", key=f"cancel_{_cid}", use_container_width=True):
                                st.session_state[_open_key] = False
                                st.rerun()

                    st.markdown(
                        "<hr style='border-color:#1e2130;margin:2px 0'>",
                        unsafe_allow_html=True,
                    )

                if _search.strip():
                    st.caption(f"Showing {len(_view)} of {len(customers)} customers")


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
                _tier_colors = {"Critical": "#f44336", "High": "#fb8c00", "Medium": "#fdd835", "Low": "#64dd17"}
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