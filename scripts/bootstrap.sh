#!/usr/bin/env bash
set -euo pipefail

mkdir -p .Rlibs
Rscript -e '.libPaths(c(".Rlibs", .libPaths())); install.packages(c("DBI","RSQLite","randomForest","rpart"), lib=".Rlibs", repos="https://cloud.r-project.org")'
Rscript -e '.libPaths(c(".Rlibs", .libPaths())); source("mvp_run_demo.R")'
