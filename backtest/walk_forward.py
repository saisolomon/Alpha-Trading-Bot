"""
Walk-forward validation harness.

Produces rolling in-sample (IS) / out-of-sample (OOS) windows with zero
leakage between them. The strategy is fit on the IS window and evaluated
on the OOS window; the process repeats with a step forward.

Walk-forward is the minimum validation standard for this repo. Combinatorial
purged CV (López de Prado) is reserved for ML-based signals.

Usage:
    windows = generate_windows(data, is_bars=504, oos_bars=63, step_bars=63)
    results = run_walk_forward(data, strategy_factory, engine_factory, windows)
    for r in results:
        print(r.oos_metrics.sharpe, r.window.oos_start)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pandas as pd

from backtest.costs import CostModel, SymbolSpec
from backtest.engine import BacktestEngine, BacktestResult, Strategy
from backtest.metrics import PerformanceMetrics, compute as compute_metrics

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Window descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardWindow:
    """One IS/OOS split."""

    window_index: int
    is_start: datetime
    is_end: datetime        # exclusive
    oos_start: datetime
    oos_end: datetime       # exclusive
    is_bars: int
    oos_bars: int


# ---------------------------------------------------------------------------
# Per-window result
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardResult:
    """Results for one IS/OOS split."""

    window: WalkForwardWindow
    is_result: BacktestResult
    oos_result: BacktestResult
    is_metrics: PerformanceMetrics
    oos_metrics: PerformanceMetrics


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------


def generate_windows(
    data: pd.DataFrame,
    is_bars: int,
    oos_bars: int,
    step_bars: int | None = None,
    min_is_bars: int | None = None,
) -> list[WalkForwardWindow]:
    """Generate rolling IS/OOS splits for a walk-forward test.

    Parameters
    ----------
    data:
        Full dataset (DatetimeIndex).
    is_bars:
        Number of bars in each in-sample window.
    oos_bars:
        Number of bars in each out-of-sample window.
    step_bars:
        How far to advance between windows. Defaults to oos_bars (non-overlapping OOS).
    min_is_bars:
        Minimum IS bars before OOS begins. Defaults to is_bars.
    """
    if step_bars is None:
        step_bars = oos_bars
    if min_is_bars is None:
        min_is_bars = is_bars

    n = len(data)
    if n < min_is_bars + oos_bars:
        raise ValueError(
            f"Not enough bars ({n}) for min_is_bars={min_is_bars} + oos_bars={oos_bars}"
        )

    windows: list[WalkForwardWindow] = []
    oos_start_idx = min_is_bars

    while oos_start_idx + oos_bars <= n:
        is_start_idx = max(0, oos_start_idx - is_bars)
        is_end_idx = oos_start_idx
        oos_end_idx = min(oos_start_idx + oos_bars, n)

        windows.append(WalkForwardWindow(
            window_index=len(windows),
            is_start=data.index[is_start_idx].to_pydatetime(),
            is_end=data.index[is_end_idx - 1].to_pydatetime(),
            oos_start=data.index[oos_start_idx].to_pydatetime(),
            oos_end=data.index[oos_end_idx - 1].to_pydatetime(),
            is_bars=is_end_idx - is_start_idx,
            oos_bars=oos_end_idx - oos_start_idx,
        ))
        oos_start_idx += step_bars

    log.info(
        "walk_forward.windows_generated",
        extra={"count": len(windows), "is_bars": is_bars, "oos_bars": oos_bars},
    )
    return windows


# ---------------------------------------------------------------------------
# Run walk-forward
# ---------------------------------------------------------------------------


StrategyFactory = Callable[[pd.DataFrame], Strategy]
"""A callable that receives IS data and returns a fitted Strategy instance."""


def run_walk_forward(
    data: pd.DataFrame,
    strategy_factory: StrategyFactory,
    spec: SymbolSpec,
    windows: list[WalkForwardWindow],
    initial_capital: float = 100_000.0,
    cost_model: CostModel | None = None,
    periods_per_year: float = 252.0,
    min_bars_warmup: int = 1,
) -> list[WalkForwardResult]:
    """Run walk-forward on all windows.

    For each window:
      1. Call strategy_factory(is_data) to get a fitted strategy.
      2. Run the engine on IS data → is_result.
      3. Run the same fitted strategy on OOS data → oos_result.
      4. Compute metrics for both.

    Parameters
    ----------
    data:
        Full dataset. Windows are sliced from this.
    strategy_factory:
        Callable receiving IS data, returning a fitted Strategy.
        This is where parameter fitting / optimisation happens.
    spec:
        Symbol specification.
    windows:
        From generate_windows().
    initial_capital:
        Starting equity for each window run (same capital, not compounded).
    cost_model:
        Cost model. Defaults to DEFAULT_COST_MODEL.
    periods_per_year:
        For metric annualisation.
    min_bars_warmup:
        Passed to BacktestEngine.run().
    """
    results: list[WalkForwardResult] = []

    for win in windows:
        is_data = data.loc[win.is_start:win.is_end]
        oos_data = data.loc[win.oos_start:win.oos_end]

        if len(is_data) < 2 or len(oos_data) < 2:
            log.warning(
                "walk_forward.window_skipped",
                extra={"window": win.window_index, "is_bars": len(is_data), "oos_bars": len(oos_data)},
            )
            continue

        # Fit strategy on IS
        try:
            strategy = strategy_factory(is_data)
        except Exception as exc:
            log.error(
                "walk_forward.strategy_factory_error",
                extra={"window": win.window_index, "error": str(exc)},
            )
            continue

        # Run IS backtest
        is_engine = BacktestEngine(is_data, spec, cost_model)
        is_result = is_engine.run(strategy, initial_capital, min_bars_warmup)

        # Run OOS backtest (same fitted strategy — no re-fitting)
        oos_engine = BacktestEngine(oos_data, spec, cost_model)
        oos_result = oos_engine.run(strategy, initial_capital, min_bars_warmup)

        is_metrics = compute_metrics(is_result.equity_curve, is_result.trades, periods_per_year=periods_per_year)
        oos_metrics = compute_metrics(oos_result.equity_curve, oos_result.trades, periods_per_year=periods_per_year)

        results.append(WalkForwardResult(
            window=win,
            is_result=is_result,
            oos_result=oos_result,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
        ))

        log.info(
            "walk_forward.window_complete",
            extra={
                "window": win.window_index,
                "is_sharpe": round(is_metrics.sharpe, 3),
                "oos_sharpe": round(oos_metrics.sharpe, 3),
                "is_trades": is_metrics.total_trades,
                "oos_trades": oos_metrics.total_trades,
            },
        )

    return results


# ---------------------------------------------------------------------------
# Summary across all OOS windows
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardSummary:
    """Aggregate stats across all OOS windows."""

    n_windows: int
    avg_oos_sharpe: float
    median_oos_sharpe: float
    avg_oos_return: float
    avg_oos_max_drawdown: float
    sharpe_degradation: float    # IS avg Sharpe - OOS avg Sharpe
    positive_oos_windows: int    # count of OOS windows with positive return


def summarize(results: list[WalkForwardResult]) -> WalkForwardSummary:
    """Aggregate walk-forward results into a summary."""
    if not results:
        return WalkForwardSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    oos_sharpes = [r.oos_metrics.sharpe for r in results]
    is_sharpes = [r.is_metrics.sharpe for r in results]
    oos_returns = [r.oos_metrics.total_return for r in results]
    oos_dds = [r.oos_metrics.max_drawdown for r in results]

    import statistics
    return WalkForwardSummary(
        n_windows=len(results),
        avg_oos_sharpe=statistics.mean(oos_sharpes),
        median_oos_sharpe=statistics.median(oos_sharpes),
        avg_oos_return=statistics.mean(oos_returns),
        avg_oos_max_drawdown=statistics.mean(oos_dds),
        sharpe_degradation=statistics.mean(is_sharpes) - statistics.mean(oos_sharpes),
        positive_oos_windows=sum(1 for r in oos_returns if r > 0),
    )
