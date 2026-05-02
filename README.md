# CounterAI MVP 0.1

CounterAI MVP 0.1 now includes:

- End-to-end AML backend flow (KYC -> scoring -> alerts -> CDD -> STR draft -> dashboard metrics)
- Shiny user interface for client presentation and pilot testing
- Assignment 2 AML data packaged into:
  - `data/demo/aml_demo_data.csv` (presentation dataset)
  - `data/pilot/aml_pilot_data.csv` (pilot testing dataset)

## Project Structure

- `app.R`: Shiny UI for operating MVP 0.1
- `R/`: feature engineering, model training/scoring, service modules
- `scripts/prepare_client_data.R`: generates demo and pilot datasets from `SAML-D.csv`
- `mvp_run_demo.R`: CLI end-to-end run (non-UI)
- `templates/str_template.md`: STR draft template

## Prerequisites

Use a project-local library:

```r
dir.create(".Rlibs", showWarnings = FALSE)
.libPaths(c(".Rlibs", .libPaths()))
install.packages(c("DBI", "RSQLite", "randomForest", "rpart", "shiny"), lib = ".Rlibs")
```

## Prepare Client Data

From project root:

```bash
Rscript scripts/prepare_client_data.R
```

By default this reads:

`/Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/SAML-D.csv`

Or override:

```bash
SAML_DATA_PATH=/absolute/path/to/SAML-D.csv Rscript scripts/prepare_client_data.R
```

## Run UI (Client Demo / Pilot)

```bash
Rscript -e '.libPaths(c(".Rlibs", .libPaths())); shiny::runApp(".", host="127.0.0.1", port=5173)'
```

In the UI:

- Choose **Demo** or **Pilot** dataset mode
- Click **Run MVP Flow**
- Review Dashboard, Scored Transactions, CDD, STR, and Audit Log tabs

## CLI MVP Run (Optional)

```bash
Rscript -e '.libPaths(c(".Rlibs", .libPaths())); source("mvp_run_demo.R")'
```
