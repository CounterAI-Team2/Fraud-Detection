from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils.sidebar import render_sidebar
from utils.aml_services import (
    attach_case_files,
    ensure_case_for_transaction,
    ensure_scored_defaults,
    get_case_by_transaction,
    get_related_transactions,
    update_case_record,
)
from utils.audit_logger import log_action
from utils.constants import (
    ALERT_STATUS_DISMISSED,
    CASE_STATUSES,
    CASE_STATUS_ESCALATED,
    CASE_STATUS_IN_REVIEW,
    CASE_STATUS_OPEN,
    CASE_STATUS_RESOLVED,
    CDD_LEVEL_ENHANCED,
    CDD_LEVEL_STANDARD,
    CDD_LEVELS,
    RISK_TIER_COLORS,
)
from utils.cdd_rules import recommend_for_case
from utils.data_store import get_customers, upsert_customers
from utils.feature_engineering import CATEGORICAL_FEATURES, ENGINEERED_FEATURES, prepare_model_matrix
from utils.kyc_store import (
    SANCTIONS_REVIEW_PENDING,
    get_kyc_by_account,
    update_kyc_record,
)
from utils.model_loader import load_models
from utils.session_utils import get_current_analyst, require_scored_df
from utils.shap_explainer import FEATURE_DESCRIPTIONS, get_model_xai_explanation

render_sidebar()

st.title("Case Investigation")
st.caption("Deep-dive into escalated transactions with XAI explanations and case management.")

require_scored_df()
scored_df = st.session_state["scored_df"]
scored_df = ensure_scored_defaults(scored_df)
st.session_state["scored_df"] = scored_df

selected_txn_id = st.session_state.get("selected_txn_id")
if selected_txn_id is None:
    st.warning("No transaction selected from Alert Queue.")
    flagged_options = scored_df[scored_df["rf_prediction"].astype(int) == 1]
    if flagged_options.empty:
        st.info("No flagged transactions available for investigation.")
        st.stop()
    selected_txn_id = st.selectbox(
        "Select transaction", flagged_options["transaction_id"].astype(str).tolist()
    )

rows = scored_df[scored_df["transaction_id"].astype(str) == str(selected_txn_id)]
if rows.empty:
    st.error("Selected transaction not found.")
    st.stop()

selected_txn  = rows.iloc[0]
analyst_id, actor_role = get_current_analyst()
case_record   = ensure_case_for_transaction(selected_txn, analyst_id)
existing_case = get_case_by_transaction(str(selected_txn["transaction_id"])) or case_record
st.session_state["selected_case_id"] = existing_case["case_id"]

tier        = str(selected_txn["risk_tier"])
tier_color  = RISK_TIER_COLORS.get(tier, "#cfd8dc")
score       = float(selected_txn["risk_score"])
case_status = existing_case.get("status", CASE_STATUS_OPEN)

# ── Status bar ────────────────────────────────────────────────────────────────
_status_colors = {
    CASE_STATUS_OPEN:      "#4da6ff",
    CASE_STATUS_IN_REVIEW: "#fb8c00",
    CASE_STATUS_ESCALATED: "#f44336",
    CASE_STATUS_RESOLVED:  "#4caf50",
}
_sc = _status_colors.get(case_status, "#888")

with st.container(border=True):
    _sb1, _sb2, _sb3 = st.columns(3)
    _sb1.markdown(f"Active case: **{existing_case['case_id']}**")
    _sb2.markdown(f"Transaction: **{selected_txn['transaction_id']}**")
    _sb3.markdown(
        f"Status: <span style='color:{_sc};font-weight:700'>{case_status}</span>",
        unsafe_allow_html=True,
    )

# ── XAI (computed once, used in right panel) ─────────────────────────────────
rf_model, cart_model, logit_model = load_models()
_x = prepare_model_matrix(scored_df[ENGINEERED_FEATURES + CATEGORICAL_FEATURES], rf_model.feature_names_in_)
_row_for_xai = _x.loc[[rows.index[0]]].copy()

try:
    top_features, plain_text, _ = get_model_xai_explanation(
        cart_model, logit_model, _row_for_xai, list(_x.columns)
    )
except Exception:
    top_features = [("amount_log", 0.0), ("cross_border", 0.0), ("cross_currency", 0.0)]
    plain_text   = "This transaction was flagged due to a combination of risk indicators."

st.session_state["shap_top3_text"] = "; ".join([f for f, _ in top_features[:3]])

# ── Layout ────────────────────────────────────────────────────────────────────
_left, _right = st.columns([2, 3], gap="medium")

