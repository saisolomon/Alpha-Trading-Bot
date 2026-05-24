"""
Exotic-FX carry: universe-level sweep mirroring jpy_carry_universe_sweep.py.

The hypothesis: USD-vs-emerging FX rate differentials (Banxico, SARB,
TCMB) are structurally larger than USD-vs-G10 differentials. The probe
(scripts/probe_exotic_swap_rates.py, 2026-05-19) confirms:

  USDMXN long carry: +24.87 $/lot/day  (vs AUDJPY +3.52 -- 7x larger!)
  USDZAR short carry: +5.60 $/lot/day
  USDTRY: zero (broker suspends -- skip)
  USDSEK: noise
  USDNOK short carry: +1.67 $/lot/day

Question: does ranking the universe by current carry and going L/S
top-N/bot-N earn a positive spot return on 12y D1 history? Same three
robustness sweeps as the JPY-cross test: cut-size, horizon, sub-period.

PASS to deploy: positive Sharpe at multiple cut-sizes AND positive in
2+ of 3 sub-periods (carry premium robust to regime changes).
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

# From scripts/probe_exotic_swap_rates.py (2026-05-19). Units: USD/lot/day.
# swap_long > 0 -> LONG position earns; swap_short > 0 -> SHORT position
# earns. We use the better of the two for ranking (the strategy will
# go long if swap_long is best, short if swap_short is best).
EXOTIC_CARRY = {
    # symbol -> (swap_long, swap_short)
    "USDMXN": (+24.87, +11.49),   # MEX rates >> US rates: long earns
    "USDZAR": (-11.55,  +5.60),   # SAF rates > US rates: short earns
    "USDTRY": (  0.00,   0.00),   # TRY swap suspended -- skip
    "USDSEK": ( -0.48,  -0.52),   # near zero
    "USDNOK": ( -5.38,  +1.67),   # NOR rates >= US rates: short earns
}

# Derived "best carry side" per symbol (the side that earns).
def carry_side_and_yield(swaps: tuple[float, float]) -> tuple[int, float]:
    """Returns (+1 if long earns more, -1 if short earns more, carry_value)."""
    sl, ss = swaps
    if sl >= ss:
        return +1, sl
    return -1, ss


def load_closes(years: int = 12) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    cols = {}
    for sym in EXOTIC_CARRY:
        if sym == "USDTRY":  # skip -- TRY swap zeroed; data quality dubious
            continue
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            cols[sym] = df["close"]
    return pd.concat(cols, axis=1, join="inner").dropna()


def ls_portfolio_spot(closes: pd.DataFrame, horizon: int, k: int,
                       window: slice | None = None):
    """L/S carry portfolio using side-aware ranking. For each symbol,
    the leg sign = +1 if long earns more carry, -1 if short does. We
    then go long top-k by absolute carry-earning value, short bot-k."""
    log_rets = np.log(closes).diff()
    fwd = log_rets.shift(-horizon).rolling(horizon).sum()

    # Score: signed carry yield (positive means the side earns)
    sides = {sym: carry_side_and_yield(EXOTIC_CARRY[sym])
             for sym in closes.columns}
    scores = pd.Series({sym: side * abs(score)
                         for sym, (side, score) in sides.items()})
    ranked = scores.sort_values(ascending=False)

    if k > len(ranked) // 2:
        return None

    top = ranked.head(k).index.tolist()
    bot = ranked.tail(k).index.tolist()

    # For TOP: if side is +1 we earn LONG; signed return = +fwd. If side
    # is -1 (we'd want short for carry), signed return = -fwd.
    def signed_return(sym: str) -> pd.Series:
        side = sides[sym][0]
        return side * fwd[sym]

    top_rets = pd.concat([signed_return(s) for s in top], axis=1).mean(axis=1)
    # For BOT: these are the WORST carry-side; we go OPPOSITE of their
    # carry side. So if a pair's best carry side is +1 (long), but it
    # sits in BOT (low carry), we go short. signed_return = -side * fwd.
    def opposed_return(sym: str) -> pd.Series:
        side = sides[sym][0]
        return -side * fwd[sym]

    bot_rets = pd.concat([opposed_return(s) for s in bot], axis=1).mean(axis=1)

    port = (top_rets + bot_rets).dropna() / 2.0  # equal-weight L+S basket
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


def single_pair(closes: pd.DataFrame, horizon: int, sym: str, side: int,
                window: slice | None = None):
    """Single-pair signed forward return (spot only)."""
    log_rets = np.log(closes[sym]).diff()
    fwd = log_rets.shift(-horizon).rolling(horizon).sum() * side
    fwd = fwd.dropna()
    if window is not None:
        fwd = fwd.loc[window]
    if len(fwd) < 50:
        return None
    daily_eq = fwd / horizon
    ann_ret = float(daily_eq.mean()) * 252
    ann_vol = float(daily_eq.std()) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    t = float(fwd.mean() / (fwd.std() / np.sqrt(len(fwd))))
    return sharpe, t, len(fwd), ann_ret, ann_vol


def main() -> None:
    closes = load_closes(12)
    print(f"Sample: {closes.index[0].date()} -- {closes.index[-1].date()}  "
          f"({len(closes)} bars)")
    print(f"Universe: {list(closes.columns)}\n")

    # Carry-side breakdown
    print("Carry-side ranking (current broker swap):")
    for sym in closes.columns:
        side, val = carry_side_and_yield(EXOTIC_CARRY[sym])
        side_label = "LONG"  if side > 0 else "SHORT"
        print(f"  {sym:<8} best side: {side_label:<5} earning {val:+6.2f} $/lot/day")
    print()

    # ----------------------------------------------------------
    # Single-pair test: USDMXN long (the standout)
    # ----------------------------------------------------------
    print("=" * 75)
    print("SINGLE-PAIR: USDMXN long (spot only; ignores carry income)")
    print("=" * 75)
    print(f"  {'period':<14} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    halves = [
        ("Full sample",   None),
        ("2014-2018",     slice("2014-01-01", "2018-12-31")),
        ("2019-2022",     slice("2019-01-01", "2022-12-31")),
        ("2023-2026",     slice("2023-01-01", "2026-12-31")),
    ]
    for label, win in halves:
        r = single_pair(closes, 20, "USDMXN", +1, win)
        if r is None:
            print(f"  {label:<14}   (insufficient data)")
            continue
        sh, t, n, ar, av = r
        print(f"  {label:<14} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Single-pair test: USDZAR short
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SINGLE-PAIR: USDZAR short (spot only; ignores carry income)")
    print("=" * 75)
    print(f"  {'period':<14} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    for label, win in halves:
        r = single_pair(closes, 20, "USDZAR", -1, win)
        if r is None:
            continue
        sh, t, n, ar, av = r
        print(f"  {label:<14} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Sweep: cut-size sensitivity
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SWEEP 1: Cut-size sensitivity (horizon=20d, full sample)")
    print("=" * 75)
    print(f"  {'cut':<10} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    for k in [1, 2]:
        r = ls_portfolio_spot(closes, 20, k)
        if r is None:
            print(f"  top{k}/bot{k}    -- insufficient k")
            continue
        sh, t, n, ar, av = r
        print(f"  top{k}/bot{k}{'':<3} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Sweep: horizon sensitivity (at top-1/bot-1)
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SWEEP 2: Horizon sensitivity (top-1/bot-1, full sample)")
    print("=" * 75)
    print(f"  {'horizon':<10} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    for h in [5, 10, 20, 40, 60]:
        r = ls_portfolio_spot(closes, h, 1)
        if r is None:
            continue
        sh, t, n, ar, av = r
        print(f"  {h}d{'':<7} {n:>6} {100*ar:>+8.2f}% {100*av:>+8.2f}% "
              f"{sh:>+7.2f} {t:>+7.2f}")

    # ----------------------------------------------------------
    # Sweep: sub-period stability (at top-1/bot-1, horizon=20)
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("SWEEP 3: Sub-period stability (top-1/bot-1, horizon=20d)")
    print("=" * 75)
    print(f"  {'period':<14} {'n':>6} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'t-stat':>7}")
    sharpes = []
    for label, win in halves:
        r = ls_portfolio_spot(closes, 20, 1, win)
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
    pos = sum(1 for s in sharpes if s > 0.3)
    print(f"  Sub-periods with Sharpe > +0.3:    {pos}/{len(sharpes)}")
    print(f"  Min sub-period Sharpe:             {min(sharpes):+.2f}")
    print(f"  Max sub-period Sharpe:             {max(sharpes):+.2f}")
    print()
    if pos >= 2 and min(sharpes) > -0.2:
        print("  ROBUST -- exotic carry edge persists. Build as 2nd carry EA.")
    elif pos >= 1 and min(sharpes) > -0.5:
        print("  REGIME-DEPENDENT -- like JPY carry, needs a regime gate.")
    else:
        print("  FRAGILE -- exotic carry too noisy. Stick with JPY only.")


if __name__ == "__main__":
    main()
