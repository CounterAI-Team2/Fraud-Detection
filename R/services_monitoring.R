source("R/db.R")
source("R/model_score.R")

monitor_transactions <- function(db_path, txn_df, model_bundle) {
  scores <- score_transactions(txn_df, model_bundle)
  out <- cbind(txn_df, scores)

  out$alert_status <- ifelse(out$risk_band == "LOW", "DISMISSED", "OPEN")
  out$created_at <- as.character(Sys.time())
  out$sender_account <- out$Sender_account
  out$receiver_account <- out$Receiver_account
  out$amount <- out$Amount
  out$payment_currency <- out$Payment_currency
  out$received_currency <- out$Received_currency
  out$sender_bank_location <- out$Sender_bank_location
  out$receiver_bank_location <- out$Receiver_bank_location
  out$payment_type <- out$Payment_type
  out$txn_time <- out$Time
  out$txn_date <- out$Date

  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)
  DBI::dbWriteTable(conn, "transactions", out[, c(
    "txn_id", "sender_account", "receiver_account", "amount", "payment_currency", "received_currency",
    "sender_bank_location", "receiver_bank_location", "payment_type", "txn_time", "txn_date",
    "ai_risk_score", "risk_band", "alert_status", "created_at"
  )], append = TRUE)

  alert_rows <- out[out$alert_status == "OPEN", c("txn_id", "ai_risk_score")]
  if (nrow(alert_rows) > 0) {
    alerts <- data.frame(
      alert_id = paste0("ALERT-", seq_len(nrow(alert_rows)), "-", format(Sys.time(), "%Y%m%d%H%M%S")),
      txn_id = alert_rows$txn_id,
      risk_score = alert_rows$ai_risk_score,
      status = "OPEN",
      action_taken = "INVESTIGATE",
      created_at = as.character(Sys.time()),
      closed_at = NA_character_,
      stringsAsFactors = FALSE
    )
    DBI::dbWriteTable(conn, "alerts", alerts, append = TRUE)

    apply(alerts, 1, function(a) {
      log_event(db_path, "ALERT_CREATED", a[["alert_id"]], paste("Txn", a[["txn_id"]], "risk", a[["risk_score"]]))
    })
  }

  out
}
