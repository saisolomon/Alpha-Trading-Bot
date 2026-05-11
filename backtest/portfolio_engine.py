"""
Multi-symbol portfolio backtest engine for cross-sectional strategies.

Mechanics:
  - Signal fires at bar N close; execution at bar N+1 open with slippage.
  - P&L accounting: initial_capital + sum(closed_pnl) + unrealized_pnl.
  - equity_low: worst intrabar equity (long → bar low; short → bar high).
  - Rebalancing: signal change triggers close of old + open of new at next open.
  - All symbols run on a shared daily bar grid; missing bars for a symbol on
    a given day are skipped (no phantom fills).

Usage:
    engine = PortfolioEngine(symbol_specs, cost_model)
    result = engine.run(data, config, sizing_config, initial_capital=100_000)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from backtest.costs import CostModel, DEFAULT_COST_MODEL, SymbolSpec
from strategies.fx_momentum.signal import MomentumConfig
from strategies.fx_momentum.strategy import SharedSignalStore
from strategies.fx_momentum.sizing import MomentumSizer, SizingConfig, compute_atr


# ---------------------------------------------------------------------------
# Open position state
# ---------------------------------------------------------------------------


@dataclass
class OpenPosition:
    symbol: str
    direction: int          # +1 long, -1 short
    lots: float
    entry_price: float      # fill price (after slippage)
    entry_bar: int
    entry_time: datetime
    open_commission: float  # commission paid on entry leg


# ---------------------------------------------------------------------------
# Closed trade record
# ---------------------------------------------------------------------------


@dataclass
class PortfolioTrade:
    symbol: str
    direction: int
    lots: float
    entry_price: float
    exit_price: float
    entry_bar: int
    exit_bar: int
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float        # before commission
    commission: float       # total both legs
    net_pnl: float
    z_score_at_entry: float = 0.0
    exit_reason: str = "signal"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class PortfolioResult:
    equity_curve: pd.Series        # DatetimeIndex → equity
    equity_low: pd.Series          # DatetimeIndex → worst intrabar equity
    trades: list[PortfolioTrade]
    initial_capital: float

    @property
    def total_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return self.equity_curve.iloc[-1] / self.equity_curve.iloc[0] - 1.0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.net_pnl > 0) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        loss = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        return gross / loss if loss > 0 else 0.0

    @property
    def avg_win_loss_ratio(self) -> float:
        wins = [t.net_pnl for t in self.trades if t.net_pnl > 0]
        losses = [abs(t.net_pnl) for t in self.trades if t.net_pnl < 0]
        if not wins or not losses:
            return 1.0
        return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


# ---------------------------------------------------------------------------
# Portfolio engine
# ---------------------------------------------------------------------------


class PortfolioEngine:
    """Bar-by-bar portfolio simulation for cross-sectional FX momentum.

    Parameters
    ----------
    symbol_specs:
        dict of symbol → SymbolSpec (contract size, point, tick_value, etc.)
    cost_model:
        CostModel — slippage and commission parameters.
    """

    def __init__(
        self,
        symbol_specs: dict[str, SymbolSpec],
        cost_model: CostModel = DEFAULT_COST_MODEL,
    ) -> None:
        self._specs = symbol_specs
        self._cost = cost_model

    def run(
        self,
        data: dict[str, pd.DataFrame],
        config: MomentumConfig,
        sizing_config: SizingConfig,
        initial_capital: float = 100_000.0,
        atr_period: int = 14,
        atr_multiple: float = 1.5,
        win_rate_prior: float = 0.50,
        avg_win_loss_prior: float = 1.0,
    ) -> PortfolioResult:
        """Run the portfolio backtest.

        Parameters
        ----------
        data:
            dict of symbol → OHLCV DataFrame (must share a common DatetimeIndex
            or at minimum cover the same calendar dates).
        config:
            MomentumConfig — signal parameters.
        sizing_config:
            SizingConfig — Kelly fraction, per-trade risk cap.
        initial_capital:
            Starting account equity.
        atr_period, atr_multiple:
            Stop-loss sizing parameters.
        win_rate_prior, avg_win_loss_prior:
            Initial Kelly inputs (updated after each completed trade).
        """
        store = SharedSignalStore(config, data)
        start_bar = store.start_bar

        # Use the symbol with the most bars as the bar grid
        master_sym = max(data, key=lambda s: len(data[s]))
        master_df = data[master_sym]
        n_bars = len(master_df)

        # State
        realized_pnl: float = 0.0
        open_positions: dict[str, OpenPosition] = {}
        closed_trades: list[PortfolioTrade] = []
        equity_vals: list[float] = []
        equity_low_vals: list[float] = []
        timestamps: list[pd.Timestamp] = []

        # Running performance estimates for Kelly
        trade_pnls: list[float] = []
        win_rate = win_rate_prior
        avg_wl = avg_win_loss_prior

        # Build per-symbol sizers
        sizers: dict[str, MomentumSizer] = {
            sym: MomentumSizer(sizing_config, spec)
            for sym, spec in self._specs.items()
            if sym in data
        }

        for bar_i in range(n_bars):
            ts = master_df.index[bar_i]

            # ------------------------------------------------------------------
            # Mark open positions to close (and compute intrabar worst)
            # ------------------------------------------------------------------
            unrealized = 0.0
            worst_unrealized = 0.0

            for sym, pos in open_positions.items():
                if sym not in data:
                    continue
                sym_df = data[sym]
                if bar_i >= len(sym_df):
                    continue
                bar = sym_df.iloc[bar_i]
                spec = self._specs.get(sym)
                if spec is None:
                    continue

                close_pnl = spec.pnl(pos.entry_price, bar["close"], pos.direction, pos.lots)
                # Worst intrabar price: long uses low, short uses high
                worst_price = bar["low"] if pos.direction == 1 else bar["high"]
                worst_pnl = spec.pnl(pos.entry_price, worst_price, pos.direction, pos.lots)

                unrealized += close_pnl - pos.open_commission
                worst_unrealized += worst_pnl - pos.open_commission

            equity = initial_capital + realized_pnl + unrealized
            equity_low = initial_capital + realized_pnl + worst_unrealized

            equity_vals.append(equity)
            equity_low_vals.append(equity_low)
            timestamps.append(ts)

            # ------------------------------------------------------------------
            # Signal check — no look-ahead; signal at bar_i executes at bar_i+1
            # ------------------------------------------------------------------
            if bar_i < start_bar or bar_i + 1 >= n_bars:
                continue

            snap = store.get(bar_i)
            if snap is None:
                continue

            # Update Kelly inputs from recent trades
            if len(trade_pnls) >= 10:
                wins_n = [p for p in trade_pnls[-30:] if p > 0]
                losses_n = [abs(p) for p in trade_pnls[-30:] if p < 0]
                if wins_n and losses_n:
                    win_rate = len(wins_n) / (len(wins_n) + len(losses_n))
                    avg_wl = (sum(wins_n) / len(wins_n)) / (sum(losses_n) / len(losses_n))

            for sym, sym_sig in snap.signals.items():
                if sym not in data or sym not in self._specs:
                    continue

                sym_df = data[sym]
                if bar_i + 1 >= len(sym_df):
                    continue

                target_dir = sym_sig.direction
                current_dir = open_positions[sym].direction if sym in open_positions else 0

                if target_dir == current_dir:
                    continue  # no change

                spec = self._specs[sym]
                next_bar = sym_df.iloc[bar_i + 1]
                next_open = float(next_bar["open"])
                next_ts = sym_df.index[bar_i + 1]
                bar_vol = float(next_bar.get("tick_volume", 0)) or None

                # ----------------------------------------------------------
                # Close existing position at next bar open
                # ----------------------------------------------------------
                if sym in open_positions:
                    pos = open_positions.pop(sym)
                    fill = self._cost.fill_price(
                        next_open, -pos.direction, spec, pos.lots, bar_vol
                    )
                    gross = spec.pnl(pos.entry_price, fill, pos.direction, pos.lots)
                    close_comm = self._cost.commission(pos.lots, spec)
                    net = gross - pos.open_commission - close_comm

                    realized_pnl += net
                    trade_pnls.append(net)

                    closed_trades.append(PortfolioTrade(
                        symbol=sym,
                        direction=pos.direction,
                        lots=pos.lots,
                        entry_price=pos.entry_price,
                        exit_price=fill,
                        entry_bar=pos.entry_bar,
                        exit_bar=bar_i + 1,
                        entry_time=pos.entry_time,
                        exit_time=next_ts,
                        gross_pnl=gross,
                        commission=pos.open_commission + close_comm,
                        net_pnl=net,
                        z_score_at_entry=sym_sig.z_score,
                        exit_reason="signal",
                    ))

                # ----------------------------------------------------------
                # Open new position (if direction is non-zero)
                # ----------------------------------------------------------
                if target_dir == 0:
                    continue

                # Compute ATR-based stop
                history = sym_df.iloc[: bar_i + 1]
                atr = 0.0
                if len(history) > atr_period:
                    atr = compute_atr(history["high"], history["low"], history["close"], atr_period)

                sizer = sizers.get(sym)
                if sizer is None:
                    continue

                stop_dist = sizer.atr_stop_distance(atr, atr_multiple) if atr > 0 else next_open * 0.005
                current_equity = initial_capital + realized_pnl + unrealized

                lots = sizer.compute_lots(
                    equity=current_equity,
                    stop_distance_price=stop_dist,
                    win_rate=win_rate,
                    avg_win_loss_ratio=avg_wl,
                )

                if lots <= 0:
                    continue

                fill = self._cost.fill_price(next_open, target_dir, spec, lots, bar_vol)
                open_comm = self._cost.commission(lots, spec)

                open_positions[sym] = OpenPosition(
                    symbol=sym,
                    direction=target_dir,
                    lots=lots,
                    entry_price=fill,
                    entry_bar=bar_i + 1,
                    entry_time=next_ts,
                    open_commission=open_comm,
                )

        # Close any remaining open positions at the last bar's close
        last_i = n_bars - 1
        last_ts = master_df.index[last_i]
        for sym, pos in list(open_positions.items()):
            if sym not in data:
                continue
            sym_df = data[sym]
            if last_i >= len(sym_df):
                continue
            last_close = float(sym_df.iloc[last_i]["close"])
            spec = self._specs.get(sym)
            if spec is None:
                continue
            gross = spec.pnl(pos.entry_price, last_close, pos.direction, pos.lots)
            close_comm = self._cost.commission(pos.lots, spec)
            net = gross - pos.open_commission - close_comm
            realized_pnl += net
            closed_trades.append(PortfolioTrade(
                symbol=sym,
                direction=pos.direction,
                lots=pos.lots,
                entry_price=pos.entry_price,
                exit_price=last_close,
                entry_bar=pos.entry_bar,
                exit_bar=last_i,
                entry_time=pos.entry_time,
                exit_time=last_ts,
                gross_pnl=gross,
                commission=pos.open_commission + close_comm,
                net_pnl=net,
                exit_reason="end_of_data",
            ))

        idx = pd.DatetimeIndex(timestamps, tz="UTC")
        equity_s = pd.Series(equity_vals, index=idx, name="equity")
        equity_low_s = pd.Series(equity_low_vals, index=idx, name="equity_low")

        return PortfolioResult(
            equity_curve=equity_s,
            equity_low=equity_low_s,
            trades=closed_trades,
            initial_capital=initial_capital,
        )


# ---------------------------------------------------------------------------
# Walk-forward for portfolio strategies
# ---------------------------------------------------------------------------


@dataclass
class PortfolioWFWindow:
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    oos_result: PortfolioResult


def portfolio_walk_forward(
    data: dict[str, pd.DataFrame],
    config: MomentumConfig,
    symbol_specs: dict[str, SymbolSpec],
    sizing_config: SizingConfig,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    is_months: int = 36,
    oos_months: int = 12,
    initial_capital: float = 100_000.0,
) -> list[PortfolioWFWindow]:
    """Rolling walk-forward with non-overlapping OOS windows.

    For cross-sectional momentum, no parameters are fitted on IS data;
    the IS period merely provides the history needed for signal warmup.
    The OOS window is the true out-of-sample test.

    Parameters
    ----------
    is_months, oos_months:
        In-sample and out-of-sample window lengths in months.
        Step size = oos_months (non-overlapping OOS).
    """
    engine = PortfolioEngine(symbol_specs, cost_model)

    # Use master symbol index for slicing
    master_sym = max(data, key=lambda s: len(data[s]))
    idx = data[master_sym].index

    start_ts = idx[0]
    end_ts = idx[-1]

    windows: list[PortfolioWFWindow] = []
    # Slide OOS window across the data
    oos_start = start_ts + pd.DateOffset(months=is_months)

    while oos_start < end_ts:
        oos_end = min(oos_start + pd.DateOffset(months=oos_months), end_ts)
        is_start = oos_start - pd.DateOffset(months=is_months)

        # Slice data: give the engine IS + OOS (signal only acts in OOS zone)
        # Since SharedSignalStore enforces no look-ahead via as_of_bar,
        # the OOS signals are computed only from data up to that bar.
        window_data: dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            sliced = df[(df.index >= is_start) & (df.index <= oos_end)]
            if not sliced.empty:
                window_data[sym] = sliced

        if not window_data:
            oos_start += pd.DateOffset(months=oos_months)
            continue

        # Run backtest on the full window (IS+OOS bars)
        full_result = engine.run(
            window_data, config, sizing_config, initial_capital=initial_capital,
        )

        # Slice OOS portion of the equity curve
        oos_equity = full_result.equity_curve[
            (full_result.equity_curve.index >= oos_start) &
            (full_result.equity_curve.index <= oos_end)
        ]
        oos_equity_low = full_result.equity_low[
            (full_result.equity_low.index >= oos_start) &
            (full_result.equity_low.index <= oos_end)
        ]
        oos_trades = [
            t for t in full_result.trades
            if t.entry_time >= oos_start and t.exit_time <= oos_end
        ]

        oos_result = PortfolioResult(
            equity_curve=oos_equity,
            equity_low=oos_equity_low,
            trades=oos_trades,
            initial_capital=oos_equity.iloc[0] if len(oos_equity) else initial_capital,
        )

        windows.append(PortfolioWFWindow(
            is_start=is_start,
            is_end=oos_start,
            oos_start=oos_start,
            oos_end=oos_end,
            oos_result=oos_result,
        ))

        oos_start += pd.DateOffset(months=oos_months)

    return windows
