"""Regime-gated strategies — the one untested alpha hypothesis on existing data (2026-06-20).

Hypothesis (CLAUDE.md Phase-1 form): trend-following extracts edge ONLY in persistent/
trending regimes and bleeds in chop; mean-reversion extracts edge ONLY in ranging/anti-
persistent regimes and bleeds in trends. Gate each by a regime classifier (Hurst exponent
or ADX) and the survivor — if any — clears the walk-forward + White's Reality Check gate.

Two regime detectors:
  - ADX(14): >adx_trend_thr = trending, <adx_range_thr = ranging (Wilder).
  - Hurst (aggregated-variance slope over a trailing window): >0.55 persistent, <0.45 mean-reverting.

Indicators are computed on a TRAILING SLICE of state.bars each bar (O(window) not O(N)), so
the run stays fast on 80k-bar histories; no look-ahead (only rows up to the current bar).
Trailing stop uses the engine's same-direction modify-in-place path.

Self-test: python strategies/regime_gated/strategy.py
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from backtest.engine import Signal, Direction, BacktestState
from backtest.costs import SymbolSpec, GBPUSD_SPEC


# --------------------------------------------------------------------------- #
# Indicators (operate on numpy arrays; return the LATEST value)
# --------------------------------------------------------------------------- #
def wilder_atr(high, low, close, period=14) -> float:
    n = len(close)
    if n < period + 1:
        return float("nan")
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = tr[1:period+1].mean()
    for i in range(period+1, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return float(atr)


def adx(high, low, close, period=14) -> float:
    n = len(close)
    if n < 2 * period + 1:
        return float("nan")
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([high[1:] - low[1:],
                            np.abs(high[1:] - close[:-1]),
                            np.abs(low[1:] - close[:-1])])

    def rma(x):
        s = np.empty(len(x))
        s[:period] = np.nan
        seed = x[:period].sum()
        s[period-1] = seed
        for i in range(period, len(x)):
            seed = seed - seed / period + x[i]
            s[i] = seed
        return s

    atr_s = rma(tr)
    pdi = 100 * rma(plus_dm) / atr_s
    mdi = 100 * rma(minus_dm) / atr_s
    dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = dx[~np.isnan(dx)]
    if len(dx) < period:
        return float("nan")
    adx_v = dx[:period].mean()
    for i in range(period, len(dx)):
        adx_v = (adx_v * (period - 1) + dx[i]) / period
    return float(adx_v)


def hurst(close, min_lag=2, max_lag=20) -> float:
    """Aggregated-variance Hurst: std of k-lagged log-price diffs ~ k^H; H = log-log slope."""
    lp = np.log(close)
    lags = np.arange(min_lag, max_lag)
    tau = []
    for lag in lags:
        d = lp[lag:] - lp[:-lag]
        s = np.std(d)
        tau.append(s if s > 0 else 1e-12)
    return float(np.polyfit(np.log(lags), np.log(tau), 1)[0])


# --------------------------------------------------------------------------- #
def _lots(risk_pct, equity, stop_dist, spec, step=0.01, vmin=0.01, vmax=100.0):
    if stop_dist <= 0:
        return 0.0
    loss_per_lot = stop_dist / spec.point * spec.tick_value
    raw = (risk_pct * equity) / loss_per_lot if loss_per_lot > 0 else 0.0
    return float(min(max(np.floor(raw / step) * step, 0.0), vmax)) if raw >= vmin else 0.0


class RegimeTrendStrategy:
    """Donchian breakout + ATR trailing stop, gated to TRENDING regime."""
    def __init__(self, spec: SymbolSpec = GBPUSD_SPEC, donchian=20, atr_period=14,
                 atr_stop=2.0, atr_trail=2.5, risk_pct=0.005, regime="adx",
                 adx_thr=25.0, hurst_thr=0.55, window=120):
        self._spec = spec; self._dc = donchian; self._atrp = atr_period
        self._atr_stop = atr_stop; self._atr_trail = atr_trail; self._risk = risk_pct
        self._regime = regime; self._adx_thr = adx_thr; self._hurst_thr = hurst_thr
        self._window = window; self._trail_sl = None; self._dir = 0

    @property
    def name(self): return f"RegimeTrend[{self._regime}]"

    def _trending(self, h, l, c) -> bool:
        if self._regime == "adx":
            v = adx(h, l, c, self._atrp)
            return v == v and v > self._adx_thr
        v = hurst(c, max_lag=min(20, len(c)//3))
        return v == v and v > self._hurst_thr

    def generate_signal(self, state: BacktestState) -> Signal | None:
        need = max(self._dc, self._window, 2*self._atrp) + 2
        if state.bar_index < need:
            return None
        b = state.bars.iloc[-(self._window+2*self._atrp+5):]
        h = b["high"].values; l = b["low"].values; c = b["close"].values
        atr = wilder_atr(h, l, c, self._atrp)
        if not (atr == atr) or atr <= 0:
            return None
        px = c[-1]
        # manage open trade: trail the stop
        if state.has_position:
            d = state.open_positions[0].direction
            if d == Direction.LONG:
                self._trail_sl = max(self._trail_sl or -1e18, px - self._atr_trail*atr)
            else:
                self._trail_sl = min(self._trail_sl or 1e18, px + self._atr_trail*atr)
            return Signal(direction=d, size=state.open_positions[0].size,
                          stop_loss_price=self._trail_sl, comment="trail")
        # flat: look for a regime-gated breakout
        if not self._trending(h, l, c):
            return None
        dc_hi = c[-(self._dc+1):-1].max(); dc_lo = c[-(self._dc+1):-1].min()
        if px > dc_hi:
            sl = px - self._atr_stop*atr; self._trail_sl = sl
            sz = _lots(self._risk, state.equity, px - sl, self._spec)
            if sz <= 0: return None
            return Signal(Direction.LONG, sz, stop_loss_price=sl, comment="trend_long")
        if px < dc_lo:
            sl = px + self._atr_stop*atr; self._trail_sl = sl
            sz = _lots(self._risk, state.equity, sl - px, self._spec)
            if sz <= 0: return None
            return Signal(Direction.SHORT, sz, stop_loss_price=sl, comment="trend_short")
        return None


class RegimeMeanRevStrategy:
    """Z-score fade to the mean + ATR stop, gated to RANGING regime."""
    def __init__(self, spec: SymbolSpec = GBPUSD_SPEC, z_lookback=20, entry_z=2.0,
                 atr_period=14, atr_stop=2.0, risk_pct=0.005, regime="adx",
                 adx_thr=20.0, hurst_thr=0.45, window=120):
        self._spec = spec; self._zl = z_lookback; self._entry_z = entry_z
        self._atrp = atr_period; self._atr_stop = atr_stop; self._risk = risk_pct
        self._regime = regime; self._adx_thr = adx_thr; self._hurst_thr = hurst_thr
        self._window = window

    @property
    def name(self): return f"RegimeMeanRev[{self._regime}]"

    def _ranging(self, h, l, c) -> bool:
        if self._regime == "adx":
            v = adx(h, l, c, self._atrp)
            return v == v and v < self._adx_thr
        v = hurst(c, max_lag=min(20, len(c)//3))
        return v == v and v < self._hurst_thr

    def generate_signal(self, state: BacktestState) -> Signal | None:
        need = max(self._zl, self._window, 2*self._atrp) + 2
        if state.bar_index < need:
            return None
        b = state.bars.iloc[-(self._window+2*self._atrp+5):]
        h = b["high"].values; l = b["low"].values; c = b["close"].values
        win = c[-self._zl:]
        mu, sd = win.mean(), win.std()
        if sd <= 0:
            return None
        z = (c[-1] - mu) / sd
        if state.has_position:
            d = state.open_positions[0].direction
            # exit when reverted through the mean
            if (d == Direction.LONG and z >= 0) or (d == Direction.SHORT and z <= 0):
                return Signal.flat()
            return None
        if not self._ranging(h, l, c):
            return None
        atr = wilder_atr(h, l, c, self._atrp)
        if not (atr == atr) or atr <= 0:
            return None
        px = c[-1]
        if z <= -self._entry_z:
            sl = px - self._atr_stop*atr
            sz = _lots(self._risk, state.equity, px - sl, self._spec)
            if sz <= 0: return None
            return Signal(Direction.LONG, sz, stop_loss_price=sl, comment="mr_long")
        if z >= self._entry_z:
            sl = px + self._atr_stop*atr
            sz = _lots(self._risk, state.equity, sl - px, self._spec)
            if sz <= 0: return None
            return Signal(Direction.SHORT, sz, stop_loss_price=sl, comment="mr_short")
        return None


def _selftest():
    rng = np.random.default_rng(0)
    n = 500
    rw = 100 + np.cumsum(rng.normal(0, 1, n))                      # random walk -> H~0.5
    trend = 100 + np.cumsum(rng.normal(0.3, 1, n))                 # drift -> H>0.5, ADX high
    mr = 100 + rng.normal(0, 1, n)                                 # noise around mean -> H<0.5
    h_rw, h_tr, h_mr = hurst(rw), hurst(trend), hurst(mr)
    print(f"Hurst: random_walk={h_rw:.2f} (~0.5), trend={h_tr:.2f} (>0.5), meanrev={h_mr:.2f} (<0.5)")
    assert h_tr > h_rw > h_mr, (h_rw, h_tr, h_mr)
    hi = trend + 0.5; lo = trend - 0.5
    a_tr = adx(hi, lo, trend, 14)
    hi2 = mr + 0.5; lo2 = mr - 0.5
    a_mr = adx(hi2, lo2, mr, 14)
    print(f"ADX: trend={a_tr:.1f} (high), meanrev={a_mr:.1f} (low)")
    assert a_tr > a_mr
    print("PASS regime indicator self-test")


if __name__ == "__main__":
    _selftest()
