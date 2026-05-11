"""
FX Momentum Strategy adapter — implements the backtest.engine.Strategy protocol.

This wraps MomentumSignalEngine for single-symbol backtesting. The BacktestEngine
runs per-symbol; the cross-sectional signal is precomputed from all symbols and
stored in a SharedSignalStore, which each per-symbol strategy instance reads from.

Usage (for a full portfolio backtest see backtest.py):
    store = SharedSignalStore(config, multi_symbol_data)
    strategy = FXMomentumStrategy("EURUSD", store, spec, sizing_config)
    engine = BacktestEngine(eurusd_data, eurusd_spec)
    result = engine.run(strategy, initial_capital=100_000)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.costs import SymbolSpec
from backtest.engine import BacktestState, Direction, Signal
from strategies.fx_momentum.signal import (
    MomentumConfig,
    MomentumSignalEngine,
    SignalSnapshot,
    compute_signals_series,
)
from strategies.fx_momentum.sizing import MomentumSizer, SizingConfig, compute_atr


# ---------------------------------------------------------------------------
# Shared signal store (precomputed cross-sectional signals)
# ---------------------------------------------------------------------------


class SharedSignalStore:
    """Precomputes cross-sectional momentum signals for all bars.

    This decouples the portfolio-level cross-sectional computation from the
    per-symbol backtest loop. All per-symbol strategies read from the same store.

    Parameters
    ----------
    config:
        MomentumConfig.
    data:
        dict of symbol → OHLCV DataFrame (aligned, same DatetimeIndex).
    """

    def __init__(
        self,
        config: MomentumConfig,
        data: dict[str, pd.DataFrame],
    ) -> None:
        self._snapshots: list[SignalSnapshot] = compute_signals_series(data, config)
        self._start_bar = (
            config.formation_bars + config.skip_bars + config.xvol_lookback_bars
        )

    def get(self, bar_index: int) -> SignalSnapshot | None:
        """Return the signal snapshot for bar_index, or None if not available."""
        idx = bar_index - self._start_bar
        if idx < 0 or idx >= len(self._snapshots):
            return None
        return self._snapshots[idx]

    @property
    def start_bar(self) -> int:
        return self._start_bar


# ---------------------------------------------------------------------------
# Per-symbol strategy (implements backtest.engine.Strategy protocol)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FXMomentumStrategyConfig:
    """Combines signal, sizing, and risk parameters for one symbol."""

    symbol: str
    momentum_config: MomentumConfig
    sizing_config: SizingConfig
    spec: SymbolSpec
    atr_period: int = 14
    atr_multiple: float = 1.5
    # Historical performance estimates (updated by walk-forward OOS results)
    estimated_win_rate: float = 0.50
    estimated_avg_win_loss: float = 1.0


class FXMomentumStrategy:
    """Single-symbol FX momentum strategy for the BacktestEngine.

    Reads precomputed cross-sectional signals from a SharedSignalStore.
    Generates Signal objects compatible with the BacktestEngine protocol.

    Parameters
    ----------
    symbol:
        The symbol this instance manages (e.g. "EURUSD").
    store:
        Precomputed signal store from SharedSignalStore.
    spec:
        SymbolSpec for this symbol.
    sizing_config:
        Position sizing parameters.
    atr_period, atr_multiple:
        Stop-loss placement parameters.
    estimated_win_rate, estimated_avg_win_loss:
        Used for Kelly sizing. Updated externally from OOS walk-forward results.
    """

    def __init__(
        self,
        symbol: str,
        store: SharedSignalStore,
        spec: SymbolSpec,
        sizing_config: SizingConfig | None = None,
        atr_period: int = 14,
        atr_multiple: float = 1.5,
        estimated_win_rate: float = 0.50,
        estimated_avg_win_loss: float = 1.0,
    ) -> None:
        self._symbol = symbol
        self._store = store
        self._sizer = MomentumSizer(sizing_config or SizingConfig(), spec)
        self._atr_period = atr_period
        self._atr_multiple = atr_multiple
        self._win_rate = estimated_win_rate
        self._avg_win_loss = estimated_avg_win_loss

    def update_performance_estimates(
        self,
        win_rate: float,
        avg_win_loss_ratio: float,
    ) -> None:
        """Update Kelly inputs from OOS walk-forward results."""
        self._win_rate = win_rate
        self._avg_win_loss = avg_win_loss_ratio

    def generate_signal(self, state: BacktestState) -> Signal | None:
        """Called by BacktestEngine for each bar. Returns a Signal or None.

        Returns None to hold current position (no change).
        Returns Signal.flat() to close all positions.
        Returns Signal(direction=LONG/SHORT, ...) to open/flip.
        """
        snap = self._store.get(state.bar_index)
        if snap is None:
            return None  # no signal yet (warmup period)

        sym_signal = snap.signals.get(self._symbol)
        if sym_signal is None:
            return None

        target_direction = sym_signal.direction

        # Determine current position direction
        current_direction = 0
        if state.open_positions:
            pos = state.open_positions[0]
            current_direction = 1 if pos.direction == Direction.LONG else -1

        # No change needed
        if target_direction == current_direction:
            return None

        # Close (go flat)
        if target_direction == 0:
            return Signal.flat()

        # Compute ATR-based stop distance
        bars = state.bars
        atr = 0.0
        if len(bars) > self._atr_period:
            atr = compute_atr(
                bars["high"], bars["low"], bars["close"], self._atr_period
            )
        stop_distance = self._sizer.atr_stop_distance(atr, self._atr_multiple)

        # Entry price will be next bar's open — we don't know it yet, so we use
        # current close as a proxy for stop placement. The engine fills at next open.
        entry_proxy = float(bars["close"].iloc[-1])

        # Compute position size
        lots = self._sizer.compute_lots(
            equity=state.equity,
            stop_distance_price=stop_distance if stop_distance > 0 else entry_proxy * 0.005,
            win_rate=self._win_rate,
            avg_win_loss_ratio=self._avg_win_loss,
        )

        if lots <= 0:
            return Signal.flat()

        direction = Direction.LONG if target_direction == 1 else Direction.SHORT

        # Stop-loss price: entry ± stop_distance
        # We use a placeholder since actual entry price is unknown pre-fill.
        # The engine doesn't use stop_loss_price for position sizing — it uses
        # the size directly. Stop checking is done via high/low vs. sl_price.
        if direction == Direction.LONG:
            sl_price = entry_proxy - stop_distance if stop_distance > 0 else 0.0
        else:
            sl_price = entry_proxy + stop_distance if stop_distance > 0 else 0.0

        return Signal(
            direction=direction,
            size=lots,
            stop_loss_price=sl_price,
            take_profit_price=0.0,  # exit by signal reversal, not fixed TP
            comment=f"mom_z={sym_signal.z_score:.2f}",
        )
