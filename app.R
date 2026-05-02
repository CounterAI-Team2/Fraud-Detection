library(shiny)

source("R/config.R")
source("R/db.R")
source("R/model_train.R")
source("R/services_kyc.R")
source("R/services_monitoring.R")
source("R/services_cdd.R")
source("R/services_str.R")
source("R/services_dashboard.R")

ui <- fluidPage(
  titlePanel("CounterAI MVP 0.1 - AML Monitoring UI"),
  sidebarLayout(
    sidebarPanel(
      h4("Run Controls"),
      selectInput(
        "data_mode",
        "Dataset Mode",
        choices = c(
          "Demo (client presentation)" = "demo",
          "Pilot (client testing)" = "pilot"
        )
      ),
      numericInput("train_n", "Training sample size", value = 12000, min = 1000, max = 50000, step = 1000),
      numericInput("txn_n", "Transactions to score", value = 300, min = 50, max = 5000, step = 50),
      actionButton("run_mvp", "Run MVP Flow", class = "btn-primary"),
      hr(),
      verbatimTextOutput("run_status")
    ),
    mainPanel(
      tabsetPanel(
        tabPanel("Dashboard", tableOutput("metrics_table")),
        tabPanel("Scored Transactions", tableOutput("txn_table")),
        tabPanel("CDD Cases", tableOutput("cdd_table")),
        tabPanel("STR Drafts", tableOutput("str_table")),
        tabPanel("Audit Log", tableOutput("audit_table"))
      )
    )
  )
)

server <- function(input, output, session) {
  rv <- reactiveValues(
    status = "Click 'Run MVP Flow' to start.",
    metrics = data.frame(),
    txns = data.frame(),
    cdd = data.frame(),
    str = data.frame(),
    audit = data.frame()
  )

  observeEvent(input$run_mvp, {
    tryCatch({
      .libPaths(c(".Rlibs", .libPaths()))
      dir.create("output", showWarnings = FALSE)

      data_file <- if (input$data_mode == "demo") {
        "data/demo/aml_demo_data.csv"
      } else {
        "data/pilot/aml_pilot_data.csv"
      }

      if (!file.exists(data_file)) {
        stop(paste("Missing", data_file, "- run scripts/prepare_client_data.R first."))
      }

      init_db(counterai_config$db_path)
      raw <- read.csv(data_file)

      n_train <- min(input$train_n, nrow(raw))
      n_txn <- min(input$txn_n, nrow(raw))

      train_df <- raw[sample.int(nrow(raw), n_train), ]
      model_bundle <- train_models(train_df, seed = counterai_config$seed)
      saveRDS(model_bundle, counterai_config$model_artifact)

      customers <- data.frame(
        customer_id = c("CUST-1001", "CUST-1002", "CUST-1003", "CUST-1004"),
        name = c("Meridian Pte Ltd", "Atlas Exports", "BlueNova Trading", "Polar Capital"),
        country = c("SG", "MY", "AE", "IR"),
        sanctions_hit = c(0, 0, 0, 1),
        stringsAsFactors = FALSE
      )
      run_kyc(counterai_config$db_path, customers)

      txns <- raw[sample.int(nrow(raw), n_txn), c(
        "Sender_account", "Receiver_account", "Amount", "Payment_currency",
        "Received_currency", "Sender_bank_location", "Receiver_bank_location",
        "Payment_type", "Time", "Date"
      )]
      txns$txn_id <- paste0("TXN-", sprintf("%05d", seq_len(nrow(txns))))
      txns <- txns[, c("txn_id", "Sender_account", "Receiver_account", "Amount", "Payment_currency",
                       "Received_currency", "Sender_bank_location", "Receiver_bank_location",
                       "Payment_type", "Time", "Date")]

      monitored <- monitor_transactions(counterai_config$db_path, txns, model_bundle)
      cdd_cases <- run_cdd(counterai_config$db_path, monitored)
      str_reports <- generate_str(counterai_config$db_path, counterai_config$str_template)
      metrics <- get_dashboard_metrics(counterai_config$db_path)

      conn <- get_conn(counterai_config$db_path)
      on.exit(DBI::dbDisconnect(conn), add = TRUE)
      audit <- DBI::dbReadTable(conn, "audit_log")

      rv$metrics <- metrics
      rv$txns <- monitored
      rv$cdd <- cdd_cases
      rv$str <- str_reports
      rv$audit <- audit
      rv$status <- paste("Completed.", nrow(monitored), "transactions scored using", input$data_mode, "dataset.")
    }, error = function(e) {
      rv$status <- paste("Run failed:", e$message)
    })
  })

  output$run_status <- renderText(rv$status)
  output$metrics_table <- renderTable(rv$metrics)
  output$txn_table <- renderTable(head(rv$txns, 50))
  output$cdd_table <- renderTable(rv$cdd)
  output$str_table <- renderTable(rv$str)
  output$audit_table <- renderTable(tail(rv$audit, 50))
}

shinyApp(ui, server)
