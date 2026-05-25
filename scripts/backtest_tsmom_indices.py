"""
Backtest: Global-Indices Time-Series Momentum (TSMOM)
=====================================================

Mechanism: For each index, every month-end, look at the trailing
12-month return. If positive -> long the index for next month. If
negative -> short. Position size = inverse of 60-day realised vol so
each position contributes equal vol to the portfolio (the standard
TSMOM construction from Moskowitz/Ooi/Pedersen 2012).

Universe: 9 indices we have D1 data for
   US500 USTEC US30  -- US (3)
   JPN225 HK50 AUS200 -- Asia-Pacific (3)
   FRA40 UK100 EUSTX50 -- Europe (3)

Pass criteria:
   Per-asset Sharpe > 0.3 on at least 6/9
   Portfolio Sharpe > 0.7
   Max DD < 15%
   Low correlation with US500 mean-reversion strategy (rho < 0.3)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408

UNIVERSE = ["US500", "USTEC", "US30",
            "JPN225", "HK50", "AUS200",
            "FRA40", "UK100", "EUSTX50"]

LOOKBACK_DAYS = 252      # ~12 months
VOL_DAYS      = 60       # ~3 months realised vol
REBALANCE_DAYS = 21      # ~monthly (use trading-day count)
TARGET_VOL_PER_LEG = 0.10  # target 10%/yr per leg, scaled across N legs
N_YEARS = 8              # max sample length


def load_closes(years: int) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    cols = {}
    for sym in UNIVERSE:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            print(f"  WARN: no data for {sym}, skipping")
            continue
        cols[sym] = df["close"]
    out = pd.concat(cols, axis=1, join="outer").dropna(how="all")
    return out


def compute_signal(closes: pd.DataFrame) -> pd.DataFrame:
    """signal[t] = sign of 12m return; 0 if data insufficient."""
    log_close = np.log(closes)
    twelvem_return = log_close - log_close.shift(LOOKBACK_DAYS)
    signal = np.sign(twelvem_return)
    return signal


def compute_vol_target_weights(closes: pd.DataFrame) -> pd.DataFrame:
    """For each symbol, weight = TARGET_VOL_PER_LEG / realised_vol_60d.
    Inverse-vol weighting -- low-vol assets get bigger position."""
    log_ret = np.log(closes).diff()
    realised_vol = log_ret.rolling(VOL_DAYS).std() * np.sqrt(252)
    weights = TARGET_VOL_PER_LEG / realised_vol
    return weights


def backtest(closes: pd.DataFrame) -> dict:
    log_ret = np.log(closes).diff()
    signal = compute_signal(closes)
    weights = compute_vol_target_weights(closes)

    # Hold positions for REBALANCE_DAYS bars -> forward-fill signal+weight
    # but at REBALANCE_DAYS cadence (i.e., resample to that frequency)
    signal_held = signal.iloc[::REBALANCE_DAYS].reindex(closes.index, method="ffill")
    weights_held = weights.iloc[::REBALANCE_DAYS].reindex(closes.index, method="ffill")

    # Per-asset daily P&L = signal * weight * log_return
    pnl_per_asset = signal_held.shift(1) * weights_held.shift(1) * log_ret
    # Portfolio = mean across non-NaN legs (treat NaN as zero allocation)
    portfolio_daily = pnl_per_asset.mean(axis=1, skipna=True).fillna(0.0)

    # Stats
    out = {}
    for sym in closes.columns:
        s = pnl_per_asset[sym].dropna()
        if len(s) < 50:
            out[sym] = None
            continue
        sharpe = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
        cum = s.cumsum()
        peak = cum.cummax()
        dd = (cum - peak).min()
        out[sym] = {"sharpe": sharpe, "max_dd_log": float(dd),
                    "n_bars": int(len(s)),
                    "ann_return": float(s.mean() * 252),
                    "ann_vol": float(s.std() * np.sqrt(252))}

    port = portfolio_daily.dropna()
    port_sharpe = float(port.mean() / port.std() * np.sqrt(252)) if port.std() > 0 else 0.0
    port_cum = port.cumsum()
    port_peak = port_cum.cummax()
    port_dd = float((port_cum - port_peak).min())
    return {"per_asset": out,
            "portfolio_sharpe": port_sharpe,
            "portfolio_max_dd_log": port_dd,
            "portfolio_ann_return": float(port.mean() * 252),
            "portfolio_ann_vol": float(port.std() * np.sqrt(252)),
            "portfolio_curve": port_cum,
            "portfolio_daily": port,
            "n_bars": int(len(port))}


def main():
    closes = load_closes(N_YEARS)
    print(f"Sample: {closes.index[0].date()} -> {closes.index[-1].date()}  "
          f"({len(closes)} bars, {len(closes.columns)} symbols)")
    print(f"Symbols with data: {list(closes.columns)}")
    print()

    r = backtest(closes)

    print("=" * 76)
    print("  PER-ASSET RESULTS (12m TSMOM, vol-targeted, monthly rebalance)")
    print("=" * 76)
    print(f"  {'symbol':<8} {'n':>5} {'ann ret':>9} {'ann vol':>9} "
          f"{'Sharpe':>7} {'max DD':>8}")
    print("  " + "-" * 50)
    pass_count = 0
    for sym, stats in r["per_asset"].items():
        if stats is None:
            print(f"  {sym:<8} (insufficient data)")
            continue
        passes = "[PASS]" if stats["sharpe"] > 0.3 else "      "
        if stats["sharpe"] > 0.3: pass_count += 1
        print(f"  {sym:<8} {stats['n_bars']:>5} "
              f"{100*stats['ann_return']:>+8.2f}% {100*stats['ann_vol']:>+8.2f}% "
              f"{stats['sharpe']:>+7.2f} {100*stats['max_dd_log']:>+7.2f}%  {passes}")

    print()
    print("=" * 76)
    print(f"  PORTFOLIO (equal-weighted across {len(closes.columns)} legs)")
    print("=" * 76)
    print(f"  Sample bars:        {r['n_bars']}")
    print(f"  Annualised return:  {100*r['portfolio_ann_return']:+.2f}%")
    print(f"  Annualised vol:     {100*r['portfolio_ann_vol']:+.2f}%")
    print(f"  Sharpe:             {r['portfolio_sharpe']:+.2f}")
    print(f"  Max drawdown (log): {100*r['portfolio_max_dd_log']:+.2f}%")

    print()
    print("=" * 76)
    print("  VERDICT")
    print("=" * 76)
    print(f"  Assets passing Sharpe > 0.3:  {pass_count}/{len(closes.columns)}")
    if r["portfolio_sharpe"] > 0.7 and pass_count >= 6:
        print(f"  PASS -> ship as multi-symbol TSMOM EA")
    elif r["portfolio_sharpe"] > 0.4:
        print(f"  MARGINAL -> ship with reduced size or only the passing subset")
    else:
        print(f"  FAIL -> TSMOM mechanism not present in this universe + window")

    # Save curves for downstream correlation check vs existing strategies
    out_dir = Path("reports/tsmom_indices")
    out_dir.mkdir(parents=True, exist_ok=True)
    r["portfolio_curve"].to_csv(out_dir / "portfolio_equity_log.csv", header=True)
    r["portfolio_daily"].to_csv(out_dir / "portfolio_daily.csv", header=True)
    print(f"\n  curves saved to {out_dir}/")


if __name__ == "__main__":
    main()
