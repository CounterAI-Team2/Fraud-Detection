from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from utils.audit_logger import log_action
from utils.aml_services import ensure_scored_defaults, sync_customer_profiles
from utils.constants import (
    ALERT_STATUS_NEW,
    DATA_PREVIEW_LIMIT,
    DATA_UPLOAD_SCORE_ROLES,
    display_role,
)
from utils.data_store import get_model_registry
from utils.feature_engineering import (
    CATEGORICAL_FEATURES,
    ENGINEERED_FEATURES,
    RED_FLAG_COLS,
    SAML_REQUIRED_COLUMNS,
    apply_risk_tier,
    engineer_features,
    prepare_model_matrix,
    validate_schema,
)
from utils.kyc_store import apply_cdd_escalation_from_transactions
from utils.model_loader import load_models
from utils.session_utils import can_act, get_current_analyst, is_read_only
from utils.sidebar import render_sidebar

render_sidebar()

st.title("Transaction Data Upload")
st.caption("Upload SAML-D transaction data, score AML risk, and prepare alerts for investigation.")

_actor_id_top, _actor_role_top = get_current_analyst()
_can_score = can_act(_actor_role_top, DATA_UPLOAD_SCORE_ROLES)
_read_only = is_read_only(_actor_role_top)
if not _can_score:
    st.info(
        f"Your role ({display_role(_actor_role_top)}) has view-only access to this page. "
        "Upload and scoring controls are disabled."
    )

_feat_display = st.session_state.get("scored_df")
_meta = st.session_state.get("_scoring_meta", {})

with st.container(border=True):
    st.markdown("**Upload Transaction Dataset**")
    st.caption("SAML-D format CSV. Schema is validated before scoring begins.")
    _uploaded = st.file_uploader(
        "Transaction CSV", type=["csv"], label_visibility="collapsed",
        disabled=not _can_score,
    )
    if _uploaded is not None:
        _size_mb = getattr(_uploaded, "size", 0) / (1024 * 1024)
        st.success(f"Ready: `{_uploaded.name}` ({_size_mb:.2f} MB)")
    elif _meta.get("filename"):
        st.info(f"Last scored file: `{_meta['filename']}`")

    with st.expander("Expected CSV columns"):
        st.code(", ".join(SAML_REQUIRED_COLUMNS))

    st.divider()

    st.markdown("**Scoring Options**")
    _oc1, _oc2 = st.columns(2)
    _cap_rows = _oc1.number_input(
        "Row cap", min_value=1000, max_value=200_000, value=50_000, step=1000,
        disabled=not _can_score,
    )
    _threshold = _oc2.slider(
        "Risk threshold", min_value=0.05, max_value=0.95, value=0.50, step=0.05,
        disabled=not _can_score,
    )
    _score_btn = st.button(
        "Score Dataset",
        type="primary",
        use_container_width=True,
        disabled=_uploaded is None or not _can_score,
    )
    if _feat_display is not None:
        st.caption(
            f"Current session has **{len(_feat_display):,}** scored transactions. "
            "Upload and score a new CSV to replace them."
        )

if _score_btn and _uploaded is not None:
    _t0 = time.time()
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
    _feat["rf_prediction"] = _pred
    _feat["risk_score"] = _risk_prob
    _feat["risk_threshold"] = _threshold
    _feat = apply_risk_tier(_feat)
    _feat["prediction_wrong"] = ""
    _feat["prediction_feedback_reason"] = ""
    _feat = ensure_scored_defaults(_feat)

    _aid3, _arole3 = get_current_analyst()
    _statuses = {
        _txid: {"status": ALERT_STATUS_NEW, "reason": ""}
        for _txid in _feat["transaction_id"].astype(str)
    }
    st.session_state["scored_df"] = _feat
    st.session_state["alert_status"] = _statuses

    _customer_profiles = sync_customer_profiles(_feat)
    _cdd_changes = apply_cdd_escalation_from_transactions(_feat)
    _elapsed = time.time() - _t0
    _registry = get_model_registry().get("models", [])
    _cur_model = _registry[-1] if _registry else {}
    _meta = {
        "elapsed": _elapsed,
        "profiles": len(_customer_profiles),
        "cdd_changes": _cdd_changes,
        "filename": _uploaded.name,
        "flagged": int((_feat["rf_prediction"] == 1).sum()),
        "tier_counts": _feat["risk_tier"].value_counts().to_dict(),
        "threshold": _threshold,
        "model_label": f"{_cur_model.get('model_id', 'rf_model')} {_cur_model.get('version', '')}".strip(),
    }
    st.session_state["_scoring_meta"] = _meta
    _feat_display = _feat

    log_action(
        action="dataset_uploaded",
        details=f"filename={_uploaded.name}; row_count={len(_feat)}; flagged={int((_feat['rf_prediction']==1).sum())}",
        analyst_id=_aid3,
        module="data_upload",
        event_type="dataset_uploaded",
        entity_type="dataset",
        entity_id=_uploaded.name,
        actor_role=_arole3,
        payload={
            "filename": _uploaded.name,
            "row_count": len(_feat),
            "flagged_count": int((_feat["rf_prediction"] == 1).sum()),
            "tiers": _feat["risk_tier"].value_counts().to_dict(),
            "threshold": _threshold,
        },
    )
    for _, _txrow in _feat.iterrows():
        log_action(
            action="prediction_generated",
            transaction_id=str(_txrow["transaction_id"]),
            details=f"risk_score={float(_txrow['risk_score']):.4f}; risk_tier={_txrow['risk_tier']}",
            analyst_id=_aid3,
            module="risk_scoring",
            event_type="prediction_generated",
            entity_type="transaction",
            entity_id=str(_txrow["transaction_id"]),
            actor_role=_arole3,
            payload={
                "risk_score": round(float(_txrow["risk_score"]), 4),
                "risk_tier": _txrow["risk_tier"],
                "threshold": _threshold,
                "prediction": int(_txrow["rf_prediction"]),
            },
        )

