"""First walk-forward / full-history backtest of the ported roster strategies (2026-06-20).

Loads the MT5 parity spine (broker-time, labeled UTC for the engine), runs each ported
Strategy through BacktestEngine over its full cached history, and reports trade counts +
edge metrics. This is the first real n=hundreds backtest the pivot was built for.

PARITY NOTE: the spine is RAW BROKER time; we tz-localize it as UTC purely to satisfy the
engine's tz-aware requirement. The strategies read state.timestamp.hour in broker time,
exactly as the live EAs do (broker TimeCurrent()), so session-hour logic is parity-faithful.

Run: python backtest/run_roster.py
"""
from __future__ import annotations
import io
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backtest.engine import BacktestEngine
from backtest.costs import GBPUSD_SPEC, XAUUSD_SPEC, AUDJPY_SPEC
from strategies.london_momo import LondonMomoStrategy
from strategies.london_fix import LondonFixStrategy
from strategies.audjpy_trend import AudjpyTrendStrategy

DATA = REPO / "data" / "history" / "mt5"
INITIAL = 200_000.0

ROSTER = [
    ("LondonMomo  (GBPUSD M15)", LondonMomoStrategy, "GBPUSD", "M15", GBPUSD_SPEC),
    ("LondonFix   (XAUUSD M15)", LondonFixStrategy, "XAUUSD", "M15", XAUUSD_SPEC),
    ("AudjpyTrend (AUDJPY H4)",  AudjpyTrendStrategy, "AUDJPY", "H4", AUDJPY_SPEC),
]


def load_spine(symbol: str, tf: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA / f"{symbol}_{tf}.parquet").rename(columns={"volume": "tick_volume"})
    t = pd.to_datetime(df["time"])
    df["time"] = t.dt.tz_localize("UTC") if t.dt.tz is None else t.dt.tz_convert("UTC")
    return df.set_index("time").sort_index()


def metrics(res, initial: float) -> dict:
    tr = res.trades
    n = len(tr)
    if n == 0:
        return {"n": 0}
    pnls = np.array([t.net_pnl for t in tr])
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    gp, gl = wins.sum(), -losses.sum()
    eq = res.equity_curve.values
    eql = res.equity_low.values
    peak = np.maximum.accumulate(eq)
    dd = (peak - eql)
    max_dd = float(dd.max())
    # daily Sharpe from equity-curve returns resampled to day
    daily = res.equity_curve.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    reasons = {}
    for t in tr:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    # Bootstrap: P(mean per-trade P&L > 0) under resampling — the project's
    # anti-naive-Sharpe gate. Low p_pos = significantly losing edge.
    rng = np.random.default_rng(42)
    boot = rng.choice(pnls, size=(5000, n), replace=True).mean(axis=1)
    p_pos = float((boot > 0).mean())
    return {
        "n": n, "win_rate": len(wins) / n, "pf": (gp / gl) if gl > 0 else float("inf"),
        "net": pnls.sum(), "ret_pct": pnls.sum() / initial * 100,
        "avg_win": wins.mean() if len(wins) else 0, "avg_loss": losses.mean() if len(losses) else 0,
        "max_dd": max_dd, "max_dd_pct": max_dd / initial * 100, "sharpe": sharpe,
        "p_pos": p_pos, "reasons": reasons,
    }


def main():
    print(f"# Roster backtest — MT5 spine, initial ${INITIAL:,.0f}\n")
    rows = []
    for label, Strat, sym, tf, spec in ROSTER:
        try:
            data = load_spine(sym, tf)
            strat = Strat(spec=spec)
            eng = BacktestEngine(data, spec)
            res = eng.run(strat, initial_capital=INITIAL, min_bars_warmup=50)
            m = metrics(res, INITIAL)
            span = f"{data.index[0]:%Y-%m-%d}..{data.index[-1]:%Y-%m-%d}"
            rows.append((label, span, len(data), m))
        except Exception as e:
            import traceback
            print(f"## {label}: ERROR\n```\n{traceback.format_exc()}\n```")
            rows.append((label, "ERR", 0, {"n": 0}))

    print("| strategy | history | bars | trades | win% | PF | net $ | ret% | maxDD% | Sharpe | P(edge>0) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, span, nb, m in rows:
        if m["n"] == 0:
            print(f"| {label} | {span} | {nb} | 0 | — | — | — | — | — | — | — |")
            continue
        print(f"| {label} | {span} | {nb:,} | {m['n']} | {m['win_rate']*100:.0f}% | "
              f"{m['pf']:.2f} | ${m['net']:,.0f} | {m['ret_pct']:+.1f}% | "
              f"{m['max_dd_pct']:.1f}% | {m['sharpe']:.2f} | {m['p_pos']*100:.1f}% |")
    print()
    for label, span, nb, m in rows:
        if m["n"]:
            print(f"- {label}: exits {m['reasons']}  avg_win ${m['avg_win']:,.0f}  avg_loss ${m['avg_loss']:,.0f}")


if __name__ == "__main__":
    main()
