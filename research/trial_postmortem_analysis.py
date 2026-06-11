"""Trial #1 post-mortem analysis (M10 Tier-1 #1).

Inputs (committed alongside this script):
  research/trial_2026-05_deals_raw.json   -- full Convex deals export (84 deals)
  research/trial_2026-05_factors.json     -- DXY/SPX/VIX daily closes (yfinance)

Window rule (per TRIAL_LOG.md "OFFICIAL END"):
  Realized (OUT) deals with 2026-05-28T00:00Z <= dealTime < 2026-06-10T22:00Z.
  22:00 UTC = 00:00 Europe/Prague (CEST) -- FTMO's day boundary ending 6/10.
  Entry (IN) deals are matched by positionId and may predate the window.
  Excluded deals are counted and reported, never silently dropped.

Run:  python research/trial_postmortem_analysis.py   (any Python >= 3.10, numpy)
"""
from __future__ import annotations

import io
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
WINDOW_START = datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
WINDOW_END = datetime(2026, 6, 10, 22, 0, tzinfo=timezone.utc).timestamp() * 1000
TRADING_DAYS = 10  # 5/28,29  6/1,2,3,4,5  6/8,9,10
CLUSTER_DAYS = {"2026-06-01", "2026-06-03", "2026-06-10"}

KNOWN_EAS = [
    "EURUSD_M15_LondonMomo", "EURUSD_M15_RSIFade", "US500_M15_ORB",
    "XAUUSD_M15_LondonFix", "BTCUSD_M15_TrendFollow", "GBPUSD_H1_SwingBreak",
    "XAUUSD_H1_NewsReaction", "AUDJPY_H4_TrendFollow", "EURGBP_H4_MeanReversion",
    "US100_H1_OvernightDrift",
]


def ea_canonical(raw: str | None) -> str | None:
    if not raw:
        return None
    for ea in KNOWN_EAS:
        if raw.startswith(ea):
            return ea
    return None


