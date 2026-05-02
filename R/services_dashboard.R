source("R/db.R")

get_dashboard_metrics <- function(db_path) {
  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)

  alerts <- DBI::dbReadTable(conn, "alerts")
  str_reports <- DBI::dbReadTable(conn, "str_reports")
  audit_log <- DBI::dbReadTable(conn, "audit_log")

  total_alerts <- nrow(alerts)
  open_alerts <- sum(alerts$status == "OPEN")
  total_str <- nrow(str_reports)
  str_filing_rate <- ifelse(total_alerts == 0, 0, round(total_str / total_alerts, 4))

  data.frame(
    metric = c("audit_log_events", "alerts_total", "alerts_open", "str_total", "str_filing_rate"),
    value = c(nrow(audit_log), total_alerts, open_alerts, total_str, str_filing_rate),
    stringsAsFactors = FALSE
  )
}
