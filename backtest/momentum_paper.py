"""M11 step 1 — forward-paper harness for the momentum edge (2026-06-25).

Momentum is validated in BACKTEST (Sharpe ~0.6, White's RC p=0.001), but every backtest is
partly snooped. The only honest test left is FORWARD performance on data that didn't exist when
we built it. This harness FREEZES the strategy spec on first run and, every run, recomputes the
deterministic (no-look-ahead) daily equity of the momentum book and reports the segment SINCE
the freeze date = genuine out-of-sample. No capital, no broker — just an accumulating, un-snooped
track record to clear before self-funded deployment (IBKR / any broker, monthly rebalance).

Frozen spec: TS-12m time-series momentum, 17-asset universe, inverse-vol weighted, 10% vol target,
20bps/turnover. (The White's-RC survivor; self-funded sizing = full 10% vol, no prop DD floor.)

Run (any time; daily is plenty): python backtest/momentum_paper.py
"""
from __future__ import annotations
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "data" / "forward_paper"
STATE = STATE_DIR / "state.json"
LOG = STATE_DIR / "momentum_equity.csv"

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG",
            "GLD", "SLV", "USO", "DBC", "VNQ", "UUP", "BTC-USD", "ETH-USD"]
SPEC = {"strategy": "TS-12m", "lookback": 12, "skip": 1, "vol_target": 0.10,
        "cost_bps": 20.0, "vol_window": 12, "universe": UNIVERSE}


def momentum_daily_returns(spec) -> pd.Series:
    """Deterministic daily equity returns of the monthly-rebalanced TS-12m book. No look-ahead:
    month-end weights (from data through that close) are held over the following month."""
    px = yf.download(spec["universe"], period="max", interval="1d",
                     progress=False, auto_adjust=True)["Close"].asfreq("B").ffill(limit=3)
    dret = px.pct_change()
    mpx = px.resample("ME").last()
    mret = mpx.pct_change()
    sig = mpx.shift(spec["skip"]) / mpx.shift(spec["lookback"]) - 1.0
    vol = mret.rolling(spec["vol_window"]).std()
    avail = sig.notna() & vol.notna() & (vol > 0)
    raw = np.sign(sig).where(avail) * (1.0 / vol).where(avail)
    gross = raw.abs().sum(axis=1).replace(0, np.nan)
    w_month = raw.div(gross, axis=0).fillna(0.0)
    w_daily = w_month.reindex(dret.index, method="ffill").shift(1)
    port = (w_daily * dret).sum(axis=1)
    turn = (w_month - w_month.shift(1)).abs().sum(axis=1).reindex(dret.index).fillna(0.0)
    port = port - turn * (spec["cost_bps"] / 1e4)
    realized = port.rolling(60).std()
    scale = ((spec["vol_target"] / np.sqrt(252)) / realized.shift(1)).clip(upper=3.0).fillna(0.0)
    return (port * scale).dropna()


def stats(r):
    if len(r) < 2:
        return dict(n=len(r), ann=0, sharpe=0, total=0, maxdd=0)
    eq = (1 + r).cumprod()
    return dict(n=len(r), ann=(r.mean()*252), sharpe=(r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0),
                total=(eq.iloc[-1]-1), maxdd=((eq/eq.cummax()-1).min()))


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fresh = not STATE.exists()
    if fresh:
        STATE.write_text(json.dumps({"freeze_date": today, "spec": SPEC,
                                     "note": "forward OOS validation of momentum before self-funded deployment"}, indent=2))
        print(f"# Momentum forward-paper — STARTED (spec frozen {today})\n")
    st = json.loads(STATE.read_text())
    freeze = st["freeze_date"]

    r = momentum_daily_returns(st["spec"])
    fwd = r[r.index >= pd.Timestamp(freeze)]
    full, fs = stats(r), stats(fwd)

    # append today's forward equity point (idempotent on date)
    eq_fwd = float((1 + fwd).prod()) if len(fwd) else 1.0
    row = pd.DataFrame([{"date": today, "fwd_days": len(fwd), "fwd_equity": round(eq_fwd, 5),
                         "fwd_ann_pct": round(fs["ann"]*100, 2), "fwd_sharpe": round(fs["sharpe"], 2)}])
    if LOG.exists():
        old = pd.read_csv(LOG)
        old = old[old["date"] != today]
        row = pd.concat([old, row], ignore_index=True)
    row.to_csv(LOG, index=False)

    print(f"frozen spec: {st['spec']['strategy']}, {len(st['spec']['universe'])} assets, "
          f"{st['spec']['vol_target']:.0%} vol, {st['spec']['cost_bps']:.0f}bps")
    print(f"freeze date: {freeze}   today: {today}\n")
    print("| segment | days | ann.ret | Sharpe | total | maxDD |")
    print("|---|---|---|---|---|---|")
    print(f"| full history (reference) | {full['n']} | {full['ann']*100:+.1f}% | {full['sharpe']:+.2f} | "
          f"{full['total']*100:+.0f}% | {full['maxdd']*100:.1f}% |")
    print(f"| **FORWARD (OOS)** | {fs['n']} | {fs['ann']*100:+.1f}% | {fs['sharpe']:+.2f} | "
          f"{fs['total']*100:+.1f}% | {fs['maxdd']*100:.1f}% |")
    if fs["n"] < 60:
        print(f"\n(forward segment is {fs['n']} trading days — momentum is monthly, so a meaningful "
              f"OOS read needs ~6-12+ months. Patience is the test. Run periodically; the FORWARD row "
              f"is the un-snooped evidence that decides real-capital deployment.)")
    print(f"\nlog: {LOG}")


if __name__ == "__main__":
    main()