def utc_date(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    deals = json.loads((HERE / "trial_2026-05_deals_raw.json").read_text())
    factors = json.loads((HERE / "trial_2026-05_factors.json").read_text())

    # ---- pair deals into positions by positionId -------------------------
    by_pos: dict[int, list[dict]] = defaultdict(list)
    for d in deals:
        by_pos[d.get("positionId") or d["ticket"]].append(d)

    positions = []          # closed in-window
    excluded_out = 0        # OUT deals outside window
    open_at_cutoff = 0      # entries with no in-window exit
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d["entry"] == "IN"]
        outs = [d for d in ds if d["entry"] == "OUT"]
        if not outs:
            open_at_cutoff += 1
            continue
        out = max(outs, key=lambda d: d["dealTimeMs"])
        if not (WINDOW_START <= out["dealTimeMs"] < WINDOW_END):
            excluded_out += 1
            continue
        ein = min(ins, key=lambda d: d["dealTimeMs"]) if ins else None
        pnl = sum(d["profit"] + d.get("swap", 0) + d.get("commission", 0) for d in ds
                  if d["entry"] == "OUT" or d["entry"] == "IN")
        ea = ea_canonical(ein["eaName"] if ein else None) or ea_canonical(out.get("eaName"))
        positions.append({
            "pid": pid,
            "ea": ea or "UNATTRIBUTED",
            "symbol": out["symbol"].replace(".sim", ""),
            "side": (ein or out)["side"],
            "volume": out["volume"],
            "pnl": round(pnl, 2),
            "entry_ms": ein["dealTimeMs"] if ein else None,
            "exit_ms": out["dealTimeMs"],
            "exit_date": utc_date(out["dealTimeMs"]),
            "hold_h": round((out["dealTimeMs"] - ein["dealTimeMs"]) / 3.6e6, 2) if ein else None,
            "commission": round(sum(d.get("commission", 0) for d in ds), 2),
            "swap": round(sum(d.get("swap", 0) for d in ds), 2),
        })

    positions.sort(key=lambda p: p["exit_ms"])
    print(f"# dataset: {len(deals)} deals -> {len(positions)} closed positions in window; "
          f"{excluded_out} OUT excluded (outside window); {open_at_cutoff} open at cutoff\n")

    # ---- per-EA metrics ---------------------------------------------------
    ea_daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in positions:
        ea_daily[p["ea"]][p["exit_date"]] += p["pnl"]

    print("## Per-EA metrics (closed positions, trial window)\n")
    print("| EA | Trades | W-L | Win% | AvgWin | AvgLoss | PF | MaxConsecL | AvgHold(h) | TotalP&L | $/day |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for ea in KNOWN_EAS:
        ps = [p for p in positions if p["ea"] == ea]
        if not ps:
            print(f"| {ea} | 0 | — | — | — | — | — | — | — | $0 | $0 |")
            continue
        wins = [p for p in ps if p["pnl"] > 0]
        losses = [p for p in ps if p["pnl"] <= 0]
        gw = sum(p["pnl"] for p in wins)
        gl = abs(sum(p["pnl"] for p in losses))
        streak = best = 0
        for p in ps:
            streak = streak + 1 if p["pnl"] <= 0 else 0
            best = max(best, streak)
        holds = [p["hold_h"] for p in ps if p["hold_h"] is not None]
        total = sum(p["pnl"] for p in ps)
        aw = f"${gw / len(wins):,.0f}" if wins else "—"
        al = f"$-{gl / len(losses):,.0f}" if losses else "—"
        pf = "∞" if gl == 0 else f"{gw / gl:.2f}"
        ah = f"{sum(holds) / len(holds):.1f}" if holds else "—"
        print(f"| {ea} | {len(ps)} | {len(wins)}-{len(losses)} | {100 * len(wins) / len(ps):.0f}% | "
              f"{aw} | {al} | {pf} | {best} | {ah} | ${total:,.0f} | ${total / TRADING_DAYS:,.0f} |")
    una = [p for p in positions if p["ea"] == "UNATTRIBUTED"]
    if una:
        print(f"\nUNATTRIBUTED positions: {len(una)} (sum ${sum(p['pnl'] for p in una):,.2f}) -- listed below")
        for p in una:
            print(f"  pid={p['pid']} {p['symbol']} {p['side']} exit={p['exit_date']} pnl=${p['pnl']}")

    # ---- LondonMomo per-symbol split (it runs on two charts) ---------------
    print("\n## EA × symbol split (for multi-chart EAs)\n")
    print("| EA | Symbol | Trades | W-L | Total P&L |")
    print("|---|---|---|---|---|")
    es: dict[tuple, list] = defaultdict(list)
    for p in positions:
        es[(p["ea"], p["symbol"])].append(p)
    for (ea, sym), ps in sorted(es.items()):
        w = sum(1 for p in ps if p["pnl"] > 0)
        print(f"| {ea} | {sym} | {len(ps)} | {w}-{len(ps) - w} | ${sum(p['pnl'] for p in ps):,.0f} |")

    # ---- per-position ledger ---------------------------------------------
    print("\n## Closed-position ledger (in window)\n")
    print("| Exit (UTC) | EA | Symbol | Side | Vol | Hold(h) | P&L |")
    print("|---|---|---|---|---|---|---|")
    for p in positions:
        ts = datetime.fromtimestamp(p["exit_ms"] / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        print(f"| {ts} | {p['ea']} | {p['symbol']} | {p['side']} | {p['volume']:.2f} | "
              f"{p['hold_h'] if p['hold_h'] is not None else '—'} | ${p['pnl']:,.2f} |")

    # ---- daily P&L matrix + correlations ----------------------------------
    all_days = sorted({p["exit_date"] for p in positions})
    active_eas = [ea for ea in KNOWN_EAS if any(p["ea"] == ea for p in positions)]
    M = np.array([[ea_daily[ea].get(d, 0.0) for d in all_days] for ea in active_eas])

    print("\n## Daily realized P&L by EA (rows=EA, cols=days)\n")
    print("| EA | " + " | ".join(d[5:] for d in all_days) + " | TOTAL |")
    print("|---|" + "---|" * (len(all_days) + 1))
    for i, ea in enumerate(active_eas):
        cells = " | ".join(f"{v:,.0f}" if v else "·" for v in M[i])
        print(f"| {ea} | {cells} | {M[i].sum():,.0f} |")
    port = M.sum(axis=0)
    print("| **PORTFOLIO** | " + " | ".join(f"{v:,.0f}" for v in port) + f" | {port.sum():,.0f} |")

    print("\n## Cross-EA daily P&L correlation (Pearson, zeros included; n="
          f"{len(all_days)} days -- SMALL SAMPLE)\n")
    print("| | " + " | ".join(e.split("_")[0] + "_" + e.split("_")[2][:8] for e in active_eas) + " |")
    print("|---|" + "---|" * len(active_eas))
    C = np.corrcoef(M) if len(active_eas) > 1 else np.array([[1.0]])
    for i, ea in enumerate(active_eas):
        row = " | ".join("1.00" if i == j else f"{C[i, j]:+.2f}" for j in range(len(active_eas)))
        print(f"| {ea.split('_')[0]}_{ea.split('_')[2][:8]} | {row} |")

    # ---- cluster-day event study ------------------------------------------
    print("\n## Cluster-day event study (the 3 USD-rip days vs all other days)\n")
    cl_idx = [i for i, d in enumerate(all_days) if d in CLUSTER_DAYS]
    ot_idx = [i for i, d in enumerate(all_days) if d not in CLUSTER_DAYS]
    print("| EA | Cluster-days P&L | Other-days P&L | Cluster share of EA total loss |")
    print("|---|---|---|---|")
    for i, ea in enumerate(active_eas):
        cl = M[i, cl_idx].sum() if cl_idx else 0.0
        ot = M[i, ot_idx].sum() if ot_idx else 0.0
        share = "—"
        if cl < 0:
            neg_days = M[i][M[i] < 0].sum()
            share = f"{100 * min(cl / neg_days, 1):.0f}%" if neg_days < 0 else "—"
        print(f"| {ea} | ${cl:,.0f} | ${ot:,.0f} | {share} |")
    print(f"| **PORTFOLIO** | ${port[cl_idx].sum():,.0f} | ${port[ot_idx].sum():,.0f} | |")

    # ---- factor regression (single-factor, honest n) ----------------------
    print("\n## Factor exposure: daily EA P&L vs DXY daily return "
          "(single-factor OLS; n is TINY -- indicative only)\n")
    dxy = factors["DXY"]
    dxy_days = sorted(dxy)
    dxy_ret = {}
    for a, b in zip(dxy_days, dxy_days[1:]):
        dxy_ret[b] = math.log(dxy[b] / dxy[a])
    common = [d for d in all_days if d in dxy_ret]
    x = np.array([dxy_ret[d] for d in common])
    print(f"common days with DXY data: {len(common)} of {len(all_days)}\n")
    print("| EA | β(DXY) $ per +1% DXY | α $/day | R² | n |")
    print("|---|---|---|---|---|")
    di = [all_days.index(d) for d in common]
    for i, ea in enumerate(active_eas):
        y = M[i, di]
        if np.allclose(y, 0) or np.std(x) == 0:
            print(f"| {ea} | — | — | — | {len(common)} |")
            continue
        beta, alpha = np.polyfit(x, y, 1)
        r = np.corrcoef(x, y)[0, 1]
        print(f"| {ea} | ${beta * 0.01:,.0f} | ${alpha:,.0f} | {r * r:.2f} | {len(common)} |")
    yp = port[di]
    beta, alpha = np.polyfit(x, yp, 1)
    r = np.corrcoef(x, yp)[0, 1]
    print(f"| **PORTFOLIO** | ${beta * 0.01:,.0f} | ${alpha:,.0f} | {r * r:.2f} | {len(common)} |")

    # ---- costs --------------------------------------------------------------
    print("\n## Measured costs (exact, from deals)\n")
    sym_cost: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in positions:
        sym_cost[p["symbol"]]["commission"] += p["commission"]
        sym_cost[p["symbol"]]["swap"] += p["swap"]
        sym_cost[p["symbol"]]["n"] += 1
    print("| Symbol | Closed trades | Total commission | Total swap |")
    print("|---|---|---|---|")
    for s, c in sorted(sym_cost.items()):
        print(f"| {s} | {int(c['n'])} | ${c['commission']:,.2f} | ${c['swap']:,.2f} |")
    print("\nNOTE: bid/ask spread cost is embedded in realized P&L and NOT separable from "
          "deal records alone (requires requested-vs-filled prices). Fix queued: "
          "OnTradeTransaction upgrade (M10) captures both prices going forward.")


if __name__ == "__main__":
    main()
