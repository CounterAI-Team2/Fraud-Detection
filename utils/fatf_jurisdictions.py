"""
FATF jurisdiction lists and CDD impact rules.

Reference: FATF Plenary outcomes, 11–13 February 2026.
https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html

Categories
----------
Black  — High-Risk Jurisdictions subject to a Call for Action (countermeasures).
         Iran, Democratic People's Republic of Korea (DPRK).

EDD    — Jurisdiction subject to a call for enhanced due diligence (not full
         countermeasures). Myanmar.

Grey   — Jurisdictions under Increased Monitoring. FATF does not mandate blanket
         EDD, but members must factor these jurisdictions into risk analysis.
"""
from __future__ import annotations

import re
from typing import Literal

from utils.kyc_store import (
    CDD_ENHANCED,
    CDD_SIMPLIFIED,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
)

FATF_LIST_VERSION = "2026-02-13"

FATF_CATEGORY_BLACK = "Black"
FATF_CATEGORY_EDD = "EDD"
FATF_CATEGORY_GREY = "Grey"
FATF_CATEGORY_NONE = ""

FatfCategory = Literal["", "Black", "EDD", "Grey"]

# --- Black list: call for countermeasures (Feb 2026) ---
FATF_BLACK_JURISDICTIONS: tuple[str, ...] = (
    "Iran",
    "Democratic People's Republic of Korea",
)

# --- EDD jurisdiction (Feb 2026) ---
FATF_EDD_JURISDICTIONS: tuple[str, ...] = (
    "Myanmar",
)

# --- Grey list: increased monitoring (Feb 2026) ---
FATF_GREY_JURISDICTIONS: tuple[str, ...] = (
    "Algeria",
    "Angola",
    "Bolivia",
    "Bulgaria",
    "Cameroon",
    "Côte d'Ivoire",
    "Democratic Republic of the Congo",
    "Haiti",
    "Kenya",
    "Kuwait",
    "Lao People's Democratic Republic",
    "Lebanon",
    "Monaco",
    "Namibia",
    "Nepal",
    "Papua New Guinea",
    "South Sudan",
    "Syria",
    "Venezuela",
    "Vietnam",
    "Virgin Islands (UK)",
    "Yemen",
)

# Canonical name -> aliases for matching nationality, address, bank_location fields.
JURISDICTION_ALIASES: dict[str, tuple[str, ...]] = {
    "Iran": ("iran", "iranian", "irn", "islamic republic of iran"),
    "Democratic People's Republic of Korea": (
        "democratic people's republic of korea",
        "democratic peoples republic of korea",
        "north korea",
        "north korean",
        "dprk",
        "d.p.r.k",
        "korea, democratic people's republic of",
    ),
    "Myanmar": ("myanmar", "burma", "burmese", "mmr"),
    "Algeria": ("algeria", "algerian", "dza"),
    "Angola": ("angola", "angolan", "ago"),
    "Bolivia": ("bolivia", "bolivian", "bol"),
    "Bulgaria": ("bulgaria", "bulgarian", "bgr"),
    "Cameroon": ("cameroon", "cameroonian", "cmr"),
    "Côte d'Ivoire": ("cote d'ivoire", "côte d'ivoire", "ivory coast", "ivorian", "civ"),
    "Democratic Republic of the Congo": (
        "democratic republic of the congo",
        "dr congo",
        "drc",
        "congo, democratic republic of the",
        "cod",
    ),
    "Haiti": ("haiti", "haitian", "hti"),
    "Kenya": ("kenya", "kenyan", "ken"),
    "Kuwait": ("kuwait", "kuwaiti", "kwt"),
    "Lao People's Democratic Republic": (
        "lao people's democratic republic",
        "lao pdr",
        "laos",
        "lao",
        "laotian",
        "lao peoples democratic republic",
    ),
    "Lebanon": ("lebanon", "lebanese", "lbn"),
    "Monaco": ("monaco", "monegasque", "mco"),
    "Namibia": ("namibia", "namibian", "nam"),
    "Nepal": ("nepal", "nepalese", "npl"),
    "Papua New Guinea": ("papua new guinea", "png", "papua new guinean"),
    "South Sudan": ("south sudan", "south sudanese", "ssd"),
    "Syria": ("syria", "syrian", "syr", "syrian arab republic"),
    "Venezuela": ("venezuela", "venezuelan", "ven"),
    "Vietnam": ("vietnam", "vietnamese", "viet nam", "vnm"),
    "Virgin Islands (UK)": (
        "virgin islands (uk)",
        "british virgin islands",
        "bvi",
        "virgin islands, british",
        "vgb",
    ),
    "Yemen": ("yemen", "yemeni", "yem"),
}

