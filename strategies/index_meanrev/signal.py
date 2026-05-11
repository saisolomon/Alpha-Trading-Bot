"""
Signal module for index short-horizon mean-reversion (long-only).

Computes the rolling z-score of a `formation_bars` cumulative log return, per
symbol, with all rolling windows ending at bar N (no look-ahead). Returns
both the latest snapshot and a full time-series of z-scores for backtest
preprocessing.

Long entry fires when:
  - z(T) < -entry_z_threshold  (price is in the tail of its drawdown distribution)
  - regime filters all pass    (see hypothesis doc)

Long exit fires when ANY of:
  - bars_held >= max_hold_bars (time stop)
  - z(T) > -exit_z_threshold   (reversion has played out)
  - intrabar stop hit          (handled by the engine, not here)
  - intrabar TP hit            (handled by the engine, not here)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeanRevConfig:
    """Parameters for the long-only mean-reversion signal."""

    symbols: tuple[str, ...]

    # Signal core
    formation_bars: int = 10        # past-return window for z-score
    z_lookback_bars: int = 252      # rolling window for z-score normalisation (~1y)
    entry_z_threshold: float = 1.5  # |z| > this fires entry (long when z < -threshold)
    exit_z_threshold: float = 0.5   # close long when z > -this

    # Time stop
    max_hold_bars: int = 10         # close even if no other exit triggers

    # Stops and take-profit (in ATR multiples; engine handles the conversion)
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    atr_tp_mult: float = 2.0

    # Regime filters
    require_long_term_uptrend: bool = True
    long_term_ema_bars: int = 200
    # Allow longs only when close/EMA(200) >= this floor (e.g. 0.92 = within 8%
    # of the long-term trend). Below this, the dip may be a regime change.
    long_term_drawdown_floor: float = 0.92

    # Vol regime (pause new entries in extreme-vol regimes)
    vol_lookback_bars: int = 20
    vol_pause_quantile: float = 0.90   # pause when realised vol > 90th percentile
    vol_history_bars: int = 504        # window for the quantile (~2y)

    @property
    def warmup_bars(self) -> int:
        """First bar at which the signal can fire (longest rolling window)."""
        return max(
            self.formation_bars + self.z_lookback_bars,
            self.long_term_ema_bars,
            self.vol_history_bars + self.vol_lookback_bars,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "MeanRevConfig":
        return cls(
            symbols=tuple(d["symbols"]),
            formation_bars=d.get("formation_bars", 10),
            z_lookback_bars=d.get("z_lookback_bars", 252),
            entry_z_threshold=d.get("entry_z_threshold", 1.5),
            exit_z_threshold=d.get("exit_z_threshold", 0.5),
            max_hold_bars=d.get("max_hold_bars", 10),
            atr_period=d.get("atr_period", 14),
            atr_stop_mult=d.get("atr_stop_mult", 1.5),
            atr_tp_mult=d.get("atr_tp_mult", 2.0),
            require_long_term_uptrend=d.get("require_long_term_uptrend", True),
            long_term_ema_bars=d.get("long_term_ema_bars", 200),
            long_term_drawdown_floor=d.get("long_term_drawdown_floor", 0.92),
            vol_lookback_bars=d.get("vol_lookback_bars", 20),
            vol_pause_quantile=d.get("vol_pause_quantile", 0.90),
            vol_history_bars=d.get("vol_history_bars", 504),
        )


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class SymbolSnapshot:
    z: float                 # current z-score of past-formation return
    atr: float               # current ATR(14)
    long_entry_ok: bool      # all regime filters say yes
    long_exit_ok: bool       # reversion has played out (z > -exit_threshold)
    note: str = ""           # debug reason


# ---------------------------------------------------------------------------
# Helpers (all rolling; no look-ahead)
# ---------------------------------------------------------------------------


def _rolling_log_return(close: pd.Series, n: int) -> pd.Series:
    return np.log(close).diff(n)


def _rolling_z(series: pd.Series, lookback: int) -> pd.Series:
    mean = series.rolling(lookback).mean()
    std = series.rolling(lookback).std()
    return (series - mean) / std


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _realised_vol(close: pd.Series, lookback: int) -> pd.Series:
    rets = np.log(close).diff()
    return rets.rolling(lookback).std()


# ---------------------------------------------------------------------------
# Precomputation: build per-symbol feature panels once
# ---------------------------------------------------------------------------


@dataclass
class SymbolFeatures:
    """All rolling features for one symbol, indexed by the symbol's DatetimeIndex.

    Every feature is computed using only past+current data. The engine reads
    `features.z.iloc[bar_i]` to get the z-score at the close of bar_i.
    """

    z: pd.Series              # rolling z-score of past-formation log return
    atr: pd.Series            # ATR(period)
    close_over_ema: pd.Series # close / EMA(long_term_ema_bars) - 1
    vol_pct_rank: pd.Series   # current realised vol's percentile rank in vol_history window


def build_features(
    df: pd.DataFrame,
    config: MeanRevConfig,
) -> SymbolFeatures:
    """Precompute the rolling feature panel for one symbol.

    The DataFrame must have columns: open, high, low, close.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]

    past_return = _rolling_log_return(close, config.formation_bars)
    z = _rolling_z(past_return, config.z_lookback_bars)

    atr = _atr(high, low, close, config.atr_period)

    ema = _ema(close, config.long_term_ema_bars)
    close_over_ema = close / ema - 1.0

    rvol = _realised_vol(close, config.vol_lookback_bars)
    # Percentile rank of CURRENT rvol within trailing vol_history_bars window.
    # rolling().apply(...) is slow but acceptable for a one-time precompute.
    vol_pct_rank = rvol.rolling(config.vol_history_bars).apply(
        lambda w: (w[-1] >= w).mean(), raw=True,
    )

    return SymbolFeatures(
        z=z, atr=atr, close_over_ema=close_over_ema, vol_pct_rank=vol_pct_rank,
    )


