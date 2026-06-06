# Model Pipeline

How CounterAI's risk models are trained, evaluated, and served. The training
code lives in [`python_app/aml_pipeline.py`](../python_app/aml_pipeline.py) and
the CLI wrapper in
[`python_app/train_pretrained_models.py`](../python_app/train_pretrained_models.py).
Models are **trained offline and used for inference only** at runtime.

## The three models

| Model | File | Role |
|---|---|---|
| Random Forest | `models/rf_model.pkl` | The **only** risk scorer. The app calls `predict_proba` and applies an adjustable threshold to produce the risk score, prediction (0/1), and tier. |
| CART (decision tree) | `models/cart_model.pkl` | Explainability — contributes to the top-feature rationale shown during investigation. |
| Logistic Regression | `models/logit_model.pkl` | Explainability — contributes to the top-feature rationale. |

All three are saved together in `models/aml_models.joblib` and split into the
individual pickles by [`scripts/split_models.py`](../scripts/split_models.py),
which is what the running app loads.

## Retraining

Requires a SAML-D CSV with an `Is_laundering` target column. The trainer imports
both `aml_pipeline` (in `python_app/`) and `utils/` (at the repo root), so
**both must be on `PYTHONPATH`**:

```powershell
$env:PYTHONPATH = "$PWD\python_app;$PWD"
python python_app/train_pretrained_models.py --train-data <path-to-SAML-D.csv>
python scripts/split_models.py
```

Without the `PYTHONPATH` line you get `ModuleNotFoundError: No module named 'utils'`.

### Optional RF hyperparameter tuning

```powershell
python python_app/train_pretrained_models.py --train-data <csv> --tune-rf
```

`--tune-rf` runs `RandomizedSearchCV` (configurable via `--rf-tune-iterations`,
`--rf-tune-cv-folds`, `--rf-tune-scoring`) and feeds the best parameters into
the final RF fit.

## Training flow

`train_models()` runs these steps in order:

1. **Split first.** The raw dataframe is split 70/30 (stratified on the target)
   *before* any feature engineering. This is critical — see [Avoiding data
   leakage](#avoiding-data-leakage).
2. **Engineer features.** Row-level features are computed per row; account-level
   aggregates (transaction counts, unique-counterparty counts, totals) are
   computed from the **training set only** and then applied to the test set.
   Accounts unseen in training fall back to the training-set mean.
3. **Encode.** Categorical columns are one-hot encoded on the training set; the
   test set is reindexed to the training columns (no unseen categories leak in).
4. **Balance.** The training set is balanced by downsampling the majority
   (non-laundering) class to match the minority class.
5. **Train** RF, CART, and Logit on the balanced training set.
6. **Evaluate** all three on the untouched test set and return metrics.

## Features

Numeric features (`ENGINEERED_FEATURES`):

- `amount_log` — log10 of the transaction amount
- `cross_currency` — payment and received currencies differ
- `cross_border` — sender and receiver bank locations differ
- `sender_txn_count`, `receiver_txn_count` — activity volume per account
- `sender_unique_receivers`, `receiver_unique_senders` — counterparty spread
- `hour`, `day_of_week`, `is_off_hours` — timing signals

Categorical features (one-hot encoded, `CATEGORICAL_FEATURES`): `Payment_type`,
`Payment_currency`, `Received_currency`, `Sender_bank_location`,
`Receiver_bank_location`.

> **Keep both feature lists in sync.** Offline training features live in
> `python_app/aml_pipeline.py`; the runtime app re-engineers features in
> `utils/feature_engineering.py` and reindexes to the trained model's
> `feature_names_in_`. A feature added to one but not the other is silently
> dropped at scoring time.

### Why `Laundering_type` is excluded

The SAML-D `Laundering_type` column is **not** a feature — it is a target leak.
Each typology value maps to exactly one class (e.g. `Structuring`, `Smurfing`
only ever appear on laundering rows; `Normal_*` only on legitimate ones), so a
model trained on it simply reads the answer instead of detecting laundering. It
is also a post-hoc investigator annotation that does not exist at the moment a
real transaction is scored. It is dropped from the model matrix entirely.

## Avoiding data leakage

The pipeline is deliberately ordered to prevent train/test contamination:

- **Split before feature engineering.** Account aggregates (counts, unique
  counterparties, totals) are derived from training rows only. If they were
  computed on the full dataset first, test-set activity would influence the
  features the model sees in training.
- **Encode on train, reindex test.** One-hot columns come from the training
  set; the test set is reindexed to them so test-only categories cannot widen
  the feature space.
- **`Laundering_type` excluded** (see above).

## Reading the metrics

Training prints a per-model table and a confusion matrix for each model:

```
Metric          Random Forest      CART     Logistic
Accuracy        ...
Precision       ...
Recall          ...
F1 Score        ...
AUC-ROC         ...

Confusion Matrix — Random Forest
              Pred Neg   Pred Pos
Actual Neg    ...        ...
Actual Pos    ...        ...
```

For AML, **recall** (the share of true laundering caught) and **precision**
(how many flags are real) matter most; the RF block is the one that reflects
production behaviour, since RF is the scorer. Metrics are also written to
`data/model_registry.json` via the model registry.