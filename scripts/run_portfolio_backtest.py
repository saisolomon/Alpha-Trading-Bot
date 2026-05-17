"""
Run the multi-strategy portfolio: HMM-gated Index MR + Gold-Silver Pairs.

Computes:
  1. Each strategy standalone (Sharpe, Max DD, FTMO sim)
  2. Pairwise correlation
  3. Three combined portfolios under equal / inverse-vol / risk-parity weights
  4. FTMO sim on each combined portfolio

If the combined portfolio's Sharpe exceeds the better individual leg's
Sharpe (or matches it with substantially lower drawdown), the
diversification has portfolio value.

Usage:
    uv run python scripts/run_portfolio_backtest.py
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
    p = argparse.ArgumentParser(description="Multi-strategy portfolio backtest")
    p.add_argument("--years", type=int, default=12)
    p.add_argument("--capital", type=float, default=100_000)
    # Index MR config
    p.add_argument("--mr-formation", type=int, default=20)
    p.add_argument("--mr-entry-z", type=float, default=1.0)
    p.add_argument("--mr-risk-pct", type=float, default=0.005)
    p.add_argument("--use-hmm", action="store_true", default=True,
                   help="Enable HMM regime gate on the Index MR leg")
    # Pairs config
    p.add_argument("--pairs-entry-z", type=float, default=2.5)
    p.add_argument("--pairs-exit-z", type=float, default=0.5)
    p.add_argument("--pairs-cat-z", type=float, default=5.0)
    p.add_argument("--pairs-risk-pct", type=float, default=0.005)
    return p.parse_args()


def load_index_data(years: int):
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


def load_metals_data(years: int):
    import pandas as pd
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    out: dict[str, pd.DataFrame] = {}
    for sym in ["XAUUSD", "XAGUSD"]:
        df = cache.read(sym, D1, start, end)
        if df is not None and not df.empty:
            out[sym] = df
    return out


def run_index_mr(args, data, with_hmm: bool):
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine
    from scripts.run_meanrev_backtest import INDEX_SPECS

    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=args.mr_formation,
        z_lookback_bars=252,
        entry_z_threshold=args.mr_entry_z,
        exit_z_threshold=0.5,
        max_hold_bars=10,
        atr_stop_mult=1.5,
        atr_tp_mult=2.0,
        require_long_term_uptrend=True,
    )
    specs = {s: INDEX_SPECS[s] for s in data}
    gate_factory = None
    if with_hmm:
        from strategies.regime_markov.hmm import HMMConfig, HMMGateConfig, HMMRegimeGate
        all_prices = {s: df["close"] for s, df in data.items()}
        hmm_cfg = HMMConfig()
        gcfg = HMMGateConfig()
        def gate_factory(symbol, df):
            return HMMRegimeGate(all_prices, symbol, hmm_cfg, gcfg)
    engine = MeanRevEngine(specs, per_trade_risk_pct=args.mr_risk_pct,
                            regime_gate_factory=gate_factory)
    return engine.run(data, config, initial_capital=args.capital)


def run_pairs(args, prices_xau, prices_xag):
    from strategies.metals_pairs.pairs import PairsConfig, PairsEngine
    from scripts.run_pairs_backtest import get_metals_specs
    config = PairsConfig(
        symbol_a="XAUUSD", symbol_b="XAGUSD",
        entry_z=args.pairs_entry_z, exit_z=args.pairs_exit_z,
        catastrophic_z=args.pairs_cat_z,
        per_trade_risk_pct=args.pairs_risk_pct,
    )
    engine = PairsEngine(get_metals_specs())
    return engine.run(prices_xau, prices_xag, config,
                      initial_capital=args.capital)


def run_ftmo(equity_curve, equity_low, capital):
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital, opening_balance=capital,
    )
    return sim.run(equity_curve, equity_low=equity_low)


def summarize_curve(label, equity, equity_low, capital, trades=None):
    import numpy as np
    r = equity.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    rmax = equity.cummax()
    max_dd = float(((equity - rmax) / rmax).min())
    n_days = (equity.index[-1] - equity.index[0]).days
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (365.0/max(n_days,1)) - 1.0 if n_days > 0 else 0.0
    total_ret = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    ftmo = run_ftmo(equity, equity_low, capital)
    print(f"  {label:<32}  Sharpe {sharpe:+5.2f}  CAGR {100*cagr:+5.2f}%  "
          f"TotalRet {100*total_ret:+6.2f}%  MaxDD {100*max_dd:+5.2f}%  "
          f"FTMO {'PASS' if ftmo.passed else 'FAIL'}")
    return {
        "label": label, "sharpe": sharpe, "cagr": cagr, "total_ret": total_ret,
        "max_dd": max_dd, "ftmo_pass": ftmo.passed,
    }


def main() -> None:
    args = parse_args()
    print(f"Loading {args.years}y D1 data...")
    idx_data = load_index_data(args.years)
    metals_data = load_metals_data(args.years)
    print(f"  Indices:  {list(idx_data.keys())}")
    print(f"  Metals:   {list(metals_data.keys())}")
    if not metals_data.get("XAUUSD") is not None or "XAGUSD" not in metals_data:
        print("Need XAUUSD + XAGUSD cached")
        sys.exit(1)

    # Standalone strategies
    print(f"\nRunning Index MR (HMM-gated)...")
    mr = run_index_mr(args, idx_data, with_hmm=args.use_hmm)
    print(f"Running Gold-Silver Pairs...")
    pairs = run_pairs(args, metals_data["XAUUSD"]["close"], metals_data["XAGUSD"]["close"])

    print(f"\n{'=' * 100}")
    print(f"  STANDALONE STRATEGY METRICS")
    print(f"{'=' * 100}")
    mr_s = summarize_curve("Index MR (HMM-gated)", mr.equity_curve, mr.equity_low, args.capital)
    pa_s = summarize_curve("Gold-Silver Pairs", pairs.equity_curve, pairs.equity_low, args.capital)

    # Correlation analysis
    import numpy as np
    import pandas as pd
    mr_rets = mr.equity_curve.pct_change().dropna()
    pa_rets = pairs.equity_curve.pct_change().dropna()
    paired = pd.concat([mr_rets, pa_rets], axis=1, join="inner").dropna()
    paired.columns = ["Index MR", "Pairs"]
    rho = float(paired["Index MR"].corr(paired["Pairs"]))
    print(f"\n{'=' * 100}")
    print(f"  CORRELATION ANALYSIS  (n={len(paired)} aligned days)")
    print(f"{'=' * 100}")
    print(f"  Pearson correlation: {rho:+.3f}")
    if abs(rho) < 0.2: verdict = "EXCELLENT diversification (|rho| < 0.2)"
    elif abs(rho) < 0.4: verdict = "GOOD diversification (|rho| < 0.4)"
    elif abs(rho) < 0.6: verdict = "MODERATE diversification (|rho| < 0.6)"
    else: verdict = "POOR diversification -- strategies overlap"
    print(f"  Verdict: {verdict}")

    # Combine under three weighting schemes
    from backtest.portfolio_combiner import (
        StrategyLeg, combine, WEIGHTING_SCHEMES,
    )
    legs = [
        StrategyLeg("Index MR", mr.equity_curve, mr.equity_low, args.capital, mr.trades),
        StrategyLeg("Pairs",   pairs.equity_curve, pairs.equity_low, args.capital, pairs.trades),
    ]

    print(f"\n{'=' * 100}")
    print(f"  COMBINED PORTFOLIO (initial_capital = $100k)")
    print(f"{'=' * 100}")
    for scheme in ["equal", "inverse_vol", "risk_parity"]:
        port = combine(legs, weighting=scheme, total_capital=args.capital)
        w_str = "  ".join(f"{k}={v:.2f}" for k, v in port.weights.items())
        print(f"  Weighting: {scheme:<14}  ({w_str})")
        summarize_curve(f"  -> {scheme} portfolio", port.equity_curve,
                          port.equity_low, args.capital)

    # FTMO PASS summary
    print(f"\n{'=' * 100}")
    print(f"  COMBINED-PORTFOLIO PASS/FAIL  (Index MR alone vs each portfolio scheme)")
    print(f"{'=' * 100}")
    best_sharpe = max(mr_s["sharpe"], pa_s["sharpe"])
    print(f"  Best standalone Sharpe: {best_sharpe:+.2f}")
    print(f"  -> A useful portfolio must EXCEED this (or match with smaller MaxDD).")


if __name__ == "__main__":
    main()
