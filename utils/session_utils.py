from __future__ import annotations

import streamlit as st

from utils.constants import DEFAULT_ACTOR_ID, DEFAULT_ACTOR_ROLE


def get_current_analyst() -> tuple[str, str]:
    actor_id   = st.session_state.get("current_actor_id",   DEFAULT_ACTOR_ID)
    actor_role = st.session_state.get("current_actor_role", DEFAULT_ACTOR_ROLE)
    return actor_id, actor_role


def require_scored_df() -> None:
    """Stop the page early if no scored dataset is in session state."""
    if st.session_state.get("scored_df") is None:
        st.error("No scored dataset found. Please upload and score data on Page 1 first.")
        st.stop()


def first_row_as_dict(df) -> dict | None:
    return df.iloc[0].to_dict() if not df.empty else None