# ════════════════════════════════════════════════════════════════════════════
# LEFT — Transaction Details + Case Actions
# ════════════════════════════════════════════════════════════════════════════
with _left:

    # Transaction Details
    with st.container(border=True):
        st.markdown("**Transaction Details**")
        st.divider()

        def _row(label: str, value: str, color: str | None = None) -> None:
            _lc, _vc = st.columns([1.2, 1.8])
            _lc.markdown(f"<span style='color:#666;font-size:13px'>{label}</span>", unsafe_allow_html=True)
            _val_html = (
                f"<span style='font-weight:700;color:{color}'>{value}</span>"
                if color else f"<span style='font-weight:700;color:#e0e0e0'>{value}</span>"
            )
            _vc.markdown(_val_html, unsafe_allow_html=True)

        _row("Transaction ID",  str(selected_txn["transaction_id"]))
        _row("Customer",        f"{selected_txn.get('customer_id', '—')}")
        _row("Amount",          f"${float(selected_txn['Amount']):,.0f}", "#f44336")
        _row("Date / Time",     f"{selected_txn['Date']} {selected_txn['Time']}")
        _row("Payment Type",    str(selected_txn["Payment_type"]))
        _row("Risk Score",      f"{score:.2f} — {tier}", tier_color)

        # CDD level from KYC
        kyc_row = get_kyc_by_account(str(selected_txn["Sender_account"]))
        _cdd_val = kyc_row["CDDLevel"] if kyc_row else "—"
        _row("CDD Level", _cdd_val)

    # MAS red-flag evidence panel
    with st.container(border=True):
        st.markdown("**🚩 MAS Red Flags**")
        _flag_defs = {
            "smurfing_flag": (
                "🔴 Smurfing / Structuring Detected",
                "MAS Notice 626 para 6.4",
            ),
            "uturn_flag": (
                "🔴 U-Turn Transaction",
                "MAS Appendix B-11(viii)",
            ),
            "rapid_movement_flag": (
                "🟠 Rapid Fund Movement",
                "MAS Appendix B-11(iii)",
            ),
            "dormant_spike_flag": (
                "🟠 Dormant Account Spike",
                "MAS Appendix B-11(iv)",
            ),
            "high_risk_jurisdiction": (
                "🔴 High-Risk Jurisdiction",
                "MAS Notice 626 para 8.6(a)/(b)",
            ),
            "profile_inconsistency_flag": (
                "🟠 Profile Inconsistency",
                "MAS Appendix B-11(i)/(v)",
            ),
            "cdd_threshold_breach": (
                "🟡 CDD Threshold Breach",
                "MAS Notice 626 para 6.3(b)",
            ),
            "cross_currency": (
                "🟡 Currency Mismatch",
                "MAS Notice 626 para 4.1(d)",
            ),
            "cross_border": (
                "🟡 Cross-Border Transfer",
                "MAS Notice 626 para 4.1(b)",
            ),
            "is_off_hours": (
                "🟡 Off-Hours Transaction",
                "MAS Notice 626 para 4.1(d)",
            ),
        }
        _active_flags = [
            (label, basis)
            for _col, (label, basis) in _flag_defs.items()
            if int(selected_txn.get(_col, 0)) == 1
        ]
        if _active_flags:
            for _label, _basis in _active_flags:
                st.markdown(f"- **{_label}**")
                st.caption(_basis)
            st.markdown(
                f"**Red Flag Score:** {int(selected_txn.get('red_flag_score', 0))} / 10  "
                f"| **Risk Tier:** {tier}"
            )
        else:
            st.success("No MAS red flags detected for this transaction.")

    # Case Actions
    with st.container(border=True):
        st.markdown("**Case Actions**")
        st.divider()

        customers      = get_customers()
        customer_mask  = customers["customer_id"].astype(str) == str(selected_txn["customer_id"])
        customer_row   = customers[customer_mask].iloc[0] if not customers.empty and customer_mask.any() else None
        sanctions_pend = bool(kyc_row) and str(kyc_row.get("SanctionsReview", "")) == SANCTIONS_REVIEW_PENDING
        recommended_cdd = recommend_for_case(kyc_row, tier, sanctions_pending=sanctions_pend)

        if kyc_row:
            if sanctions_pend:
                st.error(f"Sanctions review pending for {kyc_row['FullName']} — additional CDD required.")
            if recommended_cdd != kyc_row["CDDLevel"]:
                st.info(f"Recommended CDD: **{recommended_cdd}** (current: {kyc_row['CDDLevel']})")
        else:
            st.caption(f"No KYC record for `{selected_txn['Sender_account']}`. Enrol on KYC page to enable CDD.")

        default_cdd = existing_case.get("cdd_level") or recommended_cdd or CDD_LEVEL_STANDARD
        default_idx = CDD_LEVELS.index(default_cdd) if default_cdd in CDD_LEVELS else 1
        cdd_level   = st.radio("CDD Level", CDD_LEVELS, index=default_idx, horizontal=True)
        status      = st.selectbox(
            "Case Status", CASE_STATUSES,
            index=1 if existing_case.get("status") == CASE_STATUS_IN_REVIEW else 0,
        )
        notes = st.text_area("Investigation notes", value=existing_case.get("notes", ""), height=100)
        outcome_reason = st.text_input(
            "Resolution reason (required if resolving without STR)",
            value=existing_case.get("resolution", ""),
        )
        attachment_names = st.text_input(
            "Attachments (comma-separated)", value=existing_case.get("attachment_names", ""),
        )

        # Action buttons
        if st.button("File STR", type="primary", use_container_width=True):
            if not notes.strip():
                st.error("Investigation notes are required before filing an STR.")
            else:
                updated_case = update_case_record(
                    existing_case["case_id"],
                    {
                        "status": CASE_STATUS_ESCALATED, "cdd_level": cdd_level,
                        "notes": notes, "str_required": True,
                        "kyc_risk_tier": "High" if cdd_level == CDD_LEVEL_ENHANCED else existing_case.get("kyc_risk_tier", "Medium"),
                    },
                )
                st.session_state["str_case"] = {
                    "case_id":             updated_case["case_id"],
                    "customer_id":         str(selected_txn["customer_id"]),
                    "customer_name":       customer_row["customer_name"] if customer_row is not None else "",
                    "transaction_id":      str(selected_txn["transaction_id"]),
                    "date":                str(selected_txn["Date"]),
                    "sender_account":      str(selected_txn["Sender_account"]),
                    "receiver_account":    str(selected_txn["Receiver_account"]),
                    "amount":              float(selected_txn["Amount"]),
                    "payment_type":        str(selected_txn["Payment_type"]),
                    "risk_score":          score,
                    "risk_tier":           tier,
                    "cdd_level":           cdd_level,
                    "investigation_notes": notes,
                    "shap_top3":           st.session_state.get("shap_top3_text", ""),
                    "escalated_at":        datetime.now().isoformat(),
                    "escalated_by":        analyst_id,
                }
                log_action(
                    action="case_escalated_to_str",
                    transaction_id=str(selected_txn["transaction_id"]),
                    details=f"case_id={updated_case['case_id']}; cdd_level={cdd_level}",
                    analyst_id=analyst_id, module="cdd_module",
                    event_type="case_escalated_to_str", entity_type="case",
                    entity_id=updated_case["case_id"], actor_role=actor_role,
                    payload={"cdd_level": cdd_level, "notes_length": len(notes), "str_required": True},
                )
                st.switch_page("pages/5_STR_Generation.py")

        if st.button("Close Case", use_container_width=True):
            updated_case = update_case_record(
                existing_case["case_id"],
                {
                    "status": status, "cdd_level": cdd_level,
                    "notes": notes, "resolution": outcome_reason,
                    "str_required": cdd_level == CDD_LEVEL_ENHANCED,
                    "kyc_risk_tier": "High" if cdd_level == CDD_LEVEL_ENHANCED else ("Medium" if cdd_level == CDD_LEVEL_STANDARD else "Low"),
                },
            )
            attachment_list = [a.strip() for a in attachment_names.split(",") if a.strip()]
            attach_case_files(updated_case["case_id"], attachment_list)
            if customer_row is not None:
                customers.loc[customer_mask, "cdd_level"]      = cdd_level
                customers.loc[customer_mask, "kyc_risk_tier"]  = updated_case["kyc_risk_tier"]
                customers.loc[customer_mask, "last_review_date"] = str(pd.Timestamp.utcnow().date())
                customers.loc[customer_mask, "updated_at"]     = datetime.now().isoformat()
                upsert_customers(customers)
            if kyc_row:
                update_kyc_record(kyc_row["id"], {"CDDLevel": cdd_level, "RiskStatus": updated_case["kyc_risk_tier"]})
            log_action(
                action="cdd_case_updated",
                transaction_id=str(selected_txn["transaction_id"]),
                details=f"case_id={updated_case['case_id']}; cdd_level={cdd_level}; status={status}",
                analyst_id=analyst_id, module="cdd_module",
                event_type="cdd_case_updated", entity_type="case",
                entity_id=updated_case["case_id"], actor_role=actor_role,
                payload={"cdd_level": cdd_level, "status": status, "notes_length": len(notes)},
            )
            st.success("Case closed.")

        if st.button("Resolve — No STR Required", use_container_width=True):
            if not outcome_reason.strip():
                st.error("Please provide a resolution reason.")
            else:
                updated_case = update_case_record(
                    existing_case["case_id"],
                    {"status": CASE_STATUS_RESOLVED, "cdd_level": cdd_level,
                     "notes": notes, "resolution": outcome_reason, "str_required": False},
                )
                status_map = st.session_state.get("alert_status", {})
                status_map[str(selected_txn["transaction_id"])] = {"status": ALERT_STATUS_DISMISSED, "reason": outcome_reason}
                st.session_state["alert_status"] = status_map
                log_action(
                    action="case_resolved_no_str",
                    transaction_id=str(selected_txn["transaction_id"]),
                    details=f"case_id={updated_case['case_id']}; reason={outcome_reason}",
                    analyst_id=analyst_id, module="cdd_module",
                    event_type="case_resolved_no_str", entity_type="case",
                    entity_id=updated_case["case_id"], actor_role=actor_role,
                    payload={"cdd_level": cdd_level, "reason": outcome_reason},
                )
                st.success("Case resolved without STR.")

