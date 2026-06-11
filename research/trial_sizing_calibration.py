"""Position-sizing calibration from Trial #1 data (M10 Tier-1 #2).

Method (per Tasks.md upgraded spec + research/volatility_sizing_review_2026-06.md):
  1. R-multiple normalization: every trade's P&L / $500 (the 0.25%-of-$200K
     risk unit actually used in the trial). Makes results size-transferable.
  2. Per-EA Bayesian binary Kelly (Sukhov-style): Beta(2,2) prior on win
     probability; payoff ratio b = avgWin/|avgLoss|; conservative sizing off
     the posterior 25th percentile of p (cold-start shrinkage).
  3. Classical continuous Kelly per spec: f* = mu_R/sigma_R^2,
     G(f) = f*mu - f^2*sigma^2/2, closed-form P(ruin) table.
  4. Portfolio Monte Carlo: stationary bootstrap of the 10 OBSERVED daily
     EA-P&L vectors (cluster days at true 3/10 frequency, cross-EA
     correlation preserved exactly), 10k paths x 10 trading days, at
     risk multipliers m in {1x..5x} of trial sizing. Gates per spec:
     P(touch 5% daily line) < 1% AND P(touch 10% max line) < 0.1%,
     with a 1.6x intraday-excursion buffer on daily losses (single worst
     observed close-vs-trough ratio; refine in Tier-2 with snapshot series).
     Recovery constraint (Lee-style, MC variant): P(path that dips below
     -1% equity recovers to >= 0 by day 10) >= 60%.
  5. ERC (equal risk contribution) weights from the daily covariance --
     correlation-aware replacement for independent inverse-vol (Baltas).

Honest limitations, documented in the report:
  - n per EA is 3-11 trades; ALL outputs are provisional pending Tier-2
    bootstrap/SPA. Bayesian shrinkage is the mitigation, not a cure.
  - Daily-close P&L proxies intraday equity excursion (1.6x buffer).
  - Yang-Zhang vol estimator needs OHLC; deferred to EA implementation.
  - Factor-alpha residual as mu (spec) deferred: with n=10 days the
    single-factor alpha is noisier than raw mean; raw R-mean used.

Run: python research/trial_sizing_calibration.py   (numpy; seed=42 fixed)
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
RISK_UNIT = 500.0          # $ risked per trade in the trial (0.25% of 200K)
EQUITY0 = 200_000.0
DAILY_LINE = 0.05 * EQUITY0    # $10,000
MAX_LINE = 0.10 * EQUITY0      # $20,000
INTRADAY_BUFFER = 1.6      # close-vs-trough excursion buffer (worst observed)
HORIZON_DAYS = 10          # trading days in a 14-calendar-day challenge window
N_PATHS = 10_000
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


def load_positions():
    deals = json.loads((HERE / "trial_2026-05_deals_raw.json").read_text())
    by_pos = defaultdict(list)
    for d in deals:
        by_pos[d.get("positionId") or d["ticket"]].append(d)
    out = []
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
        out.append({
            "ea": ea or "UNATTRIBUTED",
            "chart": (ein or o)["symbol"].replace(".sim", ""),
            "pnl": pnl,
            "R": pnl / RISK_UNIT,
            "date": datetime.fromtimestamp(o["dealTimeMs"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
        })
    return out


def beta_ppf(q, a, b, n=200_001):
    """Quantile of Beta(a,b) via numerical CDF inversion (no scipy)."""
    x = np.linspace(0, 1, n)
    pdf = x ** (a - 1) * (1 - x) ** (b - 1)
    cdf = np.cumsum(pdf)
    cdf /= cdf[-1]
    return float(x[np.searchsorted(cdf, q)])


def main():
    ps = load_positions()
    active = [ea for ea in KNOWN_EAS if any(p["ea"] == ea for p in ps)]

    # ------------------------------------------------------------------ #
    print("## 1. Per-EA R-multiple stats + Bayesian binary Kelly\n")
    print("(R = trade P&L / $500 risk unit. Prior on win prob: Beta(2,2). "
          "f*bin = p − (1−p)/b. Conservative = posterior 25th pct of p.)\n")
    print("| EA | n | mean R | std R | win p̂ (post.) | p 25th | b (W/L) | "
          "f*bin(mean p) | f*bin(p25) | ½·f*bin(p25) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    ea_stats = {}
    for ea in active:
        rs = np.array([p["R"] for p in ps if p["ea"] == ea])
        wins = rs[rs > 0]
        losses = rs[rs <= 0]
        n, w = len(rs), len(wins)
        a, b_ = 2 + w, 2 + (n - w)
        p_mean = a / (a + b_)
        p25 = beta_ppf(0.25, a, b_)
        bratio = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else float("nan")
        fbin_mean = p_mean - (1 - p_mean) / bratio if bratio == bratio and bratio > 0 else float("nan")
        fbin_p25 = p25 - (1 - p25) / bratio if bratio == bratio and bratio > 0 else float("nan")
        ea_stats[ea] = dict(n=n, muR=rs.mean(), sdR=rs.std(ddof=1) if n > 1 else float("nan"),
                            p_mean=p_mean, p25=p25, b=bratio,
                            fbin_mean=fbin_mean, fbin_p25=fbin_p25)
        half = max(fbin_p25, 0) / 2 if fbin_p25 == fbin_p25 else float("nan")
        print(f"| {ea} | {n} | {rs.mean():+.2f} | {rs.std(ddof=1):.2f} | {p_mean:.2f} | "
              f"{p25:.2f} | {bratio:.2f} | {fbin_mean:+.3f} | {fbin_p25:+.3f} | {half:.3f} |")

    # ------------------------------------------------------------------ #
    print("\n## 2. Classical continuous Kelly + G(f) curves (per spec)\n")
    print("f* = μ_R/σ_R² (fraction of equity risked per TRADE). "
          "G(f) = f·μ − f²σ²/2 per trade, in equity-log units.\n")
    fgrid = [0.001, 0.0025, 0.005, 0.0075, 0.010, 0.0125]
    head = " | ".join(f"G(f={f * 100:.2f}%)" for f in fgrid)
    print(f"| EA | f* (cont.) | {head} |")
    print("|---|---|" + "---|" * len(fgrid))
    for ea in active:
        s = ea_stats[ea]
        mu, sd = s["muR"], s["sdR"]
        fstar = mu / sd ** 2 if sd and sd == sd and sd > 0 else float("nan")
        row = " | ".join(f"{(f * mu - f * f * sd * sd / 2) * 1e4:+.2f}" for f in fgrid)
        print(f"| {ea} | {fstar * 100:+.2f}% | {row} |")
    print("\n(G in basis points of log-equity per trade; negative = guaranteed long-run loss at that size.)")

    # ------------------------------------------------------------------ #
    print("\n## 3. Closed-form P(ruin) per EA (spec formula, indicative)\n")
    print("P(touch −D) ≈ exp(−2·μ·D/(σ²·f²)) with μ,σ per-trade R-stats, D in R-units of equity.\n")
    print("| EA | f | P(touch 5% daily-line scale) | P(touch 10% max-line scale) |")
    print("|---|---|---|---|")
    for ea in active:
        s = ea_stats[ea]
        mu, sd = s["muR"], s["sdR"]
        for f in [0.0025, 0.005, 0.0075, 0.010]:
            if mu <= 0 or sd != sd:
                pd5 = pm10 = 1.0
            else:
                # D in per-trade-R units: D_daily = 0.05/f trades-worth of equity
                pd5 = min(1.0, np.exp(-2 * mu * (0.05 / f) / (sd ** 2)))
                pm10 = min(1.0, np.exp(-2 * mu * (0.10 / f) / (sd ** 2)))
            print(f"| {ea} | {f * 100:.2f}% | {pd5:.3f} | {pm10:.3f} |")

    # ------------------------------------------------------------------ #
    # Daily P&L matrix (the bootstrap pool)
    days = sorted({p["date"] for p in ps})
    M = np.zeros((len(active), len(days)))
    for p in ps:
        if p["ea"] in active:
            M[active.index(p["ea"]), days.index(p["date"])] += p["pnl"]

    def mc(weights, label):
        """Bootstrap daily vectors; weights = per-EA risk multiplier vs trial."""
        port_days = (weights[:, None] * M).sum(axis=0)      # scaled daily P&L pool
        idx = RNG.integers(0, len(days), size=(N_PATHS, HORIZON_DAYS))
        daily = port_days[idx]                              # paths x days
        cum = np.cumsum(daily, axis=1)
        worst_day = daily.min(axis=1)
        trough = cum.min(axis=1)
        p_daily = float((worst_day * INTRADAY_BUFFER <= -DAILY_LINE).mean())
        p_max = float((trough * INTRADAY_BUFFER <= -MAX_LINE).mean())
        # Lee-style recovery: among paths dipping below -1% at any point,
        # fraction back >= 0 by horizon end
        dipped = (cum <= -0.01 * EQUITY0).any(axis=1)
        rec = float((cum[dipped, -1] >= 0).mean()) if dipped.any() else 1.0
        q = np.quantile(cum[:, -1], [0.05, 0.25, 0.5, 0.75, 0.95])
        print(f"| {label} | {p_daily * 100:.2f}% | {p_max * 100:.3f}% | {rec * 100:.0f}% | "
              f"${q[0]:,.0f} | ${q[2]:,.0f} | ${q[4]:,.0f} |")
        return p_daily, p_max, rec

    print("\n## 4. Portfolio Monte Carlo (bootstrap of OBSERVED daily vectors, "
          f"{N_PATHS:,} paths × {HORIZON_DAYS}d, buffer ×{INTRADAY_BUFFER}, seed 42)\n")
    print("### Config A — current roster (all 6 active EAs), uniform multiplier\n")
    print("| Multiplier (per-trade risk) | P(touch 5% daily) | P(touch 10% max) | "
          "P(recover dip→0 by d10) | P&L p5 | median | p95 |")
    print("|---|---|---|---|---|---|---|")
    for m in [1, 2, 3, 4, 5]:
        mc(np.full(len(active), float(m)), f"{m}× (={0.25 * m:.2f}%/trade)")

    print("\n### Config B — post-cut roster (drop SwingBreak + EURUSD-chart momo leg)\n")
    # rebuild matrix with cuts: zero out SwingBreak row; rebuild LondonMomo from GBPUSD chart only
    M_b = M.copy()
    if "GBPUSD_H1_SwingBreak" in active:
        M_b[active.index("GBPUSD_H1_SwingBreak")] = 0.0
    if "EURUSD_M15_LondonMomo" in active:
        i = active.index("EURUSD_M15_LondonMomo")
        M_b[i] = 0.0
        for p in ps:
            if p["ea"] == "EURUSD_M15_LondonMomo" and p["chart"] == "GBPUSD":
                M_b[i, days.index(p["date"])] += p["pnl"]
    print("| Multiplier (per-trade risk) | P(touch 5% daily) | P(touch 10% max) | "
          "P(recover dip→0 by d10) | P&L p5 | median | p95 |")
    print("|---|---|---|---|---|---|---|")
    Mref = M_b

    def mc_b(weights, label):
        port_days = (weights[:, None] * Mref).sum(axis=0)
        idx = RNG.integers(0, len(days), size=(N_PATHS, HORIZON_DAYS))
        daily = port_days[idx]
        cum = np.cumsum(daily, axis=1)
        p_daily = float(((daily.min(axis=1)) * INTRADAY_BUFFER <= -DAILY_LINE).mean())
        p_max = float((cum.min(axis=1) * INTRADAY_BUFFER <= -MAX_LINE).mean())
        dipped = (cum <= -0.01 * EQUITY0).any(axis=1)
        rec = float((cum[dipped, -1] >= 0).mean()) if dipped.any() else 1.0
        q = np.quantile(cum[:, -1], [0.05, 0.5, 0.95])
        print(f"| {label} | {p_daily * 100:.2f}% | {p_max * 100:.3f}% | {rec * 100:.0f}% | "
              f"${q[0]:,.0f} | ${q[1]:,.0f} | ${q[2]:,.0f} |")

    for m in [1, 2, 3, 4, 5]:
        mc_b(np.full(len(active), float(m)), f"{m}× (={0.25 * m:.2f}%/trade)")

    # ------------------------------------------------------------------ #
    print("\n### Config C — tailored per-EA multipliers on the cut roster\n")
    print("(Carriers upsized, ambiguous EAs held at trial size; multipliers vs "
          "the 0.25% trial unit. SwingBreak + EURUSD-momo leg remain cut.)\n")

    def vec(d):
        v = np.zeros(len(active))
        for ea, m in d.items():
            v[active.index(ea)] = m
        return v

    candidates = {
        "C1: Momo2× Fix2× ORB1× AUDJPY1× Drift1×": vec({
            "EURUSD_M15_LondonMomo": 2, "XAUUSD_M15_LondonFix": 2,
            "US500_M15_ORB": 1, "AUDJPY_H4_TrendFollow": 1, "US100_H1_OvernightDrift": 1}),
        "C2: Momo2× Fix2× ORB0 AUDJPY1× Drift0": vec({
            "EURUSD_M15_LondonMomo": 2, "XAUUSD_M15_LondonFix": 2,
            "AUDJPY_H4_TrendFollow": 1}),
        "C3: Momo3× Fix2× ORB0 AUDJPY1× Drift0": vec({
            "EURUSD_M15_LondonMomo": 3, "XAUUSD_M15_LondonFix": 2,
            "AUDJPY_H4_TrendFollow": 1}),
        "C4: Momo2× Fix1× ORB1× AUDJPY1× Drift1×": vec({
            "EURUSD_M15_LondonMomo": 2, "XAUUSD_M15_LondonFix": 1,
            "US500_M15_ORB": 1, "AUDJPY_H4_TrendFollow": 1, "US100_H1_OvernightDrift": 1}),
    }
    print("| Config | P(touch 5% daily) | P(touch 10% max) | "
          "P(recover dip→0 by d10) | P&L p5 | median | p95 |")
    print("|---|---|---|---|---|---|---|")
    for label, v in candidates.items():
        mc_b(v, label)

    # ------------------------------------------------------------------ #
    print("\n## 5. ERC (equal-risk-contribution) weights from daily covariance "
          "(Config B roster)\n")
    alive = [i for i in range(len(active)) if Mref[i].std() > 0]
    names = [active[i] for i in alive]
    C = np.cov(Mref[alive])
    w = 1 / np.sqrt(np.diag(C))
    w /= w.sum()
    for _ in range(500):                      # simple ERC fixed-point iteration
        rc = w * (C @ w)
        w = w * (rc.mean() / np.where(rc > 0, rc, rc.mean())) ** 0.5
        w = np.clip(w, 1e-6, None)
        w /= w.sum()
    rc = w * (C @ w)
    print("| EA (surviving roster) | inverse-vol w | ERC w | risk contribution share |")
    print("|---|---|---|---|")
    iv = 1 / np.sqrt(np.diag(C))
    iv /= iv.sum()
    for k, nm in enumerate(names):
        print(f"| {nm} | {iv[k] * 100:.0f}% | {w[k] * 100:.0f}% | {rc[k] / rc.sum() * 100:.0f}% |")
    print("\n(ERC vs inverse-vol gap = the correlation correction Baltas argues for.)")


if __name__ == "__main__":
    main()
