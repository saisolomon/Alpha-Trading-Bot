"""Tier-2 bootstrap reality check on the Trial #1 sample (M10 Tier-2 #5).

Implements the data-snooping discipline mandated in Tasks.md (per
Sullivan-Timmermann-White 1999; Park-Irwin 2007; Neely 2011):

  1. White's Reality Check (RC): universe = ALL TEN EAs deployed in the
     trial (the selection universe -- including silent ones; zero series
     contribute no signal but belong to the family we picked winners from).
     Null: E[daily P&L] <= 0 for every rule. Statistic: max mean daily R.
     Bootstrap: joint day resampling (preserves the cross-EA cluster
     correlation exactly), B = 10,000, seed 42.
  2. Studentized max-t variant (SPA-flavoured): same scheme on t-statistics
     -- less dominated by high-variance rules.
  3. Per-EA uncorrected bootstrap p-values (day-level AND trade-level for
     EAs with >= 5 trades) -- reported for calibration, NOT for selection.

Honest framing: with n = 10 trading days / 3-11 trades per EA, the
EXPECTED outcome is that nothing clears a 5% corrected threshold. The
Tier-2 gate's purpose here is to forbid UPSIZING on noise -- it cannot
manufacture significance from two weeks of data. Config C2 was built on
Bayesian-shrinkage + ruin-bounding, which never claimed significance.

Run: python research/tier2_bootstrap.py   (numpy; deterministic, seed 42)
"""
from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
WINDOW_START = datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
WINDOW_END = datetime(2026, 6, 10, 22, 0, tzinfo=timezone.utc).timestamp() * 1000
RISK_UNIT = 500.0
B = 10_000
RNG = np.random.default_rng(42)

KNOWN_EAS = [
    "EURUSD_M15_LondonMomo", "EURUSD_M15_RSIFade", "US500_M15_ORB",
    "XAUUSD_M15_LondonFix", "BTCUSD_M15_TrendFollow", "GBPUSD_H1_SwingBreak",
    "XAUUSD_H1_NewsReaction", "AUDJPY_H4_TrendFollow", "EURGBP_H4_MeanReversion",
    "US100_H1_OvernightDrift",
]


def ea_canonical(raw):
    if not raw:
        return None
    for ea in KNOWN_EAS:
        if raw.startswith(ea):
            return ea
    return None


def load():
    deals = json.loads((HERE / "trial_2026-05_deals_raw.json").read_text())
    by_pos = defaultdict(list)
    for d in deals:
        by_pos[d.get("positionId") or d["ticket"]].append(d)
    trades = defaultdict(list)          # ea -> [R, ...]
    daily = defaultdict(lambda: defaultdict(float))  # ea -> date -> $
    for pid, ds in by_pos.items():
        outs = [d for d in ds if d["entry"] == "OUT"]
        if not outs:
            continue
        o = max(outs, key=lambda d: d["dealTimeMs"])
        if not (WINDOW_START <= o["dealTimeMs"] < WINDOW_END):
            continue
        ins = [d for d in ds if d["entry"] == "IN"]
        ein = min(ins, key=lambda d: d["dealTimeMs"]) if ins else None
        pnl = sum(d["profit"] + d.get("swap", 0) + d.get("commission", 0) for d in ds)
        ea = ea_canonical(ein["eaName"] if ein else None) or ea_canonical(o.get("eaName"))
        if ea is None:
            continue
        trades[ea].append(pnl / RISK_UNIT)
        date = datetime.fromtimestamp(o["dealTimeMs"] / 1000, tz=timezone.utc).strftime("%m-%d")
        daily[ea][date] += pnl / RISK_UNIT
    return trades, daily


def main():
    trades, daily = load()
    days = sorted({d for ea in daily for d in daily[ea]})
    n_days = len(days)
    M = np.array([[daily[ea].get(d, 0.0) for d in days] for ea in KNOWN_EAS])

    print(f"# Tier-2 bootstrap: {len(KNOWN_EAS)}-EA universe, {n_days} trading days, "
          f"B={B:,}, seed 42\n")

    obs_mean = M.mean(axis=1)
    obs_sd = M.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        obs_t = np.where(obs_sd > 0, obs_mean / (obs_sd / np.sqrt(n_days)), 0.0)

    # ---- joint day-resample bootstrap under the recentred null ----------
    Mc = M - obs_mean[:, None]                       # impose null per rule
    idx = RNG.integers(0, n_days, size=(B, n_days))
    boot_means = Mc[:, idx].mean(axis=2)             # (n_eas, B)
    boot_sds = Mc[:, idx].std(axis=2, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        boot_t = np.where(boot_sds > 0, boot_means / (boot_sds / np.sqrt(n_days)), 0.0)

    # White's RC on means
    rc_null_max = boot_means.max(axis=0)             # (B,)
    rc_p = float((rc_null_max >= obs_mean.max()).mean())
    best_mean_ea = KNOWN_EAS[int(np.argmax(obs_mean))]

    # Studentized max-t
    t_null_max = boot_t.max(axis=0)
    t_p = float((t_null_max >= obs_t.max()).mean())
    best_t_ea = KNOWN_EAS[int(np.argmax(obs_t))]

    print("## Family-wise tests (the ones that count)\n")
    print(f"- White's Reality Check (max mean daily R): best rule = **{best_mean_ea}** "
          f"(mean {obs_mean.max():+.3f} R/day) -> **p = {rc_p:.3f}**")
    print(f"- Studentized max-t (SPA-flavoured): best rule = **{best_t_ea}** "
          f"(t = {obs_t.max():.2f}) -> **p = {t_p:.3f}**\n")

    # ---- per-EA tables ----------------------------------------------------
    print("## Per-EA detail (uncorrected -- calibration only, NOT selection)\n")
    print("| EA | n trades | mean R/trade | daily mean R | daily t | "
          "boot p (day) | boot p (trade) |")
    print("|---|---|---|---|---|---|---|")
    for i, ea in enumerate(KNOWN_EAS):
        tr = np.array(trades.get(ea, []))
        # day-level uncorrected p
        p_day = float((boot_means[i] >= obs_mean[i]).mean()) if obs_sd[i] > 0 else float("nan")
        # trade-level bootstrap (recentred) for n>=5
        if len(tr) >= 5:
            trc = tr - tr.mean()
            bi = RNG.integers(0, len(tr), size=(B, len(tr)))
            p_tr = float((trc[bi].mean(axis=1) >= tr.mean()).mean())
            p_tr_s = f"{p_tr:.3f}"
        else:
            p_tr_s = "—"
        mt = f"{tr.mean():+.2f}" if len(tr) else "—"
        pd_s = f"{p_day:.3f}" if p_day == p_day else "—"
        print(f"| {ea} | {len(tr)} | {mt} | {obs_mean[i]:+.3f} | {obs_t[i]:+.2f} | "
              f"{pd_s} | {p_tr_s} |")

    print(f"""
## Reading

- The family-wise null is "no EA in the 10-rule universe has positive
  expected daily P&L." With n={n_days} days, the corrected tests above show
  whether ANY rule's observed performance survives selection bias.
- Per-EA uncorrected p-values are reported only to calibrate magnitudes;
  picking rules off them would be exactly the data-snooping the RC exists
  to prevent.
- Trade-level bootstraps double-check the two carriers at their natural
  unit (n=11 / n=10 trades).
""")


if __name__ == "__main__":
    main()
