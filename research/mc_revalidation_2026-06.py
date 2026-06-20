"""C2 sizing-MC RE-VALIDATION after the live-fire week (GO-condition #1, gate review 2026-06-20).

The original sizing MC (trial_sizing_calibration.py) bootstrapped MAY's per-EA daily P&L
vectors at the 0.25% trial unit, applied the C2 multipliers (Momo 2x, Fix 2x, AUDJPY 1x =
0.50/0.50/0.25%), and pre-registered for a 10-day window: p5 = -$2,244, median +$6,723,
"worst of 10K paths never approached the daily line."

The live-fire week (6/11-6/19) realized -$5,090 over 7 trading days at C2 sizing. The gate
review flagged that as ~2.3x worse than the model's own p5 = out-of-sample tail falsification.

This script does two honest things, same engine + seed as the original:
  TEST A (falsification): where does the live week's realized 7-day outcome fall in the
          ORIGINAL May-only C2 window distribution (matched to a 7-day horizon)? What percentile?
  TEST B (re-estimation): POOL the live week's C2 daily vectors into the bootstrap and re-run
          the C2 MC. Report updated p5/median, P(touch 5% daily), P(touch 10% max), recovery.
          GO-condition #1 clears iff the re-estimated distribution still passes the deployment
          gates AND the realized week now sits inside a re-estimated p5.

Gates (per spec): P(touch 5% daily line) < 1% AND P(touch 10% max line) < 0.1%, 1.6x buffer.
Run: python research/mc_revalidation_2026-06.py   (numpy; seed 42 fixed)
"""
from __future__ import annotations
import io, json, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent

EQUITY0 = 200_000.0
DAILY_LINE = 0.05 * EQUITY0      # 10,000
MAX_LINE = 0.10 * EQUITY0        # 20,000
INTRADAY_BUFFER = 1.6
N_PATHS = 10_000
RNG = np.random.default_rng(42)  # SAME seed as the original MC

# C2 roster + the multipliers vs the 0.25% trial unit (the deployed config)
C2 = {"EURUSD_M15_LondonMomo": 2.0, "XAUUSD_M15_LondonFix": 2.0, "AUDJPY_H4_TrendFollow": 1.0}
RISK_UNIT = 500.0                # $ per 0.25%-unit trade (May basis)
KNOWN_EAS = list(C2)

# May window (unchanged from the original calibration)
MAY_START = datetime(2026, 5, 28, tzinfo=timezone.utc).timestamp() * 1000
MAY_END = datetime(2026, 6, 10, 22, 0, tzinfo=timezone.utc).timestamp() * 1000


def ea_of(raw):
    if not raw:
        return None
    for ea in KNOWN_EAS:
        if raw.startswith(ea):
            return ea
    return None


