from __future__ import annotations

# --- Actor defaults ---
DEFAULT_ACTOR_ID   = "Analyst"
DEFAULT_ACTOR_ROLE = "Admin"
ANALYST_ROLES      = ["Admin", "Analyst", "Compliance Officer", "Senior Management"]

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

# --- CDD levels ---
CDD_LEVEL_SIMPLIFIED = "Simplified"
CDD_LEVEL_STANDARD   = "Standard"
CDD_LEVEL_ENHANCED   = "Enhanced"
CDD_LEVELS           = [CDD_LEVEL_SIMPLIFIED, CDD_LEVEL_STANDARD, CDD_LEVEL_ENHANCED]

# --- STR workflow states ---
STR_STATUS_DRAFT    = "Draft"
STR_STATUS_L1       = "L1Review"
STR_STATUS_L2       = "L2Review"
STR_STATUS_APPROVED = "Approved"
STR_STATUS_ARCHIVED = "Archived"
STR_STATUSES        = [STR_STATUS_DRAFT, STR_STATUS_L1, STR_STATUS_L2, STR_STATUS_APPROVED, STR_STATUS_ARCHIVED]

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
    "Critical": "#f44336",
    "High":     "#fb8c00",
    "Medium":   "#fdd835",
    "Low":      "#cfd8dc",
}
ALERT_QUEUE_DISPLAY_LIMIT        = 200
RELATED_TRANSACTIONS_WINDOW_DAYS = 30
CUSTOMER_RECENT_TXNS_LIMIT       = 25
TREND_HISTORICAL_DAYS            = 30
DATA_PREVIEW_LIMIT               = 50
XAI_TOP_FEATURES                 = 5

# --- Institution ---
INSTITUTION_NAME = "Counter AI Demo Bank"
