from __future__ import annotations

from pathlib import Path
import sys
import joblib

MODELS_DIR = Path("models")
RF_PATH = MODELS_DIR / "rf_model.pkl"
CART_PATH = MODELS_DIR / "cart_model.pkl"
BUNDLE_PATH = MODELS_DIR / "aml_models.joblib"

sys.path.append(str(Path("python_app").resolve()))


def _bootstrap_from_bundle() -> None:
    if RF_PATH.exists() and CART_PATH.exists():
        return
    if not BUNDLE_PATH.exists():
        raise FileNotFoundError(
            "No pretrained model files found. Expected models/rf_model.pkl and models/cart_model.pkl, "
            "or fallback models/aml_models.joblib"
        )

    bundle = joblib.load(BUNDLE_PATH)
    # Backward compatibility with previous dataclass bundle.
    rf = bundle.rf if hasattr(bundle, "rf") else bundle["rf"]
    cart = bundle.cart if hasattr(bundle, "cart") else bundle["cart"]

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, RF_PATH)
    joblib.dump(cart, CART_PATH)


def load_models():
    _bootstrap_from_bundle()
    rf_model = joblib.load(RF_PATH)
    cart_model = joblib.load(CART_PATH)
    return rf_model, cart_model
