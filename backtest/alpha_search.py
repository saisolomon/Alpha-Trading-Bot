"""Alpha gatekeeper: walk-forward OOS evaluation + White's Reality Check across a batch.

The instrument for honest alpha discovery. Any candidate strategy is judged ONLY on
out-of-sample (OOS) performance, and the BATCH is corrected for multiple testing via White's
Reality Check (Sullivan-Timmermann-White 1999) so we never crown the luckiest of many tries —
the exact discipline CLAUDE.md mandates and the trial/Tier-2 kept invoking.

Pipeline per candidate:
  generate_windows (rolling IS/OOS) -> run_walk_forward (fit on IS, evaluate on OOS) ->
  stitch the per-window OOS daily returns -> per-candidate bootstrap P(edge>0).
Across the batch:
  White's Reality Check on the aligned daily-return matrix -> multiplicity-corrected p-value
  for the BEST candidate. If even the best can't beat the bootstrapped null, nothing survives.

NOTE: fixed-parameter candidates (factory ignores IS data) are the anti-overfit default for
discovery — no parameter mining; White's RC corrects for the number of strategies tried.

Run: python backtest/alpha_search.py
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# NOTE: backtest.run_roster (imported below) reconfigures stdout to UTF-8 at import;
# we do NOT re-wrap here (double-wrapping GC-closes the buffer).

from backtest.engine import BacktestEngine
from backtest.walk_forward import generate_windows
from backtest.costs import GBPUSD_SPEC, XAUUSD_SPEC, AUDJPY_SPEC
from backtest.run_roster import load_spine
from strategies.london_momo import LondonMomoStrategy
from strategies.london_fix import LondonFixStrategy
from strategies.audjpy_trend import AudjpyTrendStrategy
from strategies.regime_gated import RegimeTrendStrategy, RegimeMeanRevStrategy

INITIAL = 200_000.0
BARS_PER_DAY = {"M15": 96, "H1": 24, "H4": 6}
IS_DAYS, OOS_DAYS = 126, 21          # 6-month IS, 1-month rolling OOS
RNG = np.random.default_rng(42)


@dataclass
class Candidate:
    label: str
    factory: object      # callable(is_df) -> Strategy (fixed-param: ignores is_df)
    symbol: str
    tf: str
    spec: object


def oos_daily_returns(cand: Candidate) -> pd.Series:
    """Stitch per-window OOS equity into one daily fractional-return series."""
    data = load_spine(cand.symbol, cand.tf)
    bpd = BARS_PER_DAY[cand.tf]
    is_bars, oos_bars = IS_DAYS * bpd, OOS_DAYS * bpd
    try:
        windows = generate_windows(data, is_bars=is_bars, oos_bars=oos_bars)
    except ValueError:
        return pd.Series(dtype=float)
    daily_chunks = []
    for w in windows:
        oos = data.loc[w.oos_start:w.oos_end]
        if len(oos) < 2:
            continue
        strat = cand.factory(data.loc[w.is_start:w.is_end])
        res = BacktestEngine(oos, cand.spec).run(strat, INITIAL, min_bars_warmup=1)
        eq = res.equity_curve
        daily = eq.resample("1D").last().dropna()
        rets = daily.pct_change().dropna()
        daily_chunks.append(rets)
    if not daily_chunks:
        return pd.Series(dtype=float)
    return pd.concat(daily_chunks).sort_index()


def boot_p_pos(rets: np.ndarray, b: int = 5000) -> float:
    if len(rets) == 0:
        return float("nan")
    means = RNG.choice(rets, size=(b, len(rets)), replace=True).mean(axis=1)
    return float((means > 0).mean())


def whites_reality_check(mat: pd.DataFrame, b: int = 2000) -> tuple[float, str]:
    """White's RC over a (T days x K candidates) daily-return matrix.
    Returns (p_value_for_best, best_label). p = P(bootstrapped max-mean >= observed best)."""
    cols = list(mat.columns)
    X = mat.values                                  # T x K, 0 on non-trading days
    T = len(X)
    means = X.mean(axis=0)
    stat = np.sqrt(T) * means                       # per-candidate scaled mean
    best_k = int(np.argmax(stat))
    V = float(stat[best_k])
    # iid row bootstrap (v1; block bootstrap is the refinement for serial dep.)
    Vstar = np.empty(b)
    for i in range(b):
        idx = RNG.integers(0, T, size=T)
        bm = X[idx].mean(axis=0) - means            # recentred under the null
        Vstar[i] = np.sqrt(T) * bm.max()
    p = float((Vstar >= V).mean())
    return p, cols[best_k]


def main():
    specs = {"GBPUSD": GBPUSD_SPEC, "XAUUSD": XAUUSD_SPEC, "AUDJPY": AUDJPY_SPEC,
             "EURUSD": __import__("backtest.costs", fromlist=["EURUSD_SPEC"]).EURUSD_SPEC}
    # EURGBP has no predefined spec; build one (5-digit cross, ~£/€ tick — sizing R is
    # tick_value-invariant so the approximation doesn't affect edge metrics).
    from backtest.costs import SymbolSpec
    specs["EURGBP"] = SymbolSpec("EURGBP", 100_000, 0.00001, 1.3, 3.5, 1.5)

    def trend(sym, tf, regime):
        return Candidate(f"RegimeTrend[{regime}] {sym} {tf}",
                         (lambda s, r: (lambda _is: RegimeTrendStrategy(spec=specs[s], regime=r, window=60)))(sym, regime),
                         sym, tf, specs[sym])

    def mr(sym, tf, regime):
        return Candidate(f"RegimeMeanRev[{regime}] {sym} {tf}",
                         (lambda s, r: (lambda _is: RegimeMeanRevStrategy(spec=specs[s], regime=r, window=60)))(sym, regime),
                         sym, tf, specs[sym])

    candidates = [
        # --- roster baseline (known dead; part of the White's-RC universe) ---
        Candidate("LondonFix (XAUUSD M15)", lambda _is: LondonFixStrategy(spec=XAUUSD_SPEC),
                  "XAUUSD", "M15", XAUUSD_SPEC),
        # --- regime-gated TREND (ADX), H1/H4 ---
        trend("XAUUSD", "H1", "adx"), trend("GBPUSD", "H1", "adx"),
        trend("EURUSD", "H1", "adx"), trend("AUDJPY", "H4", "adx"),
        # --- regime-gated MEAN-REVERSION (ADX), H1 ---
        mr("EURGBP", "H1", "adx"), mr("EURUSD", "H1", "adx"), mr("GBPUSD", "H1", "adx"),
    ]

    print(f"# Alpha gatekeeper — walk-forward OOS + White's Reality Check\n")
    print(f"IS={IS_DAYS}d / OOS={OOS_DAYS}d rolling; initial ${INITIAL:,.0f}; "
          f"calibration batch = current roster (expected: all fail OOS).\n")

    series = {}
    print("| candidate | OOS days | OOS mean/day | OOS ann.Sharpe | OOS total% | P(edge>0) |")
    print("|---|---|---|---|---|---|")
    for c in candidates:
        r = oos_daily_returns(c)
        series[c.label] = r
        if len(r) == 0:
            print(f"| {c.label} | 0 | — | — | — | — |")
            continue
        arr = r.values
        sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0.0
        total = (np.prod(1 + arr) - 1) * 100
        print(f"| {c.label} | {len(r)} | {arr.mean()*100:+.3f}% | {sharpe:+.2f} | "
              f"{total:+.1f}% | {boot_p_pos(arr)*100:.1f}% |")

    # Align into a daily matrix for White's RC
    mat = pd.concat(series, axis=1, sort=True).fillna(0.0)
    mat = mat[(mat != 0).any(axis=1)]
    if len(mat) > 10 and mat.shape[1] >= 1:
        p_rc, best = whites_reality_check(mat)
        print(f"\n## White's Reality Check (best of {mat.shape[1]} candidates, {len(mat)} OOS days)")
        print(f"- Best candidate: **{best}**")
        print(f"- Multiplicity-corrected p-value: **{p_rc:.3f}**")
        verdict = ("NOTHING survives — no candidate beats the bootstrapped null after "
                   "correcting for the number tried" if p_rc > 0.05
                   else f"{best} SURVIVES at p={p_rc:.3f} — investigate (rare for the dead roster)")
        print(f"- Verdict: **{verdict}**")
    else:
        print("\n(insufficient aligned OOS days for White's RC)")


if __name__ == "__main__":
    main()
