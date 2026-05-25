"""
CDD recommendation rules, loosely aligned to MAS Notice 626 and TFS guidance.

This is a prototype heuristic, not legal advice. It maps the three CDD tiers
(Simplified / Standard / Enhanced) defined in ``utils.constants`` to a small
set of inputs the rest of the app already tracks: the customer's current KYC
risk status, the highest transaction risk tier their account has triggered,
and whether a sanctions name match is still pending review.
"""
from __future__ import annotations

from utils.kyc_store import (
    CDD_ENHANCED,
    CDD_SIMPLIFIED,
    CDD_STANDARD,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
)

_RISK_RANK = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2}
_TIER_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
_CDD_RANK = {CDD_SIMPLIFIED: 0, CDD_STANDARD: 1, CDD_ENHANCED: 2}


def _normalize(value: str | None, default: str) -> str:
    text = (value or "").strip()
    return text if text else default


def recommend_risk_status(current_risk: str, top_txn_tier: str) -> str:
    """Promote (never demote) the KYC RiskStatus based on a flagged transaction."""
    current = _normalize(current_risk, RISK_LOW)
    tier = _normalize(top_txn_tier, "Medium")

    if tier in {"Critical", "High"}:
        target = RISK_HIGH
    elif tier == "Medium":
        target = RISK_MEDIUM
    else:
        target = current

    if _RISK_RANK.get(target, 0) > _RISK_RANK.get(current, 0):
        return target
    return current


def recommend_cdd_level(
    current_cdd: str,
    risk_status: str,
    top_txn_tier: str | None = None,
    sanctions_pending: bool = False,
) -> str:
    """
    Decide the recommended CDD level. Returns the higher of the current level
    and what the inputs would justify (so analysts can downgrade explicitly
    in Case Investigation, but automation never lowers the bar).
    """
    current = _normalize(current_cdd, CDD_SIMPLIFIED)
    risk = _normalize(risk_status, RISK_LOW)
    tier = _normalize(top_txn_tier or "", "")

    if sanctions_pending or risk == RISK_HIGH or tier in {"Critical", "High"}:
        target = CDD_ENHANCED
    elif risk == RISK_MEDIUM or tier == "Medium":
        target = CDD_STANDARD
    else:
        target = CDD_SIMPLIFIED

    if _CDD_RANK.get(target, 0) > _CDD_RANK.get(current, 0):
        return target
    return current


def recommend_for_case(
    kyc_row: dict | None,
    txn_risk_tier: str,
    sanctions_pending: bool = False,
) -> str:
    """Convenience wrapper used by the Case Investigation page."""
    current_cdd = (kyc_row or {}).get("CDDLevel", CDD_SIMPLIFIED)
    risk_status = (kyc_row or {}).get("RiskStatus", RISK_LOW)
    promoted_risk = recommend_risk_status(risk_status, txn_risk_tier)
    return recommend_cdd_level(
        current_cdd=current_cdd,
        risk_status=promoted_risk,
        top_txn_tier=txn_risk_tier,
        sanctions_pending=sanctions_pending,
    )
