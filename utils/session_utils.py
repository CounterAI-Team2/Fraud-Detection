from __future__ import annotations

import streamlit as st

from utils.constants import DEFAULT_ACTOR_ID, DEFAULT_ACTOR_ROLE, ROLE_AUDITOR


def get_current_analyst() -> tuple[str, str]:
    actor_id   = st.session_state.get("current_actor_id",   DEFAULT_ACTOR_ID)
    actor_role = st.session_state.get("current_actor_role", DEFAULT_ACTOR_ROLE)
    return actor_id, actor_role


def is_read_only(role: str) -> bool:
    """Auditor sees everything but cannot perform any action."""
    return role == ROLE_AUDITOR


def gates_bypassed() -> bool:
    """Debug toggle for solo testing — bypasses every role and SoD gate.

    The toggle lives in the sidebar and is off by default. Never wire this to a
    role; it must be an explicit, visible session flag.
    """
    return bool(st.session_state.get("rbac_debug_bypass_gates"))


def can_act(role: str, allowed: set[str]) -> bool:
    """Thin helper: role is in the allowed set, or gates are bypassed."""
    return gates_bypassed() or role in allowed


def require_scored_df() -> None:
    """Stop the page early if no scored dataset is in session state."""
    if st.session_state.get("scored_df") is None:
        st.error("No scored dataset found. Please upload and score data on the Transaction Data Upload page first.")
        st.stop()


def first_row_as_dict(df) -> dict | None:
    return df.iloc[0].to_dict() if not df.empty else None
