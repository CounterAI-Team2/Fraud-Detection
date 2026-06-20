# CounterAI — AML Detection Platform (MVP 0.1)

A multipage Streamlit app for anti-money-laundering (AML) decision support.
It scores SAML-D transactions for laundering risk and walks an analyst through
screening → alert triage → investigation → STR filing → audit. Models are
pretrained offline and loaded at runtime for inference only.

## Live demo

A hosted version is available at
**<https://counterai-fraud-detection.streamlit.app>**. It is deployed from this
GitHub repository, so any changes pushed to the repo are automatically
reflected on the live site.

## Quick start (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run Home.py --server.port 5173 --server.address 127.0.0.1
```

Open <http://127.0.0.1:5173>. The entry point is **`Home.py`**; Streamlit
auto-discovers the workflow pages in `pages/`.

## Pages

| Page | Purpose |
|---|---|
| KYC Screening | Enrol and manage customers, risk profiles, and sanctions screening. |
| Transaction Data Upload | Upload a SAML-D CSV and score every transaction. |
| Alert Queue | Triage flagged transactions; escalate or dismiss. |
| Case Investigation | Investigate a transaction with feature-level explanations. |
| STR Generation | Draft → L1 → L2 → Approve a Suspicious Transaction Report. |
| Audit Log | View the audit trail. |
| Management Dashboard | Portfolio-level metrics. |
| AI Governance | Model registry and drift monitoring. |

## Retraining the models

Needs a SAML-D CSV with an `Is_laundering` column. Both `python_app/` and the
repo root must be on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$PWD\python_app;$PWD"
python python_app/train_pretrained_models.py --train-data <path-to-SAML-D.csv>
python scripts/split_models.py
```

Details of the pipeline (leakage-safe design, features, metrics) are in
[docs/MODEL_PIPELINE.md](docs/MODEL_PIPELINE.md).

## Layout

```
Home.py        # entry point
pages/         # one file per workflow page
python_app/    # offline model training + scoring logic
utils/         # feature engineering, model loading, data stores, rules
models/        # pretrained .pkl files + aml_models.joblib bundle
scripts/       # split_models.py and data-prep helpers
data/          # CSV/JSON stores (auto-created at startup)
tests/         # pytest suite
```
