"""
Parameter sensitivity + ablation sweep for FX Cross-Sectional Momentum.

Sweeps formation_bars, trend_ema_bars, z_threshold, and the trend filter
on/off; reports Sharpe / MaxDD / PF / n_trades for each cell so we can
read parameter stability and the marginal value of each component.

A strategy whose Sharpe holds within ~0.3 across +/-20% parameter moves
is stable; one whose Sharpe craters is overfit (per CLAUDE.md sec.9).

Usage:
    uv run python scripts/param_sweep.py
    uv run python scripts/param_sweep.py --years 5 --timeframe D1
    uv run python scripts/param_sweep.py --quick      # smaller grid
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc

_TF_MAP: dict[str, int] = {"H1": 16385, "H4": 16388, "D1": 16408}


@dataclass
class CellResult:
    formation: int
    ema: int
    z_thresh: float
    trend_filter: bool
    n_trades: int
    win_rate: float
    sharpe: float
    max_dd: float
    profit_factor: float
    total_return: float
    ftmo_pass: bool


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FX momentum parameter sweep")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--timeframe", default="D1", choices=list(_TF_MAP.keys()))
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--quick", action="store_true", help="9-cell grid instead of 27")
    p.add_argument("--out-dir", default="reports/fx_momentum")
    return p.parse_args()


def load_data(years: int, tf: str) -> dict[str, "pd.DataFrame"]:
    import pandas as pd
    from data.cache import ParquetCache
    from scripts.run_backtest import SYMBOL_SPECS

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    tf_int = _TF_MAP[tf]
    data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOL_SPECS:
        df = cache.read(sym, tf_int, start, end)
        if df is not None and not df.empty:
            data[sym] = df
    return data


def run_one(
    data: dict,
    formation: int,
    ema: int,
    z_thresh: float,
    trend_filter: bool,
    capital: float,
) -> CellResult:
    import numpy as np
    from strategies.fx_momentum.signal import MomentumConfig
    from strategies.fx_momentum.sizing import SizingConfig
    from backtest.portfolio_engine import PortfolioEngine
    from backtest.costs import DEFAULT_COST_MODEL
    from scripts.run_backtest import SYMBOL_SPECS

    config = MomentumConfig(
        symbols=tuple(data.keys()),
        usd_base_symbols=("USDJPY", "USDCAD", "USDCHF"),
        formation_bars=formation,
        skip_bars=1,
        long_z_threshold=z_thresh,
        short_z_threshold=-z_thresh,
        max_long_positions=2,
        max_short_positions=2,
        trend_ema_bars=ema,
        require_trend_confirmation=trend_filter,
        xvol_lookback_bars=5,
        xvol_pause_threshold=2.0,
    )
    sizing = SizingConfig(per_trade_risk_pct=0.005, kelly_fraction=0.25)
    specs = {s: SYMBOL_SPECS[s] for s in data if s in SYMBOL_SPECS}
    engine = PortfolioEngine(specs, DEFAULT_COST_MODEL)
    res = engine.run(data, config, sizing, initial_capital=capital)

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

    # FTMO check
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital,
        opening_balance=capital,
    )
    ftmo_report = sim.run(res.equity_curve, equity_low=res.equity_low)

    return CellResult(
        formation=formation, ema=ema, z_thresh=z_thresh,
        trend_filter=trend_filter,
        n_trades=len(res.trades), win_rate=win_rate,
        sharpe=sharpe, max_dd=max_dd, profit_factor=pf,
        total_return=total_ret, ftmo_pass=ftmo_report.passed,
    )


def print_table(results: list[CellResult], title: str) -> None:
    print(f"\n{'=' * 95}")
    print(f"  {title}")
    print(f"{'=' * 95}")
    print(f"  {'form':>4}  {'ema':>4}  {'z':>4}  {'trend':>5}  "
          f"{'trades':>6}  {'win%':>5}  {'Sharpe':>7}  "
          f"{'MaxDD':>7}  {'PF':>5}  {'Ret':>7}  {'FTMO':>4}")
    print(f"  {'-' * 90}")
    for r in results:
        print(f"  {r.formation:>4}  {r.ema:>4}  {r.z_thresh:>4.2f}  "
              f"{('on' if r.trend_filter else 'off'):>5}  "
              f"{r.n_trades:>6}  {100*r.win_rate:>4.1f}%  {r.sharpe:>+7.2f}  "
              f"{100*r.max_dd:>+6.1f}%  {r.profit_factor:>5.2f}  "
              f"{100*r.total_return:>+6.1f}%  {'PASS' if r.ftmo_pass else 'FAIL':>4}")


def stability_summary(results: list[CellResult]) -> None:
    import numpy as np
    sharpes = [r.sharpe for r in results]
    if not sharpes:
        return
    print(f"\n  Stability: Sharpe mean={np.mean(sharpes):+.2f}  "
          f"std={np.std(sharpes):.2f}  "
          f"min={min(sharpes):+.2f}  max={max(sharpes):+.2f}  "
          f"range={max(sharpes)-min(sharpes):.2f}")
    pos = sum(1 for s in sharpes if s > 0)
    print(f"  {pos}/{len(sharpes)} cells positive Sharpe  "
          f"(target: stable param surface = small range)")


def main() -> None:
    args = parse_args()
    print(f"Loading {args.years}y of {args.timeframe} data...")
    data = load_data(args.years, args.timeframe)
    if len(data) < 3:
        print("Insufficient cached data. Run scripts/fetch_backtest_data.py first.")
        sys.exit(1)
    print(f"  {len(data)} symbols, {len(next(iter(data.values())))} bars per symbol")

    if args.quick:
        formations = [16, 20, 24]
        emas = [40, 50, 60]
        z_threshs = [0.5]
    else:
        formations = [16, 20, 24]
        emas = [40, 50, 60]
        z_threshs = [0.3, 0.5, 0.7]

    # ---- Sweep with trend filter ON (baseline) ----
    print(f"\nRunning sweep: trend filter ON  "
          f"({len(formations)*len(emas)*len(z_threshs)} cells)")
    results_on: list[CellResult] = []
    for f in formations:
        for e in emas:
            for z in z_threshs:
                print(f"  cell f={f} ema={e} z={z:.1f} trend=on...", end="", flush=True)
                r = run_one(data, f, e, z, True, args.capital)
                results_on.append(r)
                print(f" Sharpe={r.sharpe:+.2f}  trades={r.n_trades}")

    # Sort by Sharpe descending
    results_on.sort(key=lambda r: -r.sharpe)
    print_table(results_on, f"TREND FILTER ON -- {args.timeframe}")
    stability_summary(results_on)

    # ---- Ablation: trend filter OFF at baseline params ----
    print(f"\nRunning ablation: trend filter OFF  "
          f"({len(formations)*len(emas)*len(z_threshs)} cells)")
    results_off: list[CellResult] = []
    for f in formations:
        for e in emas:
            for z in z_threshs:
                print(f"  cell f={f} ema={e} z={z:.1f} trend=off...", end="", flush=True)
                r = run_one(data, f, e, z, False, args.capital)
                results_off.append(r)
                print(f" Sharpe={r.sharpe:+.2f}  trades={r.n_trades}")

    results_off.sort(key=lambda r: -r.sharpe)
    print_table(results_off, f"TREND FILTER OFF -- {args.timeframe}")
    stability_summary(results_off)

    # ---- Side-by-side ablation deltas at matching cells ----
    on_map = {(r.formation, r.ema, r.z_thresh): r for r in results_on}
    off_map = {(r.formation, r.ema, r.z_thresh): r for r in results_off}
    print(f"\n{'=' * 75}")
    print(f"  TREND FILTER ABLATION: ON vs OFF (delta-Sharpe per cell)")
    print(f"{'=' * 75}")
    print(f"  {'form':>4}  {'ema':>4}  {'z':>4}  "
          f"{'Sh_on':>7}  {'Sh_off':>7}  {'delta':>7}  {'note':<20}")
    deltas: list[float] = []
    for key in sorted(on_map):
        on_r, off_r = on_map[key], off_map[key]
        delta = off_r.sharpe - on_r.sharpe
        deltas.append(delta)
        note = ""
        if delta > 0.3:
            note = "filter HURTS"
        elif delta < -0.3:
            note = "filter HELPS"
        f, e, z = key
        print(f"  {f:>4}  {e:>4}  {z:>4.2f}  "
              f"{on_r.sharpe:>+7.2f}  {off_r.sharpe:>+7.2f}  "
              f"{delta:>+7.2f}  {note:<20}")

    import numpy as np
    print(f"\n  Mean delta-Sharpe (off - on): {np.mean(deltas):+.2f}")
    print(f"  -> if mean > 0, trend filter is on net HURTING the strategy")

    # ---- Save CSV ----
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"sweep_{args.timeframe}.csv"
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("formation,ema,z_thresh,trend_filter,n_trades,win_rate,"
                 "sharpe,max_dd,profit_factor,total_return,ftmo_pass\n")
        for r in results_on + results_off:
            fh.write(f"{r.formation},{r.ema},{r.z_thresh},"
                     f"{int(r.trend_filter)},{r.n_trades},{r.win_rate:.4f},"
                     f"{r.sharpe:.4f},{r.max_dd:.4f},{r.profit_factor:.4f},"
                     f"{r.total_return:.4f},{int(r.ftmo_pass)}\n")
    print(f"\n  Sweep CSV: {csv_path}")


if __name__ == "__main__":
    main()
