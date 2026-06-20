"""Robustness battery for the TS-momentum edge — is it real/durable or fragile? (2026-06-20)

Before mapping to FTMO, stress the TS-12m winner four ways:
  1. PARAMETER PLATEAU — sweep lookback 6..24m. A smooth plateau = robust; a lone 12m spike = overfit.
  2. LEAVE-ONE-CLASS-OUT — drop crypto / bonds / commodities / equities. Survives = not driven by one bloc.
  3. COST STRESS — 10/20/30/50 bps. Survives to ~30bps = deployable.
  4. FTMO-MAPPABLE SUBSET — the decisive one: only assets with an FTMO analog (index CFDs, metals,
     oil, FX/dollar, crypto; DROP bonds/credit/REIT which FTMO lacks). If the edge dies here, it
     was living in instruments we can't trade — fatal for FTMO deployment.

Run: python backtest/momentum_robustness.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import backtest.momentum_backtest as mb     # sets utf-8 stdout once; reuse run_spec/stats/load

CLASSES = {
    "equities": ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    "bonds_credit": ["TLT", "IEF", "LQD", "HYG"],
    "commodities": ["GLD", "SLV", "USO", "DBC"],
    "realassets_fx": ["VNQ", "UUP"],
    "crypto": ["BTC-USD", "ETH-USD"],
}
# FTMO has analogs for index CFDs, metals, oil, FX/dollar, crypto — but NOT bonds/credit/REIT.
FTMO_MAPPABLE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "SLV", "USO", "DBC", "UUP", "BTC-USD", "ETH-USD"]


def run(mprice, mret, cols, lookback=12, cost=10.0):
    old = mb.COST_BPS
    mb.COST_BPS = cost
    try:
        r = mb.run_spec(mprice[cols], mret[cols], "TS", lookback)
    finally:
        mb.COST_BPS = old
    return r, mb.stats(r)


def line(label, s):
    if s.get("n", 0) < 12:
        return f"| {label} | {s.get('n',0)} | — | — | — |"
    return (f"| {label} | {s['n']} | {s['sharpe']:+.2f} | {s['ann_ret']*100:+.1f}% | "
            f"{s['p_pos']*100:.0f}% |")


def main():
    mprice, mret = mb.load_monthly()
    allc = list(mprice.columns)
    print("# TS-momentum robustness battery\n")

    print("## 1. Parameter plateau (TS, all 17 assets, 10bps)\n")
    print("| lookback | months | Sharpe | ann.ret | P(edge>0) |")
    print("|---|---|---|---|---|")
    for lb in (6, 9, 10, 11, 12, 13, 15, 18, 24):
        _, s = run(mprice, mret, allc, lookback=lb)
        print(line(f"TS-{lb}m", s))

    print("\n## 2. Leave-one-class-out (TS-12m, 10bps)\n")
    print("| universe | months | Sharpe | ann.ret | P(edge>0) |")
    print("|---|---|---|---|---|")
    _, s = run(mprice, mret, allc); print(line("ALL (17)", s))
    for cls, members in CLASSES.items():
        cols = [c for c in allc if c not in members]
        _, s = run(mprice, mret, cols)
        print(line(f"drop {cls}", s))

    print("\n## 3. Cost stress (TS-12m, all 17)\n")
    print("| cost | months | Sharpe | ann.ret | P(edge>0) |")
    print("|---|---|---|---|---|")
    for c in (10, 20, 30, 50):
        _, s = run(mprice, mret, allc, cost=c); print(line(f"{c}bps", s))

    print("\n## 4. FTMO-MAPPABLE subset (decisive) — TS-12m, 20bps, no bonds/credit/REIT\n")
    print("| universe | months | Sharpe | ann.ret | P(edge>0) |")
    print("|---|---|---|---|---|")
    _, s_all = run(mprice, mret, allc, cost=20); print(line("ALL (ref, 20bps)", s_all))
    _, s_ftmo = run(mprice, mret, FTMO_MAPPABLE, cost=20); print(line("FTMO-mappable (12)", s_ftmo))

    print("\n## Verdict")
    ok_ftmo = s_ftmo.get("sharpe", 0) > 0.3 and s_ftmo.get("p_pos", 0) > 0.9
    print(f"- FTMO-mappable subset (20bps): Sharpe {s_ftmo.get('sharpe',0):+.2f}, "
          f"P(edge>0) {s_ftmo.get('p_pos',0)*100:.0f}% -> "
          f"{'SURVIVES — edge lives in tradable instruments, green-light the mapping' if ok_ftmo else 'WEAK/FAILS — edge depends on non-FTMO instruments, reconsider'}.")


if __name__ == "__main__":
    main()
