"""
LondonFix Strategy — faithful Python port of the live MQL5 EA
`mql5/Experts/XAUUSD_M15_LondonFix.mq5` for backtesting.

Hypothesis (verbatim from the EA header):
    At 10:30 UTC the LBMA AM gold fix is set. Order-flow auctions before
    the fix often push gold in one direction, then the fix itself triggers
    profit-taking from large bullion-bank participants -> a 30-90 min
    REVERSAL after the fix. We FADE the pre-fix direction.

This module implements the backtest.engine.Strategy protocol and replicates
the EA's signal logic bar-for-bar. Signal parity with the live EA is the whole
point, so all hour/minute comparisons use the SAME Inp* constants as the .mq5
and are compared against the bar timestamp in RAW BROKER TIME (the OANDA spine
the engine feeds in, which is exactly what the live EA's TimeCurrent() sees).
NO UTC "correction" is applied — that would break live parity.

--------------------------------------------------------------------------
EA -> backtest mapping (where the engine's mechanics differ from MT5):

  * The live EA's OnTick runs once per *new bar*. It uses iClose(_,_,1) and
    ATR buffer index 1 — i.e. the LAST CLOSED bar. In the engine,
    `state.current_bar` (bar N) IS the last closed bar, and execution happens
    at bar N+1's open. So we evaluate the EA's per-bar logic on bar N and emit
    a Signal that the engine fills at N+1 open. This is the correct, no-look-
    ahead analogue of the live EA placing a market order on the new-bar tick.

  * ATR: the live EA uses MT5 iATR(M15, 14), which is Wilder's RMA of the
    True Range. We replicate Wilder's ATR in pure pandas (compute_atr). The
    EA reads atr_buf[1] (ATR of the last closed bar) => ATR computed over bars
    up to and including bar N. No look-ahead.

  * Stops/TP: the EA places a fixed SL/TP at entry (ask/bid +/- mult*ATR) and
    relies on broker-side SL/TP plus a 14:00 force-flat. We set the Signal's
    stop_loss_price / take_profit_price (engine checks them intrabar) and emit
    Signal.flat() at/after the session-close hour to replicate ForceFlat.

  * Entry price: the EA uses live ask/bid; the engine fills at next bar's open.
    We anchor SL/TP off the current bar's close as the entry proxy (the engine
    cannot know N+1's open when the signal is formed). This matches the
    fx_momentum adapter's convention and keeps SL/TP at the EA's mult*ATR
    distance — distance parity is preserved even if the absolute anchor differs
    by one bar's open-vs-close, which is unavoidable without look-ahead.

  * Sizing: ports ComputeLots() exactly —
        lots = (risk_pct * equity) / (stop_distance / tick_size * tick_value)
    floored to volume_step and clamped to [volume_min, volume_max].

  * One-trade-per-day, degenerate-range skip, pre-fix-direction==0 skip, and
    the trading-window gate are all ported verbatim. Day boundary uses the
    bar timestamp's calendar date in broker time (EA: SessionDateOf()).

  Risk/portfolio/FTMO/news gates from the EA (IsNewsBlackout, WouldExceedRiskCap,
  WouldExceedClusterCap, ftmo_check_pretrade) are EXECUTION-LAYER concerns that
  live outside the Strategy protocol (the backtest engine + FTMO simulator apply
  them separately). They are intentionally NOT reimplemented here so the strategy
  stays a pure signal generator, exactly like the other strategy adapters.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.costs import SymbolSpec, XAUUSD_SPEC
from backtest.engine import BacktestState, Direction, Signal


# ---------------------------------------------------------------------------
# Wilder ATR — matches MT5 iATR(PERIOD_M15, period)
# ---------------------------------------------------------------------------


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int,
) -> float:
    """Wilder's ATR over the supplied bars; returns the value at the LAST bar.

    MT5's iATR seeds the first ATR value with a simple average of the first
    `period` true ranges, then applies Wilder's recursive smoothing
    (RMA: atr_i = (atr_{i-1}*(period-1) + tr_i) / period). True range of the
    first bar uses high-low only (no prior close). This mirrors how MetaTrader
    fills the ATR buffer, so the value here equals the EA's atr_buf[1] when the
    series ends on the EA's last-closed bar.

    Returns 0.0 (caller treats as invalid) if there are not enough bars.
    """
    n = len(close)
    if n < period + 1:
        return 0.0

    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)

    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_close = c[:-1]
    cur_high = h[1:]
    cur_low = l[1:]
    tr[1:] = np.maximum.reduce([
        cur_high - cur_low,
        np.abs(cur_high - prev_close),
        np.abs(cur_low - prev_close),
    ])

    # Wilder seed: SMA of the first `period` true ranges, then RMA smoothing.
    atr = np.mean(tr[:period])
    for i in range(period, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return float(atr)


class LondonFixStrategy:
    """Port of XAUUSD_M15_LondonFix.mq5 to the backtest.engine.Strategy protocol.

    Parameters mirror the .mq5 ``input`` block; defaults are the exact .mq5
    values so a backtest with no overrides reproduces the live EA configuration.

    Parameters
    ----------
    spec:
        SymbolSpec for XAUUSD (tick_value / point used for lot sizing). Defaults
        to backtest.costs.XAUUSD_SPEC.
    per_trade_risk_pct:
        InpPerTradeRiskPct — fraction of equity risked per trade. .mq5 default
        0.0050 (0.50%, per Config C2 sizing calibration 2026-06-11).
    prefix_start_hour / prefix_start_minute:
        InpPreFixStartHour / InpPreFixStartMinute — pre-fix window start (09:30).
    fix_hour / fix_minute:
        InpFixHour / InpFixMinute — fix time / entry-window start (10:30).
    session_close_hour:
        InpSessionCloseHour — force-flat hour (14:00).
    atr_period:
        InpAtrPeriod — ATR period (14).
    atr_stop_mult / atr_tp_mult:
        InpAtrStopMult / InpAtrTpMult — SL/TP as multiples of ATR (1.5 / 1.5).
    min_prefix_range_pct:
        InpMinPreFixRangePct — minimum pre-fix range as a fraction of price
        (0.001 = 0.1%). Sessions with a narrower pre-fix range are skipped.

    NOTE on broker-time hours: prefix_start_hour, fix_hour, session_close_hour
    are compared against state.timestamp.hour/.minute DIRECTLY, with no UTC
    conversion. The OANDA spine the engine feeds is RAW BROKER time, which is
    exactly the clock the live EA's TimeCurrent() runs on — so keeping these
    raw preserves live/backtest signal parity. Do NOT "correct" them.
    """

    def __init__(
        self,
        spec: SymbolSpec = XAUUSD_SPEC,
        per_trade_risk_pct: float = 0.0050,   # InpPerTradeRiskPct (C2)
        prefix_start_hour: int = 9,           # InpPreFixStartHour
        prefix_start_minute: int = 30,        # InpPreFixStartMinute
        fix_hour: int = 10,                   # InpFixHour
        fix_minute: int = 30,                 # InpFixMinute
        session_close_hour: int = 14,         # InpSessionCloseHour
        atr_period: int = 14,                 # InpAtrPeriod
        atr_stop_mult: float = 1.5,           # InpAtrStopMult
        atr_tp_mult: float = 1.5,             # InpAtrTpMult
        min_prefix_range_pct: float = 0.001,  # InpMinPreFixRangePct
    ) -> None:
        self._spec = spec
        self._risk_pct = per_trade_risk_pct
        self._prefix_start_hour = prefix_start_hour
        self._prefix_start_minute = prefix_start_minute
        self._fix_hour = fix_hour
        self._fix_minute = fix_minute
        self._session_close_hour = session_close_hour
        self._atr_period = atr_period
        self._atr_stop_mult = atr_stop_mult
        self._atr_tp_mult = atr_tp_mult
        self._min_prefix_range_pct = min_prefix_range_pct

        # Per-session state (EA globals: g_traded_this_session, g_current_session_date)
        self._traded_session_date: object | None = None  # date on which we've already traded

    @property
    def name(self) -> str:
        return "XAUUSD_M15_LondonFix"

    # ------------------------------------------------------------------ #
    # Time helpers — port of the EA's MqlDateTime minute-of-day checks    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _minute_of_day(ts) -> int:
        return ts.hour * 60 + ts.minute

    def _past_fix(self, ts) -> bool:
        # EA PastFix(): tm >= InpFixHour*60 + InpFixMinute
        return self._minute_of_day(ts) >= self._fix_hour * 60 + self._fix_minute

    def _at_session_close(self, ts) -> bool:
        # EA AtSessionClose(): tm >= InpSessionCloseHour*60
        return self._minute_of_day(ts) >= self._session_close_hour * 60

    def _in_trading_window(self, ts) -> bool:
        # EA InTradingWindow(): start = fix; end = session close; [start, end)
        tm = self._minute_of_day(ts)
        start = self._fix_hour * 60 + self._fix_minute
        end = self._session_close_hour * 60
        return start <= tm < end

    # ------------------------------------------------------------------ #
    # Pre-fix direction & range — port of ComputePreFixDirection()        #
    # ------------------------------------------------------------------ #

    def _compute_prefix(self, bars: pd.DataFrame, session_date) -> tuple[int, float, float] | None:
        """Return (direction, range_width, last_close_in_window) for today's pre-fix
        window [prefix_start, fix), or None if it can't be locked.

        EA logic: scan recent M15 bars; collect those with
            session_start <= time < fix_time
        direction = sign(close_of_last_bar_in_window - open_of_first_bar_in_window)
        range_width = max(high) - min(low) over the window.
        EA requires matched >= 2 bars (the >=4 CopyRates guard is a fetch-size
        check, not a window-bar requirement; matched>=2 is the real gate).
        """
        idx = bars.index
        # Bars that fall on today's calendar date (broker time).
        same_day = idx.normalize() == session_date
        mod = idx.hour * 60 + idx.minute
        start = self._prefix_start_hour * 60 + self._prefix_start_minute
        fix = self._fix_hour * 60 + self._fix_minute
        in_window = same_day & (mod >= start) & (mod < fix)

        win = bars[in_window]
        if len(win) < 2:
            return None

        open_first = float(win["open"].iloc[0])
        close_last = float(win["close"].iloc[-1])
        hi = float(win["high"].max())
        lo = float(win["low"].min())

        if close_last > open_first:
            direction = 1
        elif close_last < open_first:
            direction = -1
        else:
            direction = 0
        return direction, hi - lo, close_last

    # ------------------------------------------------------------------ #
    # Sizing — port of ComputeLots()                                      #
    # ------------------------------------------------------------------ #

    def _compute_lots(self, equity: float, stop_distance_price: float) -> float:
        """lots = (risk_pct*equity) / (stop_distance/tick_size * tick_value),
        floored to volume_step, clamped to [volume_min, volume_max].

        The EA pulls tick_size/tick_value/step/min/max from MT5 symbol_info.
        SymbolSpec exposes `point` (== tick_size for XAUUSD: 0.01) and
        `tick_value`. Volume step/min/max are not on SymbolSpec, so we use the
        XAUUSD broker conventions: step=0.01, min=0.01, max=large. This is the
        one sizing approximation; the dollars-at-risk formula itself is exact.
        """
        if stop_distance_price <= 0 or equity <= 0:
            return 0.0
        risk_amount = equity * self._risk_pct
        tick_value = self._spec.tick_value
        tick_size = self._spec.point  # XAUUSD tick_size == point == 0.01
        if tick_value <= 0 or tick_size <= 0:
            return 0.0
        loss_per_lot = stop_distance_price / tick_size * tick_value
        if loss_per_lot <= 0:
            return 0.0
        raw = risk_amount / loss_per_lot

        # Broker volume constraints (XAUUSD typical; EA reads these from MT5).
        step = 0.01
        vol_min = 0.01
        vol_max = 100.0
        lots = np.floor(raw / step) * step
        lots = max(vol_min, min(vol_max, lots))
        return float(lots)

    # ------------------------------------------------------------------ #
    # Main signal generator                                               #
    # ------------------------------------------------------------------ #

    def generate_signal(self, state: BacktestState) -> Signal | None:
        ts = state.timestamp
        session_date = ts.normalize()  # EA SessionDateOf(): midnight of today, broker time

        # --- Force-flat at/after session close (EA: AtSessionClose -> ForceFlat) ---
        # EA flattens an open position once the clock reaches InpSessionCloseHour.
        if state.has_position and self._at_session_close(ts):
            return Signal.flat()

        # --- Gates that produce no order: hold current position unchanged ---

        # The EA only acts after the fix is locked (ComputePreFixDirection runs
        # when PastFix). Before the fix time there is nothing to do.
        if not self._past_fix(ts):
            return None

        # Must be inside the post-fix trading window [fix, session_close).
        if not self._in_trading_window(ts):
            return None

        # One trade per day (EA: g_traded_this_session). Once we've entered (or
        # explicitly skipped) for this session date, do nothing more today.
        if self._traded_session_date == session_date:
            return None

        # If a position is already open, don't stack (EA: g_open_ticket != 0).
        if state.has_position:
            return None

        # --- Lock the pre-fix direction/range for today (EA: ComputePreFixDirection) ---
        prefix = self._compute_prefix(state.bars, session_date)
        if prefix is None:
            return None  # window not formed yet; try again next bar (EA: !g_prefix_locked -> return)
        prefix_direction, prefix_range_width, _ = prefix

        # EA: if pre-fix direction is flat, mark session traded and skip.
        if prefix_direction == 0:
            self._traded_session_date = session_date
            return None

        # EA uses iClose(_,_,1) — the last closed bar — for the range%% check.
        last_close = float(state.current_bar["close"])
        if last_close <= 0 or not np.isfinite(last_close):
            return None

        # Degenerate pre-fix range skip (EA: range/price < InpMinPreFixRangePct).
        if prefix_range_width / last_close < self._min_prefix_range_pct:
            self._traded_session_date = session_date
            return None

        # --- ATR(14) on bars up to and including bar N (EA: atr_buf[1]) ---
        atr = compute_atr(
            state.bars["high"],
            state.bars["low"],
            state.bars["close"],
            self._atr_period,
        )
        if not np.isfinite(atr) or atr <= 0:
            return None

        # --- Fade the pre-fix direction (EA: target_dir = -g_prefix_direction) ---
        target_dir = -prefix_direction
        stop_distance = self._atr_stop_mult * atr
        tp_distance = self._atr_tp_mult * atr

        lots = self._compute_lots(state.equity, stop_distance)
        if lots <= 0:
            return None

        # Anchor SL/TP off the current bar's close as the entry proxy. The engine
        # fills the order at bar N+1's open; absolute entry differs by one bar's
        # open-vs-close, but SL/TP DISTANCE (mult*ATR) is exactly the EA's.
        entry_proxy = last_close
        if target_dir == 1:
            direction = Direction.LONG
            sl = entry_proxy - stop_distance
            tp = entry_proxy + tp_distance
        else:
            direction = Direction.SHORT
            sl = entry_proxy + stop_distance
            tp = entry_proxy - tp_distance

        # Mark this session as traded BEFORE emitting (EA sets g_traded_this_session
        # = true immediately before SendEntry, so one-trade-per-day holds even if
        # the fill is later rejected). Parity: one decision per day.
        self._traded_session_date = session_date

        return Signal(
            direction=direction,
            size=lots,
            stop_loss_price=sl,
            take_profit_price=tp,
            comment=f"londonfix fade prefix_dir={prefix_direction:+d} atr={atr:.2f}",
        )
