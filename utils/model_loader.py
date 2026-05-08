from __future__ import annotations

from pathlib import Path
import sys

import joblib

from utils.data_store import get_model_registry, upsert_model_registry_entry, utc_now_iso

MODELS_DIR = Path("models")
RF_PATH = MODELS_DIR / "rf_model.pkl"
CART_PATH = MODELS_DIR / "cart_model.pkl"
LOGIT_PATH = MODELS_DIR / "logit_model.pkl"
BUNDLE_PATH = MODELS_DIR / "aml_models.joblib"

sys.path.append(str(Path("python_app").resolve()))


def _bootstrap_from_bundle() -> None:
    if RF_PATH.exists() and CART_PATH.exists() and LOGIT_PATH.exists():
        return
    if not BUNDLE_PATH.exists():
        raise FileNotFoundError(
            "No pretrained model files found. Expected models/rf_model.pkl, models/cart_model.pkl and models/logit_model.pkl, "
            "or fallback models/aml_models.joblib"
        )

    bundle = joblib.load(BUNDLE_PATH)
    # Backward compatibility with previous dataclass bundle.
    rf = bundle.rf if hasattr(bundle, "rf") else bundle["rf"]
    cart = bundle.cart if hasattr(bundle, "cart") else bundle["cart"]
    logit = bundle.logit if hasattr(bundle, "logit") else bundle["logit"]

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, RF_PATH)
    joblib.dump(cart, CART_PATH)
    joblib.dump(logit, LOGIT_PATH)


def load_models():
    _bootstrap_from_bundle()
    rf_model = joblib.load(RF_PATH)
    cart_model = joblib.load(CART_PATH)
    logit_model = joblib.load(LOGIT_PATH)
    return rf_model, cart_model, logit_model


def ensure_model_registry_entry() -> None:
    registry = get_model_registry()
    models = registry.get("models", [])
    if models:
        return

    upsert_model_registry_entry(
        {
            "model_id": "counterai-rf-cart-logit",
            "version": "v0.1",
            "trained_on": utc_now_iso(),
            "precision": "",
            "recall": "",
            "f1": "",
            "error_rate": "",
            "notes": "Backfilled placeholder entry for pretrained MVP bundle.",
        }
    )
