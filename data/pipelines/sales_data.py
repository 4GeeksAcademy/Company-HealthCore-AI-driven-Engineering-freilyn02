"""Data loading and temporal split for the HealthCore sales forecasting project.

The split is chronological (never random): the model is trained on the first
8 years and evaluated on the 2 most recent years, so it never sees the future
while training.
"""

from pathlib import Path

import pandas as pd

# data/pipelines/sales_data.py -> parents[1] is the "data" folder
DATA_PATH = Path(__file__).resolve().parents[1] / "raw" / "healthcore_sales.csv"

EXPECTED_COLUMNS = [
    "month",
    "revenue_usd",
    "visits_count",
    "avg_revenue_per_visit_usd",
    "region",
]
NUMERIC_COLUMNS = ["revenue_usd", "visits_count", "avg_revenue_per_visit_usd"]

TRAIN_YEARS = 8
TEST_YEARS = 2


def load_sales(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load the sales CSV, validate its columns and handle null values."""
    df = pd.read_csv(path, parse_dates=["month"])

    missing = [col for col in EXPECTED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns: {missing}")

    # Chronological order is required for a temporal split
    df = df.sort_values("month").reset_index(drop=True)

    # Null handling: monthly series, so we interpolate linearly between
    # neighboring months instead of dropping rows (dropping would leave gaps).
    null_count = int(df[NUMERIC_COLUMNS].isna().sum().sum())
    if null_count > 0:
        df[NUMERIC_COLUMNS] = df[NUMERIC_COLUMNS].interpolate(
            method="linear", limit_direction="both"
        )
    print(f"Null values found and filled: {null_count}")

    return df


def split_train_test(
    df: pd.DataFrame,
    train_years: int = TRAIN_YEARS,
    test_years: int = TEST_YEARS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split chronologically: first `train_years` for training, next `test_years` for testing."""
    first_month = df["month"].min()
    train_end = first_month + pd.DateOffset(years=train_years)  # exclusive
    test_end = train_end + pd.DateOffset(years=test_years)  # exclusive

    train = df[df["month"] < train_end].copy()
    test = df[(df["month"] >= train_end) & (df["month"] < test_end)].copy()

    if train.empty or test.empty:
        raise ValueError("Not enough data to build both the train and test sets.")

    # Leakage guard: every training month must come strictly before every test month
    if train["month"].max() >= test["month"].min():
        raise ValueError("Data leakage: train and test periods overlap.")

    return train, test


if __name__ == "__main__":
    sales = load_sales()
    train_df, test_df = split_train_test(sales)
    print(f"Total rows: {len(sales)}")
    print(
        f"Train: {len(train_df)} rows "
        f"({train_df['month'].min().date()} to {train_df['month'].max().date()})"
    )
    print(
        f"Test:  {len(test_df)} rows "
        f"({test_df['month'].min().date()} to {test_df['month'].max().date()})"
    )