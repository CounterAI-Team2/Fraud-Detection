from __future__ import annotations

# --- Actor defaults & role model (Three Lines of Defence) ---
# Stable internal role keys. Use these everywhere — audit log, permission sets,
# persisted records. Display labels (see ROLE_LABELS) are for UI only.
ROLE_AML_ANALYST          = "AML Analyst"
ROLE_SENIOR_INVESTIGATOR  = "Senior Investigator"
ROLE_MLRO                 = "MLRO"
ROLE_AUDITOR              = "Auditor"
ROLE_SYS_ADMIN            = "System Administrator"

ANALYST_ROLES = [
    ROLE_AML_ANALYST,
    ROLE_SENIOR_INVESTIGATOR,
    ROLE_MLRO,
    ROLE_AUDITOR,
    ROLE_SYS_ADMIN,
]

# UI-facing labels (the keys above remain the stored values).
ROLE_LABELS: dict[str, str] = {
    ROLE_AML_ANALYST:         "AML Analyst",
    ROLE_SENIOR_INVESTIGATOR: "Senior Investigator / Team Lead",
    ROLE_MLRO:                "MLRO / Compliance Officer",
    ROLE_AUDITOR:             "Auditor",
    ROLE_SYS_ADMIN:           "System Administrator",
}

# Legacy role strings (pre-refactor) → new keys. Used only for **display** of
# historical audit-log rows; never re-evaluated for authorization.
LEGACY_ROLE_ALIASES: dict[str, str] = {
    "Analyst":            ROLE_AML_ANALYST,
    "Compliance Officer": ROLE_MLRO,
    "Senior Management":  ROLE_MLRO,
    "Admin":              ROLE_SYS_ADMIN,
}


def display_role(role: str) -> str:
    """Return the friendly UI label for a stored role key, aliasing legacy strings."""
    if not role:
        return ""
    key = LEGACY_ROLE_ALIASES.get(role, role)
    return ROLE_LABELS.get(key, role)


DEFAULT_ACTOR_ID   = "alice.analyst"
DEFAULT_ACTOR_ROLE = ROLE_AML_ANALYST

# Demo identities seeded for the sidebar quick-switch / SoD walkthrough.
# Each role represented by a distinct user_id so maker ≠ checker is achievable.
DEMO_IDENTITIES: list[dict[str, str]] = [
    {"user_id": "alice.analyst", "role": ROLE_AML_ANALYST,         "display": "Alice — AML Analyst"},
    {"user_id": "dan.invest",    "role": ROLE_SENIOR_INVESTIGATOR, "display": "Dan — Senior Investigator"},
    {"user_id": "carol.mlro",    "role": ROLE_MLRO,                "display": "Carol — MLRO"},
    {"user_id": "ivan.audit",    "role": ROLE_AUDITOR,             "display": "Ivan — Auditor"},
    {"user_id": "sam.admin",     "role": ROLE_SYS_ADMIN,           "display": "Sam — System Administrator"},
]

# --- Alert statuses ---
ALERT_STATUS_NEW       = "New"
ALERT_STATUS_ESCALATED = "Escalated"
ALERT_STATUS_DISMISSED = "Dismissed"

# --- Case statuses ---
CASE_STATUS_OPEN      = "Open"
CASE_STATUS_IN_REVIEW = "In Review"
CASE_STATUS_ESCALATED = "Escalated"
CASE_STATUS_RESOLVED  = "Resolved"
CASE_STATUS_ARCHIVED  = "Archived"
CASE_STATUSES        = [CASE_STATUS_OPEN, CASE_STATUS_IN_REVIEW, CASE_STATUS_ESCALATED, CASE_STATUS_RESOLVED, CASE_STATUS_ARCHIVED]
CASE_OPEN_STATUSES   = [CASE_STATUS_OPEN, CASE_STATUS_IN_REVIEW, CASE_STATUS_ESCALATED]
CASE_CLOSED_STATUSES = [CASE_STATUS_RESOLVED, CASE_STATUS_ARCHIVED]

# --- CDD levels (two-tier: Simplified / Enhanced) ---
CDD_LEVEL_SIMPLIFIED = "Simplified"
CDD_LEVEL_ENHANCED   = "Enhanced"
CDD_LEVELS           = [CDD_LEVEL_SIMPLIFIED, CDD_LEVEL_ENHANCED]

# --- Customer risk statuses (4-level; distinct from ML transaction risk_tier) ---
CUSTOMER_RISK_LOW      = "Low"
CUSTOMER_RISK_MEDIUM   = "Medium"
CUSTOMER_RISK_HIGH     = "High"
CUSTOMER_RISK_CRITICAL = "Critical"
CUSTOMER_RISK_STATUSES = [CUSTOMER_RISK_LOW, CUSTOMER_RISK_MEDIUM, CUSTOMER_RISK_HIGH, CUSTOMER_RISK_CRITICAL]

