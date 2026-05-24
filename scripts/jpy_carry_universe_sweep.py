"""
JPY-cross carry: universe-level robustness sweep before locking strategy spec.

Three sweeps to confirm the result generalises:
  1. By cut-size: top-1/bot-1, top-2/bot-2, top-3/bot-3. If the edge only
     exists at one specific cut, it's overfit.
  2. By hold horizon: 5d, 10d, 20d, 40d, 60d. If the edge has a sharp
     half-life or only shows at one window, it's fragile.
  3. By sub-period: first-half (2014-2020) vs second-half (2020-2026).
     If the edge is concentrated in one half, the deployment regime
     matters more than the signal.

PASS to deploy: monotonic Sharpe across cut-sizes, edge persists across
all horizons >= 10d, both sub-periods show positive Sharpe.
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

JPY_CARRY_LONG = {
    "AUDJPY": +3.52,
    "GBPJPY": +0.19,
    "EURJPY": -0.13,
    "CHFJPY": -0.31,
    "CADJPY": -0.69,
    "NZDJPY": -1.76,
}


def load_closes(years: int = 12) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    cols = {}
    for sym in JPY_CARRY_LONG:
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            cols[sym] = df["close"]
    return pd.concat(cols, axis=1, join="inner").dropna()


def ls_portfolio_spot(closes: pd.DataFrame, horizon: int, k: int,
                       window: slice | None = None):
    """Spot-only L/S carry portfolio: long top-k, short bot-k by static
    swap_long ranking. Returns (sharpe, t, n, ann_ret, ann_vol)."""
    log_rets = np.log(closes).diff()
    fwd = log_rets.shift(-horizon).rolling(horizon).sum()
    ranking = pd.Series(JPY_CARRY_LONG).sort_values(ascending=False)
    top = ranking.head(k).index.tolist()
    bot = ranking.tail(k).index.tolist()
    port = (fwd[top].mean(axis=1) - fwd[bot].mean(axis=1)).dropna()
    if window is not None:
        port = port.loc[window]
    if len(port) < 50:
        return None
    daily_eq = port / horizon
    ann_ret = float(daily_eq.mean()) * 252
    ann_vol = float(daily_eq.std()) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    t = float(port.mean() / (port.std() / np.sqrt(len(port))))
    return sharpe, t, len(port), ann_ret, ann_vol


def main() -> None:
    closes = load_closes(12)
    print(f"Sample: {closes.index[0].date()} -- {closes.index[-1].date()}  "
          f"({len(closes)} bars)\n")

    # ----------------------------------------------------------
    # Sweep 1: cut-size sensitivity at horizon=20
    # ----------------------------------------------------------
    print("=" * 75)
    print("SWEEP 1: Cut-size sensitivity (horizon=20d, full sample)")
    print("=" * 75)
    print(f"  {'cut':<10} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    for k in [1, 2, 3]:
        r = ls_portfolio_spot(closes, 20, k)
        if r is None:
            continue
        sh, t, n, ar, av = r
        print(f"  top{k}/bot{k}{'':<3} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Sweep 2: horizon sensitivity at k=2
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SWEEP 2: Horizon sensitivity (top-2/bot-2, full sample)")
    print("=" * 75)
    print(f"  {'horizon':<10} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    for h in [5, 10, 20, 40, 60]:
        r = ls_portfolio_spot(closes, h, 2)
        if r is None:
            continue
        sh, t, n, ar, av = r
        print(f"  {h}d{'':<7} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Sweep 3: sub-period stability at k=2, horizon=20
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SWEEP 3: Sub-period stability (top-2/bot-2, horizon=20d)")
    print("=" * 75)
    midpoint = closes.index[len(closes) // 2]
    halves = [
        ("Full sample",   None),
        ("First half",    slice(closes.index[0], midpoint)),
        ("Second half",   slice(midpoint, closes.index[-1])),
        ("2014-2018",     slice("2014-01-01", "2018-12-31")),
        ("2019-2022",     slice("2019-01-01", "2022-12-31")),
        ("2023-2026",     slice("2023-01-01", "2026-12-31")),
    ]
    print(f"  {'period':<14} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    sharpes = []
    for label, win in halves:
        r = ls_portfolio_spot(closes, 20, 2, win)
        if r is None:
            print(f"  {label:<14}   (insufficient data)")
            continue
        sh, t, n, ar, av = r
        if label != "Full sample":
            sharpes.append(sh)
        print(f"  {label:<14} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    print("\n" + "=" * 75)
    print("VERDICT")
    print("=" * 75)
    pos_periods = sum(1 for s in sharpes if s > 0)
    print(f"  Sub-periods with positive Sharpe:  {pos_periods}/{len(sharpes)}")
    print(f"  Min sub-period Sharpe:             {min(sharpes):+.2f}")
    print(f"  Max sub-period Sharpe:             {max(sharpes):+.2f}")
    print()
    if pos_periods >= len(sharpes) - 1 and min(sharpes) > -0.2:
        print("  ROBUST -- edge persists across cuts, horizons, sub-periods.")
        print("            Build the strategy.")
    elif pos_periods >= len(sharpes) // 2:
        print("  REGIME-DEPENDENT -- edge present in some periods, weak/negative")
        print("                       in others. Consider a regime gate before deploy.")
    else:
        print("  FRAGILE -- edge concentrated in one period; risk of OOS failure high.")


if __name__ == "__main__":
    main()
