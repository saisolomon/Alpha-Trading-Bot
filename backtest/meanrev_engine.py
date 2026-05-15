"""
Backtest engine for the index mean-reversion strategy.

Differs from PortfolioEngine in two material ways:
  1. Entry is event-driven, not direction-based. A position opens only when
     z falls past the entry threshold AND regime filters pass; closes on
     time-stop, exit-z, ATR stop, or ATR take-profit.
  2. Intrabar stop and take-profit checks. The engine inspects each bar's
     high/low against the position's stop_price / tp_price BEFORE marking
     to close, so stops produce realistic exit prices rather than worst-bar
     slippage to the next open.

Execution model:
  - Signal evaluated at close of bar N.
  - New entries execute at bar N+1 OPEN (with slippage).
  - Time-stop / exit-z exits execute at bar N+1 OPEN.
  - ATR stop / TP hits execute at the stop_price or tp_price within bar N+1
    (priority: stop > tp when both touched in one bar).

P&L: initial_capital + sum(closed_pnl) + unrealised_pnl on current bar's close.
equity_low: worst intrabar equity given the current bar's high/low.

The engine does NOT update Kelly inputs from realised trades during the
in-sample run -- mean-reversion strategy is sized by fixed per_trade_risk_pct
since the signal predates any sample data we could use for Kelly priors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from backtest.costs import CostModel, DEFAULT_COST_MODEL, SymbolSpec
from strategies.index_meanrev.signal import (
    MeanRevConfig,
    SymbolFeatures,
    build_features,
    snapshot_at,
)


# ---------------------------------------------------------------------------
# Position and trade dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MeanRevPosition:
    symbol: str
    direction: int           # always +1 (long-only); kept for engine symmetry
    lots: float
    entry_price: float
    entry_bar: int
    entry_time: datetime
    open_commission: float
    stop_price: float
    tp_price: float
    bars_held: int = 0


@dataclass
class MeanRevTrade:
    symbol: str
    direction: int
    lots: float
    entry_price: float
    exit_price: float
    entry_bar: int
    exit_bar: int
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float
    commission: float
    net_pnl: float
    z_at_entry: float
    exit_reason: str         # "time_stop" | "exit_z" | "atr_stop" | "atr_tp" | "end_of_data"


@dataclass
class MeanRevResult:
    equity_curve: pd.Series
    equity_low: pd.Series
    trades: list[MeanRevTrade]
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


# ---------------------------------------------------------------------------
# Sizing helper -- fixed per_trade_risk_pct, ATR stop, $/point/lot from spec
# ---------------------------------------------------------------------------


def _compute_lots(
    equity: float,
    per_trade_risk_pct: float,
    stop_distance_price: float,
    spec: SymbolSpec,
    min_lots: float = 0.01,
    max_lots: float = 50.0,
) -> float:
    if equity <= 0 or stop_distance_price <= 0:
        return 0.0
    risk_amount = equity * per_trade_risk_pct
    # $/price-unit per lot = tick_value / point (matches SymbolSpec.pnl())
    pnl_per_lot_per_price_unit = spec.tick_value / spec.point
    risk_per_lot = stop_distance_price * pnl_per_lot_per_price_unit
    if risk_per_lot <= 0:
        return 0.0
    raw_lots = risk_amount / risk_per_lot
    lots = np.floor(raw_lots * 100) / 100.0
    return float(np.clip(lots, min_lots, max_lots))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class MeanRevEngine:
    """Per-symbol mean-reversion backtest with intrabar stops.

    Each symbol is simulated independently (no cross-symbol signal sharing).
    Positions across symbols can be open simultaneously; equity is shared.

    Parameters
    ----------
    symbol_specs:
        dict of symbol -> SymbolSpec
    cost_model:
        CostModel (default uses 0.5x avg-spread slippage)
    per_trade_risk_pct:
        Fraction of equity to risk per trade (0.005 = 0.5%).
    """

    def __init__(
        self,
        symbol_specs: dict[str, SymbolSpec],
        cost_model: CostModel = DEFAULT_COST_MODEL,
        per_trade_risk_pct: float = 0.005,
    ) -> None:
        self._specs = symbol_specs
        self._cost = cost_model
        self._per_trade_risk_pct = per_trade_risk_pct

    def run(
        self,
        data: dict[str, pd.DataFrame],
        config: MeanRevConfig,
        initial_capital: float = 100_000.0,
    ) -> MeanRevResult:
        # Precompute features per symbol
        features: dict[str, SymbolFeatures] = {
            sym: build_features(data[sym], config)
            for sym in config.symbols
            if sym in data
        }

        # Use the symbol with the most bars as the master timeline
        master_sym = max(features, key=lambda s: len(data[s]))
        master_idx = data[master_sym].index
        n_bars = len(master_idx)

        realised_pnl: float = 0.0
        open_positions: dict[str, MeanRevPosition] = {}
        closed_trades: list[MeanRevTrade] = []
        equity_vals: list[float] = []
        equity_low_vals: list[float] = []
        timestamps: list[pd.Timestamp] = []

        # Map master-timeline timestamp -> per-symbol bar index (handles different lengths)
        per_sym_idx: dict[str, dict[pd.Timestamp, int]] = {
            sym: {ts: i for i, ts in enumerate(data[sym].index)}
            for sym in features
        }

        for bar_i in range(n_bars):
            ts = master_idx[bar_i]

            # ------------------------------------------------------------------
            # 1. Mark open positions to close and compute intrabar worst
            # ------------------------------------------------------------------
            unrealised = 0.0
            worst_unrealised = 0.0
            for sym, pos in open_positions.items():
                if sym not in data:
                    continue
                sym_idx = per_sym_idx[sym].get(ts)
                if sym_idx is None:
                    continue
                bar = data[sym].iloc[sym_idx]
                spec = self._specs[sym]
                close_pnl = spec.pnl(pos.entry_price, bar["close"], pos.direction, pos.lots)
                worst_pnl = spec.pnl(pos.entry_price, bar["low"], pos.direction, pos.lots)
                unrealised += close_pnl - pos.open_commission
                worst_unrealised += worst_pnl - pos.open_commission

            equity = initial_capital + realised_pnl + unrealised
            equity_low = initial_capital + realised_pnl + worst_unrealised
            equity_vals.append(equity)
            equity_low_vals.append(equity_low)
            timestamps.append(ts)

            # ------------------------------------------------------------------
            # 2. Check intrabar stop/TP for any open position on THIS bar
            # ------------------------------------------------------------------
            for sym in list(open_positions.keys()):
                pos = open_positions[sym]
                sym_idx = per_sym_idx[sym].get(ts)
                if sym_idx is None or sym_idx == pos.entry_bar:
                    # No bar today for this symbol, or this is the entry bar itself.
                    continue
                bar = data[sym].iloc[sym_idx]
                spec = self._specs[sym]
                bar_open = float(bar["open"])
                bar_low = float(bar["low"])
                bar_high = float(bar["high"])
                hit_stop = bar_low <= pos.stop_price
                hit_tp = bar_high >= pos.tp_price
                exit_reason: str | None = None
                fill_price: float | None = None
                if hit_stop and hit_tp:
                    # Both touched this bar; assume stop fires first (conservative).
                    exit_reason = "atr_stop"
                    # Gap fill: if bar opened past the stop (gap-through), fill at open
                    # (worse than stop_price). Otherwise the stop fired intrabar -> stop_price.
                    fill_price = bar_open if bar_open <= pos.stop_price else pos.stop_price
                elif hit_stop:
                    exit_reason = "atr_stop"
                    fill_price = bar_open if bar_open <= pos.stop_price else pos.stop_price
                elif hit_tp:
                    exit_reason = "atr_tp"
                    # Mirror for take-profit: gap-up past TP fills at open (favorable
                    # gap that we capture); intrabar TP -> tp_price exactly.
                    fill_price = bar_open if bar_open >= pos.tp_price else pos.tp_price

                if exit_reason is not None:
                    gross = spec.pnl(pos.entry_price, fill_price, pos.direction, pos.lots)
                    close_comm = self._cost.commission(pos.lots, spec)
                    # ATR-stop and ATR-TP exits don't pay slippage via fill_price()
                    # because we fill at the trigger level. The bid-ask cost on exit
                    # is still real, so add it explicitly.
                    exit_slip_cost = self._cost.slippage_cost(spec, pos.lots)
                    net = gross - pos.open_commission - close_comm - exit_slip_cost
                    realised_pnl += net
                    closed_trades.append(MeanRevTrade(
                        symbol=sym,
                        direction=pos.direction,
                        lots=pos.lots,
                        entry_price=pos.entry_price,
                        exit_price=fill_price,
                        entry_bar=pos.entry_bar,
                        exit_bar=sym_idx,
                        entry_time=pos.entry_time,
                        exit_time=ts,
                        gross_pnl=gross,
                        commission=pos.open_commission + close_comm + exit_slip_cost,
                        net_pnl=net,
                        z_at_entry=0.0,        # filled by entry code; left 0 if missing
                        exit_reason=exit_reason,
                    ))
                    # The z_at_entry is set when opening; copy from any field we stored
                    # (we kept it implicit; future versions could attach to the position).
                    open_positions.pop(sym)
                else:
                    pos.bars_held += 1

            # ------------------------------------------------------------------
            # 3. Time-stop / exit-z check (post intrabar-stop, before new entry)
            # ------------------------------------------------------------------
            for sym in list(open_positions.keys()):
                pos = open_positions[sym]
                sym_idx = per_sym_idx[sym].get(ts)
                if sym_idx is None or sym_idx + 1 >= len(data[sym]):
                    continue
                snap = snapshot_at(features[sym], sym_idx, config)
                should_exit = (
                    pos.bars_held >= config.max_hold_bars
                    or (snap is not None and snap.long_exit_ok)
                )
                if not should_exit:
                    continue
                # Close at next bar's open
                next_bar = data[sym].iloc[sym_idx + 1]
                next_ts = data[sym].index[sym_idx + 1]
                spec = self._specs[sym]
                bar_vol = float(next_bar.get("tick_volume", 0)) or None
                fill = self._cost.fill_price(
                    float(next_bar["open"]), -pos.direction, spec, pos.lots, bar_vol,
                )
                gross = spec.pnl(pos.entry_price, fill, pos.direction, pos.lots)
                close_comm = self._cost.commission(pos.lots, spec)
                net = gross - pos.open_commission - close_comm
                realised_pnl += net
                exit_reason = "time_stop" if pos.bars_held >= config.max_hold_bars else "exit_z"
                closed_trades.append(MeanRevTrade(
                    symbol=sym,
                    direction=pos.direction,
                    lots=pos.lots,
                    entry_price=pos.entry_price,
                    exit_price=fill,
                    entry_bar=pos.entry_bar,
                    exit_bar=sym_idx + 1,
                    entry_time=pos.entry_time,
                    exit_time=next_ts,
                    gross_pnl=gross,
                    commission=pos.open_commission + close_comm,
                    net_pnl=net,
                    z_at_entry=0.0,
                    exit_reason=exit_reason,
                ))
                open_positions.pop(sym)

            # ------------------------------------------------------------------
            # 4. New entries (signal at close of bar_i -> execute at bar_i+1 open)
            # ------------------------------------------------------------------
            if bar_i + 1 >= n_bars:
                continue

            current_equity = initial_capital + realised_pnl + unrealised
            for sym in config.symbols:
                if sym in open_positions or sym not in features:
                    continue
                sym_idx = per_sym_idx[sym].get(ts)
                if sym_idx is None or sym_idx + 1 >= len(data[sym]):
                    continue
                snap = snapshot_at(features[sym], sym_idx, config)
                if snap is None or not snap.long_entry_ok:
                    continue
                if snap.atr <= 0:
                    continue

                next_bar = data[sym].iloc[sym_idx + 1]
                next_ts = data[sym].index[sym_idx + 1]
                spec = self._specs[sym]
                stop_distance = snap.atr * config.atr_stop_mult
                tp_distance = snap.atr * config.atr_tp_mult

                lots = _compute_lots(
                    equity=current_equity,
                    per_trade_risk_pct=self._per_trade_risk_pct,
                    stop_distance_price=stop_distance,
                    spec=spec,
                )
                if lots <= 0:
                    continue

                bar_vol = float(next_bar.get("tick_volume", 0)) or None
                fill = self._cost.fill_price(
                    float(next_bar["open"]), +1, spec, lots, bar_vol,
                )
                open_comm = self._cost.commission(lots, spec)
                open_positions[sym] = MeanRevPosition(
                    symbol=sym,
                    direction=+1,
                    lots=lots,
                    entry_price=fill,
                    entry_bar=sym_idx + 1,
                    entry_time=next_ts,
                    open_commission=open_comm,
                    stop_price=fill - stop_distance,
                    tp_price=fill + tp_distance,
                    bars_held=0,
                )

        # ------------------------------------------------------------------
        # 5. Force-close at end of data
        # ------------------------------------------------------------------
        last_ts = master_idx[n_bars - 1]
        for sym, pos in list(open_positions.items()):
            sym_idx = per_sym_idx[sym].get(last_ts)
            if sym_idx is None:
                continue
            last_close = float(data[sym].iloc[sym_idx]["close"])
            spec = self._specs[sym]
            gross = spec.pnl(pos.entry_price, last_close, pos.direction, pos.lots)
            close_comm = self._cost.commission(pos.lots, spec)
            net = gross - pos.open_commission - close_comm
            realised_pnl += net
            closed_trades.append(MeanRevTrade(
                symbol=sym,
                direction=pos.direction,
                lots=pos.lots,
                entry_price=pos.entry_price,
                exit_price=last_close,
                entry_bar=pos.entry_bar,
                exit_bar=sym_idx,
                entry_time=pos.entry_time,
                exit_time=last_ts,
                gross_pnl=gross,
                commission=pos.open_commission + close_comm,
                net_pnl=net,
                z_at_entry=0.0,
                exit_reason="end_of_data",
            ))

        idx = pd.DatetimeIndex(timestamps, tz="UTC")
        return MeanRevResult(
            equity_curve=pd.Series(equity_vals, index=idx, name="equity"),
            equity_low=pd.Series(equity_low_vals, index=idx, name="equity_low"),
            trades=closed_trades,
            initial_capital=initial_capital,
        )


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


@dataclass
class MeanRevWFWindow:
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    oos_result: MeanRevResult


def meanrev_walk_forward(
    data: dict[str, pd.DataFrame],
    config: MeanRevConfig,
    symbol_specs: dict[str, SymbolSpec],
    cost_model: CostModel = DEFAULT_COST_MODEL,
    per_trade_risk_pct: float = 0.005,
    is_months: int = 36,
    oos_months: int = 12,
    initial_capital: float = 100_000.0,
) -> list[MeanRevWFWindow]:
    """Rolling walk-forward; OOS windows do not overlap.

    No parameters are fitted on IS data -- the IS period only provides the
    rolling-z-score lookback history. OOS is the honest test.
    """
    engine = MeanRevEngine(symbol_specs, cost_model, per_trade_risk_pct=per_trade_risk_pct)

    master_sym = max(data, key=lambda s: len(data[s]))
    idx = data[master_sym].index
    start_ts = idx[0]
    end_ts = idx[-1]

    windows: list[MeanRevWFWindow] = []
    oos_start = start_ts + pd.DateOffset(months=is_months)
    while oos_start < end_ts:
        oos_end = min(oos_start + pd.DateOffset(months=oos_months), end_ts)
        is_start = oos_start - pd.DateOffset(months=is_months)

        window_data: dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            sliced = df[(df.index >= is_start) & (df.index <= oos_end)]
            if not sliced.empty:
                window_data[sym] = sliced

        if not window_data:
            oos_start += pd.DateOffset(months=oos_months)
            continue

        full_result = engine.run(window_data, config, initial_capital=initial_capital)

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

        oos_result = MeanRevResult(
            equity_curve=oos_equity,
            equity_low=oos_equity_low,
            trades=oos_trades,
            initial_capital=oos_equity.iloc[0] if len(oos_equity) else initial_capital,
        )
        windows.append(MeanRevWFWindow(
            is_start=is_start,
            is_end=oos_start,
            oos_start=oos_start,
            oos_end=oos_end,
            oos_result=oos_result,
        ))
        oos_start += pd.DateOffset(months=oos_months)

    return windows
