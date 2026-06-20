"""
London-open momentum continuation — Python port of EURUSD_M15_LondonMomo.mq5.

Faithful backtest replica of the live MQL5 EA. The whole point is signal parity
with the EA, so every hour comparison, the range-locking logic, the entry
confirmation, the SL/TP placement, the one-trade-per-session rule, the
force-flat-at-close rule, and the lot-sizing formula are ported verbatim from
the .mq5.

Mechanism (from the EA header):
  - Range = first InpRangeMinutes after the session open (07:00-08:00 broker
    time = 4 M15 bars). Lock its high/low, plus the OPEN of the first range bar
    and the CLOSE of the last range bar.
  - Direction = sign(range_close - range_open). If 0, skip the session.
  - Entry: from range_end onwards (the trading window, 08:00-16:00 broker time),
    on the next M15 *close* that BREAKS the range in the established direction.
  - Stop: opposite side of the range (long -> range_low, short -> range_high).
  - TP: entry +/- InpTakeProfitMult * range_width.
  - One trade per session; force flat at InpSessionCloseHour:Minute.
  - Min-range filter: skip the session if range_width / last_close <
    InpMinRangePct.

TIME / PARITY (see backtest/engine.py header): bars carry the RAW BROKER time
on their tz-aware index (UTC+3 summer / +2 winter). The live EA runs its
session/hour logic on broker TimeCurrent() too. So we compare
state.timestamp.hour/.minute against the SAME Inp* constants from the .mq5 —
we do NOT convert to UTC. This keeps backtest signals aligned with live.

Engine semantics reminder: a Signal returned at bar N's close EXECUTES at bar
N+1's open. The EA's confirmation uses iClose(_Symbol, _Period, 1) — the last
*closed* M15 bar — which in the engine is exactly state.current_bar (the last
row of state.bars). So the parity mapping is:
    EA's iClose(...,1)   <->  state.current_bar["close"]
    EA's "on next tick"  <->  the engine fills our Signal at bar N+1 open.

NOTE: The package name is london_momo per the task; the .mq5 file is
EURUSD_M15_LondonMomo but per its own header it is symbol-agnostic and the live
C2 deployment runs it on the GBPUSD chart, so the default sizing/spec are GBPUSD.
"""
from __future__ import annotations

import math

import pandas as pd

from backtest.costs import SymbolSpec, GBPUSD_SPEC
from backtest.engine import BacktestState, Direction, Signal


