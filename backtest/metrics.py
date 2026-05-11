"""
Performance metrics suite — full set from CLAUDE.md §6.

All metrics are computed from:
  - equity_curve: pd.Series (DatetimeIndex, daily or bar resolution)
  - trades: list[Trade] (from BacktestResult)

Returns: PerformanceMetrics dataclass with all fields populated.

Usage:
    metrics = compute(result.equity_curve, result.trades)
    print(metrics.sharpe, metrics.max_drawdown_pct)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from backtest.engine import Trade


# ---------------------------------------------------------------------------
# PerformanceMetrics — the canonical output
# ---------------------------------------------------------------------------


@dataclass
class PerformanceMetrics:
    """Full performance metric set per CLAUDE.md §6."""

    # --- Returns ---
    cagr: float                   # compound annual growth rate
    total_return: float           # e.g. 0.12 = 12%
    monthly_returns: pd.Series    # index: period, values: monthly return

    # --- Risk ---
    annualized_volatility: float  # of daily returns
    max_drawdown: float           # e.g. -0.08 = -8%
    max_drawdown_duration_bars: int
    var_95: float                 # 1-day 95% VaR (negative = loss)
    cvar_95: float                # 1-day 95% CVaR (expected shortfall)

    # --- Risk-Adjusted ---
    sharpe: float
    sortino: float
    calmar: float
    information_ratio: float      # vs. zero (no benchmark) unless bench provided

    # --- Trading ---
    total_trades: int
    win_rate: float               # fraction of profitable trades
    profit_factor: float          # gross_profit / gross_loss
    avg_win: float                # average winning trade P&L
    avg_loss: float               # average losing trade P&L (negative)
    avg_win_loss_ratio: float     # |avg_win / avg_loss|
    avg_holding_bars: float

    # --- Stability ---
    return_autocorrelation: float          # lag-1 AC of daily returns
    rolling_sharpe_12m: pd.Series          # rolling 252-bar Sharpe


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute(
    equity_curve: pd.Series,
    trades: list[Trade],
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> PerformanceMetrics:
    """Compute the full metric set.

    Parameters
    ----------
    equity_curve:
        Bar-resolution equity. DatetimeIndex (UTC).
    trades:
        Closed trade list from BacktestResult.
    risk_free_rate:
        Annual risk-free rate (fraction). Default 0.
    periods_per_year:
        Number of bars per year. 252 for daily bars, 252*24 for hourly.
    """
    returns = _returns(equity_curve)

    cagr = _cagr(equity_curve, periods_per_year)
    total_ret = _total_return(equity_curve)
    monthly_rets = _monthly_returns(equity_curve)
    ann_vol = _annualized_vol(returns, periods_per_year)
    mdd, mdd_dur = _max_drawdown(equity_curve)
    var95, cvar95 = _var_cvar(returns, 0.95)
    sharpe = _sharpe(returns, risk_free_rate, periods_per_year)
    sortino = _sortino(returns, risk_free_rate, periods_per_year)
    calmar = _calmar(cagr, mdd)
    ir = _information_ratio(returns, periods_per_year)
    autocorr = float(returns.autocorr(lag=1)) if len(returns) > 2 else 0.0
    rolling_sh = _rolling_sharpe(returns, window=min(int(periods_per_year), len(returns) - 1))

    # Trade statistics
    total_trades = len(trades)
    if total_trades:
        wins = [t.net_pnl for t in trades if t.net_pnl > 0]
        losses = [t.net_pnl for t in trades if t.net_pnl <= 0]
        win_rate = len(wins) / total_trades
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
        avg_hold = float(np.mean([t.exit_bar - t.entry_bar for t in trades]))
    else:
        win_rate = profit_factor = avg_win = avg_loss = wl_ratio = avg_hold = 0.0

    return PerformanceMetrics(
        cagr=cagr,
        total_return=total_ret,
        monthly_returns=monthly_rets,
        annualized_volatility=ann_vol,
        max_drawdown=mdd,
        max_drawdown_duration_bars=mdd_dur,
        var_95=var95,
        cvar_95=cvar95,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        information_ratio=ir,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_win_loss_ratio=wl_ratio,
        avg_holding_bars=avg_hold,
        return_autocorrelation=autocorr,
        rolling_sharpe_12m=rolling_sh,
    )


# ---------------------------------------------------------------------------
# Individual metric functions (all pure, easily unit-tested)
# ---------------------------------------------------------------------------


def _returns(equity: pd.Series) -> pd.Series:
    """Bar-over-bar percentage returns."""
    return equity.pct_change().dropna()


def _total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0]) - 1.0


def _cagr(equity: pd.Series, periods_per_year: float) -> float:
    """Compound Annual Growth Rate."""
    if len(equity) < 2:
        return 0.0
    total = float(equity.iloc[-1] / equity.iloc[0])
    n_years = len(equity) / periods_per_year
    if n_years <= 0 or total <= 0:
        return 0.0
    return total ** (1.0 / n_years) - 1.0


def _annualized_vol(returns: pd.Series, periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std()) * math.sqrt(periods_per_year)


def _max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """Return (max_drawdown_fraction, max_drawdown_duration_in_bars).

    max_drawdown is negative (e.g. -0.08 = -8%).
    """
    if len(equity) < 2:
        return 0.0, 0
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    mdd = float(dd.min())

    # Duration: longest stretch below a prior peak
    in_dd = (dd < 0).astype(int)
    max_dur = 0
    cur_dur = 0
    for v in in_dd:
        if v:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0

    return mdd, max_dur


def _var_cvar(returns: pd.Series, confidence: float) -> tuple[float, float]:
    """Historical VaR and CVaR at the given confidence level.

    Returns negative values (e.g. VaR=-0.02 means 2% expected daily loss
    at the 95% confidence level).
    """
    if len(returns) < 10:
        return 0.0, 0.0
    sorted_r = np.sort(returns.values)
    idx = int(math.floor((1 - confidence) * len(sorted_r)))
    idx = max(0, min(idx, len(sorted_r) - 1))
    var = float(sorted_r[idx])
    cvar = float(sorted_r[: idx + 1].mean()) if idx >= 0 else var
    return var, cvar


def _sharpe(returns: pd.Series, risk_free_rate: float, periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    rf_per_bar = risk_free_rate / periods_per_year
    excess = returns - rf_per_bar
    std = float(excess.std())
    if std == 0:
        return 0.0
    return float(excess.mean()) / std * math.sqrt(periods_per_year)


def _sortino(returns: pd.Series, risk_free_rate: float, periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    rf_per_bar = risk_free_rate / periods_per_year
    excess = returns - rf_per_bar
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = float(downside.std()) if len(downside) > 1 else float(abs(downside.iloc[0]))
    if downside_std == 0:
        return float("inf")
    return float(excess.mean()) / downside_std * math.sqrt(periods_per_year)


def _calmar(cagr: float, max_drawdown: float) -> float:
    if max_drawdown == 0:
        return float("inf")
    return cagr / abs(max_drawdown)


def _information_ratio(returns: pd.Series, periods_per_year: float) -> float:
    """IR vs. zero benchmark (active return = raw return)."""
    return _sharpe(returns, 0.0, periods_per_year)


def _monthly_returns(equity: pd.Series) -> pd.Series:
    """Monthly compounded returns. Index is Period(M)."""
    if len(equity) < 2:
        return pd.Series(dtype=float)
    # Resample to month-end, take last equity reading, then compute returns
    monthly = equity.resample("ME").last()
    return monthly.pct_change().dropna()


def _rolling_sharpe(returns: pd.Series, window: int) -> pd.Series:
    """Rolling annualized Sharpe over `window` bars."""
    if window < 2 or len(returns) < window:
        return pd.Series(dtype=float, index=returns.index)
    roll_mean = returns.rolling(window).mean()
    roll_std = returns.rolling(window).std()
    # Annualisation factor: assume window ~ 1 year worth of bars for the scale
    scale = math.sqrt(window)
    sharpe = (roll_mean / roll_std.replace(0, float("nan"))) * scale
    return sharpe.dropna()
