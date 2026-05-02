# CounterAI MVP 0.1

The platform now works as **inference-only** for users:

- Models are pretrained from Assignment 2 data in this folder (`SAML-D.csv`)
- Users upload a **new dataset**
- Platform flags possible money laundering cases and shows full AML workflow output

## Workflow Covered

- KYC profiling
- Transaction monitoring
- Explainable AI rationale
- AI risk score and risk band
- Investigation queue + CDD level
- Dashboard summary metrics

## Main App (Python)

- `python_app/streamlit_app.py`: upload-driven UI (scoring only)
- `python_app/aml_pipeline.py`: feature engineering + inference pipeline
- `python_app/train_pretrained_models.py`: one-time model training/persistence
- `models/aml_models.joblib`: pretrained model bundle

## One-time Model Training

```bash
cd /Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/counterai-mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python python_app/train_pretrained_models.py
```

Default training source:

- `/Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/SAML-D.csv`

## Run the Platform

```bash
cd /Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/counterai-mvp
./scripts/run_python_mvp.sh
```

Then open:

- `http://127.0.0.1:5173`

Users only need to upload a scoring CSV with these columns:

- `Time`
- `Date`
- `Sender_account`
- `Receiver_account`
- `Amount`
- `Payment_currency`
- `Received_currency`
- `Sender_bank_location`
- `Receiver_bank_location`
- `Payment_type`

## R Reference

Your original R implementation is preserved for reference under `R/` and `app.R`.
