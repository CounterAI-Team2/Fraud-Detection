from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from utils.aml_services import build_governance_datasets
from utils.data_store import get_audit_events
from utils.sidebar import render_sidebar

render_sidebar()

st.title("AI Governance")
st.caption("Drift monitoring, analyst override tracking, and model performance.")

# ── Load data ─────────────────────────────────────────────────────────────────
datasets = build_governance_datasets()
hitl     = datasets["hitl"]
cases    = datasets["cases"]
registry = datasets["registry"]

# ── Compute drift metrics ─────────────────────────────────────────────────────
weekly_cases = pd.DataFrame()
alerts_df    = pd.DataFrame()

if not cases.empty:
    weekly_cases = cases.groupby("week").size().rename("case_count").to_frame()
    if not hitl.empty:
        weekly_fp = (
            hitl.assign(is_fp=hitl["corrected_label"].astype(str).eq("False Positive").astype(int))
            .groupby("week")["is_fp"]
            .mean()
            .rename("fp_rate")
        )
        weekly_cases = weekly_cases.join(weekly_fp, how="left")
    else:
        weekly_cases["fp_rate"] = 0.0
    weekly_cases["rolling_recall_proxy"] = 1 - weekly_cases["fp_rate"].fillna(0.0)
    weekly_cases["recall_drop_pp"]       = weekly_cases["rolling_recall_proxy"].diff() * 100
    weekly_cases["fp_rise_pp"]           = weekly_cases["fp_rate"].diff() * 100
    weekly_cases["recall_alert"]         = weekly_cases["recall_drop_pp"] < -3
    weekly_cases["fp_alert"]             = weekly_cases["fp_rise_pp"] > 5
    alerts_df = weekly_cases[(weekly_cases["recall_alert"]) | (weekly_cases["fp_alert"])]

# ── Top-level metrics ─────────────────────────────────────────────────────────
_override_rate = round(len(hitl) / max(len(cases), 1), 4) if not hitl.empty else "—"
_hitl_count    = len(hitl)
_model_version = str(registry.iloc[-1]["version"])  if not registry.empty else "—"
_model_id_sub  = str(registry.iloc[-1]["model_id"] or "—") if not registry.empty else "—"
_drift_count   = len(alerts_df)
_drift_color   = "#f44336" if _drift_count > 0 else "#4caf50"

