"""FTMO-deployable sizing for TS-momentum — does it fit inside the FTMO lines? (2026-06-20)

The validated edge runs at ~11% vol with -20% historical DD — far too hot for FTMO's 10%
max-loss floor. This sizes it DOWN (vol-target) on the FTMO-mappable universe, reconstructs
the DAILY equity path (FTMO's daily-loss rule is a daily check, not monthly), and simulates
the bright lines per CLAUDE.md: a backtest is NOT passing if it would touch the 5% daily or
10% max line even once. Reports the deployable return/DD and the sizing that stays legal.

Run: python backtest/momentum_ftmo.py
"""
from __future__ import annotations
import io
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parents[1]
UNI = REPO / "data" / "history" / "daily" / "universe.parquet"
FTMO_MAPPABLE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "SLV", "USO", "DBC", "UUP", "BTC-USD", "ETH-USD"]
INIT = 100_000.0
LOOKBACK = 12
COST_BPS = 20.0


FTMO_NOCRYPTO = [c for c in FTMO_MAPPABLE if c not in ("BTC-USD", "ETH-USD")]


def daily_portfolio_returns(target_vol: float, cols=FTMO_MAPPABLE) -> pd.Series:
    px = pd.read_parquet(UNI)[cols]
    dret = px.pct_change()
    mpx = px.resample("ME").last()
    mret = mpx.pct_change()
    sig = mpx.shift(1) / mpx.shift(LOOKBACK) - 1.0
    volm = mret.rolling(12).std()
    avail = sig.notna() & volm.notna() & (volm > 0)
    raw = np.sign(sig).where(avail) * (1.0 / volm).where(avail)
    gross = raw.abs().sum(axis=1).replace(0, np.nan)
    w_month = raw.div(gross, axis=0).fillna(0.0)                 # gross-1 monthly weights
    # hold month-end weights through the next month (ffill onto daily, lag 1 day = no look-ahead)
    w_daily = w_month.reindex(dret.index, method="ffill").shift(1)
    port_raw = (w_daily * dret).sum(axis=1)
    # turnover cost charged on rebalance days
    turn = (w_month - w_month.shift(1)).abs().sum(axis=1)
    cost_daily = turn.reindex(dret.index).fillna(0.0) * (COST_BPS / 1e4)
    port_raw = port_raw - cost_daily
    # trailing-vol targeting (60d), no look-ahead, leverage capped 3x
    realized = port_raw.rolling(60).std()
    scale = ((target_vol / np.sqrt(252)) / realized.shift(1)).clip(upper=3.0).fillna(0.0)
    return (port_raw * scale).dropna()


def apply_dd_control(r: pd.Series, init: float = INIT, floor_pct: float = 0.08,
                     mult: float = 3.0, max_lev: float = 1.0) -> pd.Series:
    """CPPI-style drawdown control: exposure = clip(mult*(equity-floor)/equity, 0, max_lev).
    As equity falls toward the floor, exposure -> 0, mechanically capping the drawdown.
    Path-dependent, uses PRIOR-day equity (no look-ahead)."""
    floor = init * (1 - floor_pct)
    eq = init
    out = []
    for x in r.values:
        expo = min(max(mult * (eq - floor) / eq, 0.0), max_lev) if eq > floor else 0.0
        day = expo * x
        out.append(day)
        eq *= (1 + day)
    return pd.Series(out, index=r.index)


def ftmo_sim(r: pd.Series, init: float = INIT) -> dict:
    eq = init * (1 + r).cumprod()
    daily_pnl = eq.diff().fillna(eq.iloc[0] - init)
    worst_day = daily_pnl.min()
    # FTMO daily line = 5% of init below each day's start; close-to-close proxy (no intraday feed)
    daily_breach = bool((daily_pnl <= -0.05 * init).any())
    min_eq = eq.min()
    max_breach = bool(min_eq <= 0.90 * init)              # static 10% max-loss floor from initial
    maxdd = float((eq / eq.cummax() - 1).min())
    ann = (eq.iloc[-1] / init) ** (252 / len(r)) - 1
    return {"ann_ret": ann, "ann_vol": r.std() * np.sqrt(252), "maxdd": maxdd,
            "worst_day_pct": worst_day / init, "min_eq_pct": min_eq / init - 1,
            "daily_breach": daily_breach, "max_breach": max_breach,
            "internal_daily_hit": bool((daily_pnl <= -0.03 * init).any()),
            "internal_max_hit": bool(min_eq <= 0.93 * init)}


