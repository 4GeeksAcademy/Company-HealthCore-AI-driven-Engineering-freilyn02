"""Hybrid sales forecasting model for HealthCore: growth line + Random Forest seasonality.

How to explain it to Finance:
  1. A straight line fitted on log(revenue) captures GROWTH (a steady % per year).
  2. A Random Forest learns what is left after removing growth: the SEASONAL
     pattern (summer dip in Jul/Aug, peak in Oct-Dec), using calendar features only.
  3. Final prediction = exp(growth + seasonality).

Why Random Forest and not XGBoost (algorithm choice criteria):
  - Data size: only 96 monthly rows to train. Boosting (XGBoost) fits each tree to the
    errors of the previous one and overfits easily on so little data, so it needs
    careful tuning. Random Forest averages many independent trees and is stable
    with default settings.
  - Explainability: "the forest votes on how much each calendar month is above or
    below the growth line" is easy to explain; boosting is a harder sell.
  - Tuning time: Random Forest needs almost none.
  - Uncertainty: every tree gives its own prediction, so we can show the spread.

Why not a plain Random Forest on the raw revenue? Trees predict by averaging values
seen in training, so they can NEVER predict above the maximum revenue in the training
set. Sales keep growing, so the test years would be underestimated systematically.
Removing the growth with a linear model first fixes that.

Why log(revenue)? The seasonal swing grows together with sales (a 10% dip in July is
a bigger dollar amount every year). On the log scale the swing is constant, which is
what a Random Forest can learn from only 8 years of data.

Features are calendar-only on purpose. `visits_count` and `avg_revenue_per_visit_usd`
are just revenue split in two (revenue = visits x average), and they are not known
in advance for a future month, so using them would be data leakage.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

RANDOM_STATE = 42  # fixed seed so the experiment is reproducible
TARGET = "revenue_usd"
SEASONAL_FEATURES = ["month_of_year", "month_sin", "month_cos", "is_q4", "is_summer_dip"]


def add_calendar_features(df: pd.DataFrame, origin: pd.Timestamp) -> pd.DataFrame:
    """Add the time index `t` (months since `origin`) and calendar features."""
    out = df.copy()
    month = out["month"].dt.month
    out["t"] = (out["month"].dt.year - origin.year) * 12 + (month - origin.month)
    out["month_of_year"] = month
    out["month_sin"] = np.sin(2 * np.pi * month / 12)
    out["month_cos"] = np.cos(2 * np.pi * month / 12)
    out["is_q4"] = month.isin([10, 11, 12]).astype(int)
    out["is_summer_dip"] = month.isin([7, 8]).astype(int)
    return out


class HybridSalesModel:
    """Growth line (on log revenue) + Random Forest for the seasonal residual."""

    def __init__(self, n_estimators: int = 500, random_state: int = RANDOM_STATE):
        self.trend = LinearRegression()
        self.forest = RandomForestRegressor(
            n_estimators=n_estimators,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
        )
        self.origin_: pd.Timestamp | None = None

    def fit(self, train: pd.DataFrame) -> "HybridSalesModel":
        self.origin_ = train["month"].min()
        features = add_calendar_features(train, self.origin_)
        log_revenue = np.log(train[TARGET].to_numpy())

        self.trend.fit(features[["t"]], log_revenue)
        seasonal_residual = log_revenue - self.trend.predict(features[["t"]])
        self.forest.fit(features[SEASONAL_FEATURES], seasonal_residual)
        return self

    def _features(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.origin_ is None:
            raise RuntimeError("Call fit() before predicting.")
        return add_calendar_features(df, self.origin_)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Point forecast in USD."""
        features = self._features(df)
        log_pred = self.trend.predict(features[["t"]]) + self.forest.predict(
            features[SEASONAL_FEATURES]
        )
        return np.exp(log_pred)

    def predict_per_tree(self, df: pd.DataFrame) -> np.ndarray:
        """One forecast per tree, shape (n_trees, n_months), in USD."""
        features = self._features(df)
        trend = self.trend.predict(features[["t"]])
        per_tree = np.vstack(
            [tree.predict(features[SEASONAL_FEATURES].to_numpy()) for tree in self.forest.estimators_]
        )
        return np.exp(trend + per_tree)


def backtest_log_errors(
    train: pd.DataFrame, n_folds: int = 3, random_state: int = RANDOM_STATE
) -> np.ndarray:
    """Rolling-origin backtest INSIDE the training set (never touches the test set).

    For each of the last `n_folds` training years: fit on all earlier years, forecast
    that whole year, and record log(actual / predicted). These errors tell us how
    wrong the model historically was when forecasting a year ahead.
    """
    last_year = train["month"].dt.year.max()
    errors = []
    for year in range(last_year - n_folds + 1, last_year + 1):
        fit_part = train[train["month"].dt.year < year]
        val_part = train[train["month"].dt.year == year]
        model = HybridSalesModel(random_state=random_state).fit(fit_part)
        pred = model.predict(val_part)
        errors.append(np.log(val_part[TARGET].to_numpy() / pred))
    return np.concatenate(errors)


def forecast_interval(
    point_forecast: np.ndarray,
    log_errors: np.ndarray,
    lower_q: float = 0.10,
    upper_q: float = 0.90,
) -> tuple[np.ndarray, np.ndarray]:
    """Variability band: point forecast scaled by the historical backtest errors."""
    low = point_forecast * np.exp(np.quantile(log_errors, lower_q))
    high = point_forecast * np.exp(np.quantile(log_errors, upper_q))
    return low, high
