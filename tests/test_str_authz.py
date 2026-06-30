"""STR authorisation tests — covers role permissions, segregation of duties,
and the optional debug-bypass switch.

These tests do not need a Streamlit runtime; they monkey-patch
``utils.session_utils.st`` if needed, but ``gates_bypassed`` reads from the
real ``st.session_state`` dict via Streamlit's runtime-less compatibility
layer, so calls without a session state return ``False`` by default.
"""

from __future__ import annotations

import streamlit as st

from utils.constants import (
    ROLE_AML_ANALYST,
    ROLE_AUDITOR,
    ROLE_MLRO,
    ROLE_SENIOR_INVESTIGATOR,
    ROLE_SYS_ADMIN,
    STR_ACTION_DRAFT_SUBMIT,
    STR_ACTION_L1_APPROVE,
    STR_ACTION_L2_APPROVE,
)
from utils.str_authz import authorize, can_perform


def _empty_record() -> dict:
    return {"drafted_by": "", "l1_reviewer": "", "l2_reviewer": ""}


def _clear_bypass() -> None:
    st.session_state.pop("rbac_debug_bypass_gates", None)


# --- Role matrix -------------------------------------------------------------

def test_draft_submit_roles():
    _clear_bypass()
    assert can_perform(STR_ACTION_DRAFT_SUBMIT, ROLE_AML_ANALYST)
    assert can_perform(STR_ACTION_DRAFT_SUBMIT, ROLE_SENIOR_INVESTIGATOR)
    assert not can_perform(STR_ACTION_DRAFT_SUBMIT, ROLE_MLRO)
    assert not can_perform(STR_ACTION_DRAFT_SUBMIT, ROLE_AUDITOR)
    assert not can_perform(STR_ACTION_DRAFT_SUBMIT, ROLE_SYS_ADMIN)


def test_l1_approve_roles():
    _clear_bypass()
    assert can_perform(STR_ACTION_L1_APPROVE, ROLE_SENIOR_INVESTIGATOR)
    for role in (ROLE_AML_ANALYST, ROLE_MLRO, ROLE_AUDITOR, ROLE_SYS_ADMIN):
        assert not can_perform(STR_ACTION_L1_APPROVE, role), role


def test_l2_approve_roles():
    _clear_bypass()
    assert can_perform(STR_ACTION_L2_APPROVE, ROLE_MLRO)
    for role in (ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR, ROLE_AUDITOR, ROLE_SYS_ADMIN):
        assert not can_perform(STR_ACTION_L2_APPROVE, role), role


def test_no_legacy_admin_role():
    """Authorize must refuse a legacy 'Admin' role at every gate."""
    _clear_bypass()
    rec = _empty_record()
    for action in (STR_ACTION_DRAFT_SUBMIT, STR_ACTION_L1_APPROVE, STR_ACTION_L2_APPROVE):
        ok, level, _ = authorize(action, actor_id="legacy.admin", role="Admin", record=rec)
        assert not ok and level == "role", action


# --- Segregation of duties ---------------------------------------------------

def test_l1_blocks_drafter():
    _clear_bypass()
    rec = {"drafted_by": "alice.analyst"}
    ok, level, msg = authorize(
        STR_ACTION_L1_APPROVE,
        actor_id="alice.analyst",
        role=ROLE_SENIOR_INVESTIGATOR,  # role permits, SoD blocks
        record=rec,
    )
    assert not ok and level == "sod" and "drafted" in msg.lower()


def test_l2_blocks_drafter_and_l1_reviewer():
    _clear_bypass()
    rec = {"drafted_by": "alice.analyst", "l1_reviewer": "dan.invest"}
    # Drafter at L2
    ok, level, _ = authorize(STR_ACTION_L2_APPROVE, "alice.analyst", ROLE_MLRO, rec)
    assert not ok and level == "sod"
    # L1 reviewer at L2
    ok, level, _ = authorize(STR_ACTION_L2_APPROVE, "dan.invest", ROLE_MLRO, rec)
    assert not ok and level == "sod"


def test_l2_allows_independent_mlro():
    _clear_bypass()
    rec = {"drafted_by": "alice.analyst", "l1_reviewer": "dan.invest"}
    ok, level, _ = authorize(STR_ACTION_L2_APPROVE, "carol.mlro", ROLE_MLRO, rec)
    assert ok and level == "ok"


# --- Debug bypass ------------------------------------------------------------

def test_debug_bypass_overrides_role_and_sod():
    st.session_state["rbac_debug_bypass_gates"] = True
    try:
        rec = {"drafted_by": "alice.analyst", "l1_reviewer": "dan.invest"}
        # Auditor at L2 with SoD that would otherwise block — should pass.
        ok, level, msg = authorize(STR_ACTION_L2_APPROVE, "alice.analyst", ROLE_AUDITOR, rec)
        assert ok and level == "ok" and "bypass" in msg.lower()
    finally:
        _clear_bypass()
