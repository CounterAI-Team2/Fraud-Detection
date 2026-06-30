"""Critical-customer SoD tests.

Validate that:

1. Promoting a customer to RISK_CRITICAL records ``promoted_by``.
2. ``approve_critical_customer`` refuses when the approver is the same person
   who promoted the customer (defensive SoD).
3. ``reject_critical_flag`` refuses under the same condition.

These tests use ``monkeypatch`` to redirect the KYC CSV path so they do not
touch the real demo data file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from utils import kyc_store
from utils.constants import SM_APPROVAL_PENDING
from utils.kyc_store import (
    KYC_COLUMNS,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    approve_critical_customer,
    reject_critical_flag,
    set_customer_risk_status,
)


def _seed_customer(tmp_path) -> str:
    """Create a one-row KYC CSV in ``tmp_path`` and return the customer id."""
    row = {col: "" for col in KYC_COLUMNS}
    row.update({
        "id": "CUST-0001",
        "customer_type": "Individual",
        "FullName": "Test Customer",
        "AccountNo": "ACC-0001",
        "RiskStatus": RISK_LOW,
        "CDDLevel": "Simplified",
        "IsPEP": "No",
    })
    df = pd.DataFrame([row], columns=KYC_COLUMNS)
    csv_path = tmp_path / "kyc_customers.csv"
    df.to_csv(csv_path, index=False)
    return str(csv_path)


@pytest.fixture()
def isolated_kyc(tmp_path, monkeypatch):
    csv_path = _seed_customer(tmp_path)
    monkeypatch.setattr(kyc_store, "KYC_PATH", Path(csv_path))
    return csv_path


def test_promote_to_critical_sets_promoted_by(isolated_kyc):
    updated = set_customer_risk_status(
        customer_id="CUST-0001",
        new_status=RISK_CRITICAL,
        actor_id="alice.analyst",
        reason="Manual",
    )
    assert updated is not None
    assert updated["RiskStatus"] == RISK_CRITICAL
    assert updated["promoted_by"] == "alice.analyst"
    assert updated["SMApprovalStatus"] == SM_APPROVAL_PENDING


def test_demote_clears_promoted_by(isolated_kyc):
    set_customer_risk_status("CUST-0001", RISK_CRITICAL, "alice.analyst")
    updated = set_customer_risk_status("CUST-0001", RISK_HIGH, "alice.analyst")
    assert updated is not None
    assert updated["RiskStatus"] == RISK_HIGH
    assert updated["promoted_by"] == ""


def test_approve_blocks_self_promoter(isolated_kyc):
    set_customer_risk_status("CUST-0001", RISK_CRITICAL, "alice.analyst")
    result = approve_critical_customer("CUST-0001", "alice.analyst")
    assert result is None


def test_approve_allows_independent_mlro(isolated_kyc):
    set_customer_risk_status("CUST-0001", RISK_CRITICAL, "alice.analyst")
    result = approve_critical_customer("CUST-0001", "carol.mlro")
    assert result is not None
    assert result["SMApprovalStatus"] == "Approved"
    assert result["SMApprovedBy"] == "carol.mlro"


def test_reject_blocks_self_promoter(isolated_kyc):
    set_customer_risk_status("CUST-0001", RISK_CRITICAL, "alice.analyst")
    result = reject_critical_flag("CUST-0001", "alice.analyst")
    assert result is None


def test_reject_allows_independent_mlro(isolated_kyc):
    set_customer_risk_status("CUST-0001", RISK_CRITICAL, "alice.analyst")
    result = reject_critical_flag("CUST-0001", "carol.mlro", reason="Insufficient evidence")
    assert result is not None
    assert result["RiskStatus"] == RISK_HIGH
    assert result["SMApprovalStatus"] == "Rejected"
