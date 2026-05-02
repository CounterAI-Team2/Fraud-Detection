source("R/db.R")

render_str_draft <- function(template_path, vars) {
  txt <- paste(readLines(template_path, warn = FALSE), collapse = "\n")
  for (nm in names(vars)) {
    txt <- gsub(paste0("{{", nm, "}}"), as.character(vars[[nm]]), txt, fixed = TRUE)
  }
  txt
}

generate_str <- function(db_path, template_path) {
  conn <- get_conn(db_path)
  on.exit(DBI::dbDisconnect(conn), add = TRUE)

  cdd <- DBI::dbReadTable(conn, "cdd_cases")
  cdd <- cdd[cdd$str_required == 1, ]
  if (nrow(cdd) == 0) {
    return(data.frame())
  }

  dir.create("output", showWarnings = FALSE)

  reports <- lapply(seq_len(nrow(cdd)), function(i) {
    case <- cdd[i, ]
    str_id <- paste0("STR-", i, "-", format(Sys.time(), "%Y%m%d%H%M%S"))
    draft <- render_str_draft(template_path, list(
      str_id = str_id,
      case_id = case$case_id,
      created_at = as.character(Sys.time()),
      rationale = case$rationale
    ))

    draft_path <- file.path("output", paste0(str_id, ".md"))
    writeLines(draft, draft_path)

    log_event(db_path, "STR_DRAFTED", str_id, paste("Case", case$case_id))

    data.frame(
      str_id = str_id,
      case_id = case$case_id,
      status = "DRAFTED",
      draft_path = draft_path,
      created_at = as.character(Sys.time()),
      filed_at = NA_character_,
      stringsAsFactors = FALSE
    )
  })

  reports_df <- do.call(rbind, reports)
  DBI::dbWriteTable(conn, "str_reports", reports_df, append = TRUE)
  reports_df
}
