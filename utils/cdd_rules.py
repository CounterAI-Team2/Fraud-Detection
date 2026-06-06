"""
CDD recommendation rules, loosely aligned to MAS Notice 626 and TFS guidance.

This is a prototype heuristic, not legal advice. It maps the three CDD tiers
(Simplified / Standard / Enhanced) defined in ``utils.constants`` to a small
set of inputs the rest of the app already tracks: the customer's current KYC
risk status, the highest transaction risk tier their account has triggered,
and whether a sanctions name match is still pending review.
"""
from __future__ import annotations

from utils.fatf_jurisdictions import (
    FATF_CATEGORY_BLACK,
    FATF_CATEGORY_EDD,
    FATF_CATEGORY_GREY,
    fatf_cdd_impact,
    promote_cdd,
    promote_risk,
)
from utils.kyc_store import (
    CDD_ENHANCED,
    CDD_SIMPLIFIED,
    CDD_STANDARD,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
)

# Customer RiskStatus rank — Critical is analyst-only, never auto-assigned by transactions.
_RISK_RANK = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}

# Transaction risk_tier rank (ML model output — separate concept from customer RiskStatus).
_TIER_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}

_CDD_RANK = {CDD_SIMPLIFIED: 0, CDD_STANDARD: 1, CDD_ENHANCED: 2}


def _normalize(value: str | None, default: str) -> str:
    text = (value or "").strip()
    return text if text else default


def _fatf_min_risk(category: str) -> str:
    return str(fatf_cdd_impact(category).get("min_risk", RISK_LOW))


def _fatf_min_cdd(category: str) -> str:
    return str(fatf_cdd_impact(category).get("min_cdd", CDD_SIMPLIFIED))


def recommend_risk_status(
    current_risk: str,
    top_txn_tier: str,
    fatf_category: str = "",
) -> str:
    """
    Promote (never demote) the KYC RiskStatus based on a flagged transaction tier.

    Transaction-based escalation caps at High — Critical is analyst-only and
    requires explicit manual flagging (see set_customer_risk_status in kyc_store).

    Extensibility note: future transaction rules should call this function with
    their suggested tier, letting this function arbitrate the final status so that
    the promote-only invariant is preserved across all callers.
    """
    current = _normalize(current_risk, RISK_LOW)
    tier = _normalize(top_txn_tier, "Medium")

    # Guard: if current is already Critical, transactions cannot change it.
    if current == RISK_CRITICAL:
        return RISK_CRITICAL

    if tier in {"Critical", "High"}:
        target = RISK_HIGH      # transactions cap at High; Critical is analyst-only
    elif tier == "Medium":
        target = RISK_MEDIUM
    else:
        target = current

    if _RISK_RANK.get(target, 0) > _RISK_RANK.get(current, 0):
        current = target

    if fatf_category in {FATF_CATEGORY_BLACK, FATF_CATEGORY_EDD, FATF_CATEGORY_GREY}:
        current = promote_risk(current, _fatf_min_risk(fatf_category))
    return current


def recommend_cdd_level(
    current_cdd: str,
    risk_status: str,
    top_txn_tier: str | None = None,
    sanctions_pending: bool = False,
    fatf_category: str = "",
) -> str:
    """
    Decide the recommended CDD level. Returns the higher of the current level
    and what the inputs would justify (so analysts can downgrade explicitly
    in Case Investigation, but automation never lowers the bar).

    Critical RiskStatus maps to Enhanced CDD; the additional SM-approval
    requirement is tracked via SMApprovalStatus in the KYC record, not as a
    separate CDD string.
    """
    current = _normalize(current_cdd, CDD_SIMPLIFIED)
    risk = _normalize(risk_status, RISK_LOW)
    tier = _normalize(top_txn_tier or "", "")

    if sanctions_pending or risk in {RISK_HIGH, RISK_CRITICAL} or tier in {"Critical", "High"}:
        target = CDD_ENHANCED
    elif risk == RISK_MEDIUM or tier == "Medium":
        target = CDD_STANDARD
    else:
        target = CDD_SIMPLIFIED

    if fatf_category in {FATF_CATEGORY_BLACK, FATF_CATEGORY_EDD, FATF_CATEGORY_GREY}:
        target = promote_cdd(target, _fatf_min_cdd(fatf_category))

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
    fatf_category = str((kyc_row or {}).get("FATFListCategory", ""))
    promoted_risk = recommend_risk_status(risk_status, txn_risk_tier, fatf_category=fatf_category)
    return recommend_cdd_level(
        current_cdd=current_cdd,
        risk_status=promoted_risk,
        top_txn_tier=txn_risk_tier,
        sanctions_pending=sanctions_pending,
        fatf_category=fatf_category,
    )
