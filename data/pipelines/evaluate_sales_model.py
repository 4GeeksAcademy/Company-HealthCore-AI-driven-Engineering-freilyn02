"""Evaluate the HealthCore sales forecasting model: stability and fit diagnosis.

Usage (from the repository root):
    python -m data.pipelines.evaluate_sales_model

What it does (everything runs on the 8-year TRAINING set only; the 2 held-out
test years are never touched):
  1. Temporal cross-validation with TimeSeriesSplit (5 folds, no shuffle).
     MAE and RMSE are computed on the training part and on the validation part of
     every fold, and reported as mean +/- standard deviation across folds.
  2. Learning curve: training error vs validation error as the training window
     grows. Saved to data/eval/learning_curve.png.
  3. A JSON file with every number, so the report can quote them exactly.

Leakage note: the model uses calendar-only features (month, sin/cos, Q4 flag,
summer-dip flag and a time index). There are no lag or rolling features, so there
is nothing a validation window could leak into. Even so, the model is re-fitted
from scratch on each fold's training rows only, so its time origin and its growth
line are also learned without ever seeing the fold's validation months.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no screen needed (works in Codespaces / servers)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

from data.pipelines.sales_data import load_sales, split_train_test
from data.pipelines.sales_model import TARGET, HybridSalesModel

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"

N_SPLITS = 5  # the ticket asks for at least 5 temporal folds
VALIDATION_WINDOW = 12  # learning curve: each model forecasts the next 12 months
LEARNING_CURVE_SIZES = [24, 36, 48, 60, 72, 84]  # training window sizes, in months
PRIMARY_METRIC = "RMSE"  # justified in data/eval/evaluation_report.md

# Colors from the same dataviz palette used by run_sales_forecast.py
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e6e5e1"
TRAIN_BLUE = "#2a78d6"
VALIDATION_ORANGE = "#eb6834"


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Error, in USD. Every miss weighs the same."""
    return float(mean_absolute_error(actual, predicted))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root Mean Squared Error, in USD. Large misses weigh much more than small ones."""
    return float(np.sqrt(mean_squared_error(actual, predicted)))


def score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {"MAE": mae(actual, predicted), "RMSE": rmse(actual, predicted)}


def temporal_folds(
    train: pd.DataFrame, n_splits: int = N_SPLITS
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, val_idx) pairs where training ALWAYS comes before validation.

    TimeSeriesSplit uses an expanding window: fold k trains on everything before its
    validation block. There is no shuffling, so the future never leaks into the past.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    for train_idx, val_idx in tscv.split(train):
        # Chronological guard (also checked on the real dates, not only on positions)
        assert train_idx.max() < val_idx.min(), "Validation must come after training."
        assert (
            train["month"].iloc[train_idx].max() < train["month"].iloc[val_idx].min()
        ), "Validation months must be later than every training month."
        yield train_idx, val_idx


def temporal_cross_validation(train: pd.DataFrame, n_splits: int = N_SPLITS) -> dict:
    """Run temporal CV and return per-fold scores plus mean +/- std for each metric."""
    folds = []
    for fold_number, (train_idx, val_idx) in enumerate(temporal_folds(train, n_splits), 1):
        fit_part = train.iloc[train_idx]
        val_part = train.iloc[val_idx]

        # Fresh model per fold: its time origin and growth line come from fit_part only
        model = HybridSalesModel().fit(fit_part)

        train_scores = score(fit_part[TARGET].to_numpy(), model.predict(fit_part))
        val_scores = score(val_part[TARGET].to_numpy(), model.predict(val_part))
        folds.append(
            {
                "fold": fold_number,
                "train_period": [
                    str(fit_part["month"].min().date()),
                    str(fit_part["month"].max().date()),
                ],
                "val_period": [
                    str(val_part["month"].min().date()),
                    str(val_part["month"].max().date()),
                ],
                "n_train": len(fit_part),
                "n_val": len(val_part),
                "train": train_scores,
                "validation": val_scores,
            }
        )

    summary = {}
    for split_name in ("train", "validation"):
        for metric in ("MAE", "RMSE"):
            values = np.array([fold[split_name][metric] for fold in folds])
            summary[f"{split_name}_{metric}"] = {
                "mean": float(values.mean()),
                "std": float(values.std()),
            }
    return {"folds": folds, "summary": summary}


def compute_learning_curve(
    train: pd.DataFrame,
    sizes: list[int] = LEARNING_CURVE_SIZES,
    validation_window: int = VALIDATION_WINDOW,
) -> list[dict]:
    """Training vs validation error as the training window grows.

    For each size n: fit on the first n months and measure
      - training error on those same n months,
      - validation error on the NEXT `validation_window` months (still inside the
        8-year training set, so the test years stay untouched).

    sklearn's learning_curve cannot be used directly here: with TimeSeriesSplit it
    caps the sizes at the smallest fold (16 months), which is too short to see the
    seasonal pattern. This explicit loop is the "equivalent" the ticket allows and
    keeps the order chronological by construction.
    """
    rows = []
    for n in sizes:
        if n + validation_window > len(train):
            continue
        fit_part = train.iloc[:n]
        val_part = train.iloc[n : n + validation_window]
        assert fit_part["month"].max() < val_part["month"].min()

        model = HybridSalesModel().fit(fit_part)
        train_scores = score(fit_part[TARGET].to_numpy(), model.predict(fit_part))
        val_scores = score(val_part[TARGET].to_numpy(), model.predict(val_part))
        rows.append({"n_train": n, "train": train_scores, "validation": val_scores})
    return rows


def plot_learning_curve(curve: list[dict], out_path: Path, metric: str = PRIMARY_METRIC) -> None:
    sizes = [row["n_train"] for row in curve]
    train_err = [row["train"][metric] / 1e3 for row in curve]
    val_err = [row["validation"][metric] / 1e3 for row in curve]

    fig, ax = plt.subplots(figsize=(9.5, 5.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    ax.plot(sizes, train_err, color=TRAIN_BLUE, linewidth=2, marker="o", label="Training error")
    ax.plot(sizes, val_err, color=VALIDATION_ORANGE, linewidth=2, marker="o",
            label=f"Validation error (next {VALIDATION_WINDOW} months)")

    # Direct labels at the end of both lines
    ax.annotate(f"${train_err[-1]:,.0f}K", (sizes[-1], train_err[-1]), xytext=(8, -4),
                textcoords="offset points", color=TRAIN_BLUE, fontsize=9)
    ax.annotate(f"${val_err[-1]:,.0f}K", (sizes[-1], val_err[-1]), xytext=(8, -4),
                textcoords="offset points", color=VALIDATION_ORANGE, fontsize=9)

    ax.set_title(f"Learning curve: {metric} vs training window size",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=24)
    ax.text(0, 1.03,
            "Hybrid model (growth line + Random Forest seasonality), training set only (2016-2023)",
            transform=ax.transAxes, color=INK_SECONDARY, fontsize=9.5)

    ax.set_xlabel("Training window size (months)", color=INK_SECONDARY)
    ax.set_ylabel(f"{metric} (USD thousands)", color=INK_SECONDARY)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}K")
    ax.set_xticks(sizes)
    ax.set_xlim(sizes[0] - 3, sizes[-1] + 10)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.legend(loc="upper right", frameon=False, fontsize=9, labelcolor=INK)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    sales = load_sales()
    train, test = split_train_test(sales)  # the test years are never used below

    cv = temporal_cross_validation(train)
    curve = compute_learning_curve(train)

    print(f"\n=== Temporal CV on the training set ({N_SPLITS} folds, TimeSeriesSplit) ===")
    for fold in cv["folds"]:
        print(
            f"Fold {fold['fold']}: train {fold['train_period'][0]}..{fold['train_period'][1]} "
            f"({fold['n_train']} mo) | val {fold['val_period'][0]}..{fold['val_period'][1]} "
            f"({fold['n_val']} mo) | "
            f"val MAE ${fold['validation']['MAE']:,.0f}  val RMSE ${fold['validation']['RMSE']:,.0f}"
        )
    print()
    for key, stats in cv["summary"].items():
        print(f"{key:<16}: {stats['mean']:,.0f} +/- {stats['std']:,.0f} USD")
    primary = cv["summary"][f"validation_{PRIMARY_METRIC}"]
    print(f"\nPrimary metric ({PRIMARY_METRIC}) on validation: "
          f"{primary['mean']:.4f} +/- {primary['std']:.4f}")

    print("\n=== Learning curve (train on first n months, validate on the next 12) ===")
    for row in curve:
        print(
            f"n={row['n_train']:>3} | train MAE ${row['train']['MAE']:,.0f} "
            f"RMSE ${row['train']['RMSE']:,.0f} | val MAE ${row['validation']['MAE']:,.0f} "
            f"RMSE ${row['validation']['RMSE']:,.0f}"
        )

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "model": "log-linear growth + RandomForest seasonality",
        "primary_metric": PRIMARY_METRIC,
        "n_splits": N_SPLITS,
        "train_period": [str(train["month"].min().date()), str(train["month"].max().date())],
        "test_years_used": False,
        "cross_validation": cv,
        "learning_curve": curve,
    }
    json_path = EVAL_DIR / "evaluation_metrics.json"
    json_path.write_text(json.dumps(results, indent=2))

    plot_path = EVAL_DIR / "learning_curve.png"
    plot_learning_curve(curve, plot_path)
    print(f"\nSaved: {plot_path}")
    print(f"Saved: {json_path}")


if __name__ == "__main__":
    main()
