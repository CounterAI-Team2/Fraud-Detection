from __future__ import annotations

import numpy as np
import pandas as pd
import shap

FEATURE_DESCRIPTIONS = {
    "sender_unique_receivers": "sender transacts with unusually many unique receivers (fan-out)",
    "receiver_unique_senders": "receiver receives from unusually many unique senders (fan-in)",
    "sender_txn_count": "sender has unusually high transaction velocity",
    "receiver_txn_count": "receiver has unusually high transaction velocity",
    "amount_log": "transaction amount is significantly above typical",
    "cross_border": "transaction crosses international borders",
    "cross_currency": "payment and receipt currencies differ",
    "is_off_hours": "transaction occurred outside normal banking hours",
    "Received_currency": "received currency is associated with high-risk jurisdictions",
    "Payment_type": "payment type is associated with higher laundering risk",
}


def get_shap_explanation(model, transaction_row: pd.DataFrame, feature_cols: list[str]):
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(transaction_row[feature_cols])

    vals = shap_values[1][0] if isinstance(shap_values, list) else shap_values[0]
    vals = np.array(vals)

    top_idx = np.abs(vals).argsort()[-5:][::-1]
    top_features = [(feature_cols[i], float(vals[i])) for i in top_idx]

    top3_desc = [FEATURE_DESCRIPTIONS.get(f, f) for f, _ in top_features[:3]]
    plain_text = "This transaction was flagged primarily because the " + "; the ".join(top3_desc) + "."

    bullets = [f"- {FEATURE_DESCRIPTIONS.get(f, f)}" for f, _ in top_features[:3]]
    return top_features, plain_text, bullets
