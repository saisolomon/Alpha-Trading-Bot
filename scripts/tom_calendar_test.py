"""
Turn-of-the-Month (TotM) calendar-effect test on indices.

Lakonishok & Smidt (1988) and many follow-ups document that equity index
returns are concentrated in a narrow window around month-end:
  - Days -1 to +3 relative to month-end have significantly higher mean
    returns than other trading days.
  - The effect persists post-2000 (Hensel-Ziemba 1996, McConnell-Xu 2008).

If true on our 12y index sample, this is the cleanest possible third alpha
leg: a structurally calendar-driven signal, uncorrelated with mean-
reversion and pairs (different mechanism entirely).

Test: bucket each trading day by its position in the month, compute the
mean forward 1-day return, and check whether days -1 to +3 outperform.

Usage:
    uv run python scripts/tom_calendar_test.py
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
SYMBOLS = ["US500", "USTEC", "US30", "DE40"]


def load_data(years: int = 12):
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    out: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            out[sym] = df
    return out


def label_tom_window(idx: pd.DatetimeIndex) -> pd.Series:
    """For each date, return its trading-day position relative to month-end.

    -3, -2, -1 = last 3 trading days of the month
    +1, +2, +3 = first 3 trading days of next month
    None       = "middle of the month" (not in TotM window)
    """
    out = pd.Series(index=idx, dtype="Int64")
    df = pd.DataFrame({"date": idx})
    df["ym"] = df["date"].dt.to_period("M")
    # Position within each month
    df["rank_in_month_fwd"] = df.groupby("ym").cumcount() + 1  # 1, 2, ...
    df["rank_in_month_bwd"] = df.groupby("ym").cumcount(ascending=False) + 1
    # Assign labels
    for i in df.index:
        bwd = int(df.loc[i, "rank_in_month_bwd"])
        fwd = int(df.loc[i, "rank_in_month_fwd"])
        if bwd <= 3:
            out.iloc[i] = -bwd
        elif fwd <= 3:
            out.iloc[i] = fwd
    return out


def main() -> None:
    data = load_data(12)
    print(f"Loaded: {list(data.keys())}")
    if not data:
        sys.exit(1)

    print(f"\n{'=' * 85}")
    print(f"  TURN-OF-THE-MONTH EFFECT: forward 1-day return by trading-day-in-month")
    print(f"  (per-symbol, 12y D1)")
    print(f"{'=' * 85}")
    print(f"  {'symbol':<8}  {'period':<25}  {'TotM days [-1..+3]':>22}  "
          f"{'mid-month':>11}  {'spread (bp)':>12}  {'t-stat':>8}")
    print(f"  {'-' * 80}")

    results = {}
    for sym, df in data.items():
        rets = df["close"].pct_change()
        labels = label_tom_window(df.index)
        # TotM window = labels in {-1, 1, 2, 3}  (-1 is last day of month,
        # then first 3 days of next month). Conservative "narrow window".
        tom_mask = labels.isin([-1, 1, 2, 3])
        tom_rets = rets[tom_mask].dropna()
        other_rets = rets[~tom_mask & rets.notna()].dropna()
        if len(tom_rets) < 30 or len(other_rets) < 30:
            print(f"  {sym:<8}  insufficient data")
            continue
        tom_mean = float(tom_rets.mean())
        other_mean = float(other_rets.mean())
        spread = tom_mean - other_mean
        # Two-sample t-stat (unequal var, Welch's)
        var_t = tom_rets.var() / len(tom_rets) + other_rets.var() / len(other_rets)
        t = spread / np.sqrt(var_t)
        print(f"  {sym:<8}  {df.index[0].date()} .. {df.index[-1].date()}  "
              f"{100*tom_mean:>+18.4f}%   {100*other_mean:>+9.4f}%  "
              f"{1e4*spread:>+11.2f}  {t:>+8.2f}")
        results[sym] = {"tom_mean": tom_mean, "other_mean": other_mean,
                        "spread": spread, "t": t,
                        "n_tom": len(tom_rets), "n_other": len(other_rets)}

    if not results:
        return

    # Cross-universe summary
    print()
    print(f"{'=' * 60}")
    print(f"  CROSS-UNIVERSE SUMMARY")
    print(f"{'=' * 60}")
    avg_spread_bp = np.mean([1e4 * r["spread"] for r in results.values()])
    avg_t = np.mean([r["t"] for r in results.values()])
    print(f"  Avg TotM-vs-mid-month spread: {avg_spread_bp:+.2f} bp/day")
    print(f"  Avg t-stat:                   {avg_t:+.2f}")
    print()
    print(f"  PASS criterion: avg spread > 5 bp/day AND avg t-stat > 2")
    if avg_spread_bp > 5 and avg_t > 2:
        print(f"  Result: PASS -- TotM effect present, proceed to build")
    elif avg_spread_bp > 2 and avg_t > 1.5:
        print(f"  Result: WEAK -- effect present but marginal")
    else:
        print(f"  Result: FAIL -- no significant TotM effect on this sample")

    # Quick estimate of strategy economics
    if avg_spread_bp > 0:
        n_tom_days_per_year = 4 * 12  # ~4 trading days per month in the window
        ann_excess = (avg_spread_bp / 1e4) * n_tom_days_per_year * 100
        print(f"\n  If we long-only on TotM days: expected annualised excess return")
        print(f"  ~ {ann_excess:.2f}% (rough, ignoring costs).")


if __name__ == "__main__":
    main()
