"""
Spread-sensitivity stress test for the index mean-reversion strategy.

Re-runs the best-known config under successively wider spread assumptions to
find the break-even spread -- the point at which the strategy's edge is
swallowed by transaction costs.

This protects against the optimistic demo-broker quote (0-spread reported,
unrealistic) and the unknown spread regime on a live FTMO account. If the
strategy is profitable only at our backtest's conservative 50-100pt baseline
and collapses at 2x or 3x of that, deployment is risky.

Method:
  - Run full-period + walk-forward at the production config.
  - Scale avg_spread_points by each multiplier in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0].
  - Report Sharpe, return, max DD, FTMO pass, and trade count per scenario.

Usage:
    uv run python scripts/meanrev_spread_stress.py
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408
DEFAULT_MULTS = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]


@dataclass
class StressResult:
    mult: float
    full_sharpe: float
    full_return: float
    full_max_dd: float
    full_trades: int
    full_win_rate: float
    full_pf: float
    full_ftmo_pass: bool
    oos_avg_sharpe: float
    oos_min_sharpe: float
    oos_max_sharpe: float
    is_oos_degr: float
    n_oos_windows: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spread stress test")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--formation", type=int, default=20)
    p.add_argument("--entry-z", type=float, default=1.0)
    p.add_argument("--is-months", type=int, default=36)
    p.add_argument("--oos-months", type=int, default=12)
    p.add_argument("--mults", nargs="+", type=float, default=DEFAULT_MULTS)
    return p.parse_args()


def load_data(years: int):
    import pandas as pd
    from data.cache import ParquetCache
    from scripts.run_meanrev_backtest import INDEX_SPECS

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    data: dict[str, pd.DataFrame] = {}
    for sym in INDEX_SPECS:
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            data[sym] = df
    return data


def run_one(data, mult: float, args) -> StressResult:
    import numpy as np
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine, meanrev_walk_forward
    from backtest.costs import DEFAULT_COST_MODEL
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    from scripts.run_meanrev_backtest import INDEX_SPECS

    # Scale spreads by `mult`
    scaled_specs = {
        sym: replace(spec, avg_spread_points=spec.avg_spread_points * mult)
        for sym, spec in INDEX_SPECS.items()
        if sym in data
    }

    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=args.formation,
        z_lookback_bars=252,
        entry_z_threshold=args.entry_z,
        exit_z_threshold=0.5,
        max_hold_bars=10,
        atr_stop_mult=1.5,
        atr_tp_mult=2.0,
        require_long_term_uptrend=True,
    )

    engine = MeanRevEngine(scaled_specs, DEFAULT_COST_MODEL, per_trade_risk_pct=0.005)
    full = engine.run(data, config, initial_capital=args.capital)

    eq = full.equity_curve
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min())
    total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    wins = [t.net_pnl for t in full.trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in full.trades if t.net_pnl < 0]
    win_rate = len(wins) / len(full.trades) if full.trades else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses else 0.0

    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=args.capital, opening_balance=args.capital,
    )
    full_ftmo = sim.run(full.equity_curve, equity_low=full.equity_low)

    # Walk-forward
    wf = meanrev_walk_forward(
        data, config, scaled_specs,
        per_trade_risk_pct=0.005,
        is_months=args.is_months,
        oos_months=args.oos_months,
        initial_capital=args.capital,
    )
    oos_sharpes = []
    for w in wf:
        r = w.oos_result.equity_curve.pct_change().dropna()
        s = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
        oos_sharpes.append(s)

    return StressResult(
        mult=mult,
        full_sharpe=sharpe,
        full_return=total_ret,
        full_max_dd=max_dd,
        full_trades=len(full.trades),
        full_win_rate=win_rate,
        full_pf=pf,
        full_ftmo_pass=full_ftmo.passed,
        oos_avg_sharpe=float(np.mean(oos_sharpes)) if oos_sharpes else 0.0,
        oos_min_sharpe=float(min(oos_sharpes)) if oos_sharpes else 0.0,
        oos_max_sharpe=float(max(oos_sharpes)) if oos_sharpes else 0.0,
        is_oos_degr=sharpe - float(np.mean(oos_sharpes)) if oos_sharpes else 0.0,
        n_oos_windows=len(wf),
    )


def main() -> None:
    args = parse_args()
    from scripts.run_meanrev_backtest import INDEX_SPECS

    print(f"Spread stress test: formation={args.formation} entry_z={args.entry_z}")
    print(f"  Baseline spreads (avg points): "
          f"{ {s: int(spec.avg_spread_points) for s, spec in INDEX_SPECS.items()} }")
    data = load_data(args.years)
    if not data:
        print("No cached data. Run fetch_backtest_data.py first.")
        sys.exit(1)
    print(f"  {len(data)} symbols loaded")

    results: list[StressResult] = []
    for mult in args.mults:
        print(f"\n  mult={mult}x ... ", end="", flush=True)
        r = run_one(data, mult, args)
        results.append(r)
        ftmo = "PASS" if r.full_ftmo_pass else "FAIL"
        print(f"IS Sharpe={r.full_sharpe:+.2f}  "
              f"OOS avg={r.oos_avg_sharpe:+.2f}  "
              f"PF={r.full_pf:.2f}  "
              f"trades={r.full_trades}  FTMO={ftmo}")

    print(f"\n{'=' * 110}")
    print(f"  SPREAD SENSITIVITY -- formation={args.formation}, entry_z={args.entry_z}")
    print(f"{'=' * 110}")
    print(f"  {'mult':>5}  {'IS Sh':>6}  {'OOS avg':>7}  {'OOS min':>7}  "
          f"{'IS->OOS':>8}  {'Ret':>7}  {'MaxDD':>7}  {'PF':>5}  "
          f"{'win%':>5}  {'trd':>4}  {'FTMO':>4}")
    print(f"  {'-' * 100}")
    for r in results:
        print(f"  {r.mult:>4.1f}x  {r.full_sharpe:>+6.2f}  "
              f"{r.oos_avg_sharpe:>+7.2f}  {r.oos_min_sharpe:>+7.2f}  "
              f"{r.is_oos_degr:>+8.2f}  "
              f"{100*r.full_return:>+6.1f}%  {100*r.full_max_dd:>+6.1f}%  "
              f"{r.full_pf:>5.2f}  {100*r.full_win_rate:>4.1f}%  "
              f"{r.full_trades:>4}  "
              f"{'PASS' if r.full_ftmo_pass else 'FAIL':>4}")

    # Break-even spread (last mult where OOS avg Sharpe stays positive)
    survivors = [r for r in results if r.oos_avg_sharpe > 0]
    if survivors:
        worst_ok = max(survivors, key=lambda r: r.mult)
        print(f"\n  Break-even: OOS Sharpe stays positive up to {worst_ok.mult}x baseline spread")
        print(f"  Baseline US500 spread = 50 pts -> break-even = "
              f"{int(50 * worst_ok.mult)} pts")
    else:
        print(f"\n  Strategy fails at every multiplier tested -- spread is the dominant risk")


if __name__ == "__main__":
    main()
