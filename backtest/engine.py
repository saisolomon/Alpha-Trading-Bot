"""
Event-driven bar-by-bar backtest engine.

Design invariants:
  - NO look-ahead: BacktestState passed to generate_signal() contains bars
    0..N (inclusive). The signal fires at bar N's close; execution happens
    at bar N+1's open with simulated slippage.
  - Stops and take-profits are checked intrabar using the bar's high/low.
    A stop triggered within a bar fills at the stop price (no gap slippage
    beyond the stop unless the bar opens through it).
  - The equity curve tracks worst-case intrabar equity (equity_low) so that
    the FTMO simulator can check intraday drawdown accurately.
  - Same Strategy interface is used in live execution — strategies must not
    import any backtest-only symbols.

Usage:
    engine = BacktestEngine(data, spec, cost_model)
    result = engine.run(my_strategy, initial_capital=100_000)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from backtest.costs import CostModel, SymbolSpec, DEFAULT_COST_MODEL


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


class Direction(IntEnum):
    LONG = 1
    SHORT = -1


# ---------------------------------------------------------------------------
# Signal — what the strategy emits each bar
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """Trading signal emitted by a strategy at bar close.

    Execution happens at the next bar's open.

    Parameters
    ----------
    direction:
        LONG or SHORT.
    size:
        Volume in lots. 0.0 means "close all / flat".
    stop_loss_price:
        Absolute price for the stop loss. None = no stop.
    take_profit_price:
        Absolute price for the take profit. None = no TP.
    comment:
        Optional label for logging / trade CSV.
    """

    direction: Direction
    size: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    comment: str = ""

    @classmethod
    def flat(cls) -> "Signal":
        """Close all open positions."""
        return cls(direction=Direction.LONG, size=0.0, comment="flat")

    @property
    def is_flat(self) -> bool:
        return self.size == 0.0


# ---------------------------------------------------------------------------
# Strategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Strategy(Protocol):
    """Protocol that all strategies must implement.

    The same interface is used in backtest and live. Strategies must be
    stateless with respect to bar history — all needed context is in state.
    """

    @property
    def name(self) -> str:
        ...

    def generate_signal(self, state: "BacktestState") -> Signal | None:
        """Return a Signal or None (hold current position unchanged)."""
        ...


# ---------------------------------------------------------------------------
# Position — open trade
# ---------------------------------------------------------------------------


@dataclass
class Position:
    symbol: str
    direction: Direction
    entry_price: float       # fill price (including slippage)
    size: float              # lots
    stop_loss_price: float | None
    take_profit_price: float | None
    entry_bar: int
    entry_time: datetime
    commission_paid: float   # commission at entry


# ---------------------------------------------------------------------------
# Trade — closed trade record
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    symbol: str
    direction: Direction
    entry_price: float
    exit_price: float
    size: float
    entry_time: datetime
    exit_time: datetime
    entry_bar: int
    exit_bar: int
    gross_pnl: float         # before commission
    commission: float
    net_pnl: float           # gross_pnl - commission
    exit_reason: str         # "signal", "stop", "take_profit", "end_of_data"
    signal_comment: str = ""


# ---------------------------------------------------------------------------
# BacktestState — snapshot delivered to the strategy
# ---------------------------------------------------------------------------


@dataclass
class BacktestState:
    """Immutable snapshot of the world at bar N (strategy's perspective).

    `bars` includes all rows from the first bar through bar `bar_index`
    (inclusive). The strategy MUST NOT look at any later rows.

    Equity and positions reflect the state at bar N's close (after marking
    open positions to the bar's close price).
    """

    bar_index: int
    timestamp: datetime
    bars: pd.DataFrame         # rows 0..bar_index (DatetimeIndex, UTC)
    open_positions: list[Position]
    equity: float
    cash: float
    closed_trades: list[Trade]

    @property
    def current_bar(self) -> pd.Series:
        return self.bars.iloc[-1]

    @property
    def has_position(self) -> bool:
        return len(self.open_positions) > 0

    @property
    def net_position(self) -> float:
        """Net lots (positive = long, negative = short)."""
        return sum(
            p.size * p.direction for p in self.open_positions
        )


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """Output of a completed backtest run."""

    strategy_name: str
    symbol: str
    initial_capital: float

    # --- Equity curve at bar resolution ---
    equity_curve: pd.Series          # index: DatetimeIndex, values: equity at bar close
    equity_high: pd.Series           # intrabar best-case equity
    equity_low: pd.Series            # intrabar worst-case equity (for FTMO sim)

    # --- Trade log ---
    trades: list[Trade]

    # --- Raw bar data used ---
    bars: pd.DataFrame


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Event-driven bar-by-bar simulator.

    Parameters
    ----------
    data:
        OHLCV DataFrame with UTC DatetimeIndex and columns:
        open, high, low, close, tick_volume (+ optional spread, real_volume).
    spec:
        Symbol specification (contract size, point, etc.).
    cost_model:
        Slippage and commission model.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        spec: SymbolSpec,
        cost_model: CostModel | None = None,
    ) -> None:
        self._data = data.copy()
        self._spec = spec
        self._cost = cost_model or DEFAULT_COST_MODEL
        self._validate_data()

    def run(
        self,
        strategy: Strategy,
        initial_capital: float,
        min_bars_warmup: int = 1,
    ) -> BacktestResult:
        """Run the backtest and return a BacktestResult.

        Parameters
        ----------
        strategy:
            The strategy to test.
        initial_capital:
            Starting equity in account currency.
        min_bars_warmup:
            Number of bars the strategy needs before generating signals.
            No trades execute during warmup.
        """
        bars = self._data
        n = len(bars)
        spec = self._spec
        cost = self._cost

        cash = initial_capital
        positions: list[Position] = []
        trades: list[Trade] = []

        equity_vals: list[float] = []
        equity_highs: list[float] = []
        equity_lows: list[float] = []

        pending_signal: Signal | None = None  # signal from bar N, executed at N+1

        for i in range(n):
            bar = bars.iloc[i]
            ts = bars.index[i]
            bar_open = float(bar["open"])
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])
            bar_vol = float(bar.get("tick_volume", 0))

            # ---- 1. Execute pending signal at this bar's open ----
            if pending_signal is not None and i >= min_bars_warmup:
                cash = self._execute_signal(
                    pending_signal, bar_open, bar_vol, i, ts,
                    positions, trades, cash, spec, cost
                )
                pending_signal = None

            # ---- 2. Check intrabar stops / take-profits ----
            cash = self._check_stops(
                bar_high, bar_low, i, ts, positions, trades, cash, spec, cost
            )

            # ---- 3. Mark open positions to close ----
            float_pnl = self._floating_pnl(positions, bar_close, spec)
            close_equity = cash + float_pnl

            # ---- 4. Track intrabar equity extremes ----
            # Worst intrabar equity: open positions marked to bar_low (long) or bar_high (short)
            worst_pnl = self._floating_pnl_intrabar(positions, bar_low, bar_high, spec, worst=True)
            best_pnl = self._floating_pnl_intrabar(positions, bar_low, bar_high, spec, worst=False)

            equity_vals.append(close_equity)
            equity_lows.append(cash + worst_pnl)
            equity_highs.append(cash + best_pnl)

            # ---- 5. Generate signal for next bar ----
            if i >= min_bars_warmup - 1:
                state = BacktestState(
                    bar_index=i,
                    timestamp=ts,
                    bars=bars.iloc[: i + 1],
                    open_positions=list(positions),
                    equity=close_equity,
                    cash=cash,
                    closed_trades=list(trades),
                )
                try:
                    sig = strategy.generate_signal(state)
                except Exception:
                    sig = None
                if sig is not None:
                    pending_signal = sig

        # ---- 6. Close any remaining positions at end-of-data ----
        if positions and len(bars) > 0:
            last_close = float(bars.iloc[-1]["close"])
            last_ts = bars.index[-1]
            last_i = len(bars) - 1
            for pos in list(positions):
                gross = spec.pnl(pos.entry_price, last_close, pos.direction, pos.size)
                comm = cost.commission(pos.size, spec)
                net = gross - comm - pos.commission_paid
                trades.append(Trade(
                    symbol=spec.symbol,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=last_close,
                    size=pos.size,
                    entry_time=pos.entry_time,
                    exit_time=last_ts,
                    entry_bar=pos.entry_bar,
                    exit_bar=last_i,
                    gross_pnl=gross,
                    commission=comm + pos.commission_paid,
                    net_pnl=net,
                    exit_reason="end_of_data",
                    signal_comment=pos.commission_paid.__class__.__name__,  # placeholder
                ))
                cash += gross - comm
            positions.clear()

        idx = bars.index
        return BacktestResult(
            strategy_name=strategy.name,
            symbol=spec.symbol,
            initial_capital=initial_capital,
            equity_curve=pd.Series(equity_vals, index=idx, name="equity"),
            equity_high=pd.Series(equity_highs, index=idx, name="equity_high"),
            equity_low=pd.Series(equity_lows, index=idx, name="equity_low"),
            trades=trades,
            bars=bars,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _execute_signal(
        self,
        signal: Signal,
        bar_open: float,
        bar_vol: float,
        bar_idx: int,
        ts: datetime,
        positions: list[Position],
        trades: list[Trade],
        cash: float,
        spec: SymbolSpec,
        cost: CostModel,
    ) -> float:
        """Execute a signal: flat existing positions, then open new one."""
        if signal.is_flat or (positions and positions[0].direction != signal.direction):
            # Close all open positions at this bar's open
            for pos in list(positions):
                fill = cost.fill_price(bar_open, -pos.direction, spec, pos.size, bar_vol)
                gross = spec.pnl(pos.entry_price, fill, pos.direction, pos.size)
                comm = cost.commission(pos.size, spec)
                net = gross - comm - pos.commission_paid
                trades.append(Trade(
                    symbol=spec.symbol,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=fill,
                    size=pos.size,
                    entry_time=pos.entry_time,
                    exit_time=ts,
                    entry_bar=pos.entry_bar,
                    exit_bar=bar_idx,
                    gross_pnl=gross,
                    commission=comm + pos.commission_paid,
                    net_pnl=net,
                    exit_reason="signal",
                    signal_comment=signal.comment,
                ))
                cash += gross - comm
            positions.clear()

        if not signal.is_flat:
            # Same-direction signal while already in a position = MODIFY the
            # open position's stops in place (trailing-stop support). The engine
            # has no add-to/pyramid path; our roster uses this only to ratchet
            # SL/TP (e.g. AUDJPY_H4_TrendFollow). No new fill, no commission.
            if positions and positions[0].direction == signal.direction:
                pos = positions[0]
                if signal.stop_loss_price is not None:
                    pos.stop_loss_price = signal.stop_loss_price
                if signal.take_profit_price is not None:
                    pos.take_profit_price = signal.take_profit_price
                return cash
            fill = cost.fill_price(bar_open, signal.direction, spec, signal.size, bar_vol)
            comm = cost.commission(signal.size, spec)
            cash -= comm
            positions.append(Position(
                symbol=spec.symbol,
                direction=signal.direction,
                entry_price=fill,
                size=signal.size,
                stop_loss_price=signal.stop_loss_price,
                take_profit_price=signal.take_profit_price,
                entry_bar=bar_idx,
                entry_time=ts,
                commission_paid=comm,
            ))

        return cash

    def _check_stops(
        self,
        bar_high: float,
        bar_low: float,
        bar_idx: int,
        ts: datetime,
        positions: list[Position],
        trades: list[Trade],
        cash: float,
        spec: SymbolSpec,
        cost: CostModel,
    ) -> float:
        for pos in list(positions):
            exit_price: float | None = None
            exit_reason = ""

            if pos.direction == Direction.LONG:
                if pos.stop_loss_price and bar_low <= pos.stop_loss_price:
                    exit_price = pos.stop_loss_price
                    exit_reason = "stop"
                elif pos.take_profit_price and bar_high >= pos.take_profit_price:
                    exit_price = pos.take_profit_price
                    exit_reason = "take_profit"
            else:
                if pos.stop_loss_price and bar_high >= pos.stop_loss_price:
                    exit_price = pos.stop_loss_price
                    exit_reason = "stop"
                elif pos.take_profit_price and bar_low <= pos.take_profit_price:
                    exit_price = pos.take_profit_price
                    exit_reason = "take_profit"

            if exit_price is not None:
                gross = spec.pnl(pos.entry_price, exit_price, pos.direction, pos.size)
                comm = cost.commission(pos.size, spec)
                net = gross - comm - pos.commission_paid
                trades.append(Trade(
                    symbol=spec.symbol,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    size=pos.size,
                    entry_time=pos.entry_time,
                    exit_time=ts,
                    entry_bar=pos.entry_bar,
                    exit_bar=bar_idx,
                    gross_pnl=gross,
                    commission=comm + pos.commission_paid,
                    net_pnl=net,
                    exit_reason=exit_reason,
                ))
                cash += gross - comm
                positions.remove(pos)

        return cash

    @staticmethod
    def _floating_pnl(positions: list[Position], price: float, spec: SymbolSpec) -> float:
        return sum(
            spec.pnl(p.entry_price, price, p.direction, p.size)
            for p in positions
        )

    @staticmethod
    def _floating_pnl_intrabar(
        positions: list[Position],
        bar_low: float,
        bar_high: float,
        spec: SymbolSpec,
        worst: bool,
    ) -> float:
        total = 0.0
        for p in positions:
            if p.direction == Direction.LONG:
                price = bar_low if worst else bar_high
            else:
                price = bar_high if worst else bar_low
            total += spec.pnl(p.entry_price, price, p.direction, p.size)
        return total

    def _validate_data(self) -> None:
        required = {"open", "high", "low", "close"}
        missing = required - set(self._data.columns)
        if missing:
            raise ValueError(f"Data missing required columns: {missing}")
        if not isinstance(self._data.index, pd.DatetimeIndex):
            raise TypeError("Data must have a DatetimeIndex")
        if self._data.index.tz is None:
            raise TypeError("Data index must be timezone-aware (UTC)")
        if len(self._data) < 2:
            raise ValueError("Data must have at least 2 bars")
