"""
Signal-decay (autocorrelation) test for the index TSMOM hypothesis.

For each index in the universe, compute the autocorrelation of daily returns
at lags {1, 5, 20, 60, 120, 250}. If the lag-20 to lag-120 autocorrelations are
positive and meaningful (>0.02 sustained), the time-series-momentum hypothesis
has empirical support and is worth backtesting. If they are zero or negative,
the hypothesis is empirically rejected before further work.

Method:
- Lag-k autocorrelation = corr(r_t, r_{t-k}) where r_t are daily log returns.
- Newey-West-style standard error approximation using lag-k variance:
  SE ~ 1/sqrt(N) for an iid null. Significance noted at +/- 2*SE.
- Optional: also report the autocorrelation of *signed cumulative returns* over
  formation windows ({20, 60, 120}d) vs forward returns ({1, 5, 20}d) -- this
  is closer to the actual TSMOM signal definition than raw lag autocorrelation.

Reference: Moskowitz, Ooi, Pedersen (2012) -- Figure 1 of their paper shows
positive 1-12 month autocorrelation, decaying to negative at 24+ months.

Usage:
    uv run python scripts/signal_decay.py
    uv run python scripts/signal_decay.py --symbols US500 USTEC US30 DE40
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
LAGS = [1, 5, 20, 60, 120, 250]
FORMATION_WINDOWS = [20, 60, 120]
HOLDING_WINDOWS = [1, 5, 20]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TSMOM signal decay test")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--years", type=int, default=5)
    return p.parse_args()


def autocorr(r, lag: int) -> float:
    """Lag-k Pearson autocorrelation of return series r."""
    if len(r) <= lag + 1:
        return float("nan")
    a = r.iloc[lag:].reset_index(drop=True)
    b = r.iloc[:-lag].reset_index(drop=True)
    return float(a.corr(b))


def formation_holding_corr(r, formation: int, holding: int) -> tuple[float, int]:
    """Correlation between past-formation cumulative return and forward-holding cumulative return.

    This is the actual TSMOM signal-effectiveness measure: does the past return predict
    the future return at the formation/holding horizons we plan to trade?
    """
    if len(r) <= formation + holding + 1:
        return float("nan"), 0
    cum_past = r.rolling(formation).sum()
    cum_fwd = r.shift(-holding).rolling(holding).sum()
    pair = cum_past.dropna().to_frame("past").join(cum_fwd.dropna().to_frame("fwd"), how="inner")
    if pair.empty:
        return float("nan"), 0
    return float(pair["past"].corr(pair["fwd"])), len(pair)


def main() -> None:
    args = parse_args()
    import numpy as np
    import pandas as pd
    from data.cache import ParquetCache

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * args.years)

    print(f"Loading {args.years}y D1 for {args.symbols}...\n")
    series: dict[str, pd.Series] = {}
    for sym in args.symbols:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            print(f"  {sym}: no cached data -- run fetch_backtest_data.py")
            continue
        series[sym] = np.log(df["close"]).diff().dropna()
        print(f"  {sym}: {len(df)} bars, "
              f"{df.index[0].date()} to {df.index[-1].date()}")

    if not series:
        sys.exit(1)

    # ------------------------------------------------------------------
    # Table 1: raw lag-k autocorrelation
    # ------------------------------------------------------------------
    print(f"\n{'=' * 75}")
    print(f"  RAW LAG-K AUTOCORRELATION OF DAILY LOG RETURNS")
    print(f"  (TSMOM expects positive, sustained values at lags 5-120)")
    print(f"{'=' * 75}")
    header = f"  {'symbol':<8}  {'N':>5}  " + "  ".join(f"{'lag '+str(L):>8}" for L in LAGS)
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for sym, r in series.items():
        n = len(r)
        se = 1.0 / np.sqrt(n)
        threshold = 2 * se
        cells = []
        for L in LAGS:
            ac = autocorr(r, L)
            if abs(ac) > threshold:
                marker = "*"
            else:
                marker = " "
            cells.append(f"{ac:+8.3f}{marker}")
        print(f"  {sym:<8}  {n:>5}  " + "  ".join(cells))
    print(f"\n  * = |autocorr| > 2*SE (significant at ~95% under iid null)")

    # ------------------------------------------------------------------
    # Table 2: formation -> holding correlation (actual signal test)
    # ------------------------------------------------------------------
    print(f"\n{'=' * 75}")
    print(f"  PAST-FORMATION vs FORWARD-HOLDING CUMULATIVE RETURN CORRELATION")
    print(f"  (this IS the TSMOM signal -- corr > 0 means signal has predictive power)")
    print(f"{'=' * 75}")
    print(f"  {'symbol':<8}  {'formation':>9}  " +
          "  ".join(f"{'fwd '+str(h)+'d':>10}" for h in HOLDING_WINDOWS))
    print(f"  {'-' * 60}")
    for sym, r in series.items():
        for fwin in FORMATION_WINDOWS:
            cells = []
            for hwin in HOLDING_WINDOWS:
                rho, n = formation_holding_corr(r, fwin, hwin)
                cells.append(f"{rho:+8.3f}({n:>4})" if n > 0 else f"{'n/a':>14}")
            label = f"  {sym:<8}  {fwin:>5}d   " + " ".join(cells)
            print(label)

    # ------------------------------------------------------------------
    # Table 3: average across the universe
    # ------------------------------------------------------------------
    print(f"\n{'=' * 75}")
    print(f"  CROSS-UNIVERSE AVERAGE (does the hypothesis hold on the portfolio?)")
    print(f"{'=' * 75}")
    print(f"  {'lag':>4}  {'avg autocorr':>13}  {'positive in N/N':>17}")
    for L in LAGS:
        accs = [autocorr(r, L) for r in series.values()]
        accs = [a for a in accs if not np.isnan(a)]
        if not accs:
            continue
        avg = float(np.mean(accs))
        pos = sum(1 for a in accs if a > 0)
        print(f"  {L:>4}  {avg:+13.3f}  {pos}/{len(accs):>9}")

    print(f"\n  HYPOTHESIS PASS CRITERION:")
    print(f"  - Lag 20-120 average autocorrelation should be positive (>0.02).")
    print(f"  - Past-formation -> forward-holding correlation should be > 0 in")
    print(f"    the (60d, 5d) and (60d, 20d) cells.")
    print(f"  If neither holds, TSMOM has no edge on this universe -- skip backtest.")


if __name__ == "__main__":
    main()
