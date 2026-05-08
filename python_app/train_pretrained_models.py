from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd

from aml_pipeline import train_models
from utils.data_store import upsert_model_registry_entry


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and persist CounterAI pretrained models.")
    parser.add_argument(
        "--train-data",
        default="/Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/SAML-D.csv",
        help="Path to training CSV with Is_laundering target.",
    )
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=0.7,
        help="Training fraction. The current trainer uses a 70/30 train/test split internally.",
    )
    parser.add_argument(
        "--out",
        default="models/aml_models.joblib",
        help="Output model bundle path.",
    )
    args = parser.parse_args()

    if args.train_fraction != 0.7:
        raise ValueError("This MVP trainer currently supports the required 70/30 split only.")

    train_path = Path(args.train_data)
    if not train_path.exists():
        raise FileNotFoundError(f"Training data not found: {train_path}")

    print(f"Loading training data from {train_path}")
    df = pd.read_csv(train_path)
    print(f"Total rows in source: {len(df)}")
    print("Rows used by trainer: full dataset, with internal 70/30 split")

    print("Training models (RF/CART/Logit)...")
    models, metrics = train_models(df)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, out_path)

    precision = metrics.get("rf_test_accuracy", "")
    recall = metrics.get("rf_test_recall", "")
    f1 = ""
    if precision != "" and recall != "":
        denom = precision + recall
        if denom:
            f1 = round((2 * precision * recall) / denom, 4)

    upsert_model_registry_entry(
        {
            "model_id": "counterai-rf-cart-logit",
            "version": "v0.1",
            "trained_on": out_path.stat().st_mtime,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "error_rate": round(1 - precision, 4) if precision != "" else "",
            "notes": f"Saved model bundle to {out_path}",
        }
    )

    print(f"Saved pretrained model bundle to {out_path}")
    print("Validation metrics:", metrics)


if __name__ == "__main__":
    main()