# ════════════════════════════════════════════════════════════════════════════
# RIGHT — Risk Explanation + Transaction History
# ════════════════════════════════════════════════════════════════════════════
with _right:

    # Risk Explanation
    with st.container(border=True, height=480):
        st.markdown("**Risk Explanation (Top 5 Drivers)**")
        st.divider()

        _bar_colors = ["#f44336", "#fb8c00", "#fdd835", "#4da6ff", "#888"]
        _max_val    = max((v for _, v in top_features), default=1) or 1
        _total_val  = sum(v for _, v in top_features) or 1

        _bars_html = ""
        for i, (feat, val) in enumerate(top_features[:5]):
            _clean = feat
            for pfx in ["Payment_type_", "Payment_currency_", "Received_currency_",
                        "Sender_bank_location_", "Receiver_bank_location_"]:
                if feat.startswith(pfx):
                    _clean = pfx[:-1]
                    break
            _label  = FEATURE_DESCRIPTIONS.get(_clean, _clean.replace("_", " ").title())
            _pct    = int(val / _max_val * 100)
            _pct_lbl = f"{int(val / _total_val * 100)}%"
            _c      = _bar_colors[i]
            _bars_html += (
                f"<div style='margin-bottom:14px'>"
                f"<div style='display:flex;justify-content:space-between;margin-bottom:4px'>"
                f"<span style='color:#ccc;font-size:13px'>{_label}</span>"
                f"<span style='color:{_c};font-weight:700;font-size:13px'>{_pct_lbl}</span>"
                f"</div>"
                f"<div style='background:#1e2130;border-radius:4px;height:10px'>"
                f"<div style='width:{_pct}%;background:{_c};height:100%;border-radius:4px'></div>"
                f"</div></div>"
            )
        st.markdown(_bars_html, unsafe_allow_html=True)

        # Narrative box
        st.markdown(
            f"<div style='background:#1a1d27;border:1px solid #2d3140;border-radius:8px;"
            f"padding:14px 16px;color:#888;font-size:13px;line-height:1.7;margin-top:4px'>"
            f"{plain_text}</div>",
            unsafe_allow_html=True,
        )

    # Transaction History
    with st.container(border=True):
        _sender_name = kyc_row["FullName"] if kyc_row else str(selected_txn["Sender_account"])
        st.markdown(f"**Transaction History — {_sender_name}**")
        st.divider()

        related = get_related_transactions(scored_df, selected_txn, window_days=30)
        if related.empty:
            st.info("No related transactions found in the ±30 day window.")
        else:
            # Amount over time line chart
            _hist = related.copy()
            _hist["_date"] = pd.to_datetime(_hist["Date"], errors="coerce")
            _hist = _hist.dropna(subset=["_date"]).sort_values("_date")
            if not _hist.empty:
                st.line_chart(_hist.set_index("_date")["Amount"], use_container_width=True)

            st.dataframe(
                related[[
                    "transaction_id", "Date", "Time",
                    "Receiver_account", "Amount", "risk_score", "risk_tier",
                ]],
                use_container_width=True,
                hide_index=True,
            )
