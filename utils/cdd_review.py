"""Business logic for the SCDD / ECDD due-diligence interface.

- Eligibility backend-check for SCDD (MAS 626: simplified measures are not permitted
  where there is a FATF call-for-countermeasures nexus, an existing ML/TF suspicion,
  or a PEP).
- Senior-Management approval gate for ECDD (Compliance Officer submits, Senior
  Management approves — same role model as the STR L1/L2 flow).
- Persistence to the cdd_reviews store and sync-back to the KYC customer record.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from utils.constants import (
    CASE_OPEN_STATUSES,
    CDD_LEVEL_ENHANCED,
    CDD_LEVEL_SIMPLIFIED,
)
from utils.data_store import (
    get_cases,
    get_cdd_reviews,
    get_str_cases,
    parse_payload,
    serialize_payload,
    upsert_cdd_review,
)
from utils.fatf_jurisdictions import FATF_CATEGORY_BLACK

# ── CDD types / statuses ──────────────────────────────────────────────────────
CDD_TYPE_SCDD = "SCDD"
CDD_TYPE_ECDD = "ECDD"

CDD_STATUS_DRAFT = "Draft"
CDD_STATUS_PENDING = "PendingApproval"
CDD_STATUS_APPROVED = "Approved"
CDD_STATUS_REJECTED = "Rejected"
CDD_STATUS_COMPLETED = "Completed"

# ── Form option lists (mirror the mockup) ─────────────────────────────────────
SCDD_MEASURES = [
    "Reduced frequency of periodic review",
    "Lower transaction-monitoring thresholds deferred",
    "Verification deferred to threshold/trigger",
    "Reduced identification data set",
    "Reliance on reduced ongoing monitoring",
]
SCDD_REVIEW_CYCLES = ["36 months", "24 months", "12 months"]
PURPOSE_BASES = ["Inferred from product / transaction type", "Stated by customer"]

ECDD_BASIS = [
    "Foreign PEP",
    "Domestic PEP",
    "International org PEP",
    "Family member / close associate of PEP",
    "High-risk jurisdiction nexus",
    "Complex / opaque legal structure",
    "Shell company — no clear economic purpose",
    "Adverse media",
    "Cash-intensive activity",
]
ECDD_CORP_ONLY_BASIS = {"Complex / opaque legal structure", "Shell company — no clear economic purpose"}
PEP_TYPES = ["Foreign PEP", "Domestic PEP", "International organisation PEP", "Family / close associate"]
SANCTIONS_RESULTS = ["No match", "Possible match — under review", "Confirmed match — escalate"]
ADVERSE_MEDIA_RESULTS = ["None", "Minor — mitigated", "Material — documented"]
SOF_CATEGORIES = [
    "Salary / employment income", "Business income", "Sale of property",
    "Inheritance", "Investment proceeds", "Gift",
]
ECDD_EVIDENCE_TYPES = [
    "Tax returns / NOA", "Bank statements", "Audited financial statements",
    "Payslips / employment letter", "Sale & purchase agreement",
    "Probate / inheritance documents", "Company registry extract",
]
ECDD_REVIEW_CYCLES = ["12 months", "6 months", "3 months"]
PRETXN_CHECK_OPTIONS = ["Required above threshold", "Required for all", "Not required"]
ECDD_TRIGGERS = ["Unusual transaction pattern", "Change in PEP status", "New adverse media", "Cross-border spike"]

# Roles permitted to act on the ECDD Senior-Management gate.
_SUBMIT_ROLES = {"Compliance Officer", "Admin"}
_APPROVE_ROLES = {"Senior Management", "Admin"}


def _is_pep(kyc: dict) -> bool:
    return str(kyc.get("IsPEP", "No")).strip().lower() in {"yes", "true", "1", "y"}


def _has_open_suspicion(customer_id: str) -> bool:
    """Existing ML/TF suspicion = an open case or any STR exists for the customer."""
    cid = str(customer_id)
    cases = get_cases()
    if not cases.empty and "customer_id" in cases.columns:
        open_cases = cases[
            (cases["customer_id"].astype(str) == cid)
            & (cases["status"].isin(CASE_OPEN_STATUSES))
        ]
        if not open_cases.empty:
            return True
    strs = get_str_cases()
    if not strs.empty and "customer_id" in strs.columns:
        if (strs["customer_id"].astype(str) == cid).any():
            return True
    return False


def check_scdd_eligibility(customer_id: str, kyc: dict) -> tuple[bool, list[str]]:
    """Return (eligible, reasons). SCDD is blocked if any disqualifier is present."""
    reasons: list[str] = []
    if str(kyc.get("FATFListCategory", "")) == FATF_CATEGORY_BLACK:
        reasons.append("FATF call-for-countermeasures jurisdiction")
    if _has_open_suspicion(customer_id):
        reasons.append("existing ML/TF suspicion (open case / STR)")
    if _is_pep(kyc):
        reasons.append("customer / beneficial owner is a PEP")
    return (len(reasons) == 0, reasons)


def can_submit_for_approval(role: str) -> bool:
    return role in _SUBMIT_ROLES


def can_approve(role: str, actor_id: str, review: dict) -> tuple[bool, str]:
    """Senior-Management gate. Returns (allowed, reason_if_blocked)."""
    if role not in _APPROVE_ROLES:
        return False, "Approve / Reject requires the Senior Management role."
    if str(actor_id) and str(actor_id) == str(review.get("completed_by", "")):
        return False, "Segregation of duties: you completed this ECDD and cannot also approve it."
    return True, ""


def get_latest_review(customer_id: str, cdd_type: str) -> dict | None:
    """Most recently updated review of the given type for a customer, or None."""
    reviews = get_cdd_reviews()
    if reviews.empty:
        return None
    match = reviews[
        (reviews["customer_id"].astype(str) == str(customer_id))
        & (reviews["cdd_type"].astype(str) == str(cdd_type))
    ]
    if match.empty:
        return None
    match = match.sort_values("updated_at", ascending=False)
    return match.iloc[0].to_dict()


def load_payload(review: dict | None) -> dict:
    if not review:
        return {}
    return parse_payload(review.get("payload_json", "")) or {}


def save_review(meta: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a review: `meta` holds the indexed columns, `payload` the full form."""
    row = dict(meta)
    row["payload_json"] = serialize_payload(payload)
    return upsert_cdd_review(row)


def sync_review_to_kyc(customer_id: str, cdd_type: str, payload: dict, sm_status: str = "") -> None:
    """Write the review outcome back onto the KYC customer record."""
    from utils.kyc_store import update_kyc_record  # local import avoids cycle

    updates: dict[str, str] = {
        "CDDLevel": CDD_LEVEL_ENHANCED if cdd_type == CDD_TYPE_ECDD else CDD_LEVEL_SIMPLIFIED,
        "LastCDDReviewAt": date.today().isoformat(),
    }
    if payload.get("source_of_wealth"):
        updates["SourceOfWealth"] = payload["source_of_wealth"]
    if payload.get("source_of_funds"):
        updates["SourceOfIncome"] = payload["source_of_funds"]
    if payload.get("inferred_purpose"):
        updates["PurposeOfAccount"] = payload["inferred_purpose"]
    if cdd_type == CDD_TYPE_ECDD:
        if payload.get("pep_type"):
            updates["IsPEP"] = "Yes"
        if sm_status:
            updates["SMApprovalStatus"] = sm_status
            updates["SMApprovedBy"] = payload.get("sm_approver", "")
            updates["SMApprovedAt"] = payload.get("sm_decision_at", "")
    update_kyc_record(str(customer_id), updates)
