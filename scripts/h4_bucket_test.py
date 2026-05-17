"""Quick H4 bucket signal test on cached index data.

If this gives clean negative Spearman + significant t-stat, H4 MR is
worth building. Else move on to pairs trading.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.cache import ParquetCache

UTC = timezone.utc
H4 = 16388


def main() -> None:
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * 3)

    print("H4 bucket test on indices (formation=10 H4 bars = 40h; forward=5 H4 bars = 20h)")
    print(f"{'symbol':<8} {'D1_fwd%':>10} {'D10_fwd%':>10} {'t-stat':>8} "
          f"{'Spearman':>9} {'n/dec':>6} {'n_bars':>7}")
    print("-" * 75)
    results = []
    for sym in ["US500", "USTEC", "US30", "DE40"]:
        df = cache.read(sym, H4, start, end)
        if df is None or df.empty:
            print(f"{sym}: no H4 data")
            continue
        rets = np.log(df["close"]).diff().dropna()
        cum10 = rets.rolling(10).sum()
        z = (cum10 - cum10.rolling(252).mean()) / cum10.rolling(252).std()
        fwd = rets.shift(-5).rolling(5).sum()
        bb = pd.DataFrame({"z": z, "fwd": fwd}).dropna()
        bb["dec"] = pd.qcut(bb["z"], 10, labels=False, duplicates="drop") + 1
        out = bb.groupby("dec")["fwd"].agg(["mean", "std", "count"]).reset_index()
        out["se"] = out["std"] / np.sqrt(out["count"])
        d1, d10 = out.iloc[0], out.iloc[-1]
        se_diff = np.sqrt(d1["se"] ** 2 + d10["se"] ** 2)
        t = (d10["mean"] - d1["mean"]) / se_diff
        rho = float(pd.Series(out["dec"]).corr(pd.Series(out["mean"]), method="spearman"))
        results.append((sym, d1["mean"], d10["mean"], t, rho))
        print(f"{sym:<8} {100*d1['mean']:>+9.3f}% {100*d10['mean']:>+9.3f}% "
              f"{t:>+8.2f} {rho:>+9.3f} {int(d1['count']):>6} {len(df):>7}")

    if not results:
        return
    print("-" * 75)
    avg_t = np.mean([r[3] for r in results])
    avg_rho = np.mean([r[4] for r in results])
    print(f"{'AVERAGE':<8} {' ':>10} {' ':>10} {avg_t:>+8.2f} {avg_rho:>+9.3f}")
    print()
    print("PASS criterion: avg t-stat < -2 AND avg Spearman < -0.5")
    if avg_t < -2 and avg_rho < -0.5:
        print("Result: PASS -- H4 MR has signal, proceed to build")
    elif avg_t < -1 and avg_rho < -0.3:
        print("Result: WEAK -- consider building but expect modest results")
    else:
        print("Result: FAIL -- skip H4 MR, try a different second alpha")


if __name__ == "__main__":
    main()
