from __future__ import annotations

from utils.cdd_rules import recommend_cdd_level, recommend_for_case, recommend_risk_status


def test_risk_status_only_promotes():
    assert recommend_risk_status("Low", "Medium") == "Medium"
    assert recommend_risk_status("Low", "Critical") == "High"
    assert recommend_risk_status("High", "Medium") == "High"
    assert recommend_risk_status("Medium", "Low") == "Medium"


def test_cdd_level_only_promotes():
    # Standard tier removed: Medium risk now maps to Simplified (no promotion from Simplified).
    assert recommend_cdd_level("Simplified", "Medium", "Medium") == "Simplified"
    assert recommend_cdd_level("Simplified", "High", "Critical") == "Enhanced"
    assert recommend_cdd_level("Enhanced", "Low", "Low") == "Enhanced"


def test_sanctions_pending_forces_enhanced():
    assert recommend_cdd_level("Simplified", "Low", "Low", sanctions_pending=True) == "Enhanced"


def test_recommend_for_case_uses_kyc_row():
    kyc = {"CDDLevel": "Simplified", "RiskStatus": "Low"}
    assert recommend_for_case(kyc, "Medium") == "Simplified"
    assert recommend_for_case(kyc, "Critical") == "Enhanced"
    # Missing KYC row should still recommend a sensible default for a flagged txn.
    assert recommend_for_case(None, "High") == "Enhanced"


def test_fatf_grey_floor_in_case_recommendation():
    # Standard tier removed: Grey list now floors at Simplified (no CDD promotion).
    kyc = {"CDDLevel": "Simplified", "RiskStatus": "Low", "FATFListCategory": "Grey"}
    assert recommend_for_case(kyc, "Low") == "Simplified"
