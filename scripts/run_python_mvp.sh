#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f models/aml_models.joblib ]; then
  python python_app/train_pretrained_models.py
fi

streamlit run python_app/streamlit_app.py --server.port 5173 --server.address 127.0.0.1
