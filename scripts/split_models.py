from pathlib import Path
import sys
import joblib

sys.path.append(str(Path("python_app").resolve()))

bundle_path = Path("models/aml_models.joblib")
if not bundle_path.exists():
    raise FileNotFoundError("models/aml_models.joblib not found")

bundle = joblib.load(bundle_path)
rf = bundle.rf if hasattr(bundle, "rf") else bundle["rf"]
cart = bundle.cart if hasattr(bundle, "cart") else bundle["cart"]
logit = bundle.logit if hasattr(bundle, "logit") else bundle["logit"]

joblib.dump(rf, "models/rf_model.pkl")
joblib.dump(cart, "models/cart_model.pkl")
joblib.dump(logit, "models/logit_model.pkl")
print("Wrote models/rf_model.pkl, models/cart_model.pkl and models/logit_model.pkl")
