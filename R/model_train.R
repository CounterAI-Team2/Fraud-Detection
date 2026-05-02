source("R/feature_engineering.R")

train_models <- function(raw_df, seed = 147) {
  set.seed(seed)

  # Ensure target exists for training mode
  if (!"Is_laundering" %in% names(raw_df)) {
    stop("Training data must include Is_laundering column")
  }

  split_idx <- sample(seq_len(nrow(raw_df)), size = floor(0.7 * nrow(raw_df)))
  train_df <- raw_df[split_idx, ]
  test_df <- raw_df[-split_idx, ]

  train_feats <- engineer_features(train_df)
  train_df <- train_feats$data
  ref <- train_feats$reference
  test_df <- engineer_features(test_df, train_reference = ref)$data

  train_df$Is_laundering <- as.factor(train_df$Is_laundering)
  test_df$Is_laundering <- as.factor(test_df$Is_laundering)

  maj <- train_df[train_df$Is_laundering == 0, ]
  mino <- train_df[train_df$Is_laundering == 1, ]
  maj <- maj[sample(seq_len(nrow(maj)), size = nrow(mino)), ]
  train_bal <- rbind(maj, mino)
  train_bal <- train_bal[sample(seq_len(nrow(train_bal))), ]

  train_m <- get_model_columns(train_bal)
  test_m <- get_model_columns(test_df)

  if (!requireNamespace("randomForest", quietly = TRUE) || !requireNamespace("rpart", quietly = TRUE)) {
    stop("Please install randomForest and rpart")
  }

  rf <- randomForest::randomForest(Is_laundering ~ ., data = train_m, importance = TRUE, na.action = na.omit)
  cart <- rpart::rpart(Is_laundering ~ ., data = train_m, method = "class")
  logit <- glm(Is_laundering ~ ., data = train_m, family = binomial(link = "logit"))

  list(
    models = list(rf = rf, cart = cart, logit = logit),
    reference = ref,
    eval_test = test_m
  )
}
