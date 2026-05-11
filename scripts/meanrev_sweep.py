"""
Parameter sweep for the index mean-reversion (long-only) strategy.

Sweeps the core knobs (formation_bars, entry_z, max_hold_bars, atr_stop_mult,
atr_tp_mult) and the regime-filter toggle, reports a sorted Sharpe table,
stability stats, and per-cell trade counts. Calibration sanity check before
committing to a deployment configuration.

Designed to be cheap -- the slowest part is build_features() per cell, which
takes a few hundred milliseconds.

Usage:
    uv run python scripts/meanrev_sweep.py
    uv run python scripts/meanrev_sweep.py --quick     # smaller grid
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408


@dataclass
class Cell:
    formation: int
    entry_z: float
    max_hold: int
    atr_stop: float
    atr_tp: float
    trend_filter: bool
    n_trades: int
    win_rate: float
    sharpe: float
    max_dd: float
    profit_factor: float
    total_return: float
    ftmo_pass: bool


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mean-reversion parameter sweep")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--out-dir", default="reports/index_meanrev")
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


def run_one(data, formation: int, entry_z: float, max_hold: int,
            atr_stop: float, atr_tp: float, trend_filter: bool,
            capital: float) -> Cell:
    import numpy as np
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    from scripts.run_meanrev_backtest import INDEX_SPECS

    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=formation,
        z_lookback_bars=252,
        entry_z_threshold=entry_z,
        exit_z_threshold=0.5,
        max_hold_bars=max_hold,
        atr_stop_mult=atr_stop,
        atr_tp_mult=atr_tp,
        require_long_term_uptrend=trend_filter,
    )
    specs = {s: INDEX_SPECS[s] for s in data}
    engine = MeanRevEngine(specs, per_trade_risk_pct=0.005)
    res = engine.run(data, config, initial_capital=capital)

    eq = res.equity_curve
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min())
    total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    wins = [t.net_pnl for t in res.trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in res.trades if t.net_pnl < 0]
    win_rate = len(wins) / len(res.trades) if res.trades else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses else 0.0
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital, opening_balance=capital,
    )
    rep = sim.run(res.equity_curve, equity_low=res.equity_low)
    return Cell(
        formation=formation, entry_z=entry_z, max_hold=max_hold,
        atr_stop=atr_stop, atr_tp=atr_tp, trend_filter=trend_filter,
        n_trades=len(res.trades), win_rate=win_rate,
        sharpe=sharpe, max_dd=max_dd, profit_factor=pf,
        total_return=total_ret, ftmo_pass=rep.passed,
    )


def print_table(results: list[Cell], title: str) -> None:
    print(f"\n{'=' * 110}")
    print(f"  {title}")
    print(f"{'=' * 110}")
    print(f"  {'form':>4}  {'entryZ':>6}  {'hold':>4}  {'stp':>4}  {'tp':>4}  "
          f"{'trend':>5}  {'trd':>4}  {'win%':>5}  "
          f"{'Sharpe':>7}  {'MaxDD':>7}  {'PF':>5}  {'Ret':>7}  {'FTMO':>4}")
    print(f"  {'-' * 105}")
    for r in results:
        print(f"  {r.formation:>4}  {r.entry_z:>6.2f}  {r.max_hold:>4}  "
              f"{r.atr_stop:>4.1f}  {r.atr_tp:>4.1f}  "
              f"{('on' if r.trend_filter else 'off'):>5}  "
              f"{r.n_trades:>4}  {100*r.win_rate:>4.1f}%  "
              f"{r.sharpe:>+7.2f}  {100*r.max_dd:>+6.1f}%  "
              f"{r.profit_factor:>5.2f}  {100*r.total_return:>+6.1f}%  "
              f"{'PASS' if r.ftmo_pass else 'FAIL':>4}")


def main() -> None:
    args = parse_args()
    print(f"Loading {args.years}y D1 data...")
    data = load_data(args.years)
    if not data:
        print("No data cached. Run scripts/fetch_backtest_data.py first.")
        sys.exit(1)
    print(f"  {len(data)} symbols loaded")

    if args.quick:
        grid = {
            "formation":     [5, 10, 20],
            "entry_z":       [1.0, 1.5, 2.0],
            "max_hold":      [10],
            "atr_stop":      [1.5],
            "atr_tp":        [2.0],
            "trend_filter":  [True, False],
        }
    else:
        grid = {
            "formation":     [5, 10, 20],
            "entry_z":       [1.0, 1.5, 2.0],
            "max_hold":      [5, 10, 15],
            "atr_stop":      [1.0, 1.5, 2.0],
            "atr_tp":        [1.5, 2.0, 3.0],
            "trend_filter":  [True, False],
        }

    import itertools
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"\nSweeping {len(combos)} cells...")

    results: list[Cell] = []
    import numpy as np
    for i, combo in enumerate(combos):
        kwargs = dict(zip(keys, combo))
        cell = run_one(data, capital=args.capital, **kwargs)
        results.append(cell)
        if (i + 1) % max(1, len(combos) // 20) == 0 or (i + 1) == len(combos):
            print(f"  {i+1}/{len(combos)}  Sharpe={cell.sharpe:+.2f} "
                  f"trades={cell.n_trades} "
                  f"f={cell.formation} z={cell.entry_z} h={cell.max_hold} "
                  f"s={cell.atr_stop} t={cell.atr_tp} "
                  f"trend={'on' if cell.trend_filter else 'off'}")

    # Sort and trim for printing
    results.sort(key=lambda c: -c.sharpe)
    print_table(results[:20], "TOP 20 CELLS BY SHARPE")
    print_table(results[-10:], "BOTTOM 10 CELLS BY SHARPE")

    sharpes = [c.sharpe for c in results]
    print(f"\n  Stability across {len(results)} cells:")
    print(f"    Sharpe mean={np.mean(sharpes):+.2f}  "
          f"std={np.std(sharpes):.2f}  "
          f"min={min(sharpes):+.2f}  max={max(sharpes):+.2f}")
    pos = sum(1 for s in sharpes if s > 0)
    print(f"    {pos}/{len(results)} cells positive Sharpe "
          f"({100*pos/len(results):.0f}%)")
    pass_count = sum(1 for c in results if c.ftmo_pass)
    print(f"    {pass_count}/{len(results)} cells PASS FTMO sim")

    # Save CSV
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sweep.csv"
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("formation,entry_z,max_hold,atr_stop,atr_tp,trend_filter,"
                 "n_trades,win_rate,sharpe,max_dd,profit_factor,"
                 "total_return,ftmo_pass\n")
        for r in results:
            fh.write(f"{r.formation},{r.entry_z},{r.max_hold},"
                     f"{r.atr_stop},{r.atr_tp},{int(r.trend_filter)},"
                     f"{r.n_trades},{r.win_rate:.4f},{r.sharpe:.4f},"
                     f"{r.max_dd:.4f},{r.profit_factor:.4f},"
                     f"{r.total_return:.4f},{int(r.ftmo_pass)}\n")
    print(f"\n  Sweep CSV: {csv_path}")


if __name__ == "__main__":
    main()
