from __future__ import annotations

import pandas as pd

from utils.kyc_store import (
    DEMO_SANCTIONS_TEST_PROFILES,
    apply_demo_sanctions_test_rows,
    ensure_demo_sanctions_test_customers,
    force_rescreen_kyc_sanctions,
    get_kyc_customers,
)
from utils.mas_sanctions_sync import _clear_screening_cache


def test_apply_demo_sanctions_test_rows_overwrites_first_customers():
    rows = [
        {"FullName": f"Person {index}", "SanctionsReview": "Pending"}
        for index in range(6)
    ]

    apply_demo_sanctions_test_rows(rows)

    assert rows[0]["FullName"] == DEMO_SANCTIONS_TEST_PROFILES[0]["FullName"]
    assert rows[3]["FullName"] == DEMO_SANCTIONS_TEST_PROFILES[3]["FullName"]
    assert rows[0]["SanctionsReview"] == ""
    assert rows[5]["FullName"] == "Person 5"


def test_demo_profiles_match_sanctions_list(monkeypatch, tmp_path):
    from utils import mas_sanctions_sync as mss
    from utils.kyc_store import KYC_COLUMNS

    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names.txt")
    names = "\n".join(
        [
            "AIMAN MUHAMMED RABI AL-ZAWAHIRI",
            "AGUS DWIKARNA",
            "AHMED KHALFAN GHAILANI",
            "MOHAMMAD REZA ZAHEDI",
        ]
    )
    (tmp_path / "names.txt").write_text(names, encoding="utf-8")
    _clear_screening_cache()

    rows = [{col: "" for col in KYC_COLUMNS} for _ in range(4)]
    for index, row in enumerate(rows):
        row["id"] = str(index + 1)
        row["FullName"] = "placeholder"
    apply_demo_sanctions_test_rows(rows)
    df = pd.DataFrame(rows, columns=KYC_COLUMNS)

    monkeypatch.setattr("utils.kyc_store.KYC_PATH", tmp_path / "kyc.csv")
    monkeypatch.setattr("utils.kyc_store.KYC_META_PATH", tmp_path / "meta.json")
    (tmp_path / "meta.json").write_text('{"demo_sanctions_seeded_v1": true}', encoding="utf-8")
    df.to_csv(tmp_path / "kyc.csv", index=False)

    result = force_rescreen_kyc_sanctions()
    assert result["exact"] == 2
    assert result["fuzzy"] == 2

    updated = pd.read_csv(tmp_path / "kyc.csv", dtype=str)
    assert updated.iloc[0]["SanctionsReview"] == "Confirmed"
    assert updated.iloc[2]["SanctionsReview"] == "Fuzzy — Review Required"


def test_ensure_demo_sanctions_test_customers_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.kyc_store.KYC_PATH", tmp_path / "kyc.csv")
    monkeypatch.setattr("utils.kyc_store.KYC_META_PATH", tmp_path / "meta.json")

    rows = [{"id": str(index), "FullName": f"Name {index}"} for index in range(6)]
    for column in (
        "SanctionsReview",
        "SanctionsMatchedName",
        "SanctionsListKey",
        "SanctionsMatchScore",
        "SanctionsMatchType",
        "Nationality",
        "Occupation",
        "Comments",
        "customer_type",
        "Aliases",
    ):
        for row in rows:
            row.setdefault(column, "")

    pd.DataFrame(rows).to_csv(tmp_path / "kyc.csv", index=False)
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")

    assert ensure_demo_sanctions_test_customers() is True
    first_pass = get_kyc_customers().iloc[0]["FullName"]
    assert first_pass == DEMO_SANCTIONS_TEST_PROFILES[0]["FullName"]
    assert ensure_demo_sanctions_test_customers() is False