FATF_CATEGORY_RANK: dict[str, int] = {
    FATF_CATEGORY_NONE: 0,
    FATF_CATEGORY_GREY: 1,
    FATF_CATEGORY_EDD: 2,
    FATF_CATEGORY_BLACK: 3,
}

_CDD_RANK = {CDD_SIMPLIFIED: 0, CDD_ENHANCED: 1}
_RISK_RANK = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2, RISK_CRITICAL: 3}


def _normalize_token(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("'", "'").replace("'", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def _build_lookup() -> dict[str, tuple[str, str]]:
    """Map normalized alias -> (canonical_name, category)."""
    lookup: dict[str, tuple[str, str]] = {}
    for name in FATF_BLACK_JURISDICTIONS:
        for alias in JURISDICTION_ALIASES.get(name, (name.lower(),)):
            lookup[_normalize_token(alias)] = (name, FATF_CATEGORY_BLACK)
    for name in FATF_EDD_JURISDICTIONS:
        for alias in JURISDICTION_ALIASES.get(name, (name.lower(),)):
            lookup[_normalize_token(alias)] = (name, FATF_CATEGORY_EDD)
    for name in FATF_GREY_JURISDICTIONS:
        for alias in JURISDICTION_ALIASES.get(name, (name.lower(),)):
            lookup[_normalize_token(alias)] = (name, FATF_CATEGORY_GREY)
    return lookup


_LOOKUP = _build_lookup()


def resolve_fatf_jurisdiction(text: str) -> tuple[str, str] | None:
    """
    Match free text (nationality, address, bank location) to a FATF jurisdiction.

    Returns (canonical_name, category) or None.
    """
    if not text or not str(text).strip():
        return None
    normalized = _normalize_token(str(text))
    if normalized in _LOOKUP:
        return _LOOKUP[normalized]
    for alias, (canonical, category) in _LOOKUP.items():
        if len(alias) >= 4 and alias in normalized:
            return canonical, category
    return None


def evaluate_text_fields(*values: str) -> tuple[str, str] | None:
    """Return the highest-severity FATF match across multiple text fields."""
    best: tuple[str, str] | None = None
    for value in values:
        hit = resolve_fatf_jurisdiction(value)
        if not hit:
            continue
        if best is None or FATF_CATEGORY_RANK[hit[1]] > FATF_CATEGORY_RANK[best[1]]:
            best = hit
    return best


def evaluate_customer_record(row: dict) -> tuple[str, str] | None:
    """Inspect KYC fields for FATF jurisdiction exposure."""
    return evaluate_text_fields(
        str(row.get("Nationality", "")),
        str(row.get("Address", "")),
        str(row.get("place_of_incorporation", "")),
        str(row.get("PlaceOfIncorporation", "")),
        str(row.get("RegisteredOperatingAddress", "")),
        str(row.get("principal_place_of_business", "")),
        str(row.get("PrincipalPlaceOfBusiness", "")),
    )


def fatf_category_label(category: str) -> str:
    labels = {
        FATF_CATEGORY_BLACK: "FATF Black List (call for action)",
        FATF_CATEGORY_EDD: "FATF EDD jurisdiction",
        FATF_CATEGORY_GREY: "FATF Grey List (increased monitoring)",
    }
    return labels.get(category, "")


def fatf_cdd_impact(category: str) -> dict[str, str | bool]:
    """
    Minimum CDD / risk treatment for a FATF category.

    Black  → Enhanced CDD, Critical risk, SM approval required (countermeasures).
    EDD    → Enhanced CDD, High risk, heightened monitoring.
    Grey   → Standard CDD minimum, Medium risk (risk-based heightened scrutiny).
    """
    if category == FATF_CATEGORY_BLACK:
        return {
            "min_cdd": CDD_ENHANCED,
            "min_risk": RISK_CRITICAL,
            "sm_approval_required": True,
            "flag_reason": "FATF Black List",
            "risk_indicator": "FATF high-risk jurisdiction (call for action)",
            "onboarding_note": (
                "Countermeasures apply: limit/restrict relationships; SM approval mandatory."
            ),
        }
    if category == FATF_CATEGORY_EDD:
        return {
            "min_cdd": CDD_ENHANCED,
            "min_risk": RISK_HIGH,
            "sm_approval_required": False,
            "flag_reason": "FATF EDD jurisdiction",
            "risk_indicator": "FATF enhanced due diligence jurisdiction (Myanmar)",
            "onboarding_note": "Apply enhanced due diligence proportionate to jurisdiction risk.",
        }
    if category == FATF_CATEGORY_GREY:
        return {
            "min_cdd": CDD_SIMPLIFIED,  # Standard tier removed → Grey floors at Simplified
            "min_risk": RISK_MEDIUM,
            "sm_approval_required": False,
            "flag_reason": "FATF Grey List",
            "risk_indicator": "FATF increased monitoring jurisdiction (grey list)",
            "onboarding_note": (
                "Factor grey-list status into risk analysis; heightened monitoring recommended."
            ),
        }
    return {
        "min_cdd": CDD_SIMPLIFIED,
        "min_risk": RISK_LOW,
        "sm_approval_required": False,
        "flag_reason": "",
        "risk_indicator": "",
        "onboarding_note": "",
    }


def promote_cdd(current: str, target: str) -> str:
    return target if _CDD_RANK[target] > _CDD_RANK.get(current, 0) else current


def promote_risk(current: str, target: str) -> str:
    return target if _RISK_RANK[target] > _RISK_RANK.get(current, 0) else current


def apply_fatf_to_kyc_row(row: dict[str, str]) -> dict[str, str]:
    """Apply FATF-driven CDD/risk fields to a KYC row dict (in place)."""
    hit = evaluate_customer_record(row)
    if not hit:
        row["FATFJurisdiction"] = ""
        row["FATFListCategory"] = ""
        return row

    jurisdiction, category = hit
    impact = fatf_cdd_impact(category)

    row["FATFJurisdiction"] = jurisdiction
    row["FATFListCategory"] = category
    row["CDDLevel"] = promote_cdd(str(row.get("CDDLevel", CDD_SIMPLIFIED)), str(impact["min_cdd"]))
    row["RiskStatus"] = promote_risk(str(row.get("RiskStatus", RISK_LOW)), str(impact["min_risk"]))

    indicator = str(impact["risk_indicator"])
    existing = [p.strip() for p in str(row.get("RiskIndicators", "")).split(";") if p.strip()]
    if indicator and indicator not in existing:
        existing.append(indicator)
        row["RiskIndicators"] = "; ".join(existing)

    if impact["flag_reason"] and not str(row.get("FlaggedReason", "")).strip():
        row["FlaggedReason"] = str(impact["flag_reason"])

    if impact["sm_approval_required"]:
        from utils.constants import SM_APPROVAL_PENDING

        row["SMApprovalStatus"] = SM_APPROVAL_PENDING
        row["RiskStatus"] = RISK_CRITICAL
        # System-promoted critical: record a synthetic promoter so MLRO SoD
        # has a non-empty counterparty and any human MLRO can approve.
        if not str(row.get("promoted_by", "") or "").strip():
            row["promoted_by"] = "system:fatf"

    note = str(impact["onboarding_note"])
    if note:
        comments = str(row.get("Comments", "")).strip()
        if note not in comments:
            row["Comments"] = f"{comments} | {note}".strip(" |")

    return row


def is_fatf_high_risk_bank_location(location: str) -> bool:
    """Black or EDD jurisdiction — triggers strong transaction red flag."""
    hit = resolve_fatf_jurisdiction(location)
    return bool(hit and hit[1] in {FATF_CATEGORY_BLACK, FATF_CATEGORY_EDD})


def is_fatf_grey_bank_location(location: str) -> bool:
    hit = resolve_fatf_jurisdiction(location)
    return bool(hit and hit[1] == FATF_CATEGORY_GREY)


def all_fatf_jurisdiction_names() -> frozenset[str]:
    return frozenset(FATF_BLACK_JURISDICTIONS + FATF_EDD_JURISDICTIONS + FATF_GREY_JURISDICTIONS)
