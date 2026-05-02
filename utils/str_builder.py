from __future__ import annotations

from datetime import datetime


def make_reference_number(transaction_id: str) -> str:
    d = datetime.now().strftime("%Y%m%d")
    return f"STR-{d}-{str(transaction_id)[:6]}"


def build_default_grounds(str_case: dict) -> str:
    shap_top3 = str_case.get("shap_top3", "")
    notes = str_case.get("investigation_notes", "")
    return (
        f"AI-driven indicators suggest suspicious behavior: {shap_top3}\n\n"
        f"Investigation notes:\n{notes}"
    )
