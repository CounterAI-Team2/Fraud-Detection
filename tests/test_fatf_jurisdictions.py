from __future__ import annotations

from utils.cdd_rules import recommend_cdd_level, recommend_risk_status
from utils.fatf_jurisdictions import (
    FATF_CATEGORY_BLACK,
    FATF_CATEGORY_EDD,
    FATF_CATEGORY_GREY,
    apply_fatf_to_kyc_row,
    evaluate_customer_record,
    resolve_fatf_jurisdiction,
)


def test_resolve_iran_black_list():
    hit = resolve_fatf_jurisdiction("Iranian")
    assert hit == ("Iran", FATF_CATEGORY_BLACK)


def test_resolve_myanmar_edd():
    hit = resolve_fatf_jurisdiction("Myanmar")
    assert hit == ("Myanmar", FATF_CATEGORY_EDD)


def test_resolve_vietnam_grey_list():
    hit = resolve_fatf_jurisdiction("Vietnam")
    assert hit == ("Vietnam", FATF_CATEGORY_GREY)


def test_apply_fatf_black_promotes_critical_enhanced():
    row = {
        "Nationality": "Iranian",
        "Address": "Tehran, Iran",
        "RiskStatus": "Low",
        "CDDLevel": "Simplified",
        "RiskIndicators": "",
        "FlaggedReason": "",
        "SMApprovalStatus": "",
        "Comments": "",
    }
    out = apply_fatf_to_kyc_row(row)
    assert out["FATFListCategory"] == FATF_CATEGORY_BLACK
    assert out["RiskStatus"] == "Critical"
    assert out["CDDLevel"] == "Enhanced"
    assert out["SMApprovalStatus"] == "Pending"


def test_apply_fatf_grey_promotes_medium_standard():
    row = {
        "Nationality": "Vietnamese",
        "Address": "Hanoi, Vietnam",
        "RiskStatus": "Low",
        "CDDLevel": "Simplified",
        "RiskIndicators": "",
        "FlaggedReason": "",
        "SMApprovalStatus": "",
        "Comments": "",
    }
    out = apply_fatf_to_kyc_row(row)
    assert out["FATFListCategory"] == FATF_CATEGORY_GREY
    assert out["RiskStatus"] == "Medium"
    assert out["CDDLevel"] == "Standard"


def test_cdd_rules_respect_fatf_category():
    assert recommend_risk_status("Low", "Low", fatf_category=FATF_CATEGORY_EDD) == "High"
    assert recommend_cdd_level("Simplified", "Low", fatf_category=FATF_CATEGORY_BLACK) == "Enhanced"


def test_evaluate_customer_record_from_address():
    hit = evaluate_customer_record({"Nationality": "", "Address": "Industrial Park, Yangon, Myanmar"})
    assert hit == ("Myanmar", FATF_CATEGORY_EDD)