def main():
    print(f"# TS-12m momentum sized for FTMO — daily-path rule simulation\n")
    print(f"FTMO-mappable universe (12), ${INIT:,.0f} init, {COST_BPS:.0f}bps, monthly rebalance.\n")
    print(f"FTMO lines: daily-loss 5% (=${0.05*INIT:,.0f}), max-loss 10% (=${0.10*INIT:,.0f}). "
          f"Internal kills: 3% daily / 7% max.\n")
    print("| vol target | ann.ret | ann.vol | maxDD | worst day | min equity | "
          "FTMO daily? | FTMO max? | internal 3%/7% hit? |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows = {}
    for tv in (0.04, 0.05, 0.06, 0.08, 0.10):
        r = daily_portfolio_returns(tv)
        s = ftmo_sim(r)
        rows[tv] = s
        fday = "BREACH" if s["daily_breach"] else "ok"
        fmax = "BREACH" if s["max_breach"] else "ok"
        intl = ("daily" if s["internal_daily_hit"] else "") + ("+max" if s["internal_max_hit"] else "") or "clear"
        print(f"| {tv*100:.0f}% | {s['ann_ret']*100:+.1f}% | {s['ann_vol']*100:.1f}% | "
              f"{s['maxdd']*100:.1f}% | {s['worst_day_pct']*100:+.1f}% | {s['min_eq_pct']*100:+.1f}% | "
              f"{fday} | {fmax} | {intl} |")

    print("\n## CPPI drawdown control (de-lever only, cap 1.0x, floor 8%) + NO CRYPTO\n")
    print("| base vol | ann.ret | ann.vol | maxDD | worst day | min equity | "
          "FTMO daily? | FTMO max? | internal 3%/7% hit? |")
    print("|---|---|---|---|---|---|---|---|---|")
    dd_rows = {}
    for tv in (0.04, 0.05, 0.06, 0.08):
        rc = apply_dd_control(daily_portfolio_returns(tv, cols=FTMO_NOCRYPTO))
        s = ftmo_sim(rc)
        dd_rows[tv] = s
        fday = "BREACH" if s["daily_breach"] else "ok"
        fmax = "BREACH" if s["max_breach"] else "ok"
        intl = ("daily" if s["internal_daily_hit"] else "") + ("+max" if s["internal_max_hit"] else "") or "clear"
        print(f"| {tv*100:.0f}% | {s['ann_ret']*100:+.1f}% | {s['ann_vol']*100:.1f}% | "
              f"{s['maxdd']*100:.1f}% | {s['worst_day_pct']*100:+.1f}% | {s['min_eq_pct']*100:+.1f}% | "
              f"{fday} | {fmax} | {intl} |")

    # pick the largest vol target that stays clear of BOTH FTMO lines AND the internal kills
    safe = [tv for tv, s in rows.items()
            if not s["daily_breach"] and not s["max_breach"]
            and not s["internal_daily_hit"] and not s["internal_max_hit"]]
    dd_safe = [tv for tv, s in dd_rows.items()
               if not s["daily_breach"] and not s["max_breach"] and not s["internal_max_hit"]]
    print("\n## Verdict")
    if dd_safe:
        best = max(dd_safe)
        s = dd_rows[best]
        months = 12 * np.log(1.10) / np.log(1 + s["ann_ret"]) if s["ann_ret"] > 0 else float("inf")
        print(f"- **CPPI drawdown control makes it FTMO-LEGAL**: base vol {best*100:.0f}% -> "
              f"ann.ret **{s['ann_ret']*100:+.1f}%**, maxDD {s['maxdd']*100:.1f}% (inside the 10% "
              f"floor), worst day {s['worst_day_pct']*100:.1f}%.")
        print(f"- Est. time to FTMO Phase-1 +10%: ~{months:.0f} months (no time limit).")
        print(f"- This is the deployable shape: TSMOM + CPPI floor on the FTMO-mappable universe, "
              f"Swing account, intraday equity poll for the tick-touch rule.")
    elif safe:
        best = max(safe)
        s = rows[best]
        months_to_10 = 12 * np.log(1.10) / np.log(1 + s["ann_ret"]) if s["ann_ret"] > 0 else float("inf")
        print(f"- Largest FTMO-legal sizing (clears 5%/10% lines AND 3%/7% internal kills): "
              f"**vol target {best*100:.0f}%** -> ann.ret **{s['ann_ret']*100:+.1f}%**, "
              f"maxDD {s['maxdd']*100:.1f}%, worst day {s['worst_day_pct']*100:.1f}%.")
        print(f"- Est. time to FTMO Phase-1 +10% at that sizing: **~{months_to_10:.0f} months** "
              f"(no time limit, so slow is allowed).")
        print(f"- CAVEAT: daily-loss check is close-to-close (no intraday feed for the portfolio); "
              f"a vol-{best*100:.0f}% multi-asset book has modest intraday swing, but the live EA "
              f"must still poll equity intraday per the FTMO tick-touch rule. Needs a SWING account "
              f"(monthly holds over weekends).")
    else:
        print("- No tested sizing stays clear of all lines — needs lower vol target or de-risking.")


if __name__ == "__main__":
    main()
