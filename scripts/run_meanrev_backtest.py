"""
Index Mean-Reversion (long-only) Phase 2 backtest runner.

Loads cached D1 data for US500, USTEC, US30, DE40; runs the full-period
backtest and a 36m IS / 12m OOS walk-forward; reports performance metrics
and FTMO compliance.

Usage:
    uv run python scripts/run_meanrev_backtest.py
    uv run python scripts/run_meanrev_backtest.py --no-plots
    uv run python scripts/run_meanrev_backtest.py --entry-z 2.0 --max-hold 8

Spread modeling note:
    The demo broker reports spread=0 on every index, which is unrealistic.
    Live FTMO index CFD spreads are 30-150 points during liquid hours. The
    spec table below uses conservative estimates that should be re-measured
    on a real FTMO account before deploying.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408

# Conservative spread / commission estimates for major index CFDs on FTMO.
# Demo broker reports 0 spread; these values reflect typical live conditions.
# Re-verify before deployment.
#
# tick_value here is the account-currency value per 1 point per 1 lot, matching
# the SymbolSpec.pnl() formula used elsewhere in the codebase.
from backtest.costs import CostModel, SymbolSpec

INDEX_SPECS: dict[str, SymbolSpec] = {
    # US500: 1 lot = ~$5,500 notional at S&P=5500; $1/point/lot is the FTMO standard.
    "US500": SymbolSpec("US500", contract_size=1, point=0.01,
                       tick_value=0.01, commission_per_lot=2.0,
                       avg_spread_points=50.0),
    # USTEC: 1 lot = ~$20,000 notional at NDX=20000; $1/point/lot.
    "USTEC": SymbolSpec("USTEC", contract_size=1, point=0.01,
                       tick_value=0.01, commission_per_lot=2.0,
                       avg_spread_points=100.0),
    # US30: similar to US500.
    "US30":  SymbolSpec("US30",  contract_size=1, point=0.01,
                       tick_value=0.01, commission_per_lot=2.0,
                       avg_spread_points=80.0),
    # DE40: EUR-denominated, but USD account uses ~1.10 conversion so tick_value~0.0118.
    "DE40":  SymbolSpec("DE40",  contract_size=1, point=0.01,
                       tick_value=0.0118, commission_per_lot=2.0,
                       avg_spread_points=100.0),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Index mean-reversion backtest")
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
    p.add_argument("--risk-pct", type=float, default=0.005,
                   help="Per-trade risk as fraction of equity (default 0.005)")
    p.add_argument("--no-trend-filter", action="store_true",
                   help="Disable long-term EMA trend confirmation")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--out-dir", default="reports/index_meanrev")
    return p.parse_args()


def load_data(years: int, symbols: list[str]) -> dict[str, "pd.DataFrame"]:
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
            print(f"  {sym}: no cached data -- run fetch_backtest_data.py")
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
    returns = eq.pct_change().dropna()
    ann_vol = float(returns.std() * np.sqrt(252))
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    max_dd = float(dd.min())
    calmar = (ret / abs(max_dd)) if max_dd < 0 else 0.0
    n_days = (eq.index[-1] - eq.index[0]).days
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (365.0 / max(n_days, 1)) - 1.0 if n_days > 0 else 0.0

    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses else 0.0

    # Exit reason distribution
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Per-symbol distribution
    syms: dict[str, int] = {}
    for t in trades:
        syms[t.symbol] = syms.get(t.symbol, 0) + 1

    print(f"\n{'=' * 55}")
    print(f"  {label}")
    print(f"{'=' * 55}")
    print(f"  Period:        {eq.index[0].date()} to {eq.index[-1].date()}  ({n_days} days)")
    print(f"  Bars:          {len(eq)}")
    print(f"  Total return:  {ret:+.2%}")
    print(f"  CAGR:          {cagr:+.2%}")
    print(f"  Ann. vol:      {ann_vol:.2%}")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Calmar:        {calmar:.2f}")
    print(f"  Max drawdown:  {max_dd:.2%}")
    print(f"  Trades:        {len(trades)}")
    print(f"  Win rate:      {win_rate:.1%}")
    print(f"  Avg win:       ${avg_win:,.0f}")
    print(f"  Avg loss:      ${avg_loss:,.0f}")
    print(f"  Profit factor: {pf:.2f}")
    if trades:
        print(f"  Trades/symbol: {dict(sorted(syms.items()))}")
        print(f"  Exit reasons:  {dict(sorted(reasons.items()))}")


def run_ftmo_sim(result, capital: float):
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital,
        opening_balance=capital,
    )
    return sim.run(result.equity_curve, equity_low=result.equity_low)


def print_ftmo_report(label: str, report) -> None:
    status = "PASS" if report.passed else "FAIL"
    print(f"\n  FTMO Simulation [{status}] -- {label}")
    print(f"    Daily breaches:      {report.ftmo_daily_line_breach_count}")
    print(f"    Max-loss breaches:   {report.ftmo_max_line_breach_count}")
    print(f"    Internal daily kill: {report.internal_daily_kill_count}")
    print(f"    Internal max kill:   {report.internal_max_kill_count}")
    print(f"    Min daily distance:  ${report.min_daily_distance:,.0f}")
    if report.violations:
        for v in report.violations[:3]:
            ts = v.timestamp.date() if hasattr(v.timestamp, "date") else v.timestamp
            print(f"    ! {v.violation_type} @ {ts}: equity=${v.equity:,.0f}")


def make_plots(full_result, wf_windows, capital, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np
    except ImportError:
        print("  matplotlib not available -- skipping plots")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    eq = full_result.equity_curve

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(eq.index, eq.values, lw=1.5, color="steelblue", label="Portfolio equity")
    ax.plot(eq.index, full_result.equity_low.values, lw=0.5, color="gray",
            alpha=0.4, label="Intrabar low")
    ax.axhline(capital * 0.95, color="orange", lw=1, ls="--",
               label=f"FTMO daily floor ${capital*0.95:,.0f}")
    ax.axhline(capital * 0.90, color="red", lw=1, ls="--",
               label=f"FTMO max floor ${capital*0.90:,.0f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.xticks(rotation=30)
    ax.set_title("Index Mean-Reversion (Long-Only) -- Full Period Equity Curve")
    ax.set_ylabel("Account Equity ($)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "equity_curve.png", dpi=150)
    plt.close()

    fig, ax = plt.subplots(figsize=(14, 4))
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max * 100
    ax.fill_between(dd.index, dd.values, 0, alpha=0.4, color="crimson")
    ax.plot(dd.index, dd.values, lw=0.8, color="crimson")
    ax.axhline(-5, color="orange", lw=1, ls="--", label="FTMO daily -5%")
    ax.axhline(-10, color="red", lw=1, ls="--", label="FTMO max -10%")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=30)
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "drawdown.png", dpi=150)
    plt.close()

    if wf_windows:
        labels = [f"{w.oos_start.strftime('%Y-%m')}" for w in wf_windows]
        sharpes = []
        for w in wf_windows:
            r = w.oos_result.equity_curve.pct_change().dropna()
            s = float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 1 and r.std() > 0 else 0.0
            sharpes.append(s)
        colors = ["steelblue" if s > 0 else "crimson" for s in sharpes]
        fig, ax = plt.subplots(figsize=(max(8, len(sharpes) * 1.2), 4))
        ax.bar(range(len(sharpes)), sharpes, color=colors, edgecolor="white", linewidth=0.5)
        ax.axhline(0, color="black", lw=0.8)
        ax.axhline(0.5, color="green", lw=1, ls="--", label="Sharpe=0.5 target")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title("Walk-Forward OOS Sharpe by Window")
        ax.set_ylabel("Sharpe Ratio (annualised)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        plt.savefig(out_dir / "wf_sharpe.png", dpi=150)
        plt.close()

    print(f"\n  Charts saved to {out_dir}/")


def main() -> None:
    args = parse_args()

    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine, meanrev_walk_forward

    symbols = list(INDEX_SPECS.keys())
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
    )

    specs = {sym: INDEX_SPECS[sym] for sym in data}

    # ---- Full period ----
    print("\nRunning full-period backtest...")
    engine = MeanRevEngine(specs, per_trade_risk_pct=args.risk_pct)
    full = engine.run(data, config, initial_capital=args.capital)
    print_metrics("FULL PERIOD (in-sample reference)", full, args.capital)
    print_ftmo_report("Full Period", run_ftmo_sim(full, args.capital))

    # ---- Walk-forward ----
    print(f"\nRunning walk-forward ({args.is_months}m IS / {args.oos_months}m OOS)...")
    wf_windows = meanrev_walk_forward(
        data, config, specs,
        per_trade_risk_pct=args.risk_pct,
        is_months=args.is_months,
        oos_months=args.oos_months,
        initial_capital=args.capital,
    )

    import numpy as np
    if wf_windows:
        oos_sharpes = []
        for i, w in enumerate(wf_windows):
            r = w.oos_result
            rets = r.equity_curve.pct_change().dropna()
            sh = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 1 and rets.std() > 0 else 0.0
            oos_sharpes.append(sh)
            print_metrics(f"OOS Window {i+1}: {w.oos_start.date()} to {w.oos_end.date()}",
                          r, args.capital)
            print_ftmo_report(f"OOS Window {i+1}", run_ftmo_sim(r, r.initial_capital))

        print(f"\n{'=' * 55}")
        print(f"  Walk-Forward Summary ({len(wf_windows)} OOS windows)")
        print(f"{'=' * 55}")
        print(f"  Avg OOS Sharpe:    {np.mean(oos_sharpes):.2f}")
        print(f"  Median OOS Sharpe: {np.median(oos_sharpes):.2f}")
        print(f"  Min OOS Sharpe:    {min(oos_sharpes):.2f}")
        print(f"  Max OOS Sharpe:    {max(oos_sharpes):.2f}")
        print(f"  % Positive Sharpe: {100*sum(s>0 for s in oos_sharpes)/len(oos_sharpes):.0f}%")
        is_rets = full.equity_curve.pct_change().dropna()
        is_sharpe = float(is_rets.mean() / is_rets.std() * np.sqrt(252)) if is_rets.std() > 0 else 0.0
        deg = is_sharpe - np.mean(oos_sharpes)
        print(f"  IS Sharpe:         {is_sharpe:.2f}")
        print(f"  IS->OOS degr:      {deg:+.2f}  (target: <0.3)")
    else:
        print("  Not enough data for walk-forward windows.")
        wf_windows = []

    if not args.no_plots:
        make_plots(full, wf_windows, args.capital, Path(args.out_dir))

    print(f"\n{'=' * 55}")


if __name__ == "__main__":
    main()
