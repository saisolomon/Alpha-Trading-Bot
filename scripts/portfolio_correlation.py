"""
Compute equity-curve correlation between Index MR and FX MR strategies,
then evaluate the equal-weight portfolio's metrics.

The diversification value of the second strategy depends on this correlation:
  rho < 0.3  -> meaningful diversification (portfolio Sharpe > strategy avg)
  rho 0.3-0.6 -> moderate diversification
  rho > 0.7  -> redundant strategies (no portfolio benefit)

Usage:
    uv run python scripts/portfolio_correlation.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408


def load_indices_data(years: int = 12) -> dict:
    import pandas as pd
    from data.cache import ParquetCache
    from scripts.run_meanrev_backtest import INDEX_SPECS
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    return {
        sym: df for sym in INDEX_SPECS
        for df in [cache.read(sym, D1, start, end)]
        if df is not None and not df.empty
    }


def load_fx_data(years: int = 12) -> dict:
    import pandas as pd
    from data.cache import ParquetCache
    from scripts.run_fx_meanrev_backtest import FX_SPECS
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    return {
        sym: df for sym in FX_SPECS
        for df in [cache.read(sym, D1, start, end)]
        if df is not None and not df.empty
    }


def run_index_mr(data, capital: float):
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine
    from scripts.run_meanrev_backtest import INDEX_SPECS
    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=20, entry_z_threshold=1.0,
        exit_z_threshold=0.5, max_hold_bars=10,
        atr_stop_mult=1.5, atr_tp_mult=2.0,
        require_long_term_uptrend=True,
    )
    specs = {s: INDEX_SPECS[s] for s in data}
    engine = MeanRevEngine(specs, per_trade_risk_pct=0.005)
    return engine.run(data, config, initial_capital=capital)


def run_fx_mr(data, capital: float):
    from strategies.index_meanrev.signal import MeanRevConfig
    from backtest.meanrev_engine import MeanRevEngine
    from scripts.run_fx_meanrev_backtest import FX_SPECS
    config = MeanRevConfig(
        symbols=tuple(data.keys()),
        formation_bars=10, entry_z_threshold=1.0,
        exit_z_threshold=0.5, max_hold_bars=10,
        atr_stop_mult=1.5, atr_tp_mult=2.0,
        require_long_term_uptrend=False,
        long_term_drawdown_floor=0.85,
    )
    specs = {s: FX_SPECS[s] for s in data}
    engine = MeanRevEngine(specs, per_trade_risk_pct=0.005)
    return engine.run(data, config, initial_capital=capital)


def metrics(rets, label: str) -> dict:
    import numpy as np
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    eq = (1 + rets).cumprod()
    rmax = eq.cummax()
    max_dd = float(((eq - rmax) / rmax).min())
    total_ret = float(eq.iloc[-1] - 1.0)
    n_days = (rets.index[-1] - rets.index[0]).days
    cagr = (eq.iloc[-1]) ** (365.0 / max(n_days, 1)) - 1.0 if n_days > 0 else 0.0
    return {
        "label": label,
        "sharpe": sharpe, "max_dd": max_dd,
        "total_return": total_ret, "cagr": cagr, "ann_vol": float(rets.std() * np.sqrt(252)),
    }


def print_metrics(m: dict) -> None:
    print(f"  {m['label']:<22}  Sharpe {m['sharpe']:>+5.2f}  "
          f"CAGR {100*m['cagr']:>+5.2f}%  "
          f"Vol {100*m['ann_vol']:>5.2f}%  "
          f"MaxDD {100*m['max_dd']:>+5.2f}%  "
          f"TotalRet {100*m['total_return']:>+6.2f}%")


def main() -> None:
    import pandas as pd
    import numpy as np
    capital = 100_000.0

    print("Loading 12y data and running both strategies...")
    idx_data = load_indices_data()
    fx_data = load_fx_data()
    print(f"  Index symbols: {list(idx_data.keys())}")
    print(f"  FX symbols:    {list(fx_data.keys())}")

    print("\nRunning Index MR backtest...")
    idx_result = run_index_mr(idx_data, capital)
    print(f"  done: {len(idx_result.trades)} trades, "
          f"final equity ${idx_result.equity_curve.iloc[-1]:,.0f}")

    print("Running FX MR backtest...")
    fx_result = run_fx_mr(fx_data, capital)
    print(f"  done: {len(fx_result.trades)} trades, "
          f"final equity ${fx_result.equity_curve.iloc[-1]:,.0f}")

    # Align equity curves on shared dates
    idx_eq = idx_result.equity_curve
    fx_eq = fx_result.equity_curve
    df = pd.DataFrame({"idx": idx_eq, "fx": fx_eq}).dropna(how="all")
    df = df.ffill().dropna()

    idx_rets = df["idx"].pct_change().dropna()
    fx_rets = df["fx"].pct_change().dropna()
    paired = pd.DataFrame({"idx": idx_rets, "fx": fx_rets}).dropna()

    rho = float(paired["idx"].corr(paired["fx"]))
    print(f"\n{'=' * 70}")
    print(f"  CORRELATION ANALYSIS  (n={len(paired)} aligned days)")
    print(f"{'=' * 70}")
    print(f"  Pearson correlation of daily returns: {rho:+.3f}")

    if abs(rho) < 0.2:
        verdict = "EXCELLENT diversification (rho < 0.2)"
    elif abs(rho) < 0.4:
        verdict = "GOOD diversification (rho < 0.4)"
    elif abs(rho) < 0.6:
        verdict = "MODERATE diversification (rho < 0.6)"
    else:
        verdict = "POOR diversification (strategies overlap)"
    print(f"  Verdict: {verdict}")

    # Equal-weight portfolio metrics
    print(f"\n{'=' * 70}")
    print(f"  STAND-ALONE vs EQUAL-WEIGHT PORTFOLIO")
    print(f"{'=' * 70}")
    print_metrics(metrics(paired["idx"], "Index MR (alone)"))
    print_metrics(metrics(paired["fx"], "FX MR (alone)"))
    pf_rets = 0.5 * paired["idx"] + 0.5 * paired["fx"]
    print_metrics(metrics(pf_rets, "50/50 portfolio"))

    # Inverse-vol weighted
    sd_idx = paired["idx"].std()
    sd_fx = paired["fx"].std()
    if sd_idx > 0 and sd_fx > 0:
        w_idx = (1 / sd_idx) / (1 / sd_idx + 1 / sd_fx)
        w_fx = 1 - w_idx
        ivp_rets = w_idx * paired["idx"] + w_fx * paired["fx"]
        print_metrics(metrics(ivp_rets, f"Inv-vol ({w_idx:.0%}/{w_fx:.0%})"))

    # FTMO simulation on the 50/50 portfolio
    print(f"\n{'=' * 70}")
    print(f"  FTMO SIMULATION ON 50/50 PORTFOLIO")
    print(f"{'=' * 70}")
    pf_eq = capital * (1 + pf_rets).cumprod()
    pf_eq_low = pf_eq * 0.998  # crude approximation; real impl would track per-strategy lows
    from backtest.ftmo_sim import FTMOSimulator
    from risk.ftmo import FTMOAccountType
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=capital, opening_balance=capital,
    )
    rep = sim.run(pf_eq, equity_low=pf_eq_low)
    status = "PASS" if rep.passed else "FAIL"
    print(f"  Status: {status}")
    print(f"  Daily-line breaches: {rep.ftmo_daily_line_breach_count}")
    print(f"  Max-line breaches:   {rep.ftmo_max_line_breach_count}")
    print(f"  Min daily distance:  ${rep.min_daily_distance:,.0f}")

    # Save both equity curves for inspection
    out = Path("reports/portfolio")
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "equity_curves.csv")
    print(f"\n  Equity curves saved to {out}/equity_curves.csv")


if __name__ == "__main__":
    main()
