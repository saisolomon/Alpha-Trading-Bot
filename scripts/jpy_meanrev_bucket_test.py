"""
JPY-cross D1 mean-reversion bucket test.

Same methodology as scripts/meanrev_bucket_test.py (Index MR), applied to
the 6 JPY crosses we have cached (GBPJPY, EURJPY, AUDJPY, NZDJPY, CADJPY,
CHFJPY). The hypothesis: BoJ intervention regimes + carry-unwind dynamics
make JPY crosses revert to a slow mean on D1 horizons.

If the canonical z-score signal (formation=10d, z_lookback=252d) shows
strong negative gradient on D1 forward returns, the same engine that
backs Index MR can be cloned to a JPY-cross MR strategy.

PASS criterion:
  - Average t-stat across pairs < -2 AND average Spearman < -0.5
  - At least 3 of 6 pairs individually PASS

Usage:
    uv run python scripts/jpy_meanrev_bucket_test.py
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
SYMBOLS = ["GBPJPY", "EURJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY"]


def bucket_stats(rets: pd.Series, formation: int, forward: int, z_lookback: int):
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


def monotonicity(out) -> float:
    return float(pd.Series(out["decile"].values).corr(
        pd.Series(out["mean"].values), method="spearman"
    ))


def main() -> None:
    from data.cache import ParquetCache

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * 12)

    formation, forward, z_lookback = 10, 5, 252
    print(f"JPY-cross Mean-Reversion Bucket Test")
    print(f"  formation={formation}d  forward={forward}d  z_lookback={z_lookback}d")
    print(f"  Universe: {SYMBOLS}")
    print(f"  Sample: 12y D1, decile bucketing\n")

    summary = {}
    for sym in SYMBOLS:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            print(f"  {sym}: no cached data\n")
            continue
        rets = np.log(df["close"]).diff().dropna()
        out = bucket_stats(rets, formation, forward, z_lookback)
        if out is None or len(out) < 5:
            print(f"  {sym}: insufficient data\n")
            continue
        print(f"  {sym} -- forward {forward}d return by past-z decile")
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
        d1, d10 = out.iloc[0], out.iloc[-1]
        diff = d10["mean"] - d1["mean"]
        se_diff = np.sqrt(d10["se"] ** 2 + d1["se"] ** 2)
        t_diff = diff / se_diff if se_diff > 0 else 0.0
        rho = monotonicity(out)
        print(f"\n  {sym} summary:  D10-D1 = {100*diff:+.3f}%   "
              f"t={t_diff:+.2f}  rho={rho:+.3f}")
        print()
        summary[sym] = {"t_diff": t_diff, "rho": rho,
                        "d1_mean": d1["mean"], "d10_mean": d10["mean"]}

    if not summary:
        print("No data available.")
        return

    print("=" * 75)
    print("  CROSS-UNIVERSE SUMMARY")
    print("=" * 75)
    print(f"  {'symbol':<8}  {'D1 mean %':>10}  {'D10 mean %':>10}  "
          f"{'t-stat':>7}  {'Spearman':>9}  verdict")
    individual_pass = 0
    for sym, s in summary.items():
        v = ("PASS"   if s["t_diff"] < -2 and s["rho"] < -0.5 else
             "WEAK"   if s["t_diff"] < -1 and s["rho"] < -0.3 else
             "fail")
        if v == "PASS":
            individual_pass += 1
        print(f"  {sym:<8}  {100*s['d1_mean']:>+9.3f}%  "
              f"{100*s['d10_mean']:>+9.3f}%  "
              f"{s['t_diff']:>+7.2f}  {s['rho']:>+9.3f}  {v}")

    ts = [s["t_diff"] for s in summary.values()]
    rhos = [s["rho"] for s in summary.values()]
    print(f"\n  Average t-stat:    {np.mean(ts):+.2f}")
    print(f"  Average Spearman:  {np.mean(rhos):+.3f}")
    print(f"  Individual PASS:   {individual_pass}/{len(summary)}")
    print()
    print(f"  PASS criterion: avg t < -2 AND avg rho < -0.5 AND >=3 individual PASS")
    if np.mean(ts) < -2 and np.mean(rhos) < -0.5 and individual_pass >= 3:
        print(f"  Result: PASS -- proceed to build JPY-cross MR backtest")
    elif np.mean(ts) < -1 and np.mean(rhos) < -0.3:
        print(f"  Result: WEAK -- signal present but small; only worth building")
        print(f"          if the existing MR engine generalises trivially")
    else:
        print(f"  Result: FAIL -- z-score MR signal not predictive on JPY crosses")


if __name__ == "__main__":
    main()
