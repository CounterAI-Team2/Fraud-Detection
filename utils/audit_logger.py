from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from utils.data_store import (
    AUDIT_COLUMNS,
    AUDIT_V2_PATH,
    append_csv_row,
    get_audit_events,
    make_event_id,
    parse_payload,
    serialize_payload,
    utc_now_iso,
)

LOG_PATH = Path("data/audit_log.csv")


def _ensure_parent():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_action(
    action,
    transaction_id="",
    details="",
    analyst_id="Analyst",
    module="general",
    event_type="user_action",
    entity_type="transaction",
    entity_id="",
    actor_role="Analyst",
    payload: dict[str, Any] | None = None,
):
    _ensure_parent()
    row = {
        "timestamp": utc_now_iso(),
        "action": action,
        "transaction_id": str(transaction_id),
        "details": str(details),
        "analyst_id": analyst_id,
    }
    file_exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    payload_json = payload or {}
    if details and "details" not in payload_json:
        payload_json["details"] = details
    append_csv_row(
        AUDIT_V2_PATH,
        {
            "event_id": make_event_id(),
            "timestamp_utc": utc_now_iso(),
            "module": module,
            "event_type": event_type or action,
            "entity_type": entity_type,
            "entity_id": entity_id or str(transaction_id),
            "transaction_id": str(transaction_id),
            "actor_id": analyst_id,
            "actor_role": actor_role,
            "payload_json": serialize_payload(payload_json),
        },
        AUDIT_COLUMNS,
    )


def read_audit_log():
    _ensure_parent()
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def read_audit_events():
    events = get_audit_events()
    if events.empty:
        return []
    rows = events.to_dict(orient="records")
    for row in rows:
        row["payload"] = parse_payload(row.get("payload_json"))
    return rows
