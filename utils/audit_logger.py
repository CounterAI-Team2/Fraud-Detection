from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("data/audit_log.csv")


def _ensure_parent():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_action(action, transaction_id="", details="", analyst_id="Analyst"):
    _ensure_parent()
    row = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "transaction_id": str(transaction_id),
        "details": str(details),
        "analyst_id": analyst_id,
    }
    file_exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def read_audit_log():
    _ensure_parent()
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)
