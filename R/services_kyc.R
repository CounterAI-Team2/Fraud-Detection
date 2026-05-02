source("R/db.R")

run_kyc <- function(db_path, customer_df) {
  now <- as.character(Sys.time())
  customer_df$sanctions_hit <- as.integer(customer_df$sanctions_hit)
  customer_df$kyc_risk_tier <- ifelse(customer_df$sanctions_hit == 1, "HIGH", ifelse(customer_df$country %in% c("IR", "KP", "SY"), "MEDIUM", "LOW"))
  customer_df$created_at <- now

  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)
  DBI::dbWriteTable(conn, "customers", customer_df, append = TRUE)

  apply(customer_df, 1, function(r) {
    log_event(db_path, "KYC_PROFILED", r[["customer_id"]], paste("Tier", r[["kyc_risk_tier"]]))
  })

  customer_df
}