with st.container(border=True):
    st.markdown("**Transaction Preview**")
    if _feat_display is None and _uploaded is None:
        st.info("Upload and score a CSV to preview scored transactions.")
    elif _feat_display is None and _uploaded is not None:
        st.info("File ready. Click **Score Dataset** to generate the transaction preview.")
    else:
        st.dataframe(
            _feat_display[[
                "transaction_id",
                "Date",
                "Sender_account",
                "Amount",
                "risk_score",
                "risk_tier",
                "rf_prediction",
            ]].head(DATA_PREVIEW_LIMIT),
            use_container_width=True,
            hide_index=True,
        )

with st.container(border=True):
    st.markdown("**Scoring Results**")
    if _feat_display is None:
        st.markdown(
            "<div style='text-align:center;padding:28px 0;color:#444'>"
            "<div style='font-size:32px;margin-bottom:8px'>📂</div>"
            "<div>Upload and score a CSV to see results</div></div>",
            unsafe_allow_html=True,
        )
    else:
        _model_label = _meta.get("model_label", "rf_model")
        st.caption(
            f"Processed in {_meta.get('elapsed', 0):.2f}s"
            f" &nbsp;·&nbsp; Model: {_model_label}"
            f" &nbsp;·&nbsp; Threshold: {_meta.get('threshold', _threshold)}"
        )
        st.caption("MAS red-flag features active: " + ", ".join(RED_FLAG_COLS))

        _sm1, _sm2, _sm3, _sm4 = st.columns(4)
        _flagged = int(_meta.get("flagged", 0))
        _flag_rate = (_flagged / len(_feat_display) * 100) if len(_feat_display) else 0.0
        with _sm1:
            with st.container(border=True):
                st.metric("Transactions Scored", f"{len(_feat_display):,}")
        with _sm2:
            with st.container(border=True):
                st.metric("Flagged", f"{_flagged:,}", f"{_flag_rate:.1f}%")
        with _sm3:
            with st.container(border=True):
                st.metric("Profiles Synced", f"{_meta.get('profiles', 0):,}")
        with _sm4:
            with st.container(border=True):
                st.metric("Processing Time", f"{_meta.get('elapsed', 0):.2f}s")

        st.markdown("**Risk Tier Breakdown**")
        _tier_counts = _meta.get("tier_counts", _feat_display["risk_tier"].value_counts().to_dict())
        _total_count = sum(_tier_counts.values()) or len(_feat_display) or 1
        _tier_colors = {"High": "#f44336", "Medium": "#fb8c00", "Low": "#64dd17"}
        _bars_html = ""
        for _tier, _color in _tier_colors.items():
            _cnt = _tier_counts.get(_tier, 0)
            _pct = round(_cnt / _total_count * 100, 1)
            _bars_html += (
                f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>"
                f"<span style='color:#888;font-size:12px;width:60px;text-align:right'>{_tier}</span>"
                f"<div style='flex:1;background:#1e2130;border-radius:4px;height:12px'>"
                f"<div style='width:{_pct}%;background:{_color};height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<span style='color:{_color};font-weight:700;font-size:13px;width:86px'>"
                f"{_cnt:,} · {_pct}%</span>"
                f"</div>"
            )
        st.markdown(_bars_html, unsafe_allow_html=True)

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
