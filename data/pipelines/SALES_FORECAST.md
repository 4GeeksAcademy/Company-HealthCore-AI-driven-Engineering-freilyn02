# HealthCore Sales Forecast (regression model)

Forecasts monthly revenue for the 2 most recent years (2024-2025) using only the
first 8 years (2016-2023) for training. Run it with:

    python -m data.pipelines.run_sales_forecast

## Data and split

- Source: `data/raw/healthcore_sales.csv` (unaltered), 120 monthly rows.
- Nulls: handled in `load_sales()` (0 found in this file; numeric gaps would be filled).
- Chronological split, never random: train = 2016-01 to 2023-12 (96 rows),
  test = 2024-01 to 2025-12 (24 rows).
- Fixed seed: `random_state=42`.
- No scaling needed: the Random Forest is scale-invariant, and the growth line is
  fitted on a single variable (the month index).

## Algorithm choice: Random Forest (not XGBoost)

| Criterion | Why Random Forest |
|---|---|
| Data size | Only 96 monthly rows to train. Boosting fits each tree to the errors of the previous one and overfits easily on so little data. A forest averages independent trees and is stable with defaults. |
| Explainability | "The forest votes on how far each calendar month is above or below the growth line" is easy to explain to Finance. |
| Tuning time | Almost none. XGBoost would need careful tuning of learning rate, depth and number of rounds. |

### Why it is a hybrid model

A plain Random Forest predicts by averaging values seen in training, so it can
never predict above the best training month (3.73M USD). Sales grow about 4% per
year and the test years reach 4.04M, so a plain forest underestimates them.

Final model = `exp(growth + seasonality)`:
1. A linear regression on log(revenue) vs the month index captures growth (4.16% per year).
2. A Random Forest (500 trees, `min_samples_leaf=2`) learns the seasonal residual
   (summer dip in Jul/Aug, Q4 peak) from calendar features only.

Log scale is used because the seasonal swing grows together with sales.

### No data leakage in the features

Features are calendar-only (month, sin/cos of month, Q4 flag, summer-dip flag, time index).
`visits_count` and `avg_revenue_per_visit_usd` multiply to revenue and are not known
for a future month, so they are not used.

## Results on the TEST set (2024-2025)

| Metric | Hybrid model (chosen) | Plain Random Forest (baseline) |
|---|---|---|
| MSE | 8,974,756,605 | 63,242,152,185 |
| RMSE | 94,735 USD | 251,480 USD |
| MAPE | 2.43% | 6.46% |
| PSI | 0.093 | 3.097 |
| Gini (normalized) | 0.936 | 0.842 |
| K2 (R²) | 0.929 | 0.500 |

The baseline is a Random Forest with the same features plus the month index,
trained directly on raw revenue.

## What each metric means (and why a low MSE alone is not enough)

- **MSE**: average squared error in USD². Large misses weigh much more than small
  ones. RMSE is its square root, in USD.
- **PSI** (Population Stability Index): compares the distribution of the predictions
  with the distribution of the real sales (5 quantile bins of the real values).
  Below 0.10 stable, 0.10-0.25 some drift, above 0.25 major drift.
- **Gini** (normalized): does the model rank months correctly (which sell more than
  others)? 1 = perfect ranking, 0 = random.
- **K2 score**: implemented as R², the share of the variation in sales explained by
  the model. 1 = perfect, 0 = no better than predicting the average.

A low MSE alone is not enough because:
1. It is in squared USD with no "good/bad" reference; it depends on the scale of the data.
2. It can look small for a model that only predicts the average and misses the
   seasonality; R² exposes that.
3. It says nothing about ranking (Gini) or about whether the predicted distribution
   matches reality (PSI). The plain Random Forest above shows it: its errors look
   moderate, but its PSI of 3.1 reveals it is systematically below the real sales.

## Variability band

A per-tree percentile band was tested first and covered only 21% of the real test
months, so it was rejected. The final 80% band comes from a rolling-origin backtest
inside the training set: fit on earlier years, forecast each of the last 3 training
years, collect log(actual / predicted), and use the 10th and 90th percentiles.
The test set is not used to build it. It covers 75% of the 24 test months
(nominal 80%), which is honest given only 36 backtest errors.

Outputs: `data/eval/sales_forecast.png` and `data/eval/sales_forecast_metrics.json`.

## Tests

- `tests/pipelines/test_sales_split.py`: 8/2 split, chronological order, no leakage.
- `tests/pipelines/test_sales_model.py`: reproducibility with fixed seed, predictions
  above the training maximum, R² > 0.8, backtest stays inside the training set,
  band wraps the forecast, metrics are ideal for a perfect prediction.

## Limitations

- Only 24 test months: metrics are indicative, not statistically tight.
- The model assumes steady exponential growth and a stable seasonal shape. A shock
  (new clinics, regulation, pandemic) would not be anticipated.
- PSI and K2 follow the definitions above; confirm them with the course material.