# CDD level each customer risk status maps to
CUSTOMER_RISK_TO_CDD: dict[str, str] = {
    CUSTOMER_RISK_LOW:      CDD_LEVEL_SIMPLIFIED,
    CUSTOMER_RISK_MEDIUM:   CDD_LEVEL_SIMPLIFIED,  # Standard tier removed → Medium maps to Simplified
    CUSTOMER_RISK_HIGH:     CDD_LEVEL_ENHANCED,
    CUSTOMER_RISK_CRITICAL: CDD_LEVEL_ENHANCED,  # Critical = Enhanced CDD + SM approval
}

# --- Senior Management approval (required for Critical customers) ---
SM_APPROVAL_PENDING  = "Pending"
SM_APPROVAL_APPROVED = "Approved"
SM_APPROVAL_REJECTED = "Rejected"
SM_APPROVAL_STATUSES = [SM_APPROVAL_PENDING, SM_APPROVAL_APPROVED, SM_APPROVAL_REJECTED]

# --- Flag reasons (why a customer was promoted to Critical) ---
FLAG_REASON_PEP           = "PEP"
FLAG_REASON_INVESTIGATION = "Under Investigation"
FLAG_REASON_MANUAL        = "Manual"

# --- STR workflow states ---
STR_STATUS_DRAFT    = "Draft"
STR_STATUS_L1       = "L1Review"
STR_STATUS_L2       = "L2Review"
STR_STATUS_APPROVED = "Approved"
STR_STATUS_ARCHIVED = "Archived"
STR_STATUSES        = [STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2, STR_STATUS_APPROVED, STR_STATUS_ARCHIVED]

# --- STR maker-checker authorization ---
# Workflow actions (one per gate transition).
STR_ACTION_DRAFT_SUBMIT = "draft_submit"   # Draft  -> L1 Review
STR_ACTION_L1_APPROVE   = "l1_approve"     # L1     -> L2 Review
STR_ACTION_L2_APPROVE   = "l2_approve"     # L2     -> Approved / Archived

# Three-Lines-of-Defence role permissions. No role bypasses the gate;
# segregation of duties is enforced in utils/str_authz.py.
STR_ROLE_PERMISSIONS = {
    STR_ACTION_DRAFT_SUBMIT: {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR},
    STR_ACTION_L1_APPROVE:   {ROLE_SENIOR_INVESTIGATOR},
    STR_ACTION_L2_APPROVE:   {ROLE_MLRO},
}

# Human-readable owning role per gate (for stage cards / messages).
STR_GATE_ROLE_LABEL = {
    STR_STATUS_DRAFT: ROLE_AML_ANALYST,
    STR_STATUS_L1:    ROLE_SENIOR_INVESTIGATOR,
    STR_STATUS_L2:    ROLE_MLRO,
}

# --- Capability role sets (single source of truth for the access matrix) ---
AUDIT_SEE_ALL_ROLES         = {ROLE_MLRO, ROLE_AUDITOR, ROLE_SYS_ADMIN}
CRITICAL_APPROVE_ROLES      = {ROLE_MLRO}
REF_DATA_ROLES              = {ROLE_SYS_ADMIN}
KYC_ENROL_ROLES             = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR}
KYC_RISK_MAKER_ROLES        = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR}
ALERT_ACTION_ROLES          = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR}
CASE_ACTION_ROLES           = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR}
SANCTIONS_DISPOSITION_ROLES = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR}
DATA_UPLOAD_SCORE_ROLES     = {ROLE_AML_ANALYST, ROLE_SENIOR_INVESTIGATOR, ROLE_SYS_ADMIN}
GOVERNANCE_SIGNOFF_ROLES    = {ROLE_MLRO}
GOVERNANCE_CONFIG_ROLES     = {ROLE_SYS_ADMIN}

# Suspicious-transaction typologies offered as reason codes on the STR form.
STR_REASON_CODES = [
    "Structuring",
    "Cross-border layering",
    "Smurfing",
    "Trade-based ML",
    "Rapid movement of funds",
    "Unusual for profile",
    "High-risk jurisdiction",
    "PEP involvement",
]

# --- Risk scoring ---
ALERT_THRESHOLDS: dict[str, float] = {
    "Critical": 0.85,
    "High":     0.70,
    "Medium":   0.50,
}
HIGH_VALUE_THRESHOLD = 10_000

# --- Feature engineering ---
OFF_HOURS_START = 6
OFF_HOURS_END   = 22

# --- UI display ---
RISK_TIER_COLORS: dict[str, str] = {
    "High":   "#f44336",
    "Medium": "#fb8c00",
    "Low":    "#66bb6a",
}
ALERT_QUEUE_DISPLAY_LIMIT        = 200
RELATED_TRANSACTIONS_WINDOW_DAYS = 30
CUSTOMER_RECENT_TXNS_LIMIT       = 25
TREND_HISTORICAL_DAYS            = 30
DATA_PREVIEW_LIMIT               = 50
XAI_TOP_FEATURES                 = 5

# --- Institution ---
INSTITUTION_NAME = "Counter AI Demo Bank"
