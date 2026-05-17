"""
Backtest the gold-silver pairs trading strategy.

Usage:
    uv run python scripts/run_pairs_backtest.py
    uv run python scripts/run_pairs_backtest.py --entry-z 1.5 --exit-z 0.5
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gold-silver pairs backtest")
    p.add_argument("--years", type=int, default=12)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--entry-z", type=float, default=2.0)
    p.add_argument("--exit-z", type=float, default=0.5)
    p.add_argument("--max-hold", type=int, default=60)
    p.add_argument("--catastrophic-z", type=float, default=4.0)
    p.add_argument("--coint-lookback", type=int, default=504)
    p.add_argument("--z-lookback", type=int, default=252)
    p.add_argument("--risk-pct", type=float, default=0.005)
    return p.parse_args()


METALS_SPECS = None  # lazy-init


def get_metals_specs():
    global METALS_SPECS
    if METALS_SPECS is None:
        from backtest.costs import SymbolSpec
        METALS_SPECS = {
            # MT5 broker spec (probed via scripts/probe_commodities.py):
            #   XAUUSD: contract=100, point=0.01, tick_value=0.10
            #   XAGUSD: contract=5000, point=0.001, tick_value=0.50
            "XAUUSD": SymbolSpec("XAUUSD", 100, 0.01, 0.10, 0.0, 30.0),
            "XAGUSD": SymbolSpec("XAGUSD", 5000, 0.001, 0.50, 0.0, 30.0),
        }
    return METALS_SPECS


def main() -> None:
    args = parse_args()
    from data.cache import ParquetCache
    from strategies.metals_pairs.pairs import PairsConfig, PairsEngine
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    import numpy as np

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * args.years)

    xau = cache.read("XAUUSD", D1, start, end)
    xag = cache.read("XAGUSD", D1, start, end)
    if xau is None or xag is None:
        print("Need XAUUSD and XAGUSD cached -- run fetch_backtest_data.py first")
        sys.exit(1)
    print(f"Loaded {len(xau)} XAUUSD bars and {len(xag)} XAGUSD bars")

    config = PairsConfig(
        symbol_a="XAUUSD", symbol_b="XAGUSD",
        entry_z=args.entry_z, exit_z=args.exit_z,
        max_hold_bars=args.max_hold,
        catastrophic_z=args.catastrophic_z,
        coint_lookback=args.coint_lookback,
        z_lookback=args.z_lookback,
        per_trade_risk_pct=args.risk_pct,
    )
    engine = PairsEngine(get_metals_specs())
    result = engine.run(xau["close"], xag["close"], config,
                       initial_capital=args.capital)

    eq = result.equity_curve
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    rmax = eq.cummax()
    max_dd = float(((eq - rmax) / rmax).min())
    n_days = (eq.index[-1] - eq.index[0]).days
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (365.0 / max(n_days, 1)) - 1.0 if n_days > 0 else 0.0

    wins = [t for t in result.trades if t.net_pnl > 0]
    losses = [t for t in result.trades if t.net_pnl < 0]
    win_rate = len(wins) / len(result.trades) if result.trades else 0.0
    pf = (sum(t.net_pnl for t in wins) /
          abs(sum(t.net_pnl for t in losses))) if losses else 0.0

    print(f"\n{'=' * 55}")
    print(f"  XAUUSD-XAGUSD PAIRS  (entry_z={args.entry_z}, exit_z={args.exit_z})")
    print(f"{'=' * 55}")
    print(f"  Period:        {eq.index[0].date()} to {eq.index[-1].date()}")
    print(f"  Total return:  {result.total_return:+.2%}")
    print(f"  CAGR:          {cagr:+.2%}")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Max drawdown:  {max_dd:.2%}")
    print(f"  Calmar:        {(result.total_return/abs(max_dd)) if max_dd<0 else 0:.2f}")
    print(f"  Trades:        {len(result.trades)}")
    print(f"  Win rate:      {win_rate:.1%}")
    print(f"  Profit factor: {pf:.2f}")
    if result.trades:
        reasons = {}
        for t in result.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        print(f"  Exit reasons:  {reasons}")
        # Direction split
        n_long = sum(1 for t in result.trades if t.direction == +1)
        n_short = sum(1 for t in result.trades if t.direction == -1)
        print(f"  Long-spread:   {n_long}  Short-spread: {n_short}")

    # FTMO sim
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=args.capital, opening_balance=args.capital,
    )
    rep = sim.run(result.equity_curve, equity_low=result.equity_low)
    status = "PASS" if rep.passed else "FAIL"
    print(f"\n  FTMO sim [{status}] -- daily breaches={rep.ftmo_daily_line_breach_count}, "
          f"max breaches={rep.ftmo_max_line_breach_count}, "
          f"min daily distance=${rep.min_daily_distance:,.0f}")

    # Save equity curve for portfolio harness
    out_dir = Path("reports/metals_pairs")
    out_dir.mkdir(parents=True, exist_ok=True)
    result.equity_curve.to_csv(out_dir / "equity_curve.csv", header=True)
    print(f"\n  Equity curve saved to {out_dir}/equity_curve.csv")


if __name__ == "__main__":
    main()
