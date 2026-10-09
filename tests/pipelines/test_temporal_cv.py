"""Unit tests for the temporal cross-validation used to evaluate the sales model.

The ticket requires that every fold keeps chronological order: training months
always come before validation months, and nothing is shuffled.
"""

import numpy as np
import pytest
from sklearn.model_selection import TimeSeriesSplit

from data.pipelines.evaluate_sales_model import (
    N_SPLITS,
    compute_learning_curve,
    temporal_cross_validation,
    temporal_folds,
)
from data.pipelines.sales_data import load_sales, split_train_test


@pytest.fixture(scope="module")
def split():
    return split_train_test(load_sales())


@pytest.fixture(scope="module")
def train(split):
    return split[0]


def test_temporal_cv_preserves_chronological_order(train):
    tscv = TimeSeriesSplit(n_splits=N_SPLITS)
    for train_idx, val_idx in tscv.split(train):
        assert max(train_idx) < min(val_idx)
        # Nothing was shuffled: indices stay in ascending order inside each block
        assert list(train_idx) == sorted(train_idx)
        assert list(val_idx) == sorted(val_idx)


def test_pipeline_folds_are_chronological_on_real_dates(train):
    folds = list(temporal_folds(train))

    assert len(folds) >= 5
    for train_idx, val_idx in folds:
        assert train["month"].iloc[train_idx].max() < train["month"].iloc[val_idx].min()
        assert set(train_idx).isdisjoint(val_idx)


def test_validation_blocks_move_forward_in_time(train):
    previous_val_end = None
    for _, val_idx in temporal_folds(train):
        if previous_val_end is not None:
            assert val_idx.min() > previous_val_end  # later fold, later months
        previous_val_end = val_idx.max()


def test_cv_never_touches_the_held_out_test_years(split):
    train, test = split
    last_training_month = train["month"].max()

    for _, val_idx in temporal_folds(train):
        assert train["month"].iloc[val_idx].max() <= last_training_month
        assert train["month"].iloc[val_idx].max() < test["month"].min()


def test_cv_reports_mae_and_rmse_for_train_and_validation(train):
    cv = temporal_cross_validation(train)

    assert len(cv["folds"]) >= 5
    for key in ("train_MAE", "train_RMSE", "validation_MAE", "validation_RMSE"):
        assert cv["summary"][key]["mean"] > 0
        assert cv["summary"][key]["std"] >= 0
    # RMSE can never be smaller than MAE on the same errors
    assert cv["summary"]["validation_RMSE"]["mean"] >= cv["summary"]["validation_MAE"]["mean"]


def test_learning_curve_validates_on_months_after_the_training_window(train):
    curve = compute_learning_curve(train)

    assert len(curve) >= 3
    sizes = [row["n_train"] for row in curve]
    assert sizes == sorted(sizes)
    assert max(sizes) + 12 <= len(train)  # validation stays inside the training set
    assert all(np.isfinite(row["validation"]["RMSE"]) for row in curve)
