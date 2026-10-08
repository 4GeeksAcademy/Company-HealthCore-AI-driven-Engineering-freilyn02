"""Run the HealthCore sales forecast end to end.

Usage (from the repository root):
    python -m data.pipelines.run_sales_forecast

Outputs:
    - metrics printed on the console (copy them into the Pull Request)
    - data/eval/sales_forecast_metrics.json
    - data/eval/sales_forecast.png  (forecast + variability band vs real test data)
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no screen needed (works in Codespaces / servers)
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from data.pipelines.sales_data import load_sales, split_train_test
from data.pipelines.sales_metrics import evaluate
from data.pipelines.sales_model import (
    TARGET,
    HybridSalesModel,
    backtest_log_errors,
    forecast_interval,
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
LOWER_Q, UPPER_Q = 0.10, 0.90  # 80% variability band

# Colors from the validated dataviz palette (light surface)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e6e5e1"
FORECAST_BLUE = "#2a78d6"  # categorical slot 1
ACTUAL_ORANGE = "#eb6834"  # categorical slot 2


def plot_forecast(train, test, predicted, low, high, metrics, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    history = train[train["month"] >= "2022-01-01"]  # recent history only, for readability
    ax.plot(history["month"], history[TARGET] / 1e6, color=INK_SECONDARY, linewidth=1.6,
            label="Training data (history)")

    ax.fill_between(test["month"], low / 1e6, high / 1e6, color=FORECAST_BLUE, alpha=0.18,
                    linewidth=0, label=f"Variability band ({int((UPPER_Q - LOWER_Q) * 100)}%)")
    ax.plot(test["month"], predicted / 1e6, color=FORECAST_BLUE, linewidth=2, label="Forecast")
    ax.plot(test["month"], test[TARGET] / 1e6, color=ACTUAL_ORANGE, linewidth=2, label="Actual (test years)")

    test_start = test["month"].min()
    ax.axvline(test_start, color=INK_SECONDARY, linestyle=(0, (4, 4)), linewidth=1)
    ax.text(test_start, ax.get_ylim()[1], "  Test period: the model never saw these months",
            color=INK_SECONDARY, fontsize=9, va="top", ha="left")

    # Direct labels at the end of the two lines (above / below to avoid collisions)
    last = test["month"].max()
    ax.annotate("Actual", (last, test[TARGET].iloc[-1] / 1e6), xytext=(6, 6),
                textcoords="offset points", color=INK, fontsize=9)
    ax.annotate("Forecast", (last, predicted[-1] / 1e6), xytext=(6, -12),
                textcoords="offset points", color=INK, fontsize=9)

    ax.set_title("HealthCore monthly revenue: forecast vs actual (2024-2025)",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=26)
    ax.text(0, 1.03,
            f"MAPE {metrics['MAPE_pct']:.1f}%  |  R\u00b2 {metrics['K2_R2']:.2f}  |  "
            f"RMSE ${metrics['RMSE'] / 1e3:,.0f}K  |  band = 10th-90th percentile of past forecast errors",
            transform=ax.transAxes, color=INK_SECONDARY, fontsize=9.5)

    ax.set_ylabel("Revenue (USD millions)", color=INK_SECONDARY)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.1f}M")
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.set_xlim(history["month"].min(), last + np.timedelta64(75, "D"))
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.93), frameon=False, fontsize=9,
              labelcolor=INK)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    sales = load_sales()
    train, test = split_train_test(sales)

    model = HybridSalesModel().fit(train)  # trained ONLY on the first 8 years
    predicted = model.predict(test)
    actual = test[TARGET].to_numpy()

    metrics = evaluate(actual, predicted)

    # Variability band from a backtest inside the training set (test set stays untouched)
    log_errors = backtest_log_errors(train)
    low, high = forecast_interval(predicted, log_errors, LOWER_Q, UPPER_Q)
    coverage = float(np.mean((actual >= low) & (actual <= high)))

    growth_pct_per_year = float((np.exp(model.trend.coef_[0] * 12) - 1) * 100)

    print("\n=== Test-set metrics (2024-2025, never seen during training) ===")
    print(f"MSE   : {metrics['MSE']:,.0f}  (USD^2)")
    print(f"RMSE  : ${metrics['RMSE']:,.0f}")
    print(f"MAPE  : {metrics['MAPE_pct']:.2f}%")
    print(f"PSI   : {metrics['PSI']:.3f}  (predicted vs actual distribution)")
    print(f"Gini  : {metrics['Gini']:.3f}  (normalized)")
    print(f"K2/R2 : {metrics['K2_R2']:.3f}")
    print(f"\nLearned growth: {growth_pct_per_year:.2f}% per year")
    print(f"Variability band ({int((UPPER_Q - LOWER_Q) * 100)}%): "
          f"{coverage:.0%} of the 24 test months fall inside it")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "model": "log-linear growth + RandomForest seasonality",
        "random_state": 42,
        "train_period": [str(train["month"].min().date()), str(train["month"].max().date())],
        "test_period": [str(test["month"].min().date()), str(test["month"].max().date())],
        "metrics": metrics,
        "growth_pct_per_year": growth_pct_per_year,
        "band_coverage_on_test": coverage,
    }
    (EVAL_DIR / "sales_forecast_metrics.json").write_text(json.dumps(results, indent=2))

    plot_path = EVAL_DIR / "sales_forecast.png"
    plot_forecast(train, test, predicted, low, high, metrics, plot_path)
    print(f"\nSaved: {plot_path}")
    print(f"Saved: {EVAL_DIR / 'sales_forecast_metrics.json'}")


if __name__ == "__main__":
    main()
