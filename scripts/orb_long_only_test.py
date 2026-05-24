"""Variant test: long-only ORB with stricter filters.

The full ORB failed because shorts lose against US bullish drift.
Question: does LONG-ONLY ORB with stricter range/breakout filters
have enough per-trade magnitude to clear realistic costs (10-15 bp)?
"""
from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
M30 = 30
SESSION_OPEN_UTC = time(14, 30)
SESSION_CLOSE_UTC = time(21, 0)
RANGE_END_UTC = time(15, 30)


def test_variant(symbol: str, min_range_pct: float, breakout_buffer_pct: float):
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * 3)
    df = cache.read(symbol, M30, start, end)
    if df is None or df.empty:
        return None

    sess = df[(df.index.time >= SESSION_OPEN_UTC) & (df.index.time < SESSION_CLOSE_UTC)].copy()
    sess["date"] = sess.index.date

    long_fwd = []
    for day, day_df in sess.groupby("date"):
        rw = day_df[day_df.index.time < RANGE_END_UTC]
        pr = day_df[day_df.index.time >= RANGE_END_UTC]
        if len(rw) < 2 or len(pr) < 1:
            continue
        rh = float(rw["high"].max())
        rl = float(rw["low"].min())
        ref = float(pr.iloc[0]["open"])
        if ref <= 0 or (rh - rl) / ref < min_range_pct:
            continue
        # Require breakout to CLEAR the range high by buffer_pct (more conviction)
        trigger = rh * (1.0 + breakout_buffer_pct)
        for ts, bar in pr.iterrows():
            if bar["close"] > trigger:
                entry = float(bar["close"])
                end_px = float(pr.iloc[-1]["close"])
                long_fwd.append((end_px - entry) / entry)
                break
    return long_fwd


def main():
    print("Long-only ORB variants (US500 only for speed)")
    print()
    print(f"{'min_range%':>10} {'breakout+%':>10} {'n_trades':>9} "
          f"{'mean%':>7} {'std%':>7} {'t-stat':>7}  verdict")
    print("-" * 80)
    for min_range in [0.0015, 0.003, 0.005]:
        for buf in [0.0, 0.0005, 0.001, 0.002]:
            r = test_variant("US500", min_range, buf)
            if r is None or len(r) < 30:
                continue
            arr = np.array(r)
            mean = float(arr.mean())
            std = float(arr.std(ddof=1))
            se = std / np.sqrt(len(arr))
            t = mean / se if se > 0 else 0.0
            # Need ~10bp net mean to clear ~10bp costs at 1lot, looser at smaller sizes
            verdict = ("CLEARS COSTS" if mean > 0.001 and t > 1.5 else
                       "marginal" if mean > 0.0005 and t > 1.0 else "weak")
            print(f"{100*min_range:>9.2f}% {100*buf:>9.2f}% {len(arr):>9} "
                  f"{100*mean:>+6.3f}% {100*std:>6.3f}% {t:>+7.2f}  {verdict}")


if __name__ == "__main__":
    main()