_k1, _k2, _k3, _k4 = st.columns(4)
for _kcol, _klabel, _kval, _kcolor, _ksub in [
    (_k1, "OVERRIDE RATE",    str(_override_rate), "#fb8c00", "HITL corrections / total cases"),
    (_k2, "HITL CORRECTIONS", str(_hitl_count),    "#fdd835", "Analyst prediction overrides"),
    (_k3, "MODEL VERSION",    _model_version,      "#4da6ff", _model_id_sub),
    (_k4, "DRIFT ALERTS",     str(_drift_count),   _drift_color, "Threshold breaches this period"),
]:
    with _kcol:
        with st.container(border=True):
            st.markdown(
                f"<div style='padding:6px 0'>"
                f"<div style='font-size:11px;color:#555;text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:6px'>{_klabel}</div>"
                f"<div style='font-size:32px;font-weight:700;color:{_kcolor}'>"
                f"{_html.escape(str(_kval))}</div>"
                f"<div style='font-size:12px;color:#555;margin-top:4px'>"
                f"{_html.escape(str(_ksub))}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

st.markdown("<br>", unsafe_allow_html=True)

# ── Shared helpers ────────────────────────────────────────────────────────────
def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _hbar(label: str, value: int, max_val: int, color: str) -> str:
    pct = int(value / max_val * 100) if max_val else 0
    return (
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px'>"
        f"<div style='font-size:12px;color:#888;width:150px;flex-shrink:0;text-align:right'>"
        f"{_html.escape(label)}</div>"
        f"<div style='flex:1;background:#1e2130;border-radius:4px;height:10px'>"
        f"<div style='width:{pct}%;background:{color};height:100%;border-radius:4px'></div>"
        f"</div>"
        f"<div style='font-size:12px;font-weight:700;color:{color};width:40px;text-align:right'>"
        f"{value}</div>"
        f"</div>"
    )


_LABEL_BADGE_COLORS = {
    "False Positive":   ("#f44336", _hex_rgba("#f44336", 0.15)),
    "False Negative":   ("#fb8c00", _hex_rgba("#fb8c00", 0.15)),
    "Needs retraining": ("#4da6ff", _hex_rgba("#4da6ff", 0.15)),
    "Needs Retraining": ("#4da6ff", _hex_rgba("#4da6ff", 0.15)),
    "Other":            ("#888",    _hex_rgba("#888888", 0.15)),
}

_LABEL_HBAR_COLORS = {
    "False Positive":   "#f44336",
    "False Negative":   "#fb8c00",
    "Needs retraining": "#4da6ff",
    "Needs Retraining": "#4da6ff",
    "Other":            "#888",
}


def _correction_badge(label: str) -> str:
    clr, bg = _LABEL_BADGE_COLORS.get(label, ("#888", "rgba(136,136,136,0.15)"))
    return (
        f"<span style='display:inline-flex;padding:3px 9px;border-radius:10px;"
        f"font-size:11px;font-weight:600;background:{bg};color:{clr}'>"
        f"{_html.escape(str(label))}</span>"
    )


_TH_STYLE = (
    "color:#555;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;"
    "padding:10px 12px;text-align:left;border-bottom:1px solid #1e2130;background:#0e1117;"
    "white-space:nowrap"
)


def _thead(headers: list[str]) -> str:
    return (
        "<thead><tr>"
        + "".join(f"<th style='{_TH_STYLE}'>{h}</th>" for h in headers)
        + "</tr></thead>"
    )


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_drift, tab_hitl, tab_model = st.tabs(
    ["Drift Monitor", "HITL Override Tracker", "Model Registry"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Drift Monitor
# ══════════════════════════════════════════════════════════════════════════════
with tab_drift:

    if weekly_cases.empty:
        st.info("Case activity is required before drift indicators can be calculated.")
    else:
        # ── Status banner ─────────────────────────────────────────────────────
        _no_breach    = alerts_df.empty
        _b_main_color = "#4caf50" if _no_breach else "#f44336"
        _b_bg         = _hex_rgba(_b_main_color, 0.08)
        _b_border     = _hex_rgba(_b_main_color, 0.3)
        _b_title      = (
            "All Clear — No Threshold Breaches"
            if _no_breach else
            f"⚠ Breach Detected — {len(alerts_df)} week(s) flagged"
        )
        _b_desc = (
            "Recall proxy and false-positive rate are within acceptable limits across all recorded weeks."
            if _no_breach else
            "One or more weeks have breached recall drop or FP rise thresholds. Review the table below."
        )
        st.markdown(
            f"<div style='border-radius:10px;padding:16px 20px;display:flex;align-items:center;"
            f"gap:14px;margin-bottom:16px;background:{_b_bg};border:1px solid {_b_border}'>"
            f"<div style='width:12px;height:12px;border-radius:50%;flex-shrink:0;"
            f"background:{_b_main_color};box-shadow:0 0 8px {_b_main_color}'></div>"
            f"<div>"
            f"<div style='font-size:15px;font-weight:700;color:{_b_main_color}'>{_b_title}</div>"
            f"<div style='font-size:13px;color:#888;margin-top:2px'>{_b_desc}</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        # ── Two drift charts ──────────────────────────────────────────────────
        _dc1, _dc2 = st.columns(2, gap="medium")

        with _dc1:
            with st.container(border=True):
                st.markdown("**Recall Proxy (Weekly)**")
                st.markdown(
                    "<div style='font-size:12px;color:#555;margin-bottom:8px'>"
                    "Higher is better — drops &gt;3pp trigger an alert</div>",
                    unsafe_allow_html=True,
                )
                st.bar_chart(
                    weekly_cases[["rolling_recall_proxy"]].fillna(0.0).rename(
                        columns={"rolling_recall_proxy": "Recall Proxy"}
                    ),
                    height=140,
                )

        with _dc2:
            with st.container(border=True):
                st.markdown("**False Positive Rate (Weekly)**")
                st.markdown(
                    "<div style='font-size:12px;color:#555;margin-bottom:8px'>"
                    "Lower is better — rises &gt;5pp trigger an alert</div>",
                    unsafe_allow_html=True,
                )
                st.bar_chart(
                    weekly_cases[["fp_rate"]].fillna(0.0).rename(
                        columns={"fp_rate": "FP Rate"}
                    ),
                    height=140,
                )

        # ── Threshold reference ───────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Alert Thresholds**")
            st.divider()
            _tc1, _tc2, _tc3 = st.columns(3)
            for _tcol, _tlabel, _ttext, _tcolor in [
                (_tc1, "Recall Drop Alert",  "> 3 percentage points week-over-week", "#f44336"),
                (_tc2, "FP Rise Alert",      "> 5 percentage points week-over-week", "#fb8c00"),
                (_tc3, "Breach Action",      "Flag for retraining review",           "#888"),
            ]:
                _tcol.markdown(
                    f"<div style='display:flex;flex-direction:column;gap:3px'>"
                    f"<span style='font-size:11px;color:#555;text-transform:uppercase;"
                    f"letter-spacing:0.8px'>{_tlabel}</span>"
                    f"<span style='font-size:13px;font-weight:700;color:{_tcolor}'>{_ttext}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ── Breach table (only if breaches) ───────────────────────────────────
        if not alerts_df.empty:
            _b_headers = ["Week", "Case Count", "FP Rate", "Recall Drop (pp)", "FP Rise (pp)", "Recall Alert", "FP Alert"]
            _b_rows    = ""
            for _, _brow in alerts_df.reset_index().iterrows():
                _w_val  = _html.escape(str(_brow.get("week", _brow.get("index", "—"))))
                _cc     = int(_brow.get("case_count", 0) or 0)
                _fp_v   = round(float(_brow.get("fp_rate", 0) or 0), 3)
                _rd_v   = round(float(_brow.get("recall_drop_pp", 0) or 0), 2)
                _fr_v   = round(float(_brow.get("fp_rise_pp", 0) or 0), 2)
                _ra     = bool(_brow.get("recall_alert", False))
                _fa     = bool(_brow.get("fp_alert", False))
                _rd_clr = "#f44336" if _ra else "#888"
                _fr_clr = "#fb8c00" if _fa else "#888"
                _ra_html = (
                    "<span style='padding:3px 9px;border-radius:10px;font-size:11px;font-weight:600;"
                    "background:rgba(244,67,54,0.15);color:#f44336'>Yes</span>"
                    if _ra else "<span style='color:#555;font-size:12px'>No</span>"
                )
                _fa_html = (
                    "<span style='padding:3px 9px;border-radius:10px;font-size:11px;font-weight:600;"
                    "background:rgba(251,140,0,0.15);color:#fb8c00'>Yes</span>"
                    if _fa else "<span style='color:#555;font-size:12px'>No</span>"
                )
                _b_rows += (
                    f"<tr style='border-bottom:1px solid #1a1d27'>"
                    f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_w_val}</td>"
                    f"<td style='padding:10px 12px;color:#ccc'>{_cc}</td>"
                    f"<td style='padding:10px 12px;color:#f44336'>{_fp_v}</td>"
                    f"<td style='padding:10px 12px;color:{_rd_clr}'>{_rd_v}</td>"
                    f"<td style='padding:10px 12px;color:{_fr_clr}'>{_fr_v}</td>"
                    f"<td style='padding:10px 12px'>{_ra_html}</td>"
                    f"<td style='padding:10px 12px'>{_fa_html}</td>"
                    f"</tr>"
                )
            st.markdown(
                f"<div style='border:1px solid rgba(244,67,54,0.3);border-radius:10px;"
                f"overflow:hidden;margin-top:8px'>"
                f"<div style='padding:14px 20px;background:rgba(244,67,54,0.05)'>"
                f"<span style='font-size:14px;font-weight:700;color:#f44336'>⚠ Breach Weeks</span></div>"
                f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
                f"{_thead(_b_headers)}<tbody>{_b_rows}</tbody></table></div>",
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — HITL Override Tracker
# ══════════════════════════════════════════════════════════════════════════════
with tab_hitl:

    if hitl.empty:
        st.info("No HITL corrections logged yet.")
    else:
        # ── Daily override activity chart ─────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Daily Override Activity**")
            if "timestamp_dt" in hitl.columns:
                _daily_ov = (
                    hitl.set_index("timestamp_dt")
                    .resample("D")
                    .size()
                    .rename("Overrides")
                )
                st.bar_chart(_daily_ov, height=110)
            else:
                st.caption("Timestamp data unavailable.")

        # ── Overrides by analyst + Label distribution ─────────────────────────
        _hc1, _hc2 = st.columns(2, gap="medium")

        with _hc1:
            with st.container(border=True):
                st.markdown("**Overrides by Analyst**")
                st.divider()
                _analyst_counts = hitl.groupby("actor_id").size().sort_values(ascending=False)
                _analyst_max    = int(_analyst_counts.max()) if not _analyst_counts.empty else 1
                _hbars_a = "".join(
                    _hbar(str(_aid), int(_acnt), _analyst_max, "#fdd835")
                    for _aid, _acnt in _analyst_counts.items()
                )
                st.markdown(_hbars_a or "<div style='color:#555;font-size:13px'>No data.</div>", unsafe_allow_html=True)

        with _hc2:
            with st.container(border=True):
                st.markdown("**Correction Label Distribution**")
                st.divider()
                _label_counts = hitl["corrected_label"].value_counts()
                _label_max    = int(_label_counts.max()) if not _label_counts.empty else 1
                _hbars_l = "".join(
                    _hbar(str(_lbl), int(_lcnt), _label_max, _LABEL_HBAR_COLORS.get(str(_lbl), "#888"))
                    for _lbl, _lcnt in _label_counts.items()
                )
                st.markdown(_hbars_l or "<div style='color:#555;font-size:13px'>No data.</div>", unsafe_allow_html=True)

        # ── Top override reasons ──────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Top Override Reasons**")
            st.divider()
            _reason_counts = (
                hitl["reason"].fillna("No reason provided").astype(str).value_counts().head(8)
            )
            _reason_max = int(_reason_counts.max()) if not _reason_counts.empty else 1
            _hbars_r = "".join(
                _hbar(str(_rsn), int(_rcnt), _reason_max, "#888")
                for _rsn, _rcnt in _reason_counts.items()
            )
            st.markdown(_hbars_r or "<div style='color:#555;font-size:13px'>No data.</div>", unsafe_allow_html=True)

        # ── Recent HITL corrections table ─────────────────────────────────────
        _hitl_headers = ["Timestamp", "Transaction ID", "Original Prediction", "Correction Label", "Reason", "Analyst"]
        _hitl_recent  = (
            hitl.sort_values("timestamp_dt", ascending=False).head(20)
            if "timestamp_dt" in hitl.columns else hitl.head(20)
        )
        _hitl_rows = ""
        for _, _hr in _hitl_recent.iterrows():
            _ts  = str(_hr.get("timestamp_dt", _hr.get("timestamp_utc", "—")))[:16].replace("T", " ")
            _txn = _html.escape(str(_hr.get("transaction_id", "—") or "—"))
            _org = _html.escape(str(_hr.get("original_prediction", "—") or "—"))
            _lbl = str(_hr.get("corrected_label", "Other") or "Other")
            _rsn = _html.escape(str(_hr.get("reason", "—") or "—"))
            _act = _html.escape(str(_hr.get("actor_id", "—") or "—"))
            _hitl_rows += (
                f"<tr style='border-bottom:1px solid #1a1d27'>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px;white-space:nowrap'>{_ts}</td>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_txn}</td>"
                f"<td style='color:#888;font-size:12px;padding:10px 12px'>{_org}</td>"
                f"<td style='padding:10px 12px'>{_correction_badge(_lbl)}</td>"
                f"<td style='color:#666;font-size:12px;padding:10px 12px;max-width:200px;"
                f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{_rsn}</td>"
                f"<td style='color:#ccc;padding:10px 12px'>{_act}</td>"
                f"</tr>"
            )
        st.markdown(
            f"<div style='border:1px solid #1e2130;border-radius:10px;overflow:hidden'>"
            f"<div style='padding:14px 20px 0'>"
            f"<span style='font-size:14px;font-weight:700'>Recent HITL Corrections</span></div>"
            f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            f"{_thead(_hitl_headers)}<tbody>{_hitl_rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Model Registry
# ══════════════════════════════════════════════════════════════════════════════
with tab_model:

    if registry.empty:
        st.info("No model registry history found.")
    else:
        _cur = registry.iloc[-1]

        # Parse trained_on date
        _trained_raw = str(_cur.get("trained_on", "") or "")
        try:
            _trained_str = pd.to_datetime(_trained_raw).strftime("%Y-%m-%d")
        except Exception:
            _trained_str = _trained_raw[:10] if len(_trained_raw) >= 10 else "—"

        _mid    = _html.escape(str(_cur.get("model_id", "—") or "—"))
        _mver   = _html.escape(str(_cur.get("version", "—") or "—"))
        _mnotes = _html.escape(str(_cur.get("notes", "") or ""))

        # ── Model card ────────────────────────────────────────────────────────
        st.markdown(
            f"<div style='border:1px solid #1e2130;border-radius:10px;background:#0e1117;"
            f"padding:18px 20px;display:flex;align-items:flex-start;gap:20px;margin-bottom:16px'>"
            f"<div style='font-size:32px;flex-shrink:0'>🤖</div>"
            f"<div style='flex:1'>"
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px'>"
            f"<span style='font-size:16px;font-weight:700'>{_mid}</span>"
            f"<span style='padding:3px 10px;border-radius:10px;font-size:11px;font-weight:700;"
            f"background:rgba(77,166,255,0.15);color:#4da6ff'>{_mver} — Active</span>"
            f"</div>"
            f"<div style='font-size:12px;color:#666;display:flex;gap:16px;flex-wrap:wrap;margin-top:6px'>"
            f"<span>🗓 Trained: {_trained_str}</span>"
            f"<span>🏗 Type: Ensemble (RF + CART + Logit)</span>"
            f"<span>📦 Format: joblib bundle</span>"
            f"</div>"
            f"<div style='font-size:12px;color:#555;margin-top:8px;font-style:italic'>{_mnotes}</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        # ── Performance metric cards ──────────────────────────────────────────
        _pm1, _pm2, _pm3, _pm4 = st.columns(4)
        _any_metrics = False
        for _pcol, _plabel, _pfield, _pcolor in [
            (_pm1, "Precision",  "precision",   "#4caf50"),
            (_pm2, "Recall",     "recall",      "#4da6ff"),
            (_pm3, "F1 Score",   "f1",          "#fdd835"),
            (_pm4, "Error Rate", "error_rate",  "#fb8c00"),
        ]:
            _raw = _cur.get(_pfield, "")
            try:
                _num  = float(_raw)
                _disp = f"{_num:.4f}"
                _sub  = ""
                _col  = _pcolor
                _any_metrics = True
            except (TypeError, ValueError):
                _disp = "—"
                _sub  = "Not yet evaluated"
                _col  = "#333"
            with _pcol:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center;padding:8px 0'>"
                        f"<div style='font-size:11px;color:#555;text-transform:uppercase;"
                        f"letter-spacing:1px;margin-bottom:6px'>{_plabel}</div>"
                        f"<div style='font-size:28px;font-weight:700;color:{_col}'>{_disp}</div>"
                        f"<div style='font-size:11px;color:#333;margin-top:4px'>{_sub}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        # ── Info box (if no metrics yet) ──────────────────────────────────────
        if not _any_metrics:
            st.markdown(
                "<div style='background:rgba(77,166,255,0.04);border:1px solid #1e2130;"
                "border-radius:8px;padding:14px 18px;color:#555;font-size:13px;"
                "text-align:center;margin-bottom:16px'>"
                "Performance metrics will populate here once the model is evaluated against labelled test data. "
                "Retrain using <code style='color:#4da6ff;font-size:12px'>train_pretrained_models.py</code> "
                "with a labelled CSV to record metrics."
                "</div>",
                unsafe_allow_html=True,
            )

        # ── Version history table ─────────────────────────────────────────────
        _reg_sorted = registry.copy()
        if "trained_on" in _reg_sorted.columns:
            _reg_sorted = _reg_sorted.sort_values("trained_on", ascending=False)

        _ver_headers = ["Version", "Model ID", "Trained On", "Precision", "Recall", "F1", "Error Rate", "Notes"]
        _ver_rows    = ""
        for _, _mr in _reg_sorted.iterrows():
            _rv = _html.escape(str(_mr.get("version", "—") or "—"))
            _ri = _html.escape(str(_mr.get("model_id", "—") or "—"))
            try:
                _rt = pd.to_datetime(str(_mr.get("trained_on", ""))).strftime("%Y-%m-%d")
            except Exception:
                _rt = str(_mr.get("trained_on", "—"))[:10]
            _rp = str(_mr.get("precision",  "—") or "—")
            _rr = str(_mr.get("recall",     "—") or "—")
            _rf = str(_mr.get("f1",         "—") or "—")
            _re = str(_mr.get("error_rate", "—") or "—")
            _rn = _html.escape(str(_mr.get("notes", "") or ""))
            _ver_rows += (
                f"<tr style='border-bottom:1px solid #1a1d27'>"
                f"<td style='padding:10px 12px'>"
                f"<span style='padding:3px 9px;border-radius:10px;font-size:11px;font-weight:600;"
                f"background:rgba(77,166,255,0.15);color:#4da6ff'>{_rv}</span></td>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_ri}</td>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_rt}</td>"
                f"<td style='color:#333;font-size:13px;padding:10px 12px'>{_rp}</td>"
                f"<td style='color:#333;font-size:13px;padding:10px 12px'>{_rr}</td>"
                f"<td style='color:#333;font-size:13px;padding:10px 12px'>{_rf}</td>"
                f"<td style='color:#333;font-size:13px;padding:10px 12px'>{_re}</td>"
                f"<td style='color:#555;font-size:12px;padding:10px 12px'>{_rn}</td>"
                f"</tr>"
            )

        with st.container(border=True):
            st.markdown("**Version History**")
            st.markdown(
                f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
                f"{_thead(_ver_headers)}<tbody>{_ver_rows}</tbody></table>",
                unsafe_allow_html=True,
            )

        # ── Governance evidence export ─────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Governance Evidence Export**")
            st.markdown(
                "<div style='font-size:13px;color:#666;margin-bottom:14px'>"
                "Download a full audit trail of all system events for regulatory evidence or external review."
                "</div>",
                unsafe_allow_html=True,
            )
            audit_events = get_audit_events()
            if audit_events.empty:
                st.info("No v2 audit events available for export yet.")
            else:
                _csv_bytes = audit_events.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇  Download Governance Evidence CSV",
                    data=_csv_bytes,
                    file_name="governance_evidence.csv",
                    mime="text/csv",
                )