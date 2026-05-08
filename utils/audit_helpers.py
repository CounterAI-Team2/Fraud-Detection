from __future__ import annotations

from utils.audit_logger import log_action


def log_alert_escalated(txid: str, case_id: str, analyst_id: str, actor_role: str, risk_tier: str, risk_score: float) -> None:
    log_action(
        action="alert_escalated",
        transaction_id=txid,
        details=f"case_id={case_id}; risk_tier={risk_tier}",
        analyst_id=analyst_id,
        module="alert_queue",
        event_type="alert_escalated",
        entity_type="case",
        entity_id=case_id,
        actor_role=actor_role,
        payload={"case_id": case_id, "risk_score": round(risk_score, 4), "risk_tier": risk_tier},
    )


def log_alert_dismissed(txid: str, analyst_id: str, actor_role: str, dismiss_reason: str, risk_score: float) -> None:
    log_action(
        action="alert_dismissed",
        transaction_id=txid,
        details=f"rf_prediction={int(risk_score)}; reason={dismiss_reason}",
        analyst_id=analyst_id,
        module="alert_queue",
        event_type="alert_dismissed",
        entity_type="transaction",
        entity_id=txid,
        actor_role=actor_role,
        payload={"dismiss_reason": dismiss_reason, "risk_score": round(risk_score, 4)},
    )


def log_prediction_feedback(txid: str, analyst_id: str, actor_role: str, feedback_label: str, feedback_reason: str, original_prediction: int) -> None:
    log_action(
        action="prediction_feedback_logged",
        transaction_id=txid,
        details=f"corrected_label={feedback_label}; reason={feedback_reason}",
        analyst_id=analyst_id,
        module="alert_queue",
        event_type="prediction_feedback_logged",
        entity_type="feedback",
        entity_id=txid,
        actor_role=actor_role,
        payload={"corrected_label": feedback_label, "reason": feedback_reason, "original_prediction": original_prediction},
    )
