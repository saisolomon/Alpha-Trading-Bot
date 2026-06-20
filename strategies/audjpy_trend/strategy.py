"""
AUDJPY H4 Trend-Follow strategy adapter — faithful Python port of the live
MQL5 EA `mql5/Experts/AUDJPY_H4_TrendFollow.mq5` for backtesting.

The whole point of this module is SIGNAL PARITY with the live EA, so the entry
gate, Donchian channel, ATR stop sizing, ATR trailing-stop ratchet, the cooldown
clock, and the position-sizing math are ported verbatim from the .mq5. Where the
backtest engine's execution model forces an interpretation, it is documented in
a comment and kept as close to the EA's broker behaviour as possible.

EA mechanism (see the .mq5 header):
  - Donchian channel = max/min of the last `InpDonchianBars` (=20) CLOSED H4 bars
    EXCLUDING the just-closed trigger bar.
  - Long  when the trigger-bar close > prior Donchian high (breakout up).
  - Short when the trigger-bar close < prior Donchian low  (breakout down).
  - Initial SL: `InpAtrStopMult` (=2.0) * ATR(14) from entry.
  - Trailing SL: every bar ratchet the SL toward price by `InpAtrTrailMult`
    (=2.5) * ATR from the last closed bar's close; never moves against position.
  - No fixed TP — ride until the trailing stop is hit (or, after the stop closes
    the trade and the cooldown elapses, an opposite breakout).
  - Cooldown: `InpCooldownBars` (=6) bars after each exit before a new entry.

Parity notes baked into this port:
  * The EA only TRAILS while a position is open; it does NOT flip on an opposite
    breakout while in a trade (the OnTick handler `return`s before the entry gate
    whenever a position is open). So a reversal can only happen AFTER the stop
    closes the position and the cooldown clears. Replicated here: when we hold a
    position we never emit a flip Signal, only (re)assert the ratcheted stop.
  * ATR is MT5 `iATR(14)` = Wilder's RMA-smoothed ATR. `atr_buf[1]` is read, i.e.
    the ATR value of the just-closed trigger bar — computed here on bars up to and
    including the current (trigger) bar, taking the last value. No look-ahead.
  * The EA reads `iClose(_Symbol,_Period,1)` (the just-closed bar) as the trigger
    close. In the engine, `generate_signal` is called at bar N's close, so the
    current bar IS the trigger; the Donchian channel is the 20 bars before it.
  * Time/session: the EA has NO hour/day-of-week/session-window/force-flat logic
    (it trades H4 around the clock, gated only by news + cooldown), so there is
    nothing time-based to port. The FTMO/news/portfolio gates are live-only risk
    overlays handled outside the strategy and are intentionally NOT replicated
    here (they do not change the raw entry/exit signal the backtest measures).
  * Sizing math is ComputeLots() ported verbatim:
        risk_amount  = equity * InpPerTradeRiskPct
        loss_per_lot = stop_distance / tick_size * tick_value
        raw          = risk_amount / loss_per_lot
        lots         = clamp(floor(raw/step)*step, vol_min, vol_max)
    where tick_size == spec.point and tick_value == spec.tick_value (the engine's
    P&L uses dprice/point * tick_value * volume, identical units). Volume step/min
    /max are broker constants exposed as constructor params (sane FX defaults).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.costs import SymbolSpec
from backtest.engine import BacktestState, Direction, Signal


# ---------------------------------------------------------------------------
# .mq5 input defaults (Config C2, 2026-06-11 sizing calibration)
# ---------------------------------------------------------------------------

INP_DONCHIAN_BARS = 20        # InpDonchianBars
INP_ATR_PERIOD = 14           # InpAtrPeriod
INP_ATR_STOP_MULT = 2.0       # InpAtrStopMult  (initial SL = 2.0 * ATR)
INP_ATR_TRAIL_MULT = 2.5      # InpAtrTrailMult (trail step = 2.5 * ATR)
INP_COOLDOWN_BARS = 6         # InpCooldownBars (4h on H4)
INP_PER_TRADE_RISK_PCT = 0.0025  # InpPerTradeRiskPct (0.25% HOLD per Config C2)


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
    """ATR matching MT5 `iATR` (Wilder's RMA smoothing), value at the last bar.

    True range uses the prior bar's close. The series is seeded with an SMA of
    the first `period` true ranges, then smoothed with the Wilder recursion
        atr_i = (atr_{i-1} * (period - 1) + tr_i) / period
    exactly as MT5 computes it. Operates only on the bars provided (up to and
    including the current/trigger bar) — no look-ahead. Returns NaN if there is
    insufficient history.
    """
    n = len(close)
    if n < period + 1:
        return float("nan")

    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)

    prev_close = c[:-1]
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - prev_close),
        np.abs(l[1:] - prev_close),
    ])
    # tr[k] corresponds to bar index k+1 (TR undefined for the very first bar).
    if len(tr) < period:
        return float("nan")

    atr = float(np.mean(tr[:period]))  # SMA seed over the first `period` TRs
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


@dataclass
class AudjpyTrendStrategy:
    """Faithful port of AUDJPY_H4_TrendFollow.mq5 to the Strategy protocol.

    Parameters
    ----------
    spec:
        SymbolSpec for AUDJPY. `spec.point` is used as the EA's tick_size and
        `spec.tick_value` as the EA's tick_value in the lot sizing formula.
    donchian_bars, atr_period, atr_stop_mult, atr_trail_mult, cooldown_bars:
        The matching Inp* params from the .mq5 (defaults = .mq5 values).
    risk_pct:
        InpPerTradeRiskPct. Defaults to the .mq5 C2 value (0.0025 = 0.25%).
    volume_step, volume_min, volume_max:
        Broker volume constraints (SYMBOL_VOLUME_STEP / MIN / MAX). The .mq5
        reads these from SymbolInfoDouble; standard OANDA FX defaults used here.
    """

    spec: SymbolSpec
    donchian_bars: int = INP_DONCHIAN_BARS
    atr_period: int = INP_ATR_PERIOD
    atr_stop_mult: float = INP_ATR_STOP_MULT
    atr_trail_mult: float = INP_ATR_TRAIL_MULT
    cooldown_bars: int = INP_COOLDOWN_BARS
    risk_pct: float = INP_PER_TRADE_RISK_PCT
    volume_step: float = 0.01
    volume_min: float = 0.01
    volume_max: float = 100.0

    # --- internal state machine (mirrors the EA's globals) ---
    # g_bars_since_exit starts at 9999 (no recent exit -> first trade allowed).
    _bars_since_exit: int = 9999
    _pos_dir: int = 0          # -1 short, 0 flat, +1 long  (g_pos_dir)
    _trail_sl: float = 0.0     # current ratcheted SL price  (g_trail_sl)
    _last_seen_bar: int = -1   # to advance the cooldown clock once per new bar

    @property
    def name(self) -> str:
        return "AUDJPY_H4_TrendFollow"

    # ------------------------------------------------------------------ #
    # ComputeLots() ported verbatim from the .mq5.                         #
    # ------------------------------------------------------------------ #
    def _compute_lots(self, equity: float, stop_distance_price: float) -> float:
        if stop_distance_price <= 0 or equity <= 0:
            return 0.0
        risk_amount = equity * self.risk_pct
        tick_value = self.spec.tick_value
        tick_size = self.spec.point
        if tick_value <= 0 or tick_size <= 0:
            return 0.0
        loss_per_lot = stop_distance_price / tick_size * tick_value
        if loss_per_lot <= 0:
            return 0.0
        raw = risk_amount / loss_per_lot
        step = self.volume_step
        mn = self.volume_min
        mx = self.volume_max
        if step <= 0:
            return 0.0
        return max(mn, min(mx, math.floor(raw / step) * step))

    def _compute_donchian(self, bars: pd.DataFrame) -> tuple[float, float]:
        """Donchian high/low over the `donchian_bars` bars BEFORE the trigger.

        The EA copies bars 1..N+1 (series order, 0 = just-closed trigger) and
        uses indices 1..N as the channel, i.e. the `donchian_bars` bars strictly
        before the trigger bar. Here the trigger is the last row, so the channel
        is rows [-(donchian_bars+1) : -1].
        """
        # Need donchian_bars history bars before the current (trigger) bar.
        window = bars.iloc[-(self.donchian_bars + 1):-1]
        if len(window) < self.donchian_bars:
            return float("nan"), float("nan")
        return float(window["high"].max()), float(window["low"].min())

    def generate_signal(self, state: BacktestState) -> Signal | None:
        bars = state.bars

        # --- advance the per-bar cooldown clock exactly once per new bar ---
        # The EA bumps g_bars_since_exit on each new H4 bar in OnTick.
        if state.bar_index != self._last_seen_bar:
            self._bars_since_exit += 1
            self._last_seen_bar = state.bar_index

        # Determine the engine's view of our current position (source of truth
        # for whether the broker-side stop has closed us out since last bar).
        engine_dir = 0
        if state.open_positions:
            pos = state.open_positions[0]
            engine_dir = 1 if pos.direction == Direction.LONG else -1

        # Detect a broker-side exit (the engine's intrabar stop closed the trade)
        # since we last held one. Mirrors OnTradeTransaction / the SL-hit reset:
        # clear state and START the cooldown clock immediately.
        if self._pos_dir != 0 and engine_dir == 0:
            self._pos_dir = 0
            self._trail_sl = 0.0
            self._bars_since_exit = 0

        # ATR of the just-closed (trigger) bar — iATR(14), atr_buf[1].
        atr = _wilder_atr(bars["high"], bars["low"], bars["close"], self.atr_period)
        if not np.isfinite(atr) or atr <= 0:
            return None  # EA returns (holds) when ATR not yet valid

        last_close = float(bars["close"].iloc[-1])  # iClose(_Symbol,_Period,1)
        if not np.isfinite(last_close) or last_close <= 0:
            return None

        # ---------------------------------------------------------------- #
        # If in position: TRAIL the stop only. The EA returns before the    #
        # entry gate while holding, so no flip can happen here.             #
        # ---------------------------------------------------------------- #
        if self._pos_dir != 0 and engine_dir != 0:
            trail_distance = self.atr_trail_mult * atr
            if self._pos_dir == 1:
                new_sl = last_close - trail_distance
                should_move = new_sl > self._trail_sl
            else:
                new_sl = last_close + trail_distance
                should_move = new_sl < self._trail_sl
            if should_move:
                self._trail_sl = new_sl
            # Re-assert the (possibly ratcheted) SL every bar so the engine's
            # intrabar stop check uses the current trail level. Direction/size
            # are unchanged, so the engine treats this as a same-direction hold.
            direction = Direction.LONG if self._pos_dir == 1 else Direction.SHORT
            return Signal(
                direction=direction,
                size=state.open_positions[0].size,
                stop_loss_price=self._trail_sl,
                take_profit_price=None,
                comment="trail",
            )

        # ----------------------------- ENTRY GATE ----------------------- #
        # Cooldown: need cooldown_bars since the last exit.
        if self._bars_since_exit < self.cooldown_bars:
            return None

        # NOTE: live-only gates (FTMO pretrade, news blackout, portfolio /
        # cluster risk caps) are deliberately NOT ported — they are risk
        # overlays that do not alter the raw breakout signal under test.

        don_high, don_low = self._compute_donchian(bars)
        if not (np.isfinite(don_high) and np.isfinite(don_low)):
            return None

        target_dir = 0
        if last_close > don_high:
            target_dir = 1
        elif last_close < don_low:
            target_dir = -1
        if target_dir == 0:
            return None

        stop_distance = self.atr_stop_mult * atr
        lots = self._compute_lots(state.equity, stop_distance)
        if lots <= 0:
            return None

        # SL placement: entry +/- stop_distance. The EA uses ask/bid as entry;
        # the engine fills the pending order at the NEXT bar's open, which is
        # unknown here, so we anchor the stop to the trigger close (the same
        # proxy the sibling strategies use). stop_distance is exact per the EA.
        entry_proxy = last_close
        if target_dir == 1:
            sl = entry_proxy - stop_distance
            direction = Direction.LONG
        else:
            sl = entry_proxy + stop_distance
            direction = Direction.SHORT

        # Commit state machine (mirrors g_pos_dir / g_trail_sl assignment
        # right before SendEntry in the EA).
        self._pos_dir = target_dir
        self._trail_sl = sl

        return Signal(
            direction=direction,
            size=lots,
            stop_loss_price=sl,
            take_profit_price=None,  # no fixed TP — trail only
            comment=f"don[{don_low:.3f},{don_high:.3f}] atr={atr:.3f}",
        )
