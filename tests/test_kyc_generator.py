from __future__ import annotations

from pathlib import Path

import pandas as pd

from utils.kyc_generator import (
    KYC_TARGET_ROW_COUNT,
    PRIMARY_TRANSACTION_DATASET,
    load_account_ids_from_csv,
    load_account_ids_from_sender_receiver_csv,
    load_account_ids_from_transactions,
    resolve_account_id_source,
)


def test_resolve_account_ids_from_dataset_csv():
    assert PRIMARY_TRANSACTION_DATASET.exists()
    ids, source = resolve_account_id_source()
    assert len(ids) >= KYC_TARGET_ROW_COUNT
    assert "Dataset.csv" in source
    assert "Sender_account" in source


def test_load_sender_receiver_columns_from_dataset():
    ids = load_account_ids_from_sender_receiver_csv(PRIMARY_TRANSACTION_DATASET, limit=100)
    assert len(ids) == 100
    assert len(set(ids)) == 100


def test_load_account_ids_from_single_column_csv(tmp_path: Path):
    csv_path = tmp_path / "accounts.csv"
    csv_path.write_text("account_id\n111\n222\n111\n333\n", encoding="utf-8")
    assert load_account_ids_from_csv(csv_path) == ["111", "222", "333"]


def test_unique_accounts_from_pilot_demo():
    ids = load_account_ids_from_transactions(limit=100)
    assert len(ids) == 100
    assert len(set(ids)) == 100