# ---------------------------------------------------------------------------
# Bar-level evaluation
# ---------------------------------------------------------------------------


def snapshot_at(
    features: SymbolFeatures,
    bar_i: int,
    config: MeanRevConfig,
) -> SymbolSnapshot | None:
    """Evaluate entry/exit conditions at the close of `bar_i`.

    Returns None when any feature is NaN (warmup not satisfied).
    """
    if bar_i < 0 or bar_i >= len(features.z):
        return None

    z = features.z.iloc[bar_i]
    atr_v = features.atr.iloc[bar_i]
    coe = features.close_over_ema.iloc[bar_i]
    vol_rank = features.vol_pct_rank.iloc[bar_i]

    if any(pd.isna(x) for x in (z, atr_v, coe, vol_rank)):
        return None

    # Entry conditions (long-only)
    entry_ok = True
    reasons: list[str] = []

    if z >= -config.entry_z_threshold:
        entry_ok = False
        reasons.append(f"z={z:+.2f} not deep enough")

    if config.require_long_term_uptrend:
        # close must be within `long_term_drawdown_floor` of the EMA(200).
        # close_over_ema = close/ema - 1, so close/ema = 1 + close_over_ema.
        if (1.0 + coe) < config.long_term_drawdown_floor:
            entry_ok = False
            reasons.append(f"close/ema200={1.0+coe:.2f} below floor")

    if vol_rank >= config.vol_pause_quantile:
        entry_ok = False
        reasons.append(f"vol rank={vol_rank:.2f} too high")

    # Exit condition (reversion done)
    exit_ok = z > -config.exit_z_threshold

    return SymbolSnapshot(
        z=float(z),
        atr=float(atr_v),
        long_entry_ok=entry_ok,
        long_exit_ok=exit_ok,
        note="; ".join(reasons),
    )
