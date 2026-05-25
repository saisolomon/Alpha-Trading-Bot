"""
Quick cointegration verification on new pair candidates before we
clone the XAUUSD_XAGUSD_Pairs engine. For each pair:

  1. Rolling OLS on 504-bar (~2y) lookback
  2. Compute spread = log(A) - beta*log(B) - alpha
  3. Augmented Dickey-Fuller (ADF) test on the spread
  4. Bucket-test the spread's mean-reversion characteristics:
       - half-life via Ornstein-Uhlenbeck fit
       - in-sample z-score distribution (does it actually mean-revert
         after extreme readings?)

Pairs to check:
  WTI / BRT        — energy crack-spread analog
  GOOGL / META     — online ad duopoly
  MSFT / AAPL      — megacap tech leaders

Pass criteria (any single TRUE = the pair is worth shipping):
  - ADF p-value < 0.05 (statistical cointegration)
  - half-life 5-90 bars (slow enough to capture, fast enough to trade)
  - mean fwd-return after |z| > 2 reverts toward zero
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408

PAIRS = [
    ("WTI", "BRT"),
    ("GOOGL", "META"),
    ("MSFT", "AAPL"),
]


def load(sym: str, years: int = 5) -> pd.Series:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    df = cache.read(sym, D1, start, end)
    if df is None or df.empty:
        return None
    return df["close"]


def rolling_ols_residual(a: pd.Series, b: pd.Series, lookback: int = 504) -> pd.Series:
    """Compute the rolling-OLS spread of log(a) vs log(b)."""
    log_a, log_b = np.log(a), np.log(b)
    # Use the C++ library for parity with the EA
    try:
        from cpp.bindings import quantlib
        ols = quantlib.compute_rolling_ols(log_b.tolist(), log_a.tolist(), lookback)
        beta = pd.Series(ols[0], index=a.index)
        alpha = pd.Series(ols[1], index=a.index)
    except Exception:
        # fallback: pandas rolling OLS
        from numpy.polynomial import polynomial as P
        beta = pd.Series(index=a.index, dtype=float)
        alpha = pd.Series(index=a.index, dtype=float)
        for i in range(lookback - 1, len(a)):
            x = log_b.iloc[i - lookback + 1:i + 1].values
            y = log_a.iloc[i - lookback + 1:i + 1].values
            n = len(x)
            sx, sy = x.sum(), y.sum()
            sxx, sxy = (x * x).sum(), (x * y).sum()
            denom = n * sxx - sx * sx
            if denom == 0:
                continue
            b_v = (n * sxy - sx * sy) / denom
            a_v = (sy - b_v * sx) / n
            beta.iloc[i] = b_v
            alpha.iloc[i] = a_v
    spread = log_a - beta * log_b - alpha
    return spread.dropna()


def adf_pvalue(series: pd.Series) -> float:
    try:
        from statsmodels.tsa.stattools import adfuller
        return float(adfuller(series.dropna(), autolag="AIC")[1])
    except Exception:
        return float("nan")


def half_life_ou(series: pd.Series) -> float:
    """Estimate OU half-life via lag-1 autoregression on spread changes."""
    s = series.dropna()
    if len(s) < 50:
        return float("nan")
    s_lag = s.shift(1).dropna()
    s_diff = (s - s.shift(1)).dropna()
    s_lag = s_lag.loc[s_diff.index]
    # delta_spread = theta * (mu - spread_lag) + eps  <=>  delta = -k*spread_lag + b
    n = len(s_lag)
    x = s_lag.values
    y = s_diff.values
    sx = x.sum(); sy = y.sum()
    sxx = (x * x).sum(); sxy = (x * y).sum()
    denom = n * sxx - sx * sx
    if denom == 0:
        return float("nan")
    k = -((n * sxy - sx * sy) / denom)   # mean-reversion rate
    if k <= 0:
        return float("nan")
    return float(np.log(2) / k)


def bucket_fwd_returns(spread: pd.Series, fwd_bars: int = 10) -> dict:
    """For each z-score bucket, what is the mean forward return?
    Strong mean reversion -> high |z| bucket has fwd return of opposite sign."""
    z = (spread - spread.rolling(252).mean()) / spread.rolling(252).std()
    fwd = spread.shift(-fwd_bars) - spread
    z, fwd = z.align(fwd, join="inner")
    valid = z.dropna().index.intersection(fwd.dropna().index)
    z, fwd = z.loc[valid], fwd.loc[valid]
    buckets = {
        "z < -2": float(fwd[z < -2].mean()) if (z < -2).any() else float("nan"),
        "-2 <= z < -1": float(fwd[(z >= -2) & (z < -1)].mean()) if ((z >= -2) & (z < -1)).any() else float("nan"),
        "-1 <= z < 1": float(fwd[(z >= -1) & (z < 1)].mean()) if ((z >= -1) & (z < 1)).any() else float("nan"),
        "1 <= z < 2": float(fwd[(z >= 1) & (z < 2)].mean()) if ((z >= 1) & (z < 2)).any() else float("nan"),
        "z >= 2": float(fwd[z >= 2].mean()) if (z >= 2).any() else float("nan"),
    }
    return buckets


def main():
    for a, b in PAIRS:
        print("=" * 70)
        print(f"  {a} / {b}")
        print("=" * 70)
        ca = load(a, 5)
        cb = load(b, 5)
        if ca is None or cb is None:
            print(f"  data missing (a={ca is not None} b={cb is not None})")
            continue
        common = ca.index.intersection(cb.index)
        ca, cb = ca.loc[common], cb.loc[common]
        print(f"  sample: {common[0].date()} -> {common[-1].date()}  ({len(common)} bars)")
        spread = rolling_ols_residual(ca, cb, lookback=504)
        if spread.empty:
            print(f"  spread empty after rolling OLS warmup")
            continue
        pval = adf_pvalue(spread)
        hl = half_life_ou(spread)
        print(f"  spread mean: {spread.mean():+.5f}  std: {spread.std():.5f}")
        print(f"  ADF p-value: {pval:.4f}  (< 0.05 = stationary = cointegrated)")
        print(f"  OU half-life: {hl:.1f} bars  (5-90 = tradeable)")
        buckets = bucket_fwd_returns(spread, fwd_bars=10)
        print(f"  fwd-return by z-score bucket (10-bar forward, expect oppossing sign at extremes):")
        for label, val in buckets.items():
            print(f"    {label:<18} mean fwd-spread = {val:+.5f}")
        # Verdict
        passes = []
        if not np.isnan(pval) and pval < 0.05: passes.append("ADF<0.05")
        if not np.isnan(hl) and 5 <= hl <= 90: passes.append(f"half-life={hl:.0f}d")
        extreme_low = buckets["z < -2"]
        extreme_hi = buckets["z >= 2"]
        if not np.isnan(extreme_low) and extreme_low > 0: passes.append("z<-2 reverts up")
        if not np.isnan(extreme_hi) and extreme_hi < 0: passes.append("z>+2 reverts down")
        if passes:
            print(f"  [PASS] SHIP: {', '.join(passes)}")
        else:
            print(f"  [SKIP] SKIP: no cointegration signals")
        print()


if __name__ == "__main__":
    main()
