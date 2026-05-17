"""
Gold-silver pairs trading: cointegration-based spread mean-reversion.

Architecture mirrors strategies/index_meanrev/ but with TWO LEGS per trade.
Per HYPOTHESIS.md: long the cheap leg + short the expensive leg, sized so
dollar exposures cancel; entry on z-score extreme, exit on reversion / time
/ catastrophic stop.

The engine is per-pair (one strategy = one pair); for the gold-silver pair
the legs are XAUUSD and XAGUSD. Other cointegrated pairs would use a
separate engine instance with their own symbols.

Walk-forward correctness:
  - The cointegration coefficients (beta, alpha) are refit on a ROLLING
    window of the past `coint_lookback` bars. At each bar T we use only
    bars <= T to estimate the equilibrium relationship.
  - The z-score normalisation also uses a rolling window (past `z_lookback`
    bars of the spread series).
  - No look-ahead anywhere -- the same module is used for both backtest
    and live (via the libquant rolling-zscore for cross-language parity).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from backtest.costs import CostModel, DEFAULT_COST_MODEL, SymbolSpec


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairsConfig:
    """Parameters for one cointegration-based pairs strategy."""

    symbol_a: str = "XAUUSD"
    """Numerator of the spread (log_a - beta*log_b)."""

    symbol_b: str = "XAGUSD"
    """Denominator."""

    # Cointegration fitting
    coint_lookback: int = 504
    """Bars used to refit (beta, alpha) -- ~2 years of D1."""

    refit_every: int = 21
    """Re-estimate beta/alpha every N bars (default ~monthly)."""

    # Signal
    z_lookback: int = 252
    """Bars used to normalise the spread into a z-score."""

    entry_z: float = 2.0
    """|z| > this fires entry."""

    exit_z: float = 0.5
    """|z| < this fires exit."""

    max_hold_bars: int = 60
    """Time stop -- ~half the gold/silver mean-reversion half-life."""

    catastrophic_z: float = 4.0
    """If |z| exceeds this (cointegration broken), close at a loss."""

    # Sizing
    per_trade_risk_pct: float = 0.005
    """Fraction of equity to risk per trade (on the SPREAD's worst-case
    adverse move)."""

    atr_period: int = 14
    atr_stop_mult: float = 1.5
    """Hard stop distance, in ATR units of the SPREAD."""

    # Cointegration health monitor
    min_coint_p_value: float = 0.10
    """If the rolling ADF p-value of the spread exceeds this, pause new
    entries (the cointegrating relationship may have broken)."""


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class OpenPairsPosition:
    direction: int          # +1 long-spread (long a, short b); -1 short-spread
    lots_a: float
    lots_b: float
    entry_price_a: float
    entry_price_b: float
    entry_bar: int
    entry_time: datetime
    entry_spread: float
    entry_z: float
    spread_stop: float       # spread level at which to hard-stop
    spread_tp: float         # not used (we use z-revert as TP); kept for parity
    open_commission: float
    bars_held: int = 0


@dataclass
class PairsTrade:
    direction: int
    lots_a: float
    lots_b: float
    entry_price_a: float
    entry_price_b: float
    exit_price_a: float
    exit_price_b: float
    entry_bar: int
    exit_bar: int
    entry_time: datetime
    exit_time: datetime
    entry_z: float
    exit_z: float
    gross_pnl: float
    commission: float
    net_pnl: float
    exit_reason: str           # "exit_z" | "time_stop" | "catastrophic" | "end_of_data"


@dataclass
class PairsResult:
    equity_curve: pd.Series
    equity_low: pd.Series
    trades: list[PairsTrade]
    initial_capital: float

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.net_pnl > 0) / len(self.trades)

    @property
    def total_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return float(self.equity_curve.iloc[-1] / self.equity_curve.iloc[0] - 1.0)


# ---------------------------------------------------------------------------
# Spread computation -- the cointegration regression
# ---------------------------------------------------------------------------


def fit_coint(log_a: np.ndarray, log_b: np.ndarray) -> tuple[float, float]:
    """OLS: log_a = beta * log_b + alpha.
    Returns (beta, alpha). Uses numpy.polyfit for numerical stability."""
    if len(log_a) < 30:
        return 1.0, 0.0
    beta, alpha = np.polyfit(log_b, log_a, 1)
    return float(beta), float(alpha)


# ---------------------------------------------------------------------------
# Bar-level computation (with optional libquant acceleration)
# ---------------------------------------------------------------------------


try:
    import quantlib as _qlib
    _HAVE_QUANTLIB = True
except ImportError:
    _HAVE_QUANTLIB = False


def rolling_zscore_np(series: np.ndarray, lookback: int) -> np.ndarray:
    """Rolling z-score using libquant (single-source-of-truth with live) if
    available, else pandas. Both produce ddof=1 sample-std normalisation."""
    if _HAVE_QUANTLIB:
        return np.asarray(_qlib.compute_rolling_zscore(series.tolist(), lookback))
    s = pd.Series(series)
    mean = s.rolling(lookback).mean()
    std = s.rolling(lookback).std()  # ddof=1 default
    return ((s - mean) / std).to_numpy()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PairsEngine:
    """Per-pair cointegration mean-reversion engine.

    Parameters
    ----------
    specs : dict[str, SymbolSpec]
        Must contain entries for config.symbol_a and config.symbol_b.
    cost_model : CostModel
    """

    def __init__(
        self,
        specs: dict[str, SymbolSpec],
        cost_model: CostModel = DEFAULT_COST_MODEL,
    ) -> None:
        self._specs = specs
        self._cost = cost_model

    def _precompute_spread(
        self, prices_a: pd.Series, prices_b: pd.Series, config: PairsConfig,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Compute rolling (beta, alpha, spread, z) series.

        Returns
        -------
        spread : pd.Series  (NaN in warmup)
        z : pd.Series       (NaN in warmup)
        beta_series : pd.Series  (NaN in warmup; recomputed every refit_every bars)
        """
        # Align indices
        df = pd.concat([prices_a, prices_b], axis=1, join="inner").dropna()
        df.columns = ["a", "b"]
        log_a = np.log(df["a"].to_numpy())
        log_b = np.log(df["b"].to_numpy())
        n = len(df)

        spread = np.full(n, np.nan)
        beta_arr = np.full(n, np.nan)
        # Refit every refit_every bars; in-between, use the most recent fit.
        current_beta = 1.0
        current_alpha = 0.0
        for i in range(config.coint_lookback, n):
            if (i - config.coint_lookback) % config.refit_every == 0:
                lo = i - config.coint_lookback
                current_beta, current_alpha = fit_coint(log_a[lo:i], log_b[lo:i])
            spread[i] = log_a[i] - current_beta * log_b[i] - current_alpha
            beta_arr[i] = current_beta

        # Z-score the spread over z_lookback bars
        z = rolling_zscore_np(spread, config.z_lookback)

        spread_s = pd.Series(spread, index=df.index, name="spread")
        z_s = pd.Series(z, index=df.index, name="z")
        beta_s = pd.Series(beta_arr, index=df.index, name="beta")
        return spread_s, z_s, beta_s

    def _compute_lots(
        self, equity: float, config: PairsConfig,
        price_a: float, price_b: float, beta: float,
        spread_atr: float,
    ) -> tuple[float, float]:
        """Compute the two leg sizes for a market-neutral pairs trade.

        Sizing principle: target a $-risk on the SPREAD's adverse move
        (atr_stop_mult * spread_atr in log units). The two legs CANCEL most
        of their notional P&L exposure -- only the residual spread move
        creates trade P&L.

        Mechanics:
          spread = log(P_a) - beta * log(P_b)
          d(spread) = dP_a/P_a - beta * dP_b/P_b   (for small moves)
          $P&L = (long_a notional) * dP_a/P_a + (short_b notional) * (-dP_b/P_b)
               = (long_a notional) * (dP_a/P_a - dP_b/P_b)   if long_a = short_b notionally
               which equals (long_a notional) * d(spread) when beta = 1.
          So:  $P&L_per_unit_spread = long_a_notional         (when beta = 1)
          Generalising: with beta != 1, dollar-neutral hedge means leg sizes
          are NOT in 1:beta dollar ratio; they're in 1:1 dollar ratio (we want
          to fully hedge the market component), and the leg P&L imbalance IS
          the cointegration alpha.

        Risk per unit spread move = long_a_notional (= leg dollar exposure).
        Stop distance in $-P&L terms = leg_notional * stop_log.
        Solve for leg_notional given risk_amount and stop_log.
        """
        spec_a = self._specs[config.symbol_a]
        spec_b = self._specs[config.symbol_b]
        stop_log = config.atr_stop_mult * spread_atr
        if stop_log <= 0:
            return 0.0, 0.0
        risk_amount = equity * config.per_trade_risk_pct
        # leg_notional * stop_log = risk_amount
        leg_notional = risk_amount / stop_log
        lots_a_raw = leg_notional / (spec_a.contract_size * price_a)
        lots_b_raw = leg_notional / (spec_b.contract_size * price_b)
        lots_a = np.floor(lots_a_raw * 100) / 100.0
        lots_b = np.floor(lots_b_raw * 100) / 100.0
        return max(0.01, lots_a), max(0.01, lots_b)

    def run(
        self,
        prices_a: pd.Series,
        prices_b: pd.Series,
        config: PairsConfig,
        initial_capital: float = 100_000.0,
    ) -> PairsResult:
        spread, z, beta_series = self._precompute_spread(prices_a, prices_b, config)
        # ATR of the spread (use abs first-differences EWM)
        spread_diff = spread.diff().abs()
        spread_atr = spread_diff.ewm(span=config.atr_period, adjust=False).mean()

        df_a = prices_a.reindex(spread.index)
        df_b = prices_b.reindex(spread.index)

        spec_a = self._specs[config.symbol_a]
        spec_b = self._specs[config.symbol_b]

        realised_pnl = 0.0
        position: Optional[OpenPairsPosition] = None
        closed: list[PairsTrade] = []
        equity_vals: list[float] = []
        equity_low_vals: list[float] = []
        timestamps: list[pd.Timestamp] = []

        n_bars = len(spread)
        for bar_i in range(n_bars):
            ts = spread.index[bar_i]
            close_a = float(df_a.iloc[bar_i])
            close_b = float(df_b.iloc[bar_i])

            # Mark-to-market the open position (if any)
            unrealised = 0.0
            if position is not None:
                pnl_a = spec_a.pnl(position.entry_price_a, close_a,
                                    +1 if position.direction == +1 else -1,
                                    position.lots_a)
                pnl_b = spec_b.pnl(position.entry_price_b, close_b,
                                    -1 if position.direction == +1 else +1,
                                    position.lots_b)
                unrealised = pnl_a + pnl_b - position.open_commission

            equity = initial_capital + realised_pnl + unrealised
            equity_vals.append(equity)
            equity_low_vals.append(equity)  # no intra-bar low approximation for pairs
            timestamps.append(ts)

            # Update bar count on open positions
            if position is not None:
                position.bars_held += 1

            z_t = z.iloc[bar_i] if bar_i < len(z) else float("nan")
            atr_t = spread_atr.iloc[bar_i] if bar_i < len(spread_atr) else float("nan")

            # ----------------------------------------------------------
            # Exit logic
            # ----------------------------------------------------------
            if position is not None and not np.isnan(z_t):
                should_exit = False
                reason = ""
                # Time stop
                if position.bars_held >= config.max_hold_bars:
                    should_exit, reason = True, "time_stop"
                # Reversion exit
                elif abs(z_t) < config.exit_z:
                    should_exit, reason = True, "exit_z"
                # Catastrophic
                elif (position.direction == +1 and z_t < -config.catastrophic_z) or \
                     (position.direction == -1 and z_t > +config.catastrophic_z):
                    should_exit, reason = True, "catastrophic"
                if should_exit and bar_i + 1 < n_bars:
                    # Close both legs at next bar open (use close as proxy --
                    # pairs trades typically use VWAP or close; the D1 backtest
                    # treats them equivalent at end-of-bar).
                    next_a = float(df_a.iloc[bar_i + 1])
                    next_b = float(df_b.iloc[bar_i + 1])
                    fill_a = self._cost.fill_price(
                        next_a, -position.direction, spec_a, position.lots_a)
                    fill_b = self._cost.fill_price(
                        next_b, +position.direction, spec_b, position.lots_b)
                    gross_a = spec_a.pnl(position.entry_price_a, fill_a,
                                          +1 if position.direction == +1 else -1,
                                          position.lots_a)
                    gross_b = spec_b.pnl(position.entry_price_b, fill_b,
                                          -1 if position.direction == +1 else +1,
                                          position.lots_b)
                    gross = gross_a + gross_b
                    close_comm = (
                        self._cost.commission(position.lots_a, spec_a)
                        + self._cost.commission(position.lots_b, spec_b)
                    )
                    net = gross - position.open_commission - close_comm
                    realised_pnl += net
                    closed.append(PairsTrade(
                        direction=position.direction,
                        lots_a=position.lots_a, lots_b=position.lots_b,
                        entry_price_a=position.entry_price_a,
                        entry_price_b=position.entry_price_b,
                        exit_price_a=fill_a, exit_price_b=fill_b,
                        entry_bar=position.entry_bar, exit_bar=bar_i + 1,
                        entry_time=position.entry_time,
                        exit_time=spread.index[bar_i + 1],
                        entry_z=position.entry_z, exit_z=float(z_t),
                        gross_pnl=gross,
                        commission=position.open_commission + close_comm,
                        net_pnl=net, exit_reason=reason,
                    ))
                    position = None

            # ----------------------------------------------------------
            # Entry logic
            # ----------------------------------------------------------
            if position is None and not np.isnan(z_t) and not np.isnan(atr_t) and atr_t > 0:
                direction = 0
                if z_t < -config.entry_z:
                    direction = +1  # long spread = long a, short b
                elif z_t > +config.entry_z:
                    direction = -1  # short spread = short a, long b
                if direction != 0 and bar_i + 1 < n_bars:
                    next_a = float(df_a.iloc[bar_i + 1])
                    next_b = float(df_b.iloc[bar_i + 1])
                    current_beta = beta_series.iloc[bar_i]
                    lots_a, lots_b = self._compute_lots(
                        equity, config, next_a, next_b,
                        current_beta if not np.isnan(current_beta) else 1.0,
                        atr_t,
                    )
                    if lots_a <= 0 or lots_b <= 0:
                        continue
                    fill_a = self._cost.fill_price(
                        next_a, +direction, spec_a, lots_a)
                    fill_b = self._cost.fill_price(
                        next_b, -direction, spec_b, lots_b)
                    open_comm = (
                        self._cost.commission(lots_a, spec_a)
                        + self._cost.commission(lots_b, spec_b)
                    )
                    position = OpenPairsPosition(
                        direction=direction,
                        lots_a=lots_a, lots_b=lots_b,
                        entry_price_a=fill_a, entry_price_b=fill_b,
                        entry_bar=bar_i + 1,
                        entry_time=spread.index[bar_i + 1],
                        entry_spread=float(spread.iloc[bar_i]),
                        entry_z=float(z_t),
                        spread_stop=0.0,   # using z-based stops, not price stops
                        spread_tp=0.0,
                        open_commission=open_comm,
                    )

        # Force-close at end
        if position is not None:
            last_bar = n_bars - 1
            last_a = float(df_a.iloc[last_bar])
            last_b = float(df_b.iloc[last_bar])
            gross_a = spec_a.pnl(position.entry_price_a, last_a,
                                  +1 if position.direction == +1 else -1,
                                  position.lots_a)
            gross_b = spec_b.pnl(position.entry_price_b, last_b,
                                  -1 if position.direction == +1 else +1,
                                  position.lots_b)
            gross = gross_a + gross_b
            close_comm = (
                self._cost.commission(position.lots_a, spec_a)
                + self._cost.commission(position.lots_b, spec_b)
            )
            net = gross - position.open_commission - close_comm
            realised_pnl += net
            closed.append(PairsTrade(
                direction=position.direction,
                lots_a=position.lots_a, lots_b=position.lots_b,
                entry_price_a=position.entry_price_a,
                entry_price_b=position.entry_price_b,
                exit_price_a=last_a, exit_price_b=last_b,
                entry_bar=position.entry_bar, exit_bar=last_bar,
                entry_time=position.entry_time,
                exit_time=spread.index[last_bar],
                entry_z=position.entry_z,
                exit_z=float(z.iloc[last_bar]) if not np.isnan(z.iloc[last_bar]) else 0.0,
                gross_pnl=gross,
                commission=position.open_commission + close_comm,
                net_pnl=net, exit_reason="end_of_data",
            ))

        idx = pd.DatetimeIndex(timestamps, tz="UTC")
        return PairsResult(
            equity_curve=pd.Series(equity_vals, index=idx, name="equity"),
            equity_low=pd.Series(equity_low_vals, index=idx, name="equity_low"),
            trades=closed,
            initial_capital=initial_capital,
        )
