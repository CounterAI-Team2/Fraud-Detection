"""Maker-checker authorization for the STR workflow.

Two independent controls gate every STR transition:

1. **Role permission** (`can_perform`) — does the acting user's role include the
   right to perform this gate's action at all?
2. **Segregation of duties** (`sod_violation`) — is the acting user a *different*
   person from those who already cleared earlier gates (maker != checker)?

Both must pass before a transition button is enabled.
"""

from __future__ import annotations

from utils.constants import (
    STR_ACTION_DRAFT_SUBMIT,
    STR_ACTION_L1_APPROVE,
    STR_ACTION_L2_APPROVE,
    STR_ROLE_PERMISSIONS,
    STR_STATUS_DRAFT,
    STR_STATUS_L1,
    STR_STATUS_L2,
    display_role,
)
from utils.session_utils import gates_bypassed

# Map the STR's current status to the action that advances it.
_STATUS_TO_ACTION = {
    STR_STATUS_DRAFT: STR_ACTION_DRAFT_SUBMIT,
    STR_STATUS_L1:    STR_ACTION_L1_APPROVE,
    STR_STATUS_L2:    STR_ACTION_L2_APPROVE,
}


def gate_for_status(status: str) -> str | None:
    """Return the action that advances an STR from ``status`` (or None if terminal)."""
    return _STATUS_TO_ACTION.get(status)


def allowed_roles(action: str) -> set[str]:
    return STR_ROLE_PERMISSIONS.get(action, set())


def can_perform(action: str, role: str) -> bool:
    """True if ``role`` is permitted to perform ``action``."""
    return role in allowed_roles(action)


def sod_violation(action: str, actor_id: str, record: dict) -> str | None:
    """Return a human-readable reason if performing ``action`` as ``actor_id`` would
    breach segregation of duties, else ``None``.

    - Draft -> L1: the maker submits their own draft; no SoD constraint.
    - L1 approve: the L1 reviewer must differ from the drafter.
    - L2 approve: the L2 reviewer must differ from both the drafter and the L1 reviewer.
    """
    actor_id = (actor_id or "").strip()
    drafted_by = str(record.get("drafted_by", "") or "").strip()
    l1_reviewer = str(record.get("l1_reviewer", "") or "").strip()

    if action == STR_ACTION_L1_APPROVE:
        if actor_id and actor_id == drafted_by:
            return "You drafted this STR and cannot also approve its L1 review."
    elif action == STR_ACTION_L2_APPROVE:
        if actor_id and actor_id == drafted_by:
            return "You drafted this STR and cannot also approve it at L2."
        if actor_id and actor_id == l1_reviewer:
            return "You performed the L1 review and cannot also approve it at L2."
    return None


def authorize(action: str, actor_id: str, role: str, record: dict) -> tuple[bool, str, str]:
    """Combined check.

    Returns ``(allowed, level, message)`` where ``level`` is one of
    ``"ok" | "role" | "sod"`` so the UI can colour the banner accordingly.
    """
    if action is None:
        return False, "role", "This STR is already approved — no further action."
    if gates_bypassed():
        return True, "ok", "Debug bypass active — gates ignored for solo testing."
    if not can_perform(action, role):
        roles = ", ".join(display_role(r) for r in sorted(allowed_roles(action)))
        return False, "role", f"Your role ({display_role(role)}) cannot perform this step. Requires: {roles}."
    sod = sod_violation(action, actor_id, record)
    if sod:
        return False, "sod", f"Segregation of duties: {sod}"
    return True, "ok", f"You ({display_role(role)} · {actor_id}) are authorised to perform this step."