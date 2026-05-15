"""
FX Mean-Reversion (long-only) backtest.

Applies the same z-score-based mean-reversion engine that worked on
equity indices to the FX majors that showed a long-side signal in the
2026-05-15 bucket test:

  EURUSD (t=-3.07, sig**), GBPUSD (t=-1.61), AUDUSD (t=-0.71)

Skipped: USDJPY / NZDUSD / USDCAD (no signal), USDCHF (short-side only).

The PURPOSE is portfolio diversification with the index mean-reversion
strategy -- different asset class, different macro flow drivers. The
absolute return target is modest; what matters is correlation with the
index MR equity curve.

Usage:
    uv run python scripts/run_fx_meanrev_backtest.py
    uv run python scripts/run_fx_meanrev_backtest.py --no-plots
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408

from backtest.costs import SymbolSpec, CostModel

# FX symbol specs -- standard MT5 5-digit broker conventions.
# Spreads are conservative estimates for D1 trading on FTMO.
FX_SPECS: dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec("EURUSD", 100_000, 0.00001, 1.0,    7.0, 1.5),
    "GBPUSD": SymbolSpec("GBPUSD", 100_000, 0.00001, 1.0,    7.0, 2.0),
    "AUDUSD": SymbolSpec("AUDUSD", 100_000, 0.00001, 1.0,    7.0, 2.0),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FX mean-reversion backtest")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--is-months", type=int, default=36)
    p.add_argument("--oos-months", type=int, default=12)
    p.add_argument("--formation", type=int, default=10)
    p.add_argument("--entry-z", type=float, default=1.5)
    p.add_argument("--exit-z", type=float, default=0.5)
    p.add_argument("--max-hold", type=int, default=10)
    p.add_argument("--atr-stop", type=float, default=1.5)
    p.add_argument("--atr-tp", type=float, default=2.0)
    p.add_argument("--risk-pct", type=float, default=0.005)
    p.add_argument("--no-trend-filter", action="store_true")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--out-dir", default="reports/fx_meanrev")
    return p.parse_args()


def load_data(years: int, symbols: list[str]) -> dict:
    import pandas as pd
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    data: dict[str, pd.DataFrame] = {}
    print(f"Loading {years}y D1 for {symbols}...")
    for sym in symbols:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            print(f"  {sym}: no cached data")
            continue
        data[sym] = df
        print(f"  {sym}: {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
    return data


def print_metrics(label: str, result, capital: float) -> None:
    import numpy as np
    eq = result.equity_curve
    trades = result.trades
    if len(eq) < 2:
        print(f"\n{label}: insufficient data")
        return
    ret = eq.iloc[-1] / eq.iloc[0] - 1.0
    rets = eq.pct_change().dropna()
    ann_vol = float(rets.std() * np.sqrt(252))
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    rmax = eq.cummax()
    max_dd = float(((eq - rmax) / rmax).min())
    n_days = (eq.index[-1] - eq.index[0]).days
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (365.0 / max(n_days, 1)) - 1.0 if n_days > 0 else 0.0
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses else 0.0
    syms: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for t in trades:
        syms[t.symbol] = syms.get(t.symbol, 0) + 1
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    print(f"\n{'=' * 55}")
    print(f"  {label}")
    print(f"{'=' * 55}")
    print(f"  Period:        {eq.index[0].date()} to {eq.index[-1].date()}  ({n_days} days)")
    print(f"  Total return:  {ret:+.2%}")
    print(f"  CAGR:          {cagr:+.2%}")
    print(f"  Ann. vol:      {ann_vol:.2%}")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Max drawdown:  {max_dd:.2%}")
    print(f"  Trades:        {len(trades)}  win {100*win_rate:.1f}%  PF {pf:.2f}")
    if trades:
        print(f"  Trades/symbol: {dict(sorted(syms.items()))}")
        print(f"  Exit reasons:  {dict(sorted(reasons.items()))}")


def run_ftmo(result, capital: float):
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital, opening_balance=capital,
    )
    return sim.run(result.equity_curve, equity_low=result.equity_low)


def print_ftmo(label: str, report) -> None:
    status = "PASS" if report.passed else "FAIL"
    print(f"  FTMO [{status}] -- {label}: daily breaches={report.ftmo_daily_line_breach_count}, "
          f"max breaches={report.ftmo_max_line_breach_count}, "
          f"min daily distance=${report.min_daily_distance:,.0f}")


def main() -> None:
    args = parse_args()

    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine, meanrev_walk_forward

    symbols = list(FX_SPECS.keys())
    data = load_data(args.years, symbols)
    if len(data) < 2:
        print("Need at least 2 symbols. Fetch with scripts/fetch_backtest_data.py")
        sys.exit(1)

    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=args.formation,
        z_lookback_bars=252,
        entry_z_threshold=args.entry_z,
        exit_z_threshold=args.exit_z,
        max_hold_bars=args.max_hold,
        atr_stop_mult=args.atr_stop,
        atr_tp_mult=args.atr_tp,
        require_long_term_uptrend=not args.no_trend_filter,
        # FX has no equivalent of equity's "long-term uptrend" structural floor;
        # if the user opts in, we use a permissive floor.
        long_term_drawdown_floor=0.85,
    )

    specs = {sym: FX_SPECS[sym] for sym in data}
    engine = MeanRevEngine(specs, per_trade_risk_pct=args.risk_pct)

    print("\nRunning FX mean-reversion full-period backtest...")
    full = engine.run(data, config, initial_capital=args.capital)
    print_metrics("FULL PERIOD (FX MR)", full, args.capital)
    print_ftmo("Full Period", run_ftmo(full, args.capital))

    print(f"\nRunning walk-forward ({args.is_months}m IS / {args.oos_months}m OOS)...")
    wf = meanrev_walk_forward(
        data, config, specs,
        per_trade_risk_pct=args.risk_pct,
        is_months=args.is_months,
        oos_months=args.oos_months,
        initial_capital=args.capital,
    )

    import numpy as np
    if wf:
        oos_sharpes = []
        for i, w in enumerate(wf):
            r = w.oos_result
            rets = r.equity_curve.pct_change().dropna()
            sh = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
            oos_sharpes.append(sh)
            print_metrics(f"OOS {i+1}: {w.oos_start.date()} to {w.oos_end.date()}", r, args.capital)
            print_ftmo(f"OOS {i+1}", run_ftmo(r, r.initial_capital))

        print(f"\n{'=' * 55}")
        print(f"  FX MR Walk-Forward Summary ({len(wf)} OOS windows)")
        print(f"{'=' * 55}")
        print(f"  Avg OOS Sharpe:    {np.mean(oos_sharpes):.2f}")
        print(f"  Median OOS Sharpe: {np.median(oos_sharpes):.2f}")
        print(f"  Min:               {min(oos_sharpes):.2f}")
        print(f"  Max:               {max(oos_sharpes):.2f}")
        print(f"  % positive:        {100*sum(s>0 for s in oos_sharpes)/len(oos_sharpes):.0f}%")

    # Save equity curve for the correlation analysis script
    import pandas as pd
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full.equity_curve.to_csv(out_dir / "equity_curve.csv", header=True)
    print(f"\n  Equity curve saved to {out_dir}/equity_curve.csv")


if __name__ == "__main__":
    main()
