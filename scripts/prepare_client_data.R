#!/usr/bin/env Rscript

set.seed(147)
source_data_path <- Sys.getenv("SAML_DATA_PATH", unset = "/Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/SAML-D.csv")

if (!file.exists(source_data_path)) {
  stop("SAML-D.csv not found. Set SAML_DATA_PATH to your dataset path.")
}

dir.create("data/demo", recursive = TRUE, showWarnings = FALSE)
dir.create("data/pilot", recursive = TRUE, showWarnings = FALSE)

raw <- read.csv(source_data_path)

n_demo <- min(300, nrow(raw))
demo <- raw[sample.int(nrow(raw), n_demo), ]
write.csv(demo, "data/demo/aml_demo_data.csv", row.names = FALSE)

n_pilot <- min(15000, nrow(raw))
pilot <- raw[sample.int(nrow(raw), n_pilot), ]
write.csv(pilot, "data/pilot/aml_pilot_data.csv", row.names = FALSE)

cat("Prepared data/demo/aml_demo_data.csv and data/pilot/aml_pilot_data.csv\n")
