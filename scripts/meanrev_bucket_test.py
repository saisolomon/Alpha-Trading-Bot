"""
Bucket signal test for the index mean-reversion hypothesis.

Different statistic from the autocorrelation test that already ran: bin each
day's PAST formation-period return into z-score deciles, then compute the
mean and SE of the subsequent FORWARD-period return per bucket.

A mean-reversion signal that is actually tradeable should produce:
  - Decile 1 (most negative past z): positive forward return (price bounces)
  - Decile 10 (most positive past z): negative forward return (price fades)
  - Monotonic gradient across deciles
  - Statistical significance (decile-1 vs decile-10 t-stat > 2)

If the gradient is non-monotonic or the t-stat fails, the simple z-score
signal lacks predictive structure -- reject before building the backtest.

Usage:
    uv run python scripts/meanrev_bucket_test.py
    uv run python scripts/meanrev_bucket_test.py --formation 10 --forward 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc

D1 = 16408
DEFAULT_SYMBOLS = ["US500", "USTEC", "US30", "DE40"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mean-reversion bucket signal test")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--formation", type=int, default=10,
                   help="Past return window (D1 bars)")
    p.add_argument("--forward", type=int, default=5,
                   help="Forward return window (D1 bars)")
    p.add_argument("--z-lookback", type=int, default=252,
                   help="Rolling window for z-score normalisation")
    return p.parse_args()


def bucket_stats(rets, formation: int, forward: int, z_lookback: int):
    """Return per-decile (mean, se, count) of forward return.

    Bucketing is done on the rolling z-score of past-formation return; forward
    return is the cumulative log return over the next `forward` bars.
    """
    import numpy as np
    import pandas as pd

    cum_past = rets.rolling(formation).sum()
    z = (cum_past - cum_past.rolling(z_lookback).mean()) / cum_past.rolling(z_lookback).std()
    cum_fwd = rets.shift(-forward).rolling(forward).sum()

    df = pd.DataFrame({"z": z, "fwd": cum_fwd}).dropna()
    if len(df) < 100:
        return None

    df["decile"] = pd.qcut(df["z"], 10, labels=False, duplicates="drop") + 1
    out = df.groupby("decile")["fwd"].agg(["mean", "std", "count"]).reset_index()
    out["se"] = out["std"] / np.sqrt(out["count"])
    out["z_min"] = df.groupby("decile")["z"].min().values
    out["z_max"] = df.groupby("decile")["z"].max().values
    return out


def print_bucket_table(sym: str, out, forward: int) -> None:
    print(f"\n  {sym} -- forward {forward}d return by past-z decile")
    print(f"  {'decile':>6}  {'z range':>16}  {'n':>4}  "
          f"{'mean fwd %':>11}  {'SE %':>7}  {'t-stat':>7}  {'sig?':>5}")
    print(f"  {'-' * 65}")
    for _, row in out.iterrows():
        t = row["mean"] / row["se"] if row["se"] > 0 else 0.0
        sig = "*" if abs(t) > 2 else ""
        print(f"  {int(row['decile']):>6}  "
              f"[{row['z_min']:>+5.2f},{row['z_max']:>+5.2f}]  "
              f"{int(row['count']):>4}  "
              f"{100*row['mean']:>+10.3f}%  "
              f"{100*row['se']:>6.3f}%  "
              f"{t:>+7.2f}  {sig:>5}")


def monotonicity(out) -> float:
    """Spearman rank correlation between decile rank and mean forward return.
    Should be negative for a mean-reversion signal."""
    import numpy as np
    import pandas as pd
    return float(pd.Series(out["decile"].values).corr(
        pd.Series(out["mean"].values), method="spearman"
    ))


def main() -> None:
    args = parse_args()
    import numpy as np
    import pandas as pd
    from data.cache import ParquetCache

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * args.years)

    print(f"Bucket test: formation={args.formation}d  forward={args.forward}d  "
          f"z_lookback={args.z_lookback}d")
    print(f"Universe: {args.symbols}")

    decile_summary = {}
    for sym in args.symbols:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            print(f"\n  {sym}: no cached data")
            continue
        rets = np.log(df["close"]).diff().dropna()
        out = bucket_stats(rets, args.formation, args.forward, args.z_lookback)
        if out is None or len(out) < 5:
            print(f"\n  {sym}: insufficient data after windowing")
            continue
        print_bucket_table(sym, out, args.forward)

        # Decile-1 vs decile-10 t-stat (the "extreme buckets" test)
        d1 = out.iloc[0]
        d10 = out.iloc[-1]
        diff = d10["mean"] - d1["mean"]
        # NB: for mean-reversion we want d10 < d1 (top decile mean < bottom decile mean)
        se_diff = np.sqrt(d10["se"] ** 2 + d1["se"] ** 2)
        t_diff = diff / se_diff if se_diff > 0 else 0.0
        rho = monotonicity(out)
        print(f"\n  {sym} summary:")
        print(f"    D1 forward 5d mean: {100*d1['mean']:+.3f}%   (bottom z bucket)")
        print(f"    D10 forward 5d mean: {100*d10['mean']:+.3f}%  (top z bucket)")
        print(f"    D10 - D1: {100*diff:+.3f}%   t-stat: {t_diff:+.2f}  "
              f"(want < -2 for mean-reversion)")
        print(f"    Spearman(decile, mean_fwd): {rho:+.3f}  "
              f"(want strongly negative)")
        decile_summary[sym] = {"t_diff": t_diff, "rho": rho,
                               "d1_mean": d1["mean"], "d10_mean": d10["mean"]}

    # Cross-universe summary
    if decile_summary:
        print(f"\n{'=' * 70}")
        print(f"  CROSS-UNIVERSE SUMMARY")
        print(f"{'=' * 70}")
        print(f"  {'symbol':<8}  {'D1 mean %':>10}  {'D10 mean %':>10}  "
              f"{'t-stat':>7}  {'Spearman':>9}")
        for sym, s in decile_summary.items():
            print(f"  {sym:<8}  {100*s['d1_mean']:>+9.3f}%  "
                  f"{100*s['d10_mean']:>+9.3f}%  "
                  f"{s['t_diff']:>+7.2f}  {s['rho']:>+9.3f}")

        ts = [s["t_diff"] for s in decile_summary.values()]
        rhos = [s["rho"] for s in decile_summary.values()]
        print(f"\n  Average t-stat: {np.mean(ts):+.2f}")
        print(f"  Average Spearman: {np.mean(rhos):+.3f}")
        print(f"\n  PASS criterion: avg t-stat < -2 AND avg Spearman < -0.5")
        if np.mean(ts) < -2 and np.mean(rhos) < -0.5:
            print(f"  Result: PASS -- proceed to backtest")
        elif np.mean(ts) < -1 and np.mean(rhos) < -0.3:
            print(f"  Result: WEAK -- consider longer formation or alternative signal")
        else:
            print(f"  Result: FAIL -- z-score signal lacks predictive structure")


if __name__ == "__main__":
    main()
