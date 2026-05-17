"""
Cointegration screen across all index pairs.

For each pair of indices in the universe:
  1. Fit a linear regression log(P_a) = beta * log(P_b) + epsilon on D1 close.
  2. Run ADF test on the residual (spread). p < 0.05 -> stationary spread,
     i.e. the two series are cointegrated.
  3. Report the half-life of mean reversion (Ornstein-Uhlenbeck fit).

If any pair is cointegrated with a half-life of 5-30 D1 bars, it's a
candidate for pairs trading (long-short, market-neutral, structurally
uncorrelated with long-only equity beta).

Output: a sorted table; we build the strategy on the best-cointegrated pair.

Usage:
    uv run python scripts/pairs_cointegration_test.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408


def _ou_half_life(spread: pd.Series) -> float:
    """Estimate the half-life of mean reversion via OU regression:
       delta_spread = -lambda * spread + epsilon.
    Half-life = ln(2) / lambda. Returns inf if not mean-reverting."""
    spread = spread.dropna()
    if len(spread) < 10:
        return float("inf")
    lagged = spread.shift(1).dropna()
    delta = (spread - spread.shift(1)).dropna()
    aligned = pd.concat([delta, lagged], axis=1).dropna()
    if aligned.empty:
        return float("inf")
    y = aligned.iloc[:, 0].values
    x = aligned.iloc[:, 1].values
    # delta = -lambda * x  =>  lambda = -slope of (delta on x)
    cov = np.cov(x, y)
    var_x = cov[0, 0]
    if var_x <= 0:
        return float("inf")
    slope = cov[0, 1] / var_x
    lam = -slope
    if lam <= 0:
        return float("inf")
    return float(np.log(2.0) / lam)


def main() -> None:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * 12)

    symbols = ["US500", "USTEC", "US30", "DE40"]
    prices: dict[str, pd.Series] = {}
    for s in symbols:
        df = cache.read(s, D1, start, end)
        if df is None or df.empty:
            print(f"{s}: no D1 data, skipping")
            continue
        prices[s] = np.log(df["close"])

    print(f"\nCointegration screen on {list(prices.keys())} (log prices, D1, 12y)")
    print(f"{'pair':<15} {'beta':>7} {'ADF stat':>9} {'p-value':>9} "
          f"{'half-life':>10} {'n_bars':>7}  verdict")
    print("-" * 80)

    results = []
    for a, b in combinations(prices.keys(), 2):
        # Align and slice to common dates
        df = pd.concat([prices[a], prices[b]], axis=1, join="inner").dropna()
        df.columns = ["a", "b"]
        if len(df) < 200:
            continue
        # OLS: log(a) = beta * log(b) + intercept
        beta, alpha = np.polyfit(df["b"], df["a"], 1)
        spread = df["a"] - (alpha + beta * df["b"])
        adf = adfuller(spread, autolag="AIC")
        adf_stat, p_value = adf[0], adf[1]
        half_life = _ou_half_life(spread)
        verdict = "COINTEGRATED" if p_value < 0.05 else ("borderline" if p_value < 0.10 else "—")
        if 5.0 <= half_life <= 30.0 and p_value < 0.05:
            verdict += "  CANDIDATE"
        print(f"{a:<6}-{b:<8} {beta:>+6.3f} {adf_stat:>+9.3f} {p_value:>9.4f} "
              f"{half_life:>10.2f} {len(df):>7}  {verdict}")
        results.append({
            "pair": f"{a}-{b}", "beta": beta, "adf_stat": adf_stat,
            "p_value": p_value, "half_life": half_life, "n": len(df),
        })

    # Sort by p-value (lowest = most cointegrated)
    results.sort(key=lambda r: r["p_value"])
    if results:
        print(f"\nBest pair: {results[0]['pair']} "
              f"(p={results[0]['p_value']:.4f}, half-life={results[0]['half_life']:.1f} bars)")


if __name__ == "__main__":
    main()
