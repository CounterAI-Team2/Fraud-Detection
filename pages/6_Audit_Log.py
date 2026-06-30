from __future__ import annotations

import html as _html
from datetime import date

import pandas as pd
import streamlit as st

from utils.audit_logger import read_audit_events
from utils.constants import AUDIT_SEE_ALL_ROLES, display_role
from utils.session_utils import get_current_analyst
from utils.sidebar import render_sidebar

render_sidebar()

st.title("Audit Log")
st.caption("Full compliance trail and activity history for all system actions.")

current_actor, actor_role = get_current_analyst()
_see_all = actor_role in AUDIT_SEE_ALL_ROLES

# ── Load data ─────────────────────────────────────────────────────────────────
events = pd.DataFrame(read_audit_events())
if not events.empty:
    events["timestamp_utc"] = pd.to_datetime(events["timestamp_utc"], errors="coerce", utc=True)

_today = date.today()

# ── Always-visible metrics ────────────────────────────────────────────────────
_total   = len(events) if not events.empty else 0
_today_n = int(events["timestamp_utc"].dt.date.eq(_today).sum()) if not events.empty else 0
_users   = int(events["actor_id"].dropna().nunique()) if not events.empty else 0
_modules = int(events["module"].dropna().nunique()) if not events.empty else 0

