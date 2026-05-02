source("R/db.R")

run_cdd <- function(db_path, monitored_df) {
  escalated <- monitored_df[monitored_df$risk_band %in% c("MEDIUM", "HIGH"), ]
  if (nrow(escalated) == 0) {
    return(data.frame())
  }

  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)
  alerts <- DBI::dbReadTable(conn, "alerts")
  alerts <- alerts[alerts$txn_id %in% escalated$txn_id, ]

  cdd_level <- ifelse(escalated$ai_risk_score >= 0.85, "ENHANCED", "STANDARD")
  str_required <- as.integer(escalated$ai_risk_score >= 0.85)

  cases <- data.frame(
    case_id = paste0("CDD-", seq_len(nrow(escalated)), "-", format(Sys.time(), "%Y%m%d%H%M%S")),
    alert_id = alerts$alert_id,
    cdd_level = cdd_level,
    rationale = escalated$xai_rationale,
    str_required = str_required,
    created_at = as.character(Sys.time()),
    stringsAsFactors = FALSE
  )

  DBI::dbWriteTable(conn, "cdd_cases", cases, append = TRUE)

  apply(cases, 1, function(ca) {
    log_event(db_path, "CDD_COMPLETED", ca[["case_id"]], paste("CDD", ca[["cdd_level"]], "STR", ca[["str_required"]]))
  })

  cases
}
