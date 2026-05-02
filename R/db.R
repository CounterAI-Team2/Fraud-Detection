get_conn <- function(db_path) {
  if (!requireNamespace("DBI", quietly = TRUE) || !requireNamespace("RSQLite", quietly = TRUE)) {
    stop("Please install DBI and RSQLite: install.packages(c('DBI', 'RSQLite'))")
  }
  DBI::dbConnect(RSQLite::SQLite(), db_path)
}

init_db <- function(db_path) {
  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS customers (
      customer_id TEXT PRIMARY KEY,
      name TEXT,
      country TEXT,
      sanctions_hit INTEGER,
      kyc_risk_tier TEXT,
      created_at TEXT
    )
  ")

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS transactions (
      txn_id TEXT PRIMARY KEY,
      sender_account TEXT,
      receiver_account TEXT,
      amount REAL,
      payment_currency TEXT,
      received_currency TEXT,
      sender_bank_location TEXT,
      receiver_bank_location TEXT,
      payment_type TEXT,
      txn_time TEXT,
      txn_date TEXT,
      ai_risk_score REAL,
      risk_band TEXT,
      alert_status TEXT,
      created_at TEXT
    )
  ")

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS alerts (
      alert_id TEXT PRIMARY KEY,
      txn_id TEXT,
      risk_score REAL,
      status TEXT,
      action_taken TEXT,
      created_at TEXT,
      closed_at TEXT
    )
  ")

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS cdd_cases (
      case_id TEXT PRIMARY KEY,
      alert_id TEXT,
      cdd_level TEXT,
      rationale TEXT,
      str_required INTEGER,
      created_at TEXT
    )
  ")

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS str_reports (
      str_id TEXT PRIMARY KEY,
      case_id TEXT,
      status TEXT,
      draft_path TEXT,
      created_at TEXT,
      filed_at TEXT
    )
  ")

  DBI::dbExecute(conn, "
    CREATE TABLE IF NOT EXISTS audit_log (
      event_id TEXT PRIMARY KEY,
      event_type TEXT,
      ref_id TEXT,
      message TEXT,
      created_at TEXT
    )
  ")
}

log_event <- function(db_path, event_type, ref_id, message) {
  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)
  now <- as.character(Sys.time())
  row <- data.frame(
    event_id = paste0("EVT-", format(Sys.time(), "%Y%m%d%H%M%OS6"), "-", sample.int(9999, 1)),
    event_type = event_type,
    ref_id = ref_id,
    message = message,
    created_at = now
  )
  DBI::dbWriteTable(conn, "audit_log", row, append = TRUE)
}
