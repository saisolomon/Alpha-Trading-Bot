"""
Run the Index MR strategy with vs without the Markov regime gate.

Side-by-side comparison: full-period + 9-window walk-forward, baseline vs
gated. Specifically watches the 2019-2020 OOS window (the strategy's worst
year at Sharpe -0.52) to see if the gate fixes the whipsaw failure mode.

Usage:
    uv run python scripts/run_meanrev_gated_backtest.py
    uv run python scripts/run_meanrev_gated_backtest.py --bear-threshold 0.30
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
    p = argparse.ArgumentParser(description="MR + Markov regime gate comparison")
    p.add_argument("--years", type=int, default=12)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--is-months", type=int, default=36)
    p.add_argument("--oos-months", type=int, default=12)
    p.add_argument("--formation", type=int, default=20)
    p.add_argument("--entry-z", type=float, default=1.0)
    # Markov gate config
    p.add_argument("--bear-threshold", type=float, default=0.40)
    p.add_argument("--markov-formation", type=int, default=20)
    p.add_argument("--markov-bull-thresh", type=float, default=0.02)
    p.add_argument("--markov-bear-thresh", type=float, default=-0.02)
    p.add_argument("--markov-lookback", type=int, default=504)
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


def summarize_window(name: str, result, capital: float) -> dict:
    import numpy as np
    eq = result.equity_curve
    trades = result.trades
    if len(eq) < 2:
        return {"name": name, "sharpe": 0.0, "trades": 0, "return": 0.0,
                "max_dd": 0.0, "win_rate": 0.0, "pf": 0.0}
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    rmax = eq.cummax()
    max_dd = float(((eq - rmax) / rmax).min())
    ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else 0.0
    return {
        "name": name, "sharpe": sharpe, "trades": len(trades),
        "return": ret, "max_dd": max_dd,
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "pf": pf,
    }


def run_ftmo(result, capital: float):
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital, opening_balance=capital,
    )
    return sim.run(result.equity_curve, equity_low=result.equity_low)


def make_gate_factory(args):
    from strategies.regime_markov.markov import (
        GateConfig, MarkovConfig, MarkovRegimeGate,
    )
    mcfg = MarkovConfig(
        formation_bars=args.markov_formation,
        bull_threshold=args.markov_bull_thresh,
        bear_threshold=args.markov_bear_thresh,
        estimation_lookback=args.markov_lookback,
    )
    gcfg = GateConfig(bear_threshold=args.bear_threshold)
    def factory(symbol, df):
        return MarkovRegimeGate(prices=df["close"], markov_config=mcfg, gate_config=gcfg)
    return factory


def run_both(args, data):
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine, meanrev_walk_forward
    from scripts.run_meanrev_backtest import INDEX_SPECS

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
    specs = {s: INDEX_SPECS[s] for s in data}

    gate_factory = make_gate_factory(args)

    print("\nRunning BASELINE (no gate)...")
    engine_baseline = MeanRevEngine(specs, per_trade_risk_pct=0.005)
    baseline_full = engine_baseline.run(data, config, initial_capital=args.capital)

    print("Running GATED (Markov regime gate)...")
    engine_gated = MeanRevEngine(specs, per_trade_risk_pct=0.005,
                                  regime_gate_factory=gate_factory)
    gated_full = engine_gated.run(data, config, initial_capital=args.capital)

    print("\nRunning walk-forwards...")
    baseline_wf = meanrev_walk_forward(
        data, config, specs, per_trade_risk_pct=0.005,
        is_months=args.is_months, oos_months=args.oos_months,
        initial_capital=args.capital,
    )
    gated_wf = meanrev_walk_forward(
        data, config, specs, per_trade_risk_pct=0.005,
        is_months=args.is_months, oos_months=args.oos_months,
        initial_capital=args.capital,
        regime_gate_factory=gate_factory,
    )
    return baseline_full, gated_full, baseline_wf, gated_wf


def main() -> None:
    args = parse_args()

    print(f"Loading {args.years}y D1 data...")
    data = load_data(args.years)
    if not data:
        print("No cached data. Run scripts/fetch_backtest_data.py first.")
        sys.exit(1)
    print(f"  {len(data)} symbols: {list(data.keys())}")

    baseline_full, gated_full, baseline_wf, gated_wf = run_both(args, data)

    # ---- Full-period comparison ----
    print(f"\n{'=' * 75}")
    print(f"  FULL PERIOD COMPARISON  (formation={args.formation}, entry_z={args.entry_z}, "
          f"bear_thresh={args.bear_threshold})")
    print(f"{'=' * 75}")
    print(f"  {'metric':<14}  {'BASELINE':>12}  {'GATED':>12}  {'delta':>10}")
    bs = summarize_window("full", baseline_full, args.capital)
    gs = summarize_window("full", gated_full, args.capital)
    for k, label in [("sharpe", "Sharpe"), ("return", "Total return"),
                      ("max_dd", "Max DD"), ("win_rate", "Win rate"),
                      ("pf", "Profit factor"), ("trades", "Trades")]:
        b = bs[k]
        g = gs[k]
        if k == "trades":
            print(f"  {label:<14}  {int(b):>12}  {int(g):>12}  {int(g)-int(b):>+10}")
        elif k in ("return", "max_dd", "win_rate"):
            print(f"  {label:<14}  {100*b:>11.2f}%  {100*g:>11.2f}%  {100*(g-b):>+9.2f}%")
        else:
            print(f"  {label:<14}  {b:>+12.3f}  {g:>+12.3f}  {g-b:>+10.3f}")
    bftmo = run_ftmo(baseline_full, args.capital)
    gftmo = run_ftmo(gated_full, args.capital)
    print(f"  {'FTMO sim':<14}  {('PASS' if bftmo.passed else 'FAIL'):>12}  "
          f"{('PASS' if gftmo.passed else 'FAIL'):>12}")

    # ---- Walk-forward comparison ----
    import numpy as np
    print(f"\n{'=' * 75}")
    print(f"  WALK-FORWARD COMPARISON  ({len(baseline_wf)} OOS windows)")
    print(f"{'=' * 75}")
    print(f"  {'window':<25}  {'BASE Sh':>8}  {'GATE Sh':>8}  "
          f"{'BASE trd':>9}  {'GATE trd':>9}  {'BASE FTMO':>10}  {'GATE FTMO':>10}")
    base_sharpes, gate_sharpes = [], []
    for bw, gw in zip(baseline_wf, gated_wf):
        bs_ = summarize_window("oos", bw.oos_result, bw.oos_result.initial_capital)
        gs_ = summarize_window("oos", gw.oos_result, gw.oos_result.initial_capital)
        bf = run_ftmo(bw.oos_result, bw.oos_result.initial_capital)
        gf = run_ftmo(gw.oos_result, gw.oos_result.initial_capital)
        window_label = f"{bw.oos_start.date()} to {bw.oos_end.date()}"
        print(f"  {window_label:<25}  {bs_['sharpe']:>+8.2f}  {gs_['sharpe']:>+8.2f}  "
              f"{bs_['trades']:>9}  {gs_['trades']:>9}  "
              f"{('PASS' if bf.passed else 'FAIL'):>10}  "
              f"{('PASS' if gf.passed else 'FAIL'):>10}")
        base_sharpes.append(bs_["sharpe"])
        gate_sharpes.append(gs_["sharpe"])

    print(f"\n  {'AGGREGATE':<25}  {'BASELINE':>8}  {'GATED':>8}")
    print(f"  {'Mean OOS Sharpe':<25}  {np.mean(base_sharpes):>+8.2f}  "
          f"{np.mean(gate_sharpes):>+8.2f}")
    print(f"  {'Median OOS Sharpe':<25}  {np.median(base_sharpes):>+8.2f}  "
          f"{np.median(gate_sharpes):>+8.2f}")
    print(f"  {'Min OOS Sharpe':<25}  {min(base_sharpes):>+8.2f}  "
          f"{min(gate_sharpes):>+8.2f}")
    print(f"  {'% Positive':<25}  "
          f"{100*sum(s>0 for s in base_sharpes)/len(base_sharpes):>7.0f}%  "
          f"{100*sum(s>0 for s in gate_sharpes)/len(gate_sharpes):>7.0f}%")

    # ---- Verdict ----
    worst_base = min(base_sharpes)
    worst_gate = min(gate_sharpes)
    mean_delta = np.mean(gate_sharpes) - np.mean(base_sharpes)
    print(f"\n{'=' * 75}")
    print(f"  VERDICT (per HYPOTHESIS.md pass criteria)")
    print(f"{'=' * 75}")
    print(f"  Worst OOS lifted from {worst_base:+.2f} -> {worst_gate:+.2f}  "
          f"({'GOOD' if worst_gate > worst_base else 'NO'})")
    print(f"  Mean OOS Sharpe delta:  {mean_delta:+.2f}  "
          f"({'GOOD' if mean_delta > 0 else 'BAD' if mean_delta < -0.1 else 'NEUTRAL'})")
    print(f"  All FTMO PASS:          checked above")


if __name__ == "__main__":
    main()
