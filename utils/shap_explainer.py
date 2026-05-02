from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_DESCRIPTIONS = {
    "sender_unique_receivers": "sender has unusually high fan-out (many unique receivers)",
    "receiver_unique_senders": "receiver has unusually high fan-in (many unique senders)",
    "sender_txn_count": "sender has unusually high transaction velocity",
    "receiver_txn_count": "receiver has unusually high transaction velocity",
    "amount_log": "transaction amount is significantly above normal",
    "cross_border": "transaction crosses international borders",
    "cross_currency": "payment and receipt currencies differ",
    "is_off_hours": "transaction occurred outside normal banking hours",
}


def _clean_feature_name(name: str) -> str:
    prefixes = [
        "Payment_type_",
        "Payment_currency_",
        "Received_currency_",
        "Sender_bank_location_",
        "Receiver_bank_location_",
    ]
    for p in prefixes:
        if name.startswith(p):
            return p[:-1]
    return name


def get_model_xai_explanation(cart_model, logit_model, transaction_row: pd.DataFrame, feature_cols: list[str]):
    row = transaction_row[feature_cols]

    # Logistic local contribution: abs(coef * value)
    coef = np.asarray(logit_model.coef_[0])
    vals = row.values[0]
    logit_contrib = np.abs(coef * vals)

    # CART global importance weighted by this row's magnitude
    cart_imp = np.asarray(cart_model.feature_importances_)
    cart_contrib = np.abs(cart_imp * vals)

    combined = logit_contrib + cart_contrib

    top_idx = np.argsort(combined)[-5:][::-1]
    top_features = [(feature_cols[i], float(combined[i])) for i in top_idx]

    top3_plain = []
    for f, _ in top_features[:3]:
        k = _clean_feature_name(f)
        top3_plain.append(FEATURE_DESCRIPTIONS.get(k, k))

    plain_text = "This transaction was flagged primarily because " + "; and because ".join(top3_plain) + "."
    bullets = [f"- {t}" for t in top3_plain]

    return top_features, plain_text, bullets