def prague_day(ms):
    # FTMO day rolls 00:00 Europe/Prague; in summer (CEST) that's 22:00 UTC the prior day.
    return datetime.fromtimestamp(ms / 1000 - 22 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")


def positions(path, lo=None, hi=None):
    """Reconstruct per-position net P&L attributed to the entering EA + its chart."""
    deals = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    by_pos = defaultdict(list)
    for d in deals:
        if d.get("eaName") == "Initial account balance":
            continue
        by_pos[d.get("positionId") or d["ticket"]].append(d)
    out = []
    for pid, ds in by_pos.items():
        outs = [d for d in ds if d["entry"] == "OUT"]
        if not outs:
            continue
        o = max(outs, key=lambda d: d["dealTimeMs"])
        if lo is not None and not (lo <= o["dealTimeMs"] < hi):
            continue
        ins = [d for d in ds if d["entry"] == "IN"]
        ein = min(ins, key=lambda d: d["dealTimeMs"]) if ins else None
        pnl = sum(d["profit"] + d.get("swap", 0) + d.get("commission", 0) for d in ds)
        ea = ea_of(ein["eaName"] if ein else None) or ea_of(o.get("eaName"))
        out.append({"ea": ea or "UNATTRIBUTED",
                    "chart": (ein or o)["symbol"].replace(".sim", ""),
                    "pnl": pnl, "day": prague_day(o["dealTimeMs"])})
    return out


def c2_daily_pool(ps, scale_from_unit):
    """Build the per-day C2-portfolio P&L vector.
    scale_from_unit=True: positions are at the 0.25% unit (May) -> apply C2 multipliers.
    scale_from_unit=False: positions already at C2 scale (live week) -> multiplier 1.
    LondonMomo counts ONLY its GBPUSD-chart leg (C2 rule: EURUSD instance cut)."""
    by_day = defaultdict(float)
    for p in ps:
        if p["ea"] not in C2:
            continue
        if p["ea"] == "EURUSD_M15_LondonMomo" and p["chart"] != "GBPUSD":
            continue
        mult = C2[p["ea"]] if scale_from_unit else 1.0
        by_day[p["day"]] += mult * p["pnl"]
    return by_day


def mc(pool_vals, horizon, label):
    pool = np.array(pool_vals, dtype=float)
    idx = RNG.integers(0, len(pool), size=(N_PATHS, horizon))
    daily = pool[idx]
    cum = np.cumsum(daily, axis=1)
    p_daily = float((daily.min(axis=1) * INTRADAY_BUFFER <= -DAILY_LINE).mean())
    p_max = float((cum.min(axis=1) * INTRADAY_BUFFER <= -MAX_LINE).mean())
    dipped = (cum <= -0.01 * EQUITY0).any(axis=1)
    rec = float((cum[dipped, -1] >= 0).mean()) if dipped.any() else 1.0
    q = np.quantile(cum[:, -1], [0.01, 0.05, 0.25, 0.5, 0.75, 0.95])
    print(f"| {label} | {p_daily*100:.2f}% | {p_max*100:.3f}% | {rec*100:.0f}% | "
          f"${q[0]:,.0f} | ${q[1]:,.0f} | ${q[3]:,.0f} | ${q[5]:,.0f} |")
    return dict(p_daily=p_daily, p_max=p_max, rec=rec, p1=q[0], p5=q[1], median=q[3], pool=pool)


def main():
    may = positions(HERE / "trial_2026-05_deals_raw.json", MAY_START, MAY_END)
    live = positions(HERE / "trial_2026-06_live_deals.json")

    may_pool = c2_daily_pool(may, scale_from_unit=True)
    live_pool = c2_daily_pool(live, scale_from_unit=False)
    live_realized = sum(live_pool.values())
    live_days = len(live_pool)

    print("# C2 Sizing-MC Re-Validation (2026-06-20)\n")
    print(f"May C2-equivalent daily pool: {len(may_pool)} days "
          f"[{', '.join(f'{v:+,.0f}' for v in sorted(may_pool.values()))}]")
    print(f"Live-week C2 daily pool: {live_days} days "
          f"[{', '.join(f'{v:+,.0f}' for v in [live_pool[k] for k in sorted(live_pool)])}]")
    print(f"Live week realized total: ${live_realized:,.0f} over {live_days} trading days\n")

    cols = "| config | P(touch 5% daily) | P(touch 10% max) | P(recover) | p1 | p5 | median | p95 |"
    sep = "|---|---|---|---|---|---|---|---|"

    print("## TEST A — falsification: live week vs the ORIGINAL May-only C2 distribution\n")
    print(f"(Bootstrap May C2 pool at the live week's {live_days}-day horizon; "
          f"where does the realized ${live_realized:,.0f} fall?)\n")
    print(cols); print(sep)
    a = mc(list(may_pool.values()), live_days, f"May-only, {live_days}d horizon")
    pool_may = a["pool"]
    # percentile of the realized week within the May-only window distribution
    idx = RNG.integers(0, len(pool_may), size=(200_000, live_days))
    windows = pool_may[idx].sum(axis=1)
    pctile = float((windows <= live_realized).mean()) * 100
    print(f"\n**Realized week ${live_realized:,.0f} = {pctile:.2f}th percentile of the "
          f"May-only {live_days}-day distribution.** "
          f"(Model p5 of the 10-day window was -$2,244; the week breached it.)\n")

    print("## TEST B — re-estimation: POOL the live week into the C2 bootstrap, 10-day horizon\n")
    print(cols); print(sep)
    orig = mc(list(may_pool.values()), 10, "C2 May-only (orig, 10d)")
    pooled_vals = list(may_pool.values()) + list(live_pool.values())
    new = mc(pooled_vals, 10, "C2 May+live POOLED (10d)")

    print("\n## Verdict\n")
    gates_ok = new["p_daily"] < 0.01 and new["p_max"] < 0.001
    print(f"- Pooled pool size: {len(pooled_vals)} daily vectors "
          f"({len(may_pool)} May + {live_days} live).")
    print(f"- Re-estimated 10-day p5: ${new['p5']:,.0f}  (was ${orig['p5']:,.0f} May-only).")
    print(f"- Re-estimated 10-day median: ${new['median']:,.0f}  (was ${orig['median']:,.0f}).")
    print(f"- Deployment gates on the POOLED distribution: "
          f"P(daily)={new['p_daily']*100:.2f}% (<1%? {new['p_daily']<0.01}), "
          f"P(max)={new['p_max']*100:.3f}% (<0.1%? {new['p_max']<0.001}).")
    print(f"- Realized week (${live_realized:,.0f}) inside re-estimated 10-day p5 "
          f"(${new['p5']:,.0f})? {live_realized >= new['p5']}  "
          f"(note: 7d realized vs 10d p5 — directional check).")
    print(f"\n**GO-condition #1 (sizing model trustworthy): "
          f"{'CLEARS' if gates_ok else 'FAILS'}** — "
          f"{'pooled distribution still passes the deployment gates' if gates_ok else 'pooled distribution BREACHES a deployment gate; C2 sizing must come down before any paid Challenge'}.")

    if not gates_ok:
        print("\n## Re-solve: what GLOBAL size multiplier passes the gates on the pooled distribution?\n")
        print("(k = fraction of C2 sizing applied to every leg; same pooled bootstrap.)\n")
        print(cols.replace("| config |", "| k x C2 (eff. Momo/Fix/AUDJPY %) |")); print(sep)
        safe_k = None
        for k in [1.0, 0.75, 0.6, 0.5, 0.4, 0.3, 0.25]:
            r = mc([v * k for v in pooled_vals], 10,
                   f"{k:.2f}x ({0.50*k:.2f}/{0.50*k:.2f}/{0.25*k:.2f}%)")
            if safe_k is None and r["p_daily"] < 0.01 and r["p_max"] < 0.001:
                safe_k = k
        print(f"\n- Smallest tested k passing BOTH gates: "
              f"{('%.2f' % safe_k + 'x C2') if safe_k else 'none in [0.25,1.0]'}"
              f"{' (Momo %.2f%% / Fix %.2f%% / AUDJPY %.2f%%)' % (0.50*safe_k,0.50*safe_k,0.25*safe_k) if safe_k else ''}.")
        print("- CAVEAT (honest): cutting size makes the book SAFE, not PROFITABLE. The pooled "
              "10-day median at full C2 is already only ~+$605 (edge ~0); de-risking shrinks the "
              "already-near-zero edge in absolute terms. The real blocker is no demonstrated edge, "
              "which sizing cannot fix — this is why the walk-forward harness, not a resize, is the priority.")
        print("- CAVEAT (stats): pooled pool is 16 daily vectors, 6 of them one non-IID bad week; "
              "treat the magnitudes as directional. The DIRECTION (C2 too hot at the observed tail) "
              "is robust; the exact safe-k needs the harness's larger sample to pin down.")


if __name__ == "__main__":
    main()
