source("R/config.R")
source("R/db.R")
source("R/model_train.R")
source("R/services_kyc.R")
source("R/services_monitoring.R")
source("R/services_cdd.R")
source("R/services_str.R")
source("R/services_dashboard.R")

set.seed(counterai_config$seed)
.libPaths(c(".Rlibs", .libPaths()))

cat("CounterAI MVP 0.1 demo run\n")
init_db(counterai_config$db_path)

# Load training data from your existing project folder
source_data_path <- Sys.getenv("SAML_DATA_PATH", unset = "/Users/saikalepu/Documents/BCG/CCAs/CounterAI-Neumann/SAML-D.csv")
raw <- read.csv(source_data_path)

# Keep sample rows for faster MVP demo training
sample_n <- min(25000, nrow(raw))
raw_sample <- raw[sample.int(nrow(raw), sample_n), ]

model_bundle <- train_models(raw_sample, seed = counterai_config$seed)
dir.create("output", showWarnings = FALSE)
saveRDS(model_bundle, counterai_config$model_artifact)

customers <- data.frame(
  customer_id = c("CUST-001", "CUST-002", "CUST-003"),
  name = c("Alpha Trading", "Beta Imports", "Gamma Holdings"),
  country = c("SG", "IR", "MY"),
  sanctions_hit = c(0, 0, 1),
  stringsAsFactors = FALSE
)
run_kyc(counterai_config$db_path, customers)

txns <- data.frame(
  txn_id = paste0("TXN-", sprintf("%03d", 1:5)),
  Sender_account = c("8000A", "8000B", "8000C", "8000A", "9000X"),
  Receiver_account = c("R111", "R222", "R333", "R999", "R777"),
  Amount = c(1200, 450000, 980000, 7600, 1500000),
  Payment_currency = c("SGD", "USD", "USD", "SGD", "USD"),
  Received_currency = c("SGD", "EUR", "USD", "SGD", "EUR"),
  Sender_bank_location = c("SG", "SG", "US", "SG", "AE"),
  Receiver_bank_location = c("SG", "DE", "US", "SG", "IR"),
  Payment_type = c("Credit Card", "Wire", "ACH", "Debit Card", "Wire"),
  Time = c("10:12:10", "23:10:12", "01:10:01", "16:03:55", "03:44:20"),
  Date = as.character(Sys.Date()),
  stringsAsFactors = FALSE
)

monitored <- monitor_transactions(counterai_config$db_path, txns, model_bundle)
cdd_cases <- run_cdd(counterai_config$db_path, monitored)
str_reports <- generate_str(counterai_config$db_path, counterai_config$str_template)
metrics <- get_dashboard_metrics(counterai_config$db_path)

write.csv(monitored, "output/monitored_transactions.csv", row.names = FALSE)
write.csv(cdd_cases, "output/cdd_cases.csv", row.names = FALSE)
write.csv(str_reports, "output/str_reports.csv", row.names = FALSE)
write.csv(metrics, "output/dashboard_metrics.csv", row.names = FALSE)

cat("MVP flow complete. Outputs written to output/*.csv and output/*.md\n")
print(metrics)
