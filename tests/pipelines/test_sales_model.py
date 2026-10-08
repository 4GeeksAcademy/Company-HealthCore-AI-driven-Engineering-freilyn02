"""Sanity tests for the hybrid sales model and its metrics."""

import numpy as np
import pytest

from data.pipelines.sales_data import load_sales, split_train_test
from data.pipelines.sales_metrics import evaluate, normalized_gini, psi
from data.pipelines.sales_model import HybridSalesModel, backtest_log_errors, forecast_interval


@pytest.fixture(scope="module")
def split():
    return split_train_test(load_sales())


def test_model_is_reproducible_with_fixed_seed(split):
    train, test = split

    first = HybridSalesModel(n_estimators=50).fit(train).predict(test)
    second = HybridSalesModel(n_estimators=50).fit(train).predict(test)

    np.testing.assert_allclose(first, second)


def test_model_can_predict_above_the_training_maximum(split):
    train, test = split

    predicted = HybridSalesModel(n_estimators=50).fit(train).predict(test)

    # A plain Random Forest could never exceed the best training month.
    assert predicted.max() > train["revenue_usd"].max()


def test_model_beats_a_naive_mean_forecast(split):
    train, test = split

    predicted = HybridSalesModel(n_estimators=50).fit(train).predict(test)
    metrics = evaluate(test["revenue_usd"].to_numpy(), predicted)

    assert metrics["K2_R2"] > 0.8


def test_backtest_never_uses_the_test_years(split):
    train, _ = split

    errors = backtest_log_errors(train, n_folds=3)

    assert len(errors) == 36  # 3 validation years x 12 months, all inside the train set


def test_interval_wraps_the_point_forecast():
    point = np.array([100.0, 200.0, 300.0])
    errors = np.array([-0.05, 0.0, 0.05])

    low, high = forecast_interval(point, errors)

    assert np.all(low < point) and np.all(point < high)


def test_perfect_prediction_gives_ideal_metrics():
    actual = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])

    metrics = evaluate(actual, actual.copy())

    assert metrics["MSE"] == 0
    assert metrics["K2_R2"] == pytest.approx(1.0)
    assert normalized_gini(actual, actual) == pytest.approx(1.0)
    assert psi(actual, actual) == pytest.approx(0.0, abs=1e-9)