_hm1, _hm2, _hm3, _hm4 = st.columns(4)
for _hmcol, _hmlabel, _hmval, _hmcolor, _hmsub in [
    (_hm1, "TOTAL EVENTS",  _total,   "#4da6ff", "All recorded actions"),
    (_hm2, "EVENTS TODAY",  _today_n, "#4caf50", "Since 00:00 UTC"),
    (_hm3, "ACTIVE USERS",  _users,   "#fdd835", "Unique actors logged"),
    (_hm4, "MODULES",       _modules, "#fb8c00", "With recorded activity"),
]:
    with _hmcol:
        with st.container(border=True):
            st.markdown(
                f"<div style='padding:6px 0'>"
                f"<div style='font-size:11px;color:#555;text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:6px'>{_hmlabel}</div>"
                f"<div style='font-size:32px;font-weight:700;color:{_hmcolor}'>{_hmval}</div>"
                f"<div style='font-size:12px;color:#555;margin-top:4px'>{_hmsub}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

st.markdown("<br>", unsafe_allow_html=True)

# ── Shared helpers ────────────────────────────────────────────────────────────
_MODULE_COLOR = {
    "alert_queue":        "#fb8c00",
    "str_workflow":       "#4da6ff",
    "case_investigation": "#fdd835",
    "kyc_screening":      "#4caf50",
    "data_upload":        "#64dd17",
    "general":            "#888",
}


def _badge_for_event(event_type: str):
    """Return (text_color, bg_rgba) for an event type string."""
    et = str(event_type).lower()
    if "alert" in et:
        return "#fb8c00", "rgba(251,140,0,0.15)"
    if "str" in et:
        return "#4da6ff", "rgba(77,166,255,0.15)"
    if "case" in et:
        return "#fdd835", "rgba(253,216,53,0.15)"
    if "kyc" in et or "enrol" in et:
        return "#4caf50", "rgba(76,175,80,0.15)"
    if "upload" in et or "data" in et:
        return "#64dd17", "rgba(100,221,23,0.15)"
    return "#888", "rgba(136,136,136,0.15)"


def _key_info(payload) -> str:
    """Extract the most readable single key-value from a payload dict."""
    if not isinstance(payload, dict) or not payload:
        return "—"
    for key in ("status", "reason", "reference_number", "risk_tier", "threshold", "rows", "details"):
        val = payload.get(key)
        if val:
            return f"{key}={str(val)[:40]}"
    k, v = next(iter(payload.items()))
    return f"{k}={str(v)[:40]}"


def _hbar(label: str, value: int, max_val: int, color: str) -> str:
    pct = int(value / max_val * 100) if max_val else 0
    return (
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:10px'>"
        f"<div style='font-size:12px;color:#888;width:160px;flex-shrink:0;text-align:right'>{_html.escape(label)}</div>"
        f"<div style='flex:1;background:#1e2130;border-radius:4px;height:10px'>"
        f"<div style='width:{pct}%;background:{color};height:100%;border-radius:4px'></div>"
        f"</div>"
        f"<div style='font-size:12px;font-weight:700;color:{color};width:36px;text-align:right'>{value}</div>"
        f"</div>"
    )


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_trail, tab_summary = st.tabs(["Compliance Audit Trail", "Activity Summary"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Compliance Audit Trail
# ══════════════════════════════════════════════════════════════════════════════
with tab_trail:

    # See-all roles (MLRO, Auditor, System Administrator) see every actor's events;
    # others only see their own.
    if _see_all:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:6px;padding:6px 12px;"
            f"background:rgba(77,166,255,0.07);border:1px solid rgba(77,166,255,0.2);"
            f"border-radius:6px;font-size:12px;color:#4da6ff;margin-bottom:14px'>"
            f"● {_html.escape(display_role(actor_role))} view — showing all users' events.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:6px;padding:6px 12px;"
            f"background:rgba(253,216,53,0.07);border:1px solid rgba(253,216,53,0.2);"
            f"border-radius:6px;font-size:12px;color:#fdd835;margin-bottom:14px'>"
            f"● Showing events for <strong>{_html.escape(current_actor)}</strong> only.</div>",
            unsafe_allow_html=True,
        )

    if events.empty:
        st.info("No compliance audit events recorded yet.")
    else:
        # Role filter applied upfront
        view = events.copy()
        if not _see_all:
            view = view[view["actor_id"].astype(str) == current_actor]

        # ── Filters ──────────────────────────────────────────────────────────
        _fc1, _fc2, _fc3, _fc4, _fc5 = st.columns([3, 1.5, 1.5, 1.5, 2])

        _search  = _fc1.text_input(
            "Search",
            placeholder="Search event type / entity ID / transaction ID...",
            label_visibility="collapsed",
            key="aud_search",
        )
        _sel_mod = _fc2.selectbox(
            "Module", ["All"] + sorted(events["module"].dropna().unique().tolist()), key="aud_module"
        )
        _sel_evt = _fc3.selectbox(
            "Event Type", ["All"] + sorted(events["event_type"].dropna().unique().tolist()), key="aud_event"
        )
        _user_opts = sorted(events["actor_id"].dropna().unique().tolist())
        _sel_usr = _fc4.selectbox(
            "User",
            ["All"] + _user_opts,
            disabled=not _see_all,
            key="aud_user",
        )
        _min_d = view["timestamp_utc"].min()
        _max_d = view["timestamp_utc"].max()
        _dr = _fc5.date_input(
            "Date Range",
            value=(
                _min_d.date() if pd.notna(_min_d) else _today,
                _max_d.date() if pd.notna(_max_d) else _today,
            ),
            key="aud_daterange",
        )

        # Apply filters
        if _sel_mod != "All":
            view = view[view["module"] == _sel_mod]
        if _sel_evt != "All":
            view = view[view["event_type"] == _sel_evt]
        if _sel_usr != "All" and _see_all:
            view = view[view["actor_id"] == _sel_usr]
        if _search.strip():
            _needle = _search.strip().lower()
            view = view[
                view["event_type"].astype(str).str.lower().str.contains(_needle, na=False)
                | view["entity_id"].astype(str).str.lower().str.contains(_needle, na=False)
                | view["transaction_id"].astype(str).str.lower().str.contains(_needle, na=False)
                | view["module"].astype(str).str.lower().str.contains(_needle, na=False)
            ]
        if isinstance(_dr, tuple) and len(_dr) == 2 and _dr[0] and _dr[1]:
            _start = pd.Timestamp(_dr[0], tz="UTC")
            _end   = pd.Timestamp(_dr[1], tz="UTC") + pd.Timedelta(days=1)
            view   = view[(view["timestamp_utc"] >= _start) & (view["timestamp_utc"] < _end)]

        view = view.sort_values("timestamp_utc", ascending=False)

        # ── Events per Day chart ──────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Events per Day**")
            _chart_data = (
                view.set_index("timestamp_utc")
                .resample("D")
                .size()
                .rename("Events")
            )
            if not _chart_data.empty:
                st.bar_chart(_chart_data, height=130)
            else:
                st.caption("No events in selected range.")

        # ── Events table ──────────────────────────────────────────────────────
        _TABLE_LIMIT = 200
        _TH = (
            "color:#555;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;"
            "padding:10px 12px;text-align:left;border-bottom:1px solid #1e2130;white-space:nowrap;"
            "background:#0e1117"
        )
        _headers = ["Timestamp (UTC)", "Event Type", "Module", "Entity", "Transaction ID", "User", "Role", "Key Info"]
        _thead_html = (
            "<thead><tr>"
            + "".join(f"<th style='{_TH}'>{h}</th>" for h in _headers)
            + "</tr></thead>"
        )

        _rows_html = ""
        for _, _row in view.head(_TABLE_LIMIT).iterrows():
            _et        = str(_row.get("event_type", ""))
            _clr, _bg  = _badge_for_event(_et)
            _mod_val   = str(_row.get("module", "—") or "—")
            _mod_clr   = _MODULE_COLOR.get(_mod_val, "#888")
            _ts        = str(_row.get("timestamp_utc", ""))[:19].replace("T", " ")
            _entity    = _html.escape(str(_row.get("entity_id", "—") or "—"))
            _txn       = _html.escape(str(_row.get("transaction_id", "—") or "—"))
            _user      = _html.escape(str(_row.get("actor_id", "—") or "—"))
            _role_raw  = str(_row.get("actor_role", "—") or "—")
            _role      = _html.escape(display_role(_role_raw) if _role_raw != "—" else _role_raw)
            _ki        = _html.escape(_key_info(_row.get("payload", {})))

            _badge_html = (
                f"<span style='display:inline-flex;align-items:center;padding:3px 9px;"
                f"border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;"
                f"background:{_bg};color:{_clr}'>{_html.escape(_et)}</span>"
            )
            _mod_badge_html = (
                f"<span style='font-size:11px;padding:2px 7px;border-radius:4px;"
                f"background:#1e2130;color:{_mod_clr}'>{_html.escape(_mod_val)}</span>"
            )
            _rows_html += (
                f"<tr style='border-bottom:1px solid #1a1d27'>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;white-space:nowrap;padding:10px 12px'>{_ts}</td>"
                f"<td style='padding:10px 12px'>{_badge_html}</td>"
                f"<td style='padding:10px 12px'>{_mod_badge_html}</td>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_entity}</td>"
                f"<td style='font-family:monospace;font-size:12px;color:#888;padding:10px 12px'>{_txn}</td>"
                f"<td style='color:#ccc;padding:10px 12px'>{_user}</td>"
                f"<td style='color:#555;font-size:12px;padding:10px 12px'>{_role}</td>"
                f"<td style='font-size:12px;color:#666;max-width:240px;overflow:hidden;"
                f"text-overflow:ellipsis;white-space:nowrap;padding:10px 12px'>{_ki}</td>"
                f"</tr>"
            )

        st.markdown(
            f"<div style='border:1px solid #1e2130;border-radius:10px;overflow:hidden'>"
            f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            f"{_thead_html}<tbody>{_rows_html}</tbody>"
            f"</table></div>",
            unsafe_allow_html=True,
        )

        if len(view) > _TABLE_LIMIT:
            st.caption(f"Showing {_TABLE_LIMIT} of {len(view)} events. Use filters to narrow down.")

        # ── Download ──────────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        _csv = view.drop(columns=["payload"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇  Download Compliance Audit Trail CSV",
            data=_csv,
            file_name="audit_log_export.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Activity Summary
# ══════════════════════════════════════════════════════════════════════════════
with tab_summary:

    if events.empty:
        st.info("No events to summarise yet.")
    else:
        _col1, _col2 = st.columns(2, gap="medium")

        # ── Events by Module ──────────────────────────────────────────────────
        with _col1:
            with st.container(border=True):
                st.markdown("**Events by Module**")
                st.divider()
                _mod_counts = events["module"].dropna().value_counts()
                _mod_max    = int(_mod_counts.max()) if not _mod_counts.empty else 1
                _hbars_mod  = ""
                for _mod, _cnt in _mod_counts.items():
                    _c = _MODULE_COLOR.get(str(_mod), "#888")
                    _hbars_mod += _hbar(str(_mod), int(_cnt), _mod_max, _c)
                if _hbars_mod:
                    st.markdown(_hbars_mod, unsafe_allow_html=True)
                else:
                    st.caption("No data.")

        # ── Events by Type ────────────────────────────────────────────────────
        with _col2:
            with st.container(border=True):
                st.markdown("**Events by Type**")
                st.divider()
                _evt_counts = events["event_type"].dropna().value_counts().head(8)
                _evt_max    = int(_evt_counts.max()) if not _evt_counts.empty else 1
                _hbars_evt  = ""
                for _et, _cnt in _evt_counts.items():
                    _c, _ = _badge_for_event(str(_et))
                    _hbars_evt += _hbar(str(_et), int(_cnt), _evt_max, _c)
                if _hbars_evt:
                    st.markdown(_hbars_evt, unsafe_allow_html=True)
                else:
                    st.caption("No data.")

        # ── Daily Activity timeline ───────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**Daily Activity — Last 30 Days**")
            _daily = (
                events.set_index("timestamp_utc")
                .resample("D")
                .size()
                .rename("Events")
                .tail(30)
            )
            if not _daily.empty:
                st.bar_chart(_daily, height=150)
            else:
                st.caption("No activity data.")

        _col3, _col4 = st.columns(2, gap="medium")

        # ── Top Users ─────────────────────────────────────────────────────────
        with _col3:
            with st.container(border=True):
                st.markdown("**Top Users by Activity**")
                st.divider()
                _user_counts = (
                    events.groupby(["actor_id", "actor_role"])
                    .size()
                    .reset_index(name="count")
                    .sort_values("count", ascending=False)
                    .head(8)
                )
                if _user_counts.empty:
                    st.caption("No data.")
                else:
                    _user_html = ""
                    for _, _urow in _user_counts.iterrows():
                        _uid   = _html.escape(str(_urow.get("actor_id", "—")))
                        _urole_raw = str(_urow.get("actor_role", "—"))
                        _urole = _html.escape(display_role(_urole_raw) if _urole_raw != "—" else _urole_raw)
                        _ucnt  = int(_urow["count"])
                        _border = "border-bottom:1px solid #1e2130"
                        _user_html += (
                            f"<div style='display:flex;justify-content:space-between;align-items:center;"
                            f"padding:9px 0;{_border}'>"
                            f"<div><span style='font-size:13px;color:#ccc'>{_uid}</span>"
                            f"<span style='font-size:11px;color:#555;margin-left:8px'>{_urole}</span></div>"
                            f"<span style='font-size:13px;font-weight:700;color:#4da6ff'>{_ucnt}</span>"
                            f"</div>"
                        )
                    st.markdown(_user_html, unsafe_allow_html=True)

        # ── Alert Decisions ───────────────────────────────────────────────────
        with _col4:
            with st.container(border=True):
                st.markdown("**Alert Decisions**")
                st.divider()
                _esc_count = int(events["event_type"].astype(str).str.contains("escalat", na=False).sum())
                _dis_count = int(events["event_type"].astype(str).str.contains("dismiss", na=False).sum())
                _total_dec = _esc_count + _dis_count or 1
                _esc_rate  = round(_esc_count / _total_dec * 100, 1)
                _dec_max   = max(_esc_count, _dis_count) or 1

                st.markdown(
                    _hbar("Escalated", _esc_count, _dec_max, "#4da6ff")
                    + _hbar("Dismissed", _dis_count, _dec_max, "#555"),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='margin-top:18px'>"
                    f"<div style='font-size:11px;color:#555;margin-bottom:6px;"
                    f"text-transform:uppercase;letter-spacing:1px'>Escalation Rate</div>"
                    f"<div style='font-size:28px;font-weight:700;color:#4caf50'>{_esc_rate}%</div>"
                    f"<div style='font-size:12px;color:#555;margin-top:2px'>"
                    f"of reviewed alerts escalated to cases</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )