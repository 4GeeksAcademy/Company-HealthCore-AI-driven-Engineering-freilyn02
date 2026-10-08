"""Evaluation metrics for the sales forecasting model (all computed on the TEST set).

What each metric tells Finance:
  - MSE   : average squared error, in USD^2. Big misses weigh much more than small ones.
            RMSE (its square root) is in USD and easier to read.
  - PSI   : Population Stability Index. Do the predictions have the same shape
            (distribution) as the real sales? < 0.10 stable, 0.10-0.25 some drift, > 0.25 big drift.
  - Gini  : normalized Gini. Does the model RANK months correctly (which months sell
            more than others)? 1 = perfect ranking, 0 = no better than random.
  - K2    : R^2 (coefficient of determination). Share of the variation in sales that the
            model explains. 1 = perfect, 0 = no better than predicting the average.

Why a low MSE alone is not enough:
  - MSE is in squared dollars with no "good/bad" reference. It depends on the scale of
    the data, so by itself it cannot say whether the model is useful.
  - It can look small if the model only predicts the average well and misses the
    seasonality (R^2 would expose that).
  - It says nothing about ranking (Gini) or about whether the predicted distribution
    matches reality (PSI).
"""

import numpy as np
from sklearn.metrics import mean_squared_error, r2_score


def mse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(mean_squared_error(actual, predicted))


def k2_score(actual: np.ndarray, predicted: np.ndarray) -> float:
    """K2 score = R^2 (coefficient of determination)."""
    return float(r2_score(actual, predicted))


def _gini(actual: np.ndarray, predicted: np.ndarray) -> float:
    n = len(actual)
    order = np.lexsort((np.arange(n), -predicted))  # sort by prediction, high to low
    cumulative_share = np.cumsum(actual[order]) / actual.sum()
    return float(cumulative_share.sum() / n - (n + 1) / (2 * n))


def normalized_gini(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Gini of the model divided by the Gini of a perfect model (range up to 1)."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return _gini(actual, predicted) / _gini(actual, actual)


def psi(expected: np.ndarray, observed: np.ndarray, bins: int = 5) -> float:
    """Population Stability Index between two samples.

    Bin edges come from quantiles of `expected` (here: the real test sales).
    A tiny epsilon avoids log(0) when a bin is empty.
    """
    expected = np.asarray(expected, dtype=float)
    observed = np.asarray(observed, dtype=float)
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf

    expected_share = np.histogram(expected, bins=edges)[0] / len(expected)
    observed_share = np.histogram(observed, bins=edges)[0] / len(observed)

    eps = 1e-4
    expected_share = np.clip(expected_share, eps, None)
    observed_share = np.clip(observed_share, eps, None)
    return float(np.sum((observed_share - expected_share) * np.log(observed_share / expected_share)))


def evaluate(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mse_value = mse(actual, predicted)
    return {
        "MSE": mse_value,
        "RMSE": float(np.sqrt(mse_value)),
        "MAPE_pct": float(np.mean(np.abs((actual - predicted) / actual)) * 100),
        "PSI": psi(actual, predicted),
        "Gini": normalized_gini(actual, predicted),
        "K2_R2": k2_score(actual, predicted),
    }
