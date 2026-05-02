# CounterAI MVP 0.1

This repository implements MVP 0.1 of the AML architecture:

- KYC onboarding with simple sanctions/risk profiling
- Transaction monitoring with AI risk scoring (Random Forest + CART + Logistic Regression)
- Alert queue and investigation routing (dismiss/escalate)
- CDD level determination with model rationale
- STR draft generation from template
- Management dashboard metrics (audit log, alert summary, STR filing rate)

## Project Structure

- `R/`: feature engineering, model training/scoring, and service modules
- `mvp_run_demo.R`: runs an end-to-end MVP scenario
- `templates/str_template.md`: STR draft template
- `output/`: generated run artifacts

## Prerequisites

Install R packages (project-local library):

```r
dir.create(".Rlibs", showWarnings = FALSE)
.libPaths(c(".Rlibs", .libPaths()))
install.packages(c("DBI", "RSQLite", "randomForest", "rpart"), lib = ".Rlibs")
```

Optional (for plotting and EDA extensions): `ggplot2`, `scales`, `rpart.plot`.

## Run MVP Demo

```bash
cd counterai-mvp
Rscript mvp_run_demo.R
```

If your dataset path differs:

```bash
SAML_DATA_PATH=/absolute/path/to/SAML-D.csv Rscript mvp_run_demo.R
```

## GitHub Setup

Local git repo is initialized. To create and push to GitHub:

```bash
git add .
git commit -m "Initialize CounterAI MVP 0.1"
git branch -M main
gh repo create counterai-mvp --private --source=. --remote=origin --push
```

If `gh` is not authenticated, run `gh auth login` first.
