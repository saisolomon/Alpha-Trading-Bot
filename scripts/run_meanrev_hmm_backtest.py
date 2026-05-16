"""
Run the Index MR strategy with vs without the HMM regime gate.

Mirrors scripts/run_meanrev_gated_backtest.py but uses HMMRegimeGate
(hmmlearn-based, with returns + realized vol + cross-asset signals as
emission variables) instead of the simple observable Markov chain.

The HMM is what Roan's article points to as the better mechanism. If THIS
also fails to lift the 2019-2020 OOS Sharpe and the average, the regime-
gating direction is dead on this universe.

Usage:
    uv run python scripts/run_meanrev_hmm_backtest.py
    uv run python scripts/run_meanrev_hmm_backtest.py --bear-threshold 0.30
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
    p = argparse.ArgumentParser(description="MR + HMM regime gate")
    p.add_argument("--years", type=int, default=12)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--is-months", type=int, default=36)
    p.add_argument("--oos-months", type=int, default=12)
    p.add_argument("--formation", type=int, default=20)
    p.add_argument("--entry-z", type=float, default=1.0)
    # HMM
    p.add_argument("--n-states", type=int, default=3)
    p.add_argument("--vol-window", type=int, default=20)
    p.add_argument("--cross-window", type=int, default=60)
    p.add_argument("--initial-train", type=int, default=504)
    p.add_argument("--refit-every", type=int, default=63)
    p.add_argument("--n-init", type=int, default=5)
    p.add_argument("--bear-threshold", type=float, default=0.40)
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


def make_hmm_gate_factory(args, all_prices: dict):
    from strategies.regime_markov.hmm import (
        HMMConfig, HMMGateConfig, HMMRegimeGate,
    )
    hmm_cfg = HMMConfig(
        n_states=args.n_states,
        vol_window=args.vol_window,
        cross_window=args.cross_window,
        initial_train_bars=args.initial_train,
        refit_every=args.refit_every,
        n_init=args.n_init,
    )
    gate_cfg = HMMGateConfig(bear_state_threshold=args.bear_threshold)

    def factory(symbol, df):
        # Use the FULL cross-asset universe (all_prices) so the cross-asset
        # signal is meaningful. Walk-forward correctness: hmm.py only uses
        # bars [0, bar_i] when answering at bar_i, regardless of how many
        # bars are in the input.
        return HMMRegimeGate(
            prices_per_symbol=all_prices,
            target_symbol=symbol,
            config=hmm_cfg,
            gate_config=gate_cfg,
        )
    return factory


def main() -> None:
    args = parse_args()

    print(f"Loading {args.years}y D1 data...")
    data = load_data(args.years)
    if not data:
        print("No cached data. Run scripts/fetch_backtest_data.py first.")
        sys.exit(1)
    print(f"  {len(data)} symbols: {list(data.keys())}")

    all_prices = {sym: df["close"] for sym, df in data.items()}

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
    gate_factory = make_hmm_gate_factory(args, all_prices)

    print("\nRunning BASELINE (no gate)...")
    engine_baseline = MeanRevEngine(specs, per_trade_risk_pct=0.005)
    baseline_full = engine_baseline.run(data, config, initial_capital=args.capital)

    print("Running HMM-GATED (this is slower -- Baum-Welch refits)...")
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

    # Full period comparison
    print(f"\n{'=' * 75}")
    print(f"  FULL PERIOD: HMM gate (bear_thresh={args.bear_threshold})")
    print(f"{'=' * 75}")
    bs = summarize_window("full", baseline_full, args.capital)
    gs = summarize_window("full", gated_full, args.capital)
    print(f"  {'metric':<14}  {'BASELINE':>12}  {'HMM-GATED':>12}  {'delta':>10}")
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

    # Walk-forward
    import numpy as np
    print(f"\n{'=' * 75}")
    print(f"  WALK-FORWARD: HMM gate ({len(baseline_wf)} OOS windows)")
    print(f"{'=' * 75}")
    print(f"  {'window':<25}  {'BASE Sh':>8}  {'HMM Sh':>8}  "
          f"{'BASE trd':>9}  {'HMM trd':>9}  {'BASE FTMO':>10}  {'HMM FTMO':>10}")
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

    print(f"\n  {'AGGREGATE':<25}  {'BASELINE':>8}  {'HMM':>8}")
    print(f"  {'Mean OOS Sharpe':<25}  {np.mean(base_sharpes):>+8.2f}  "
          f"{np.mean(gate_sharpes):>+8.2f}")
    print(f"  {'Median OOS Sharpe':<25}  {np.median(base_sharpes):>+8.2f}  "
          f"{np.median(gate_sharpes):>+8.2f}")
    print(f"  {'Min OOS Sharpe':<25}  {min(base_sharpes):>+8.2f}  "
          f"{min(gate_sharpes):>+8.2f}")
    print(f"  {'% Positive':<25}  "
          f"{100*sum(s>0 for s in base_sharpes)/len(base_sharpes):>7.0f}%  "
          f"{100*sum(s>0 for s in gate_sharpes)/len(gate_sharpes):>7.0f}%")

    worst_base = min(base_sharpes)
    worst_gate = min(gate_sharpes)
    mean_delta = np.mean(gate_sharpes) - np.mean(base_sharpes)
    print(f"\n  Worst OOS lifted: {worst_base:+.2f} -> {worst_gate:+.2f}  "
          f"({'GOOD' if worst_gate > worst_base else 'NO'})")
    print(f"  Mean OOS Sharpe delta: {mean_delta:+.2f}  "
          f"({'GOOD' if mean_delta > 0.1 else 'BAD' if mean_delta < -0.1 else 'NEUTRAL'})")


if __name__ == "__main__":
    main()
