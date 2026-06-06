# Architecture

CounterAI is a multipage Streamlit app. [`Home.py`](../Home.py) is the entry
point; each file in [`pages/`](../pages/) is one step of the analyst workflow:
KYC & Scoring → Alert Queue → Case Investigation → STR Generation, plus Audit
Log, Management Dashboard, and AI Governance. Models are pretrained offline
(see [MODEL_PIPELINE.md](MODEL_PIPELINE.md)) and used for inference only.

## Session-state contract

Pages share data **only** through `st.session_state`. These keys (initialized in
[`Home.py`](../Home.py)) are the contract between pages — don't rename them, and
preserve them when adding a page.

| Key | Written by | Read by |
|---|---|---|
| `scored_df` | KYC & Scoring | Alert Queue, Case Investigation, Audit, Dashboard, Governance |
| `alert_status` (`{txn_id: {status, reason}}`) | Alert Queue | Case Investigation, Audit |
| `selected_txn_id` | Alert Queue | Case Investigation |
| `selected_case_id` | Alert Queue, Case Investigation | active-case tracking |
| `str_case` | Case Investigation | STR Generation |
| `str_log`, `current_str_id`, `selected_str_record` | STR Generation | STR Generation |
| `current_actor_id` / `current_actor_role` | sidebar | all pages |

Helpers in [`utils/session_utils.py`](../utils/session_utils.py):
`get_current_analyst()`, `require_scored_df()` (call at the top of any page that
needs scored data), and `first_row_as_dict(df)`.

## Models at runtime

`utils/model_loader.py` loads three pickles, but **RF is the only risk scorer** —
CART and Logit exist only to build the explanation rationale. Pages reindex the
engineered matrix to the RF model's `feature_names_in_`, so a new feature must be
added to **both** `utils/feature_engineering.py` and the offline trainer, or it
is silently dropped at scoring time. See [MODEL_PIPELINE.md](MODEL_PIPELINE.md).