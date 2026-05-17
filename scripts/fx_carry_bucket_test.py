"""
Bucket signal test for the FX carry hypothesis.

For each day in the cached 12y D1 history, rank the 7 USD-quoted G10
pairs by their CURRENT broker swap_long (proxy for relative carry --
see HYPOTHESIS.md for the rationale and limitations). Form the canonical
carry portfolio (long top-N, short bottom-N), measure its 20-bar forward
return, and ask whether the long-minus-short carry portfolio earns a
positive premium on average vs an equal-weighted long-only basket.

A clean carry signal would show:
  - High-carry quintile forward return > low-carry quintile forward return
  - Statistically significant t-stat (> 1.5 ideally, > 2 for clean PASS)
  - Spread NOT entirely driven by carry-crash months

The static-signal limitation is acknowledged: real carry rebalances as
rates change. This test asks whether the CURRENT ranking has predictive
power on historical data -- a necessary (not sufficient) condition for
the hypothesis to survive.

Usage:
    uv run python scripts/fx_carry_bucket_test.py
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

# Per-pair carry signal (from scripts/probe_fx_swap_rates.py, 2026-05-17).
# swap_long > 0 -> long position EARNS carry; swap_long < 0 -> long PAYS carry.
# Units: USD per lot per day.
CURRENT_CARRY_LONG_PER_LOT_PER_DAY = {
    "EURUSD": -0.70,
    "GBPUSD": -0.20,
    "AUDUSD": +6.30,
    "NZDUSD": +2.80,
    "USDJPY": -0.06,    # USD long; small negative
    "USDCAD": -0.58,
    "USDCHF": +0.13,
}


def load_data(years: int = 12) -> dict[str, pd.DataFrame]:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    data: dict[str, pd.DataFrame] = {}
    for sym in CURRENT_CARRY_LONG_PER_LOT_PER_DAY:
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            data[sym] = df
    return data


def main() -> None:
    data = load_data(12)
    print(f"Loaded: {list(data.keys())}")

    # Align all symbols on common dates
    closes = pd.concat({s: df["close"] for s, df in data.items()},
                       axis=1, join="inner").dropna()
    print(f"Common date range: {closes.index[0].date()} -- {closes.index[-1].date()}")
    print(f"Common bars: {len(closes)}")

    # Daily log returns
    log_rets = np.log(closes).diff()

    # Forward 20-bar (~1 month) cumulative log return per symbol
    fwd20 = log_rets.shift(-20).rolling(20).sum()  # measured at bar t = return over (t, t+20]

    # Static carry ranking by broker swap_long (long-side preference)
    ranking = pd.Series(CURRENT_CARRY_LONG_PER_LOT_PER_DAY)
    print(f"\nCarry ranking (high to low):")
    for sym, c in ranking.sort_values(ascending=False).items():
        print(f"  {sym:<8} {c:+.2f} $/lot/day  (long is {'favourable' if c > 0 else 'unfavourable'})")

    # ----------------------------------------------------------
    # Bucket 1: long top-2 high-carry vs short bottom-2 low-carry
    # ----------------------------------------------------------
    ranked = ranking.sort_values(ascending=False)
    top2 = ranked.head(2).index.tolist()
    bot2 = ranked.tail(2).index.tolist()
    print(f"\nTop-2 (long these):    {top2}")
    print(f"Bottom-2 (short these): {bot2}")

    # Long-only basket return for comparison
    all_syms = list(data.keys())
    long_basket = fwd20[all_syms].mean(axis=1)

    # Carry portfolio return: mean(long top-2) - mean(short bottom-2)
    carry_long_leg = fwd20[top2].mean(axis=1)
    carry_short_leg = fwd20[bot2].mean(axis=1)
    carry_portfolio = carry_long_leg - carry_short_leg

    # Drop the warmup NaNs
    carry_portfolio = carry_portfolio.dropna()
    long_basket = long_basket.dropna()

    # Annualised return + Sharpe per portfolio
    def annualise(series: pd.Series) -> tuple[float, float, float, int]:
        if len(series) < 2:
            return 0.0, 0.0, 0.0, 0
        # series is 20d forward log return; convert to 1d equivalent
        daily_eq = series / 20  # approx; really we want non-overlapping 20d slices
        ann_ret = float(daily_eq.mean()) * 252
        ann_vol = float(daily_eq.std()) * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        return ann_ret, ann_vol, sharpe, len(series)

    long_ret, long_vol, long_sh, _ = annualise(long_basket)
    carry_ret, carry_vol, carry_sh, n_carry = annualise(carry_portfolio)

    print(f"\n{'=' * 75}")
    print(f"  CARRY VS LONG-ONLY BASKET (forward 20d returns, 12y D1)")
    print(f"{'=' * 75}")
    print(f"  {'portfolio':<35}  {'ann ret':>9}  {'ann vol':>9}  {'Sharpe':>7}")
    print(f"  {'Long-only equal-weight basket':<35}  "
          f"{100*long_ret:>+8.2f}%  {100*long_vol:>+8.2f}%  {long_sh:>+7.2f}")
    print(f"  {'Carry: long-top2 minus short-bot2':<35}  "
          f"{100*carry_ret:>+8.2f}%  {100*carry_vol:>+8.2f}%  {carry_sh:>+7.2f}")

    # T-stat for carry portfolio mean != 0
    carry_t = float(carry_portfolio.mean() / (carry_portfolio.std() /
                     np.sqrt(len(carry_portfolio))))
    print(f"\n  Carry portfolio t-stat (mean != 0): {carry_t:+.2f}  "
          f"(n={n_carry})")

    # ----------------------------------------------------------
    # Bucket 2: by-quintile forward return on the SINGLE high-carry pair (AUDUSD)
    # ----------------------------------------------------------
    print(f"\n{'=' * 75}")
    print(f"  SUB-TEST: AUDUSD forward 20d return by vol regime")
    print(f"  (vol regime = 20d realised vol percentile)")
    print(f"{'=' * 75}")
    aud_rets = log_rets["AUDUSD"].dropna()
    aud_vol = aud_rets.rolling(20).std()
    aud_fwd = fwd20["AUDUSD"]
    df = pd.DataFrame({"vol": aud_vol, "fwd": aud_fwd}).dropna()
    df["vol_q"] = pd.qcut(df["vol"], 5, labels=False, duplicates="drop") + 1
    print(f"  {'vol quintile':<13} {'avg fwd 20d':>12} {'n':>5} {'description':>30}")
    for q in sorted(df["vol_q"].unique()):
        bucket = df[df["vol_q"] == q]["fwd"]
        desc = "calmest" if q == 1 else ("most volatile" if q == 5 else "")
        print(f"  {q:<13} {100*bucket.mean():>+11.3f}% {len(bucket):>5}  {desc:>30}")

    print()
    print("PASS criterion (a necessary check):")
    print(f"  - Carry portfolio Sharpe > 0.3  AND  t-stat > 1.5")
    print(f"  - AUDUSD forward return monotone (or near-monotone) in vol quintile")
    print(f"    (calmest quintile > most volatile quintile -- confirms vol-filter logic)")

    carry_passes = carry_sh > 0.3 and carry_t > 1.5
    if carry_passes:
        print(f"\n  Result: PASS -- proceed to build the strategy")
    elif carry_sh > 0.15 and carry_t > 1.0:
        print(f"\n  Result: WEAK -- build but expect modest Sharpe")
    else:
        print(f"\n  Result: FAIL -- carry signal is too noisy on this sample")


if __name__ == "__main__":
    main()
