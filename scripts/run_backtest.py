"""
FX Momentum Phase 2 backtest runner.

Loads cached D1 data, runs full-period + walk-forward backtest,
FTMO simulation, and prints a complete performance report.

Usage:
    uv run python scripts/run_backtest.py
    uv run python scripts/run_backtest.py --years 3 --is-months 24 --oos-months 6
    uv run python scripts/run_backtest.py --no-plots
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Symbol specs for backtesting (approximate; live trading fetches from MT5)
# tick_value = account-currency value per 1 point move per 1 lot
# USD-quoted pairs: tick_value = 1.0 (exact)
# JPY-quoted (USDJPY): tick_value ≈ 0.0067 (at ~150, 100k*0.001/150)
# CAD-quoted (USDCAD): tick_value ≈ 0.74 (at ~1.35, 100k*0.0001/1.35/10)
# CHF-quoted (USDCHF): tick_value ≈ 1.10 (at ~0.91, 100k*0.0001/0.91/10)
# ---------------------------------------------------------------------------

from backtest.costs import CostModel, SymbolSpec, DEFAULT_COST_MODEL

SYMBOL_SPECS: dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec("EURUSD", 100_000, 0.00001, 1.0,   7.0, 1.5),
    "GBPUSD": SymbolSpec("GBPUSD", 100_000, 0.00001, 1.0,   7.0, 2.0),
    "AUDUSD": SymbolSpec("AUDUSD", 100_000, 0.00001, 1.0,   7.0, 2.0),
    "NZDUSD": SymbolSpec("NZDUSD", 100_000, 0.00001, 1.0,   7.0, 2.5),
    "USDJPY": SymbolSpec("USDJPY", 100_000, 0.001,   0.0067, 7.0, 2.0),
    "USDCAD": SymbolSpec("USDCAD", 100_000, 0.00001, 0.74,  7.0, 2.5),
    "USDCHF": SymbolSpec("USDCHF", 100_000, 0.00001, 1.10,  7.0, 2.5),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FX Momentum Phase 2 backtest")
    p.add_argument("--years",      type=int,   default=5,    help="History to use (default: 5)")
    p.add_argument("--capital",    type=float, default=100_000, help="Initial capital")
    p.add_argument("--is-months",  type=int,   default=36,   help="IS window in months")
    p.add_argument("--oos-months", type=int,   default=12,   help="OOS window in months")
    p.add_argument("--formation",  type=int,   default=20,   help="Momentum formation bars")
    p.add_argument("--ema",        type=int,   default=50,   help="EMA trend-filter bars")
    p.add_argument("--no-plots",   action="store_true",       help="Skip matplotlib charts")
    p.add_argument("--out-dir",    default="reports/fx_momentum", help="Report output directory")
    return p.parse_args()


def load_data(years: int) -> dict[str, "pd.DataFrame"]:
    import pandas as pd
    from data.cache import ParquetCache

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    tf_int = 16408  # D1

    print(f"Loading {years}y of D1 data ({start.date()} to {end.date()})...")
    data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOL_SPECS:
        df = cache.read(sym, tf_int, start, end)
        if df is None or df.empty:
            print(f"  {sym}: no cached data --run fetch_backtest_data.py first")
            continue
        data[sym] = df
        print(f"  {sym}: {len(df)} bars")
    return data


def print_metrics(label: str, result: "PortfolioResult", capital: float) -> None:
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

    print(f"\n{'=' * 55}")
    print(f"  {label}")
    print(f"{'=' * 55}")
    print(f"  Period:        {eq.index[0].date()} to {eq.index[-1].date()}"
          f"  ({n_days} days)")
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
        syms = {}
        for t in trades:
            syms[t.symbol] = syms.get(t.symbol, 0) + 1
        print(f"  Trades/symbol: {dict(sorted(syms.items()))}")


def run_ftmo_sim(result: "PortfolioResult", capital: float) -> "FTMOSimReport":
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType

    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital,
        opening_balance=capital,
    )
    report = sim.run(result.equity_curve, equity_low=result.equity_low)
    return report


def print_ftmo_report(label: str, report: "FTMOSimReport") -> None:
    status = "PASS" if report.passed else "FAIL"
    print(f"\n  FTMO Simulation [{status}] --{label}")
    print(f"    Daily breaches:      {report.ftmo_daily_line_breach_count}")
    print(f"    Max-loss breaches:   {report.ftmo_max_line_breach_count}")
    print(f"    Internal daily kill: {report.internal_daily_kill_count}")
    print(f"    Internal max kill:   {report.internal_max_kill_count}")
    print(f"    Min daily distance:  ${report.min_daily_distance:,.0f}")
    if report.violations:
        for v in report.violations[:3]:
            ts = v.timestamp.date() if hasattr(v.timestamp, "date") else v.timestamp
            print(f"    ! {v.violation_type} @ {ts}: equity=${v.equity:,.0f}")


def make_plots(
    full_result: "PortfolioResult",
    wf_windows: list,
    capital: float,
    out_dir: Path,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np
    except ImportError:
        print("  matplotlib not available --skipping plots")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    eq = full_result.equity_curve

    # -- 1. Equity curve with FTMO lines --
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(eq.index, eq.values, lw=1.5, color="steelblue", label="Portfolio equity")
    ax.plot(eq.index, full_result.equity_low.values, lw=0.5, color="gray",
            alpha=0.4, label="Intrabar low")

    ftmo_daily = capital * 0.95  # 5% daily limit floor (worst case: anchor=capital)
    ftmo_max   = capital * 0.90  # 10% max loss floor
    ax.axhline(ftmo_daily, color="orange", lw=1, ls="--", label=f"FTMO daily floor ${ftmo_daily:,.0f}")
    ax.axhline(ftmo_max,   color="red",    lw=1, ls="--", label=f"FTMO max floor ${ftmo_max:,.0f}")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.xticks(rotation=30)
    ax.set_title("FX Cross-Sectional Momentum --Full Period Equity Curve")
    ax.set_ylabel("Account Equity ($)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "equity_curve.png", dpi=150)
    plt.close()

    # -- 2. Drawdown --
    fig, ax = plt.subplots(figsize=(14, 4))
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max * 100
    ax.fill_between(dd.index, dd.values, 0, alpha=0.4, color="crimson")
    ax.plot(dd.index, dd.values, lw=0.8, color="crimson")
    ax.axhline(-5, color="orange", lw=1, ls="--", label="FTMO daily -5%")
    ax.axhline(-10, color="red",   lw=1, ls="--", label="FTMO max -10%")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.xticks(rotation=30)
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "drawdown.png", dpi=150)
    plt.close()

    # -- 3. Monthly returns heatmap --
    monthly = eq.resample("ME").last().pct_change().dropna() * 100
    if len(monthly) > 0:
        years_list = sorted(set(monthly.index.year))
        months_list = list(range(1, 13))
        grid = np.full((len(years_list), 12), np.nan)
        for dt, val in monthly.items():
            yr_i = years_list.index(dt.year)
            grid[yr_i, dt.month - 1] = val

        fig, ax = plt.subplots(figsize=(14, max(3, len(years_list) * 0.7)))
        im = ax.imshow(grid, cmap="RdYlGn", aspect="auto", vmin=-5, vmax=5)
        ax.set_xticks(range(12))
        ax.set_xticklabels(["Jan","Feb","Mar","Apr","May","Jun",
                             "Jul","Aug","Sep","Oct","Nov","Dec"])
        ax.set_yticks(range(len(years_list)))
        ax.set_yticklabels(years_list)
        for yr_i in range(len(years_list)):
            for mo_i in range(12):
                v = grid[yr_i, mo_i]
                if not np.isnan(v):
                    ax.text(mo_i, yr_i, f"{v:.1f}%", ha="center", va="center", fontsize=7)
        plt.colorbar(im, ax=ax, label="Monthly return (%)")
        ax.set_title("Monthly Returns (%)")
        plt.tight_layout()
        plt.savefig(out_dir / "monthly_returns.png", dpi=150)
        plt.close()

    # -- 4. Walk-forward OOS Sharpe bars --
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

    from strategies.fx_momentum.signal import MomentumConfig
    from strategies.fx_momentum.sizing import SizingConfig
    from backtest.portfolio_engine import PortfolioEngine, portfolio_walk_forward

    data = load_data(args.years)
    if len(data) < 3:
        print("Need at least 3 symbols. Fetch data first: uv run python scripts/fetch_backtest_data.py")
        sys.exit(1)

    config = MomentumConfig(
        symbols=tuple(data.keys()),
        usd_base_symbols=("USDJPY", "USDCAD", "USDCHF"),
        formation_bars=args.formation,
        skip_bars=1,
        long_z_threshold=0.5,
        short_z_threshold=-0.5,
        max_long_positions=2,
        max_short_positions=2,
        trend_ema_bars=args.ema,
        require_trend_confirmation=True,
        xvol_lookback_bars=5,
        xvol_pause_threshold=2.0,
    )

    sizing = SizingConfig(per_trade_risk_pct=0.005, kelly_fraction=0.25)
    specs = {sym: SYMBOL_SPECS[sym] for sym in data if sym in SYMBOL_SPECS}
    engine = PortfolioEngine(specs, DEFAULT_COST_MODEL)

    # -------------------------------------------------------------------------
    # Full-period backtest
    # -------------------------------------------------------------------------
    print("\nRunning full-period backtest...")
    full = engine.run(data, config, sizing, initial_capital=args.capital)
    print_metrics("FULL PERIOD (in-sample reference)", full, args.capital)

    ftmo_full = run_ftmo_sim(full, args.capital)
    print_ftmo_report("Full Period", ftmo_full)

    # -------------------------------------------------------------------------
    # Walk-forward validation
    # -------------------------------------------------------------------------
    print(f"\nRunning walk-forward ({args.is_months}m IS / {args.oos_months}m OOS)...")
    wf_windows = portfolio_walk_forward(
        data, config, specs, sizing,
        is_months=args.is_months,
        oos_months=args.oos_months,
        initial_capital=args.capital,
    )

    if wf_windows:
        import numpy as np
        oos_sharpes = []
        for i, w in enumerate(wf_windows):
            r = w.oos_result
            rets = r.equity_curve.pct_change().dropna()
            sh = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 1 and rets.std() > 0 else 0.0
            oos_sharpes.append(sh)
            print_metrics(
                f"OOS Window {i+1}: {w.oos_start.date()} to {w.oos_end.date()}",
                r, args.capital,
            )
            ftmo_w = run_ftmo_sim(r, r.initial_capital)
            print_ftmo_report(f"OOS Window {i+1}", ftmo_w)

        print(f"\n{'=' * 55}")
        print(f"  Walk-Forward Summary ({len(wf_windows)} OOS windows)")
        print(f"{'=' * 55}")
        print(f"  Avg OOS Sharpe:    {np.mean(oos_sharpes):.2f}")
        print(f"  Median OOS Sharpe: {np.median(oos_sharpes):.2f}")
        print(f"  % Positive Sharpe: {100*sum(s>0 for s in oos_sharpes)/len(oos_sharpes):.0f}%")
        print(f"  Min OOS Sharpe:    {min(oos_sharpes):.2f}")
        print(f"  Max OOS Sharpe:    {max(oos_sharpes):.2f}")
        is_sharpe = float(
            full.equity_curve.pct_change().dropna().mean() /
            full.equity_curve.pct_change().dropna().std() * np.sqrt(252)
        ) if full.equity_curve.pct_change().dropna().std() > 0 else 0
        degradation = is_sharpe - np.mean(oos_sharpes)
        print(f"  IS Sharpe:         {is_sharpe:.2f}")
        print(f"  IS->OOS degradation:{degradation:+.2f}  (target: <0.5)")
    else:
        print("  Not enough data for walk-forward windows.")
        wf_windows = []

    # -------------------------------------------------------------------------
    # Plots
    # -------------------------------------------------------------------------
    if not args.no_plots:
        make_plots(full, wf_windows, args.capital, Path(args.out_dir))

    print(f"\n{'=' * 55}")


if __name__ == "__main__":
    main()