class LondonMomoStrategy:
    """London-open opening-range-breakout momentum strategy.

    Duck-typed to the backtest.engine.Strategy protocol.

    Constructor params mirror the .mq5 `input` block; defaults are the live C2
    values from EURUSD_M15_LondonMomo.mq5.

    Parameters
    ----------
    spec:
        SymbolSpec for the traded symbol. Used for the lot-sizing math
        (point / tick_value) exactly as the EA uses SYMBOL_TRADE_TICK_SIZE /
        SYMBOL_TRADE_TICK_VALUE. Defaults to GBPUSD_SPEC (the live C2 chart).
    session_open_hour, session_open_minute:
        InpSessionOpenHour / InpSessionOpenMinute (London cash open, broker time).
    range_minutes:
        InpRangeMinutes — opening-range window length.
    session_close_hour, session_close_minute:
        InpSessionCloseHour / InpSessionCloseMinute (London close, broker time).
    per_trade_risk_pct:
        InpPerTradeRiskPct — fraction of equity risked over the stop distance.
    take_profit_mult:
        InpTakeProfitMult — TP = entry +/- mult * range_width.
    min_range_pct:
        InpMinRangePct — skip the session if range too narrow relative to price.
    volume_step, volume_min, volume_max:
        Broker SYMBOL_VOLUME_STEP / MIN / MAX used by ComputeLots() to floor and
        clamp the raw lot count. Defaults are standard FX broker values
        (0.01 / 0.01 / 100.0). Override per broker symbol if needed.
    """

    # ---- .mq5 input defaults (C2 config) ----
    def __init__(
        self,
        spec: SymbolSpec | None = None,
        session_open_hour: int = 7,          # InpSessionOpenHour
        session_open_minute: int = 0,        # InpSessionOpenMinute
        range_minutes: int = 60,             # InpRangeMinutes
        session_close_hour: int = 16,        # InpSessionCloseHour
        session_close_minute: int = 0,       # InpSessionCloseMinute
        per_trade_risk_pct: float = 0.0050,  # InpPerTradeRiskPct (0.50% — C2)
        take_profit_mult: float = 1.5,       # InpTakeProfitMult
        min_range_pct: float = 0.0005,       # InpMinRangePct (0.05%)
        volume_step: float = 0.01,           # SYMBOL_VOLUME_STEP
        volume_min: float = 0.01,            # SYMBOL_VOLUME_MIN
        volume_max: float = 100.0,           # SYMBOL_VOLUME_MAX
    ) -> None:
        self._spec = spec or GBPUSD_SPEC
        self._open_h = session_open_hour
        self._open_m = session_open_minute
        self._range_minutes = range_minutes
        self._close_h = session_close_hour
        self._close_m = session_close_minute
        self._risk_pct = per_trade_risk_pct
        self._tp_mult = take_profit_mult
        self._min_range_pct = min_range_pct
        self._vol_step = volume_step
        self._vol_min = volume_min
        self._vol_max = volume_max

        # ---- per-session state (mirrors the EA's g_* globals) ----
        self._session_date = None          # g_current_session_date (date object)
        self._range_high = 0.0             # g_range_high
        self._range_low = 0.0              # g_range_low
        self._range_open = 0.0            # g_range_open
        self._range_close = 0.0          # g_range_close
        self._range_locked = False        # g_range_locked
        self._traded_this_session = False # g_traded_this_session
        self._in_position = False         # tracks g_open_ticket != 0

    @property
    def name(self) -> str:
        return "EURUSD_M15_LondonMomo"

    # ------------------------------------------------------------------ #
    # Time-window helpers — ported verbatim from the .mq5, broker time.   #
    # All compare minute-of-day (hour*60 + min) like the EA does.         #
    # ------------------------------------------------------------------ #

    def _open_min_of_day(self) -> int:
        return self._open_h * 60 + self._open_m

    def _range_end_min_of_day(self) -> int:
        return self._open_h * 60 + self._open_m + self._range_minutes

    def _close_min_of_day(self) -> int:
        return self._close_h * 60 + self._close_m

    def _in_range_window(self, ts: pd.Timestamp) -> bool:
        # InRangeWindow: tm >= om && tm < om + RangeMinutes
        tm = ts.hour * 60 + ts.minute
        om = self._open_min_of_day()
        return om <= tm < om + self._range_minutes

    def _in_trading_window(self, ts: pd.Timestamp) -> bool:
        # InTradingWindow: tm >= range_end && tm < close
        tm = ts.hour * 60 + ts.minute
        return self._range_end_min_of_day() <= tm < self._close_min_of_day()

    def _at_session_close(self, ts: pd.Timestamp) -> bool:
        # AtSessionClose: tm >= close
        tm = ts.hour * 60 + ts.minute
        return tm >= self._close_min_of_day()

    # ------------------------------------------------------------------ #
    # ComputeLots — verbatim port of the EA's ComputeLots().              #
    #   risk_amount   = equity * risk_pct                                 #
    #   loss_per_lot  = stop_distance / tick_size * tick_value            #
    #   raw           = risk_amount / loss_per_lot                        #
    #   lots          = floor(raw / step) * step, clamped to [min, max]   #
    # SymbolSpec exposes `point` (== tick_size for these FX symbols) and  #
    # `tick_value`, matching SYMBOL_TRADE_TICK_SIZE / TICK_VALUE.         #
    # ------------------------------------------------------------------ #
    def _compute_lots(self, equity: float, stop_distance_price: float) -> float:
        if stop_distance_price <= 0 or equity <= 0:
            return 0.0
        tick_value = self._spec.tick_value
        tick_size = self._spec.point
        if tick_value <= 0 or tick_size <= 0:
            return 0.0
        risk_amount = equity * self._risk_pct
        loss_per_lot = stop_distance_price / tick_size * tick_value
        if loss_per_lot <= 0:
            return 0.0
        raw = risk_amount / loss_per_lot
        lots = math.floor(raw / self._vol_step) * self._vol_step
        return max(self._vol_min, min(self._vol_max, lots))

    # ------------------------------------------------------------------ #
    # BuildRange — lock high/low/open/close over the range window.        #
    # The EA scans the last 12 M15 bars and keeps those whose time falls  #
    # in [session_open, range_end). Here we scan state.bars (no look-ahead#
    # — only rows up to and including the current bar) and select rows on  #
    # the current session date inside the range window.                   #
    # Returns True if it locked a range (matched >= 2 bars), like the EA.  #
    # ------------------------------------------------------------------ #
    def _build_range(self, bars: pd.DataFrame, session_date) -> bool:
        idx = bars.index
        # Same-session rows inside the range window [open, open+range_minutes).
        tod_min = idx.hour * 60 + idx.minute
        om = self._open_min_of_day()
        mask = (
            (idx.normalize() == pd.Timestamp(session_date).tz_localize(idx.tz)
             if idx.tz is not None
             else idx.normalize() == pd.Timestamp(session_date))
            & (tod_min >= om)
            & (tod_min < om + self._range_minutes)
        )
        window = bars[mask]
        matched = len(window)
        if matched < 2:
            return False
        self._range_high = float(window["high"].max())
        self._range_low = float(window["low"].min())
        # Open of the first (earliest) range bar, close of the last (latest).
        self._range_open = float(window["open"].iloc[0])
        self._range_close = float(window["close"].iloc[-1])
        self._range_locked = True
        return True

    def _reset_session(self, session_date) -> None:
        # Mirrors the OnTick new-session branch.
        self._session_date = session_date
        self._range_locked = False
        self._traded_this_session = False
        self._range_high = self._range_low = self._range_open = self._range_close = 0.0

    # ------------------------------------------------------------------ #
    # generate_signal — the OnTick() body, in engine terms.              #
    # ------------------------------------------------------------------ #
    def generate_signal(self, state: BacktestState) -> Signal | None:
        bars = state.bars
        ts = state.timestamp
        now = ts  # broker time; do NOT convert to UTC (parity)
        equity = state.equity

        # Track whether the engine currently holds our position. The engine owns
        # actual fills/exits (intrabar SL/TP); we mirror g_open_ticket here so
        # the one-trade-per-session and force-flat logic match the EA.
        self._in_position = state.has_position

        # ---- new-session rollover (OnTick: session_date != g_current_session_date) ----
        session_date = now.date()
        if session_date != self._session_date:
            # EA: if a position is open, ForceFlat("new_session"). The engine
            # would have flattened at session close already; if anything is
            # still open across a day boundary, close it for parity.
            flat_needed = self._in_position
            self._reset_session(session_date)
            if flat_needed:
                return Signal.flat()

        # ---- force flat at session close (OnTick: g_open_ticket!=0 && AtSessionClose) ----
        if self._in_position and self._at_session_close(now):
            return Signal.flat()

        # ---- build the range once we are past the range window, inside the day ----
        # EA: if(!g_range_locked && !InRangeWindow(now)) { if(in trading window) BuildRange(); }
        if not self._range_locked and not self._in_range_window(now):
            tm = now.hour * 60 + now.minute
            if self._range_end_min_of_day() <= tm < self._close_min_of_day():
                self._build_range(bars, session_date)

        # ---- guards (OnTick early returns) ----
        if not self._range_locked:
            return None
        if self._traded_this_session:
            return None
        if self._in_position:
            return None
        if not self._in_trading_window(now):
            return None

        # ---- direction = sign(range_close - range_open) ----
        if self._range_close > self._range_open:
            dir_ = +1
        elif self._range_close < self._range_open:
            dir_ = -1
        else:
            dir_ = 0
        if dir_ == 0:
            self._traded_this_session = True
            return None

        range_width = self._range_high - self._range_low

        # EA uses iClose(_Symbol, _Period, 1) — the last CLOSED M15 bar — which
        # in the engine is state.current_bar (last row of state.bars).
        last_close = float(state.current_bar["close"])
        if last_close <= 0 or not math.isfinite(last_close):
            return None

        # ---- min-range filter ----
        if range_width / last_close < self._min_range_pct:
            self._traded_this_session = True
            return None

        # ---- confirmation: closed bar breaks the range in the trend direction ----
        confirmed = (dir_ == +1 and last_close > self._range_high) or (
            dir_ == -1 and last_close < self._range_low
        )
        if not confirmed:
            return None

        # ---- sizing (stop_distance = range_width, per the EA) ----
        lots = self._compute_lots(equity, range_width)
        if lots <= 0:
            return None

        # NOTE on FTMO / portfolio gates: the live EA also runs IsNewsBlackout,
        # WouldExceedRiskCap, WouldExceedClusterCap, and ftmo_check_pretrade
        # before entry (and halves lots on FTMO_DECISION_IMMINENT). Those are
        # account-/portfolio-level gates evaluated by the backtest harness's
        # FTMO simulator, not by a single-symbol Strategy, so they are NOT
        # replicated here — the per-symbol signal/sizing logic is.

        # ---- SL / TP placement ----
        # EA sets entry_px = ask (long) / bid (short) and:
        #   long : sl = range_low ; tp = entry_px + tp_mult * range_width
        #   short: sl = range_high; tp = entry_px - tp_mult * range_width
        # The engine fills our signal at next bar's OPEN, which we don't know at
        # signal time, so we use last_close as the entry proxy for the TP offset
        # (the SL is an absolute range edge and needs no proxy). This is the only
        # unavoidable approximation: the EA's TP is anchored to the live
        # ask/bid at fill, we anchor it to the confirming bar's close.
        entry_proxy = last_close
        if dir_ == +1:
            direction = Direction.LONG
            sl = self._range_low
            tp = entry_proxy + self._tp_mult * range_width
        else:
            direction = Direction.SHORT
            sl = self._range_high
            tp = entry_proxy - self._tp_mult * range_width

        # EA sets g_traded_this_session = true right before SendEntry.
        self._traded_this_session = True

        return Signal(
            direction=direction,
            size=lots,
            stop_loss_price=sl,
            take_profit_price=tp,
            comment="EURUSD_M15_LondonMomo",
        )
