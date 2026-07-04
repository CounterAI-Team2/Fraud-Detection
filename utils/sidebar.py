from __future__ import annotations

import streamlit as st

from utils.constants import (
    ALERT_STATUS_NEW,
    ANALYST_ROLES,
    CASE_OPEN_STATUSES,
    DEFAULT_ACTOR_ID,
    DEFAULT_ACTOR_ROLE,
    DEMO_IDENTITIES,
    LEGACY_ROLE_ALIASES,
    ROLE_LABELS,
    ROLE_SYS_ADMIN,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
)
from utils.data_store import get_cases, get_str_cases
from utils.kyc_store import get_kyc_customers


def _normalize_role(role: str) -> str:
    """Map any stored role string to a current role key (handles legacy values)."""
    if role in ANALYST_ROLES:
        return role
    return LEGACY_ROLE_ALIASES.get(role, DEFAULT_ACTOR_ROLE)


def _apply_demo_identity(user_id: str, role: str) -> None:
    st.session_state["current_actor_id"] = user_id
    st.session_state["current_actor_role"] = role


def render_sidebar() -> None:
    for key, default in [
        ("current_actor_id", DEFAULT_ACTOR_ID),
        ("current_actor_role", DEFAULT_ACTOR_ROLE),
        ("alert_status", {}),
        ("rbac_debug_bypass_gates", False),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Normalize any legacy role still in session state.
    st.session_state["current_actor_role"] = _normalize_role(
        st.session_state["current_actor_role"]
    )

    _scored = st.session_state.get("scored_df")
    _alert_map = st.session_state.get("alert_status", {})
    _pending_alerts = sum(1 for v in _alert_map.values() if v.get("status") == ALERT_STATUS_NEW)
    try:
        _cases_df = get_cases()
        _open_cases = int(_cases_df["status"].isin(CASE_OPEN_STATUSES).sum()) if not _cases_df.empty else 0
    except Exception:
        _open_cases = 0
    try:
        _strs_df = get_str_cases()
        _strs_review = int(_strs_df["status"].isin([STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2]).sum()) if not _strs_df.empty else 0
    except Exception:
        _strs_review = 0
    try:
        _kyc_df = get_kyc_customers()
        _critical = int((_kyc_df["RiskStatus"].astype(str) == "Critical").sum()) if not _kyc_df.empty else 0
    except Exception:
        _critical = 0

    with st.sidebar:
        st.session_state["current_actor_id"] = st.text_input(
            "User ID", value=st.session_state["current_actor_id"]
        )
        _current_role = st.session_state["current_actor_role"]
        _selected_role = st.selectbox(
            "Role",
            ANALYST_ROLES,
            index=ANALYST_ROLES.index(_current_role) if _current_role in ANALYST_ROLES else 0,
            format_func=lambda r: ROLE_LABELS.get(r, r),
        )
        st.session_state["current_actor_role"] = _selected_role

        # Debug bypass — explicit, visible, off by default.
        st.session_state["rbac_debug_bypass_gates"] = st.checkbox(
            "Debug: bypass gates",
            value=bool(st.session_state.get("rbac_debug_bypass_gates")),
            help="Solo testing only — disables every role and segregation-of-duties check.",
        )
        if st.session_state["rbac_debug_bypass_gates"]:
            st.warning("Debug bypass ON — role and SoD gates are disabled.")

        # System Administrator: demo identity directory + quick-switch.
        if _selected_role == ROLE_SYS_ADMIN:
            with st.expander("Demo identities (System Administrator)", expanded=False):
                st.caption(
                    "Switch the active session to any seeded demo identity. "
                    "User and role management is otherwise out of scope for the demo."
                )
                for ident in DEMO_IDENTITIES:
                    if st.button(
                        ident["display"],
                        key=f"sysadmin_switch_{ident['user_id']}",
                        use_container_width=True,
                        on_click=_apply_demo_identity,
                        args=(ident["user_id"], ident["role"]),
                    ):
                        pass

        st.divider()
        st.caption("Session Summary")
        with st.container(border=True):
            for label, value, color in [
                ("Pending Alerts",    str(_pending_alerts), "inherit"),
                ("Open Cases",        str(_open_cases),     "inherit"),
                ("STRs In Review",    str(_strs_review),    "inherit"),
                ("Critical Customers", str(_critical),      "inherit"),
            ]:
                c1, c2 = st.columns([2, 1])
                c1.markdown(label)
                c2.markdown(f"<div style='text-align:right;font-weight:bold;color:{color}'>{value}</div>", unsafe_allow_html=True)
            if _scored is not None:
                c1, c2 = st.columns([2, 1])
                c1.markdown("Dataset Loaded")
                c2.markdown(f"<div style='text-align:right;font-weight:bold;color:#00cc88'>{len(_scored):,} rows</div>", unsafe_allow_html=True)
