"""
FX Cross-Sectional Momentum — signal computation.

Primary signal:   cross-sectional z-scored return rank over a formation window.
Secondary signal: 50-bar EMA trend confirmation (direction must agree with momentum).
Regime filter:    cross-sectional volatility of z-scores — pause when > threshold.

All signals are expressed as the *foreign* currency's strength vs. USD:
  - EURUSD:  EUR strength (standard, already quoted as foreign/USD)
  - USDJPY:  JPY strength = -USDJPY return   (USD is base, so we invert)
  - USDCAD:  CAD strength = -USDCAD return
  - USDCHF:  CHF strength = -USDCHF return

Usage:
    engine = MomentumSignalEngine(config)
    signals = engine.compute(multi_symbol_data, as_of_bar=-1)
    # returns dict[str, int] — symbol → +1 long, -1 short, 0 flat
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Config (mirrors config.yaml — passed in directly for testability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MomentumConfig:
    """Parameters for the cross-sectional momentum signal."""

    # Universe
    symbols: tuple[str, ...]
    usd_base_symbols: tuple[str, ...]   # returns are negated before ranking

    # Primary signal
    formation_bars: int = 20
    skip_bars: int = 1
    long_z_threshold: float = 0.5
    short_z_threshold: float = -0.5
    max_long_positions: int = 2
    max_short_positions: int = 2

    # Secondary: trend confirmation
    trend_ema_bars: int = 50
    require_trend_confirmation: bool = True

    # Regime filter
    xvol_lookback_bars: int = 5
    xvol_pause_threshold: float = 2.0

    @classmethod
    def from_dict(cls, d: dict) -> "MomentumConfig":
        sig = d.get("signal", {})
        uni = d.get("universe", {})
        return cls(
            symbols=tuple(uni.get("symbols", [])),
            usd_base_symbols=tuple(uni.get("usd_base_symbols", [])),
            formation_bars=sig.get("formation_bars", 20),
            skip_bars=sig.get("skip_bars", 1),
            long_z_threshold=sig.get("long_z_threshold", 0.5),
            short_z_threshold=sig.get("short_z_threshold", -0.5),
            max_long_positions=sig.get("max_long_positions", 2),
            max_short_positions=sig.get("max_short_positions", 2),
            trend_ema_bars=sig.get("trend_ema_bars", 50),
            require_trend_confirmation=sig.get("require_trend_confirmation", True),
            xvol_lookback_bars=sig.get("xvol_lookback_bars", 5),
            xvol_pause_threshold=sig.get("xvol_pause_threshold", 2.0),
        )


# ---------------------------------------------------------------------------
# Signal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolSignal:
    """Signal output for one symbol at one bar."""

    symbol: str
    direction: Literal[1, -1, 0]   # +1 long, -1 short, 0 flat
    z_score: float                  # raw momentum z-score before filters
    raw_return: float               # formation-period return (foreign/USD perspective)
    trend_aligned: bool             # True if EMA confirms direction
    regime_active: bool             # False when cross-sectional vol is too high


@dataclass
class SignalSnapshot:
    """All symbol signals for one bar."""

    bar_index: int
    signals: dict[str, SymbolSignal]          # symbol → signal
    cross_sectional_vol: float                # regime indicator
    regime_active: bool                       # False = strategy paused (crisis mode)
    n_long: int
    n_short: int

    def direction(self, symbol: str) -> int:
        s = self.signals.get(symbol)
        return s.direction if s else 0


# ---------------------------------------------------------------------------
# Core signal engine
# ---------------------------------------------------------------------------


class MomentumSignalEngine:
    """Computes cross-sectional momentum signals for the FX universe.

    Parameters
    ----------
    config:
        MomentumConfig — derived from config.yaml.
    """

    def __init__(self, config: MomentumConfig) -> None:
        self._cfg = config

    def compute(
        self,
        data: dict[str, pd.DataFrame],
        as_of_bar: int = -1,
    ) -> SignalSnapshot:
        """Compute signals using data up to `as_of_bar` (inclusive).

        Parameters
        ----------
        data:
            dict mapping symbol → OHLCV DataFrame with DatetimeIndex.
            All DataFrames must have at minimum: 'close'. 'high', 'low' used
            for ATR only (optional).
        as_of_bar:
            Last bar index to use (-1 = use all available data).
            Enforces no-look-ahead: strategy sees only data[symbol].iloc[:as_of_bar+1].

        Returns
        -------
        SignalSnapshot
            Signals for every symbol in the universe at this bar.
        """
        cfg = self._cfg
        min_bars_needed = cfg.formation_bars + cfg.skip_bars + 1

        # Slice each symbol's history up to as_of_bar
        sliced: dict[str, pd.Series] = {}
        for sym in cfg.symbols:
            if sym not in data:
                continue
            closes = data[sym]["close"]
            if as_of_bar >= 0:
                closes = closes.iloc[: as_of_bar + 1]
            sliced[sym] = closes

        if not sliced or min(len(v) for v in sliced.values()) < min_bars_needed:
            # Not enough history — return flat signals
            return self._flat_snapshot(as_of_bar, cfg.symbols)

        # ------------------------------------------------------------------
        # Primary signal: formation-period return (foreign/USD perspective)
        # ------------------------------------------------------------------
        raw_returns: dict[str, float] = {}
        for sym, closes in sliced.items():
            # return from bar -(formation+skip) to bar -skip (skip-adjusted)
            end_idx = -cfg.skip_bars if cfg.skip_bars > 0 else len(closes)
            start_idx = end_idx - cfg.formation_bars
            try:
                end_price = closes.iloc[end_idx - 1] if cfg.skip_bars > 0 else closes.iloc[-1]
                start_price = closes.iloc[start_idx - 1]
            except IndexError:
                continue
            ret = (end_price / start_price) - 1.0
            # Invert for USD-base symbols (express as foreign currency strength vs. USD)
            if sym in cfg.usd_base_symbols:
                ret = -ret
            raw_returns[sym] = ret

        if len(raw_returns) < 2:
            return self._flat_snapshot(as_of_bar, cfg.symbols)

        returns_arr = np.array(list(raw_returns.values()), dtype=float)
        mean_ret = float(np.mean(returns_arr))
        std_ret = float(np.std(returns_arr, ddof=1)) if len(returns_arr) > 1 else 1.0
        if std_ret < 1e-12:
            std_ret = 1e-12

        z_scores: dict[str, float] = {
            sym: (ret - mean_ret) / std_ret
            for sym, ret in raw_returns.items()
        }

        # ------------------------------------------------------------------
        # Regime filter: cross-sectional volatility of z-scores
        # (a spike here means the cross-section is unusually dispersed = crisis)
        # ------------------------------------------------------------------
        xvol = self._cross_sectional_vol(data, cfg, as_of_bar)
        regime_active = xvol < cfg.xvol_pause_threshold

        # ------------------------------------------------------------------
        # Secondary signal: EMA trend filter
        # ------------------------------------------------------------------
        ema_aligned: dict[str, bool] = {}
        for sym, closes in sliced.items():
            if len(closes) < cfg.trend_ema_bars:
                ema_aligned[sym] = True  # not enough data: don't penalise
                continue
            ema = float(closes.ewm(span=cfg.trend_ema_bars, adjust=False).mean().iloc[-1])
            current_close = float(closes.iloc[-1])
            z = z_scores.get(sym, 0.0)
            if z > 0:
                ema_aligned[sym] = current_close > ema   # long: above EMA
            elif z < 0:
                ema_aligned[sym] = current_close < ema   # short: below EMA
            else:
                ema_aligned[sym] = True

        # ------------------------------------------------------------------
        # Assign raw directions before position caps
        # ------------------------------------------------------------------
        raw_directions: dict[str, int] = {}
        for sym, z in z_scores.items():
            if not regime_active:
                raw_directions[sym] = 0
                continue
            trend_ok = (not cfg.require_trend_confirmation) or ema_aligned.get(sym, True)
            if z > cfg.long_z_threshold and trend_ok:
                raw_directions[sym] = 1
            elif z < cfg.short_z_threshold and trend_ok:
                raw_directions[sym] = -1
            else:
                raw_directions[sym] = 0

        # ------------------------------------------------------------------
        # Apply concentration cap: keep top-N longs and top-N shorts by |z|
        # ------------------------------------------------------------------
        final_directions = self._apply_position_caps(raw_directions, z_scores, cfg)

        # ------------------------------------------------------------------
        # Assemble snapshot
        # ------------------------------------------------------------------
        sym_signals = {}
        for sym in cfg.symbols:
            direction = final_directions.get(sym, 0)
            sym_signals[sym] = SymbolSignal(
                symbol=sym,
                direction=direction,
                z_score=z_scores.get(sym, 0.0),
                raw_return=raw_returns.get(sym, 0.0),
                trend_aligned=ema_aligned.get(sym, True),
                regime_active=regime_active,
            )

        return SignalSnapshot(
            bar_index=as_of_bar,
            signals=sym_signals,
            cross_sectional_vol=xvol,
            regime_active=regime_active,
            n_long=sum(1 for d in final_directions.values() if d == 1),
            n_short=sum(1 for d in final_directions.values() if d == -1),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cross_sectional_vol(
        self,
        data: dict[str, pd.DataFrame],
        cfg: MomentumConfig,
        as_of_bar: int,
    ) -> float:
        """Rolling cross-sectional z-score std over the past xvol_lookback_bars.

        Returns 0.0 if there is insufficient history.
        """
        lookback = cfg.xvol_lookback_bars
        window_size = cfg.formation_bars + cfg.skip_bars + lookback

        per_bar_std: list[float] = []
        for offset in range(lookback):
            bar = (as_of_bar - offset) if as_of_bar >= 0 else -(offset + 1)
            bar_returns: list[float] = []
            for sym in cfg.symbols:
                if sym not in data:
                    continue
                closes = data[sym]["close"]
                end = bar if bar < 0 else bar + 1
                c = closes.iloc[:end] if end < 0 or end <= len(closes) else closes
                if len(c) < cfg.formation_bars + cfg.skip_bars + 1:
                    continue
                skip = cfg.skip_bars
                e_price = c.iloc[-skip - 1] if skip > 0 else c.iloc[-1]
                s_price = c.iloc[-cfg.formation_bars - skip - 1]
                ret = (e_price / s_price) - 1.0
                if sym in cfg.usd_base_symbols:
                    ret = -ret
                bar_returns.append(ret)
            if len(bar_returns) >= 2:
                per_bar_std.append(float(np.std(bar_returns, ddof=1)))

        if not per_bar_std:
            return 0.0
        return float(np.mean(per_bar_std))

    @staticmethod
    def _apply_position_caps(
        raw: dict[str, int],
        z_scores: dict[str, float],
        cfg: MomentumConfig,
    ) -> dict[str, int]:
        """Keep only the top-N longs and top-N shorts by absolute z-score."""
        longs = sorted(
            [(sym, abs(z_scores.get(sym, 0.0))) for sym, d in raw.items() if d == 1],
            key=lambda x: x[1],
            reverse=True,
        )[: cfg.max_long_positions]

        shorts = sorted(
            [(sym, abs(z_scores.get(sym, 0.0))) for sym, d in raw.items() if d == -1],
            key=lambda x: x[1],
            reverse=True,
        )[: cfg.max_short_positions]

        kept_longs = {sym for sym, _ in longs}
        kept_shorts = {sym for sym, _ in shorts}

        return {
            sym: (1 if sym in kept_longs else -1 if sym in kept_shorts else 0)
            for sym in raw
        }

    @staticmethod
    def _flat_snapshot(bar_index: int, symbols: tuple[str, ...]) -> SignalSnapshot:
        flat_signals = {
            sym: SymbolSignal(
                symbol=sym,
                direction=0,
                z_score=0.0,
                raw_return=0.0,
                trend_aligned=True,
                regime_active=True,
            )
            for sym in symbols
        }
        return SignalSnapshot(
            bar_index=bar_index,
            signals=flat_signals,
            cross_sectional_vol=0.0,
            regime_active=True,
            n_long=0,
            n_short=0,
        )


# ---------------------------------------------------------------------------
# Batch compute — convenience function for backtesting
# ---------------------------------------------------------------------------


def compute_signals_series(
    data: dict[str, pd.DataFrame],
    config: MomentumConfig,
    start_bar: int | None = None,
) -> list[SignalSnapshot]:
    """Compute a signal snapshot for every bar from start_bar onwards.

    Parameters
    ----------
    data:
        dict of symbol → OHLCV DataFrame (same-length DatetimeIndex).
    config:
        MomentumConfig.
    start_bar:
        First bar to compute (default: formation_bars + skip_bars + 1).

    Returns
    -------
    list[SignalSnapshot], one per bar from start_bar to end.
    """
    if not data:
        return []
    n_bars = min(len(df) for df in data.values())
    if start_bar is None:
        start_bar = config.formation_bars + config.skip_bars + config.xvol_lookback_bars

    engine = MomentumSignalEngine(config)
    return [engine.compute(data, as_of_bar=i) for i in range(start_bar, n_bars)]
