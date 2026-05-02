# CounterAI MVP 0.1 (Multi-Page Streamlit)

This MVP uses **pretrained models** and a **five-page Streamlit workflow**:

- `app.py` (entry)
- `pages/1_Data_Upload.py`
- `pages/2_Alert_Queue.py`
- `pages/3_Case_Investigation.py`
- `pages/4_STR_Generation.py`
- `pages/5_Audit_Log.py`

## Folder Layout

- `utils/feature_engineering.py`
- `utils/model_loader.py`
- `utils/shap_explainer.py`
- `utils/audit_logger.py`
- `utils/str_builder.py`
- `models/rf_model.pkl`
- `models/cart_model.pkl`
- `data/audit_log.csv` (append-only, auto-created)

## Run

```bash
cd /Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/counterai-mvp
./scripts/run_python_mvp.sh
```

Open `http://127.0.0.1:5173`.

## Notes

- Models are inference-only at runtime.
- Data upload validates SAML-D schema, engineers features, scores risk, and stores results in `st.session_state["scored_df"]`.
- STR page uses `st.session_state["str_case"]` passed from Case Investigation.
