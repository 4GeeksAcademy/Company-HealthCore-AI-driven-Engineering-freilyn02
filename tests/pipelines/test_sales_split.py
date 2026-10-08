"""Unit tests for the HealthCore sales train/test split.

The ticket requires: first 8 years for training, 2 most recent years for
testing, and no data leakage between both sets.
"""

import pandas as pd
import pytest

from data.pipelines.sales_data import load_sales, split_train_test


@pytest.fixture(scope="module")
def sales_df() -> pd.DataFrame:
    return load_sales()


@pytest.fixture(scope="module")
def split(sales_df):
    return split_train_test(sales_df)


def test_split_follows_8_year_2_year_rule(split):
    train, test = split

    assert train["month"].dt.year.nunique() == 8
    assert test["month"].dt.year.nunique() == 2
    assert len(train) == 96
    assert len(test) == 24


def test_test_set_is_the_two_most_recent_years(sales_df, split):
    _, test = split

    last_year = sales_df["month"].dt.year.max()
    assert sorted(test["month"].dt.year.unique()) == [last_year - 1, last_year]


def test_no_data_leakage_between_sets(split):
    train, test = split

    # No month appears in both sets
    assert set(train["month"]).isdisjoint(set(test["month"]))
    # Every training month comes strictly before every test month
    assert train["month"].max() < test["month"].min()


def test_split_uses_every_row_exactly_once(sales_df, split):
    train, test = split

    assert len(train) + len(test) == len(sales_df)


def test_split_is_chronological_even_if_input_is_shuffled(sales_df):
    shuffled = sales_df.sample(frac=1, random_state=42)

    train, test = split_train_test(shuffled)

    assert train["month"].max() < test["month"].min()
    assert len(train) == 96
    assert len(test) == 24


def test_split_raises_when_there_is_not_enough_data():
    short_df = pd.DataFrame(
        {"month": pd.date_range("2016-01-01", periods=60, freq="MS")}
    )

    with pytest.raises(ValueError):
        split_train_test(short_df)
