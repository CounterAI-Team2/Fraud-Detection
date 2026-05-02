engineer_features <- function(df, train_reference = NULL) {
  payment_currency_chr <- as.character(df$Payment_currency)
  received_currency_chr <- as.character(df$Received_currency)
  sender_loc_chr <- as.character(df$Sender_bank_location)
  receiver_loc_chr <- as.character(df$Receiver_bank_location)

  df$Payment_type <- as.factor(df$Payment_type)
  df$Sender_bank_location <- as.factor(df$Sender_bank_location)
  df$Receiver_bank_location <- as.factor(df$Receiver_bank_location)
  df$Payment_currency <- as.factor(df$Payment_currency)
  df$Received_currency <- as.factor(df$Received_currency)

  df$amount_log <- log10(df$Amount + 1)
  df$cross_currency <- as.integer(payment_currency_chr != received_currency_chr)
  df$cross_border <- as.integer(sender_loc_chr != receiver_loc_chr)
  df$double_flag <- as.integer(df$cross_currency == 1 & df$cross_border == 1)

  if (is.null(train_reference)) {
    sender_counts <- table(df$Sender_account)
    receiver_counts <- table(df$Receiver_account)
    sender_unique_recv <- tapply(df$Receiver_account, df$Sender_account, function(x) length(unique(x)))
    receiver_unique_send <- tapply(df$Sender_account, df$Receiver_account, function(x) length(unique(x)))
    sender_total_amt <- tapply(df$Amount, df$Sender_account, sum, na.rm = TRUE)
    receiver_total_amt <- tapply(df$Amount, df$Receiver_account, sum, na.rm = TRUE)

    train_reference <- list(
      sender_counts = sender_counts,
      receiver_counts = receiver_counts,
      sender_unique_recv = sender_unique_recv,
      receiver_unique_send = receiver_unique_send,
      sender_total_amt = sender_total_amt,
      receiver_total_amt = receiver_total_amt
    )
  }

  map_agg <- function(ids, agg) {
    vals <- as.numeric(agg[ids])
    vals[is.na(vals)] <- 0
    vals
  }

  df$sender_txn_count <- map_agg(df$Sender_account, train_reference$sender_counts)
  df$receiver_txn_count <- map_agg(df$Receiver_account, train_reference$receiver_counts)
  df$sender_unique_receivers <- map_agg(df$Sender_account, train_reference$sender_unique_recv)
  df$receiver_unique_senders <- map_agg(df$Receiver_account, train_reference$receiver_unique_send)
  df$sender_total_amount <- map_agg(df$Sender_account, train_reference$sender_total_amt)
  df$receiver_total_amount <- map_agg(df$Receiver_account, train_reference$receiver_total_amt)

  df$hour <- as.POSIXlt(df$Time, format = "%H:%M:%S")$hour
  df$day_of_week <- as.POSIXlt(as.Date(df$Date))$wday
  df$is_off_hours <- as.integer(df$hour < 6 | df$hour >= 22)

  list(data = df, reference = train_reference)
}

get_model_columns <- function(df) {
  drop_cols <- c(
    "Laundering_type", "Sender_account", "Receiver_account",
    "Amount", "Date", "Time", "double_flag",
    "sender_total_amount", "receiver_total_amount"
  )
  df[, !names(df) %in% drop_cols, drop = FALSE]
}
