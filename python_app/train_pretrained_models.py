from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from aml_pipeline import train_models, tune_rf_hyperparameters
from utils.data_store import upsert_model_registry_entry


def _print_metrics(metrics: dict) -> None:
    test_size = metrics["test_size"]
    pos = metrics["test_positives"]
    pos_pct = 100 * pos / test_size if test_size else 0

    print()
    print("=" * 62)
    print("  MODEL EVALUATION — TEST SET RESULTS")
    print("=" * 62)
    print(f"  Test set size  : {test_size:>10,} transactions")
    print(f"  Positives      : {pos:>10,}  ({pos_pct:.1f}%)")
    print(f"  Train rows     : {metrics['balanced_train_rows']:>10,}  (balanced)")
    print(f"  Train positives: {metrics['balanced_train_positives']:>10,}")
    print()

    col_w = 15
    print(f"  {'Metric':<12}  {'Random Forest':>{col_w}}  {'CART':>{col_w}}  {'Logistic Reg.':>{col_w}}")
    print("  " + "-" * (12 + 3 * (col_w + 2)))

    for key, label in [
        ("accuracy",  "Accuracy"),
        ("precision", "Precision"),
        ("recall",    "Recall"),
        ("f1",        "F1 Score"),
        ("auc_roc",   "AUC-ROC"),
    ]:
        rf_v = metrics["rf"][key]
        ca_v = metrics["cart"][key]
        lo_v = metrics["logit"][key]
        print(f"  {label:<12}  {rf_v:>{col_w}.4f}  {ca_v:>{col_w}.4f}  {lo_v:>{col_w}.4f}")

    print()
    for model_name, key in [("Random Forest", "rf"), ("CART", "cart"), ("Logistic Reg.", "logit")]:
        m = metrics[key]
        print(f"  Confusion Matrix — {model_name}")
        print(f"    {'':>14}  {'Pred Neg':>10}  {'Pred Pos':>10}")
        print(f"    {'Actual Neg':>14}  {m['tn']:>10,}  {m['fp']:>10,}")
        print(f"    {'Actual Pos':>14}  {m['fn']:>10,}  {m['tp']:>10,}")
        print()

    print("=" * 62)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and persist CounterAI pretrained models.")
    parser.add_argument(
        "--train-data",
        required=True,
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
    parser.add_argument(
        "--tune-rf",
        action="store_true",
        help="Run RandomizedSearchCV hyperparameter tuning for RF before training.",
    )
    parser.add_argument(
        "--rf-tune-iterations",
        type=int,
        default=40,
        help="Number of RandomizedSearchCV iterations when --tune-rf is enabled.",
    )
    parser.add_argument(
        "--rf-tune-cv-folds",
        type=int,
        default=5,
        help="Cross-validation folds for RF tuning.",
    )
    parser.add_argument(
        "--rf-tune-scoring",
        default="f1",
        help="Scoring metric for RF tuning (for example: f1, recall, precision).",
    )
    args = parser.parse_args()

    if args.train_fraction != 0.7:
        raise ValueError("This MVP trainer currently supports the required 70/30 split only.")

    train_path = Path(args.train_data)
    if not train_path.exists():
        raise FileNotFoundError(f"Training data not found: {train_path}")

    print(f"Loading training data from {train_path}")
    df = pd.read_csv(train_path)
    print(f"Total rows in source: {len(df):,}")
    print("Rows used by trainer: full dataset, with internal 70/30 split")

    rf_overrides = None
    rf_tune_score = None
    if args.tune_rf:
        print("Tuning Random Forest hyperparameters...")
        rf_overrides, rf_tune_score = tune_rf_hyperparameters(
            df=df,
            n_iter=args.rf_tune_iterations,
            cv_folds=args.rf_tune_cv_folds,
            scoring=args.rf_tune_scoring,
        )
        print(f"Best RF params: {rf_overrides}")
        print(f"Best CV score ({args.rf_tune_scoring}): {rf_tune_score:.4f}")

    print("Training models (RF/CART/Logit)...")
    models, metrics = train_models(df, rf_overrides=rf_overrides)
    if rf_tune_score is not None:
        metrics["rf_tune_cv_best_score"] = rf_tune_score
        metrics["rf_tune_scoring"] = args.rf_tune_scoring

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, out_path)
    print(f"Saved pretrained model bundle to {out_path}")

    _print_metrics(metrics)

    rf_m = metrics["rf"]
    upsert_model_registry_entry(
        {
            "model_id": "counterai-rf-cart-logit",
            "version": "v0.1",
            "trained_on": out_path.stat().st_mtime,
            "precision": rf_m["precision"],
            "recall": rf_m["recall"],
            "f1": rf_m["f1"],
            "error_rate": round(1 - rf_m["accuracy"], 4),
            "notes": (
                f"Saved model bundle to {out_path}; "
                f"rf_params={json.dumps(metrics.get('rf_params', {}), sort_keys=True)}"
            ),
        }
    )


if __name__ == "__main__":
    main()