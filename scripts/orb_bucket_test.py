"""
Bucket signal test for the Opening Range Breakout (ORB) hypothesis.

For each US-cash-session day in the cached M30 history:
  1. Define range = [min(low), max(high)] over the first 2 M30 bars
     after 14:30 UTC (= the first 60 minutes of NY session)
  2. Detect breakouts during the rest of the session (15:30 - 21:00 UTC):
     LONG breakout when close > range_high; SHORT when close < range_low
  3. Measure forward return from breakout bar's close to session close
     (21:00 UTC or last available bar before that)

Pass criterion (necessary, not sufficient):
  - LONG breakouts have positive mean session-end return
  - SHORT breakouts have negative mean session-end return  (i.e. the
    short trade is profitable)
  - Combined directional t-stat > 2 (statistically distinguishable
    from zero)

If this passes, build the backtest engine. If not, abandon ORB and
move to Strategy B.

Usage:
    uv run python scripts/orb_bucket_test.py
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
SYMBOLS = ["US500", "USTEC", "US30"]

# US cash session in UTC (winter / standard time -- ignore DST shift for now,
# all our analysis is at 30-min granularity which absorbs the 1h DST drift).
SESSION_OPEN_UTC = time(14, 30)   # 9:30 EST
SESSION_CLOSE_UTC = time(21, 0)   # 16:00 EST
RANGE_END_UTC = time(15, 30)      # 14:30 + 60min


def load_m30(symbol: str, years: int = 3) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    return cache.read(symbol, M30, start, end)


def analyze_symbol(symbol: str, df: pd.DataFrame,
                    min_range_pct: float = 0.0015) -> dict:
    """Bucket analysis for one symbol.

    Returns dict with:
      n_days, n_long_breakouts, n_short_breakouts, n_no_breakouts,
      mean_long_fwd_pct, mean_short_fwd_pct, combined_t_stat
    """
    # Restrict to US session bars only (14:30 - 21:00 UTC)
    session_mask = (
        (df.index.time >= SESSION_OPEN_UTC) &
        (df.index.time < SESSION_CLOSE_UTC)
    )
    sess = df[session_mask].copy()
    sess["date"] = sess.index.date

    longs_fwd: list[float] = []   # forward returns of long breakouts
    shorts_fwd: list[float] = []
    n_days_with_data = 0

    for day, day_df in sess.groupby("date"):
        # Need at least 2 bars within the [14:30, 15:30) range window AND
        # at least 1 bar after 15:30 to detect a breakout
        range_window = day_df[day_df.index.time < RANGE_END_UTC]
        post_range = day_df[day_df.index.time >= RANGE_END_UTC]
        if len(range_window) < 2 or len(post_range) < 1:
            continue
        n_days_with_data += 1

        range_high = float(range_window["high"].max())
        range_low = float(range_window["low"].min())
        range_width = range_high - range_low
        # First post-range bar's open as reference price; range width as % of price
        ref_price = float(post_range.iloc[0]["open"])
        if ref_price <= 0 or range_width / ref_price < min_range_pct:
            continue  # range too narrow to be a meaningful breakout

        # Walk post-range bars in time order; record FIRST breakout
        breakout_dir = 0
        entry_price = 0.0
        for ts, bar in post_range.iterrows():
            if bar["close"] > range_high:
                breakout_dir = +1
                entry_price = float(bar["close"])
                break
            elif bar["close"] < range_low:
                breakout_dir = -1
                entry_price = float(bar["close"])
                break

        if breakout_dir == 0:
            continue  # no breakout this session

        # Forward return: from breakout bar close to session close
        # (last bar before 21:00)
        session_end_price = float(post_range.iloc[-1]["close"])
        fwd_pct = (session_end_price - entry_price) / entry_price
        # Signed by breakout direction: positive = profitable trade
        signed_fwd = breakout_dir * fwd_pct

        if breakout_dir == +1:
            longs_fwd.append(fwd_pct)
        else:
            shorts_fwd.append(fwd_pct)

    # Compute statistics
    longs = np.array(longs_fwd)
    shorts = np.array(shorts_fwd)
    n_long = len(longs)
    n_short = len(shorts)

    long_mean = float(longs.mean()) if n_long > 0 else 0.0
    short_mean = float(shorts.mean()) if n_short > 0 else 0.0

    # Combined trade returns (long-side returns + INVERTED short-side returns)
    # because for a short trade, profit = -price_change
    all_signed = np.concatenate([longs, -shorts]) if n_long + n_short > 0 else np.array([])
    n_total = len(all_signed)
    if n_total > 1:
        mean_signed = float(all_signed.mean())
        se = float(all_signed.std(ddof=1) / np.sqrt(n_total))
        t_stat = mean_signed / se if se > 0 else 0.0
    else:
        mean_signed = 0.0
        t_stat = 0.0

    return {
        "symbol": symbol,
        "n_days": n_days_with_data,
        "n_long": n_long,
        "n_short": n_short,
        "n_total": n_total,
        "mean_long_pct": long_mean,
        "mean_short_pct": short_mean,
        "mean_signed_pct": mean_signed,
        "t_stat": t_stat,
    }


def main() -> None:
    print("ORB bucket test on 3-year M30 cache")
    print("=" * 80)
    print(f"  Range window:  14:30 - 15:30 UTC (first 60 min of NY session)")
    print(f"  Trade window:  15:30 - 21:00 UTC (rest of session)")
    print(f"  Min range:     0.15% of price (skip ultra-narrow days)")
    print()
    print(f"  {'symbol':<8} {'n_days':>7} {'n_long':>7} {'n_short':>8} "
          f"{'long%':>7} {'short%':>7} {'signed_avg%':>11} {'t-stat':>7}")
    print("  " + "-" * 78)

    all_results = []
    for sym in SYMBOLS:
        df = load_m30(sym)
        if df is None or df.empty:
            print(f"  {sym}: NO M30 cache")
            continue
        r = analyze_symbol(sym, df)
        all_results.append(r)
        print(f"  {sym:<8} {r['n_days']:>7} {r['n_long']:>7} {r['n_short']:>8} "
              f"{100*r['mean_long_pct']:>+6.3f}% {100*r['mean_short_pct']:>+6.3f}% "
              f"{100*r['mean_signed_pct']:>+10.3f}% {r['t_stat']:>+7.2f}")

    if not all_results:
        return

    # Cross-universe aggregate
    print("  " + "-" * 78)
    total_n = sum(r["n_total"] for r in all_results)
    weighted_signed = sum(r["mean_signed_pct"] * r["n_total"] for r in all_results) / max(1, total_n)
    avg_t = np.mean([r["t_stat"] for r in all_results])
    print(f"  {'AGGREGATE':<8} {' ':>7} {sum(r['n_long'] for r in all_results):>7} "
          f"{sum(r['n_short'] for r in all_results):>8} "
          f"{'':>7} {'':>7} {100*weighted_signed:>+10.3f}% {avg_t:>+7.2f}")

    print()
    print("=" * 80)
    print("PASS CRITERIA")
    print("=" * 80)
    print("  1. Each symbol's t-stat >= 2.0  (signal distinguishable from noise)")
    print("  2. Each symbol's mean_signed_pct >= +0.05%  (after-cost margin)")
    print("  3. Aggregate t-stat >= 2.5  (signal robust across universe)")
    print()
    all_t_pass = all(r["t_stat"] >= 2.0 for r in all_results)
    all_mag_pass = all(r["mean_signed_pct"] >= 0.0005 for r in all_results)
    agg_pass = avg_t >= 2.5

    if all_t_pass and all_mag_pass and agg_pass:
        print("  Result: STRONG PASS -- proceed to build the backtest engine")
    elif weighted_signed > 0 and avg_t > 1.5:
        print("  Result: WEAK PASS -- signal exists but expect modest Sharpe")
        print("          Build the backtest but set expectations to 0.7-1.0, not 1.5")
    else:
        print("  Result: FAIL -- ORB doesn't have positive expectancy on this universe")
        print("          Abandon Strategy A, move to Strategy B (news straddle).")


if __name__ == "__main__":
    main()
