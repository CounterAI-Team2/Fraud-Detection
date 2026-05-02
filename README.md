# CounterAI MVP 0.1

This MVP is now **upload-driven** and supports the complete AML workflow:

- KYC profiling
- Transaction monitoring with AI risk score
- Explainable AI rationale per flagged case
- Investigation queue and CDD level determination
- Dashboard metrics for management reporting

Your original R implementation is preserved as model/feature engineering reference under `R/`.
The primary client-facing MVP is implemented in Python + Streamlit.

## Main App (Python)

- `python_app/streamlit_app.py`: UI for uploading datasets and running the full AML flow
- `python_app/aml_pipeline.py`: engineered features + model training/scoring + KYC/CDD/dashboard transforms
- `requirements.txt`: Python dependencies
- `scripts/run_python_mvp.sh`: one-command local run script

## Dataset Inputs

### 1. Training dataset
Must include all transactional columns plus `Is_laundering` target.

### 2. Scoring dataset
Must include transactional columns (target optional) and is used for case flagging.

Required transaction columns:

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

## Run Python MVP UI

```bash
cd /Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/counterai-mvp
./scripts/run_python_mvp.sh
```

Then open `http://127.0.0.1:5173`.

## Assignment 2 Data Packaging

You can generate client-friendly sample datasets from your Assignment 2 `SAML-D.csv`:

```bash
Rscript scripts/prepare_client_data.R
```

This creates:

- `data/demo/aml_demo_data.csv` (for presentation)
- `data/pilot/aml_pilot_data.csv` (for pilot testing)

## Legacy R MVP

R implementation remains available for reference and comparison:

- `app.R`
- `mvp_run_demo.R`
- `R/` modules
