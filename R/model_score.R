source("R/feature_engineering.R")

score_transactions <- function(new_txn_df, model_bundle) {
  features <- engineer_features(new_txn_df, train_reference = model_bundle$reference)$data

  # Add placeholder target to satisfy formula interface
  features$Is_laundering <- as.factor(0)
  model_input <- get_model_columns(features)

  align_levels <- function(df, xlevels) {
    for (nm in names(xlevels)) {
      if (!nm %in% names(df)) {
        next
      }
      lvl <- xlevels[[nm]]
      vals <- as.character(df[[nm]])
      vals[!(vals %in% lvl)] <- lvl[1]
      df[[nm]] <- factor(vals, levels = lvl)
    }
    df
  }

  model_input_rf <- align_levels(model_input, model_bundle$models$rf$forest$xlevels)
  model_input_cart <- align_levels(model_input, model_bundle$models$cart$xlevels)
  model_input_logit <- align_levels(model_input, model_bundle$models$logit$xlevels)

  p_rf <- tryCatch(
    as.numeric(predict(model_bundle$models$rf, newdata = model_input_rf, type = "prob")[, "1"]),
    error = function(e) rep(NA_real_, nrow(model_input_rf))
  )
  p_cart <- tryCatch(
    as.numeric(predict(model_bundle$models$cart, newdata = model_input_cart, type = "prob")[, "1"]),
    error = function(e) rep(NA_real_, nrow(model_input_cart))
  )
  p_logit <- tryCatch(
    as.numeric(predict(model_bundle$models$logit, newdata = model_input_logit, type = "response")),
    error = function(e) rep(NA_real_, nrow(model_input_logit))
  )

  score_mat <- cbind(p_rf, p_cart, p_logit)
  unified <- rowMeans(score_mat, na.rm = TRUE)
  unified[is.nan(unified)] <- 0

  risk_band <- ifelse(unified >= 0.8, "HIGH", ifelse(unified >= 0.5, "MEDIUM", "LOW"))

  coefs <- coef(model_bundle$models$logit)[-1]
  feature_names <- names(coefs)
  numeric_cols <- names(model_input)[vapply(model_input, is.numeric, logical(1))]
  usable_features <- intersect(feature_names, numeric_cols)

  xai <- vapply(seq_len(nrow(model_input)), function(i) {
    if (length(usable_features) == 0) {
      return("Insufficient numeric features for contribution breakdown")
    }
    row_vals <- model_input[i, usable_features, drop = FALSE]
    contrib <- as.numeric(row_vals[1, ]) * coefs[usable_features]
    top_idx <- order(abs(contrib), decreasing = TRUE)[1:min(3, length(contrib))]
    paste0(usable_features[top_idx], "=", round(contrib[top_idx], 4), collapse = "; ")
  }, character(1))

  data.frame(
    ai_risk_score = round(unified, 4),
    risk_band = risk_band,
    xai_rationale = xai,
    stringsAsFactors = FALSE
  )
}
