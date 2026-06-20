"""Multi-asset momentum backtest — the highest-prior alpha shot (2026-06-20).

Tests time-series (TSMOM, Moskowitz-Ooi-Pedersen) and cross-sectional (Asness) momentum on
the diversified daily universe, monthly rebalanced, vol-scaled, cost-modeled. Multiple
lookbacks form a spec universe corrected by White's Reality Check — the same honesty bar as
the intraday gatekeeper. No look-ahead: signal at month-end t uses returns through t;
positions earn month t+1.

Run: python backtest/momentum_backtest.py
"""
from __future__ import annotations
import io
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "history" / "daily" / "universe.parquet"

TARGET_VOL = 0.10          # annualized portfolio vol target
COST_BPS = 10.0            # round-trip cost per unit turnover (10bps — generous for liquid ETFs)
VOL_WINDOW = 12            # months for inverse-vol scaling
RNG = np.random.default_rng(42)


def load_monthly():
    px = pd.read_parquet(DATA)
    m = px.resample("ME").last()
    return m, m.pct_change()


def momentum_signal(mprice: pd.DataFrame, lookback: int, skip: int = 1) -> pd.DataFrame:
    """Trailing return from t-lookback to t-skip (classic skip-recent-month)."""
    return mprice.shift(skip) / mprice.shift(lookback) - 1.0


def run_spec(mprice, mret, style: str, lookback: int, skip: int = 1) -> pd.Series:
    sig = momentum_signal(mprice, lookback, skip)
    vol = mret.rolling(VOL_WINDOW).std()
    avail = sig.notna() & vol.notna() & (vol > 0)
    inv_vol = (1.0 / vol).where(avail)

    if style == "TS":
        raw = np.sign(sig).where(avail) * inv_vol          # long up / short down, vol-scaled
    else:  # XS cross-sectional: long top third / short bottom third by rank
        ranks = sig.where(avail).rank(axis=1, pct=True)
        longs = (ranks >= 2/3).astype(float)
        shorts = (ranks <= 1/3).astype(float)
        raw = (longs - shorts) * inv_vol

    # normalize gross leverage to 1 each month, then vol-target the portfolio
    gross = raw.abs().sum(axis=1).replace(0, np.nan)
    w = raw.div(gross, axis=0).fillna(0.0)
    # portfolio return: weights at t earn month t+1
    port = (w.shift(1) * mret).sum(axis=1)
    # scale to target vol using trailing realized vol (expanding, min 12m; no look-ahead)
    realized = port.rolling(12).std()
    scale = (TARGET_VOL / np.sqrt(12)) / realized.shift(1)
    scale = scale.clip(upper=3.0).fillna(0.0)              # cap leverage 3x
    port_scaled = port * scale
    # turnover cost
    turn = (w - w.shift(1)).abs().sum(axis=1)
    cost = turn * (COST_BPS / 1e4) * scale.abs()
    return (port_scaled - cost).dropna()


def stats(r: pd.Series) -> dict:
    if len(r) < 12:
        return {"n": len(r)}
    ann_ret = (1 + r).prod() ** (12 / len(r)) - 1
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    boot = RNG.choice(r.values, size=(5000, len(r)), replace=True).mean(axis=1)
    return {"n": len(r), "ann_ret": ann_ret, "ann_vol": ann_vol, "sharpe": sharpe,
            "maxdd": dd, "p_pos": float((boot > 0).mean())}


def whites_rc(mat: pd.DataFrame, b: int = 5000) -> tuple[float, str]:
    X = mat.fillna(0.0).values
    T = len(X)
    means = X.mean(axis=0)
    stat = np.sqrt(T) * means
    k = int(np.argmax(stat)); V = float(stat[k])
    Vs = np.empty(b)
    for i in range(b):
        idx = RNG.integers(0, T, size=T)
        Vs[i] = (np.sqrt(T) * (X[idx].mean(axis=0) - means)).max()
    return float((Vs >= V).mean()), list(mat.columns)[k]


def main():
    mprice, mret = load_monthly()
    print(f"# Multi-asset momentum — {mprice.shape[1]} assets, monthly, "
          f"{mprice.index[0].date()}..{mprice.index[-1].date()}\n")
    print(f"(vol target {TARGET_VOL:.0%}, cost {COST_BPS:.0f}bps/turnover, "
          f"inverse-vol scaled, skip-1-month)\n")
    specs = [(s, lb) for s in ("TS", "XS") for lb in (3, 6, 12)]
    series = {}
    print("| spec | months | ann.ret | ann.vol | Sharpe | maxDD | P(edge>0) |")
    print("|---|---|---|---|---|---|---|")
    for style, lb in specs:
        r = run_spec(mprice, mret, style, lb)
        label = f"{style}-{lb}m"
        series[label] = r
        s = stats(r)
        if s.get("n", 0) < 12:
            print(f"| {label} | {s['n']} | — | — | — | — | — |"); continue
        print(f"| {label} | {s['n']} | {s['ann_ret']*100:+.1f}% | {s['ann_vol']*100:.1f}% | "
              f"{s['sharpe']:+.2f} | {s['maxdd']*100:.1f}% | {s['p_pos']*100:.1f}% |")

    mat = pd.concat(series, axis=1).dropna(how="all")
    p_rc, best = whites_rc(mat)
    print(f"\n## White's Reality Check (best of {mat.shape[1]} specs, {len(mat)} months)")
    print(f"- Best: **{best}**  |  multiplicity-corrected p = **{p_rc:.3f}**")
    if p_rc <= 0.05:
        print(f"- Verdict: **{best} SURVIVES** (p={p_rc:.3f}) — first edge to clear the gate. "
              f"Next: OOS robustness + map to FTMO-tradable instruments.")
    else:
        print(f"- Verdict: nothing clears multiple-testing correction at 5% (best p={p_rc:.3f}).")

    # quick OOS robustness: split at 2015, report best spec's two halves
    print("\n## Robustness — best spec by sub-period")
    r = series[best]
    for lo, hi, lbl in [(r.index[0], "2014-12-31", "pre-2015"), ("2015-01-01", r.index[-1], "2015+")]:
        sub = r.loc[lo:hi]
        s = stats(sub)
        if s.get("n", 0) >= 12:
            print(f"- {best} {lbl}: n={s['n']}, ann.ret {s['ann_ret']*100:+.1f}%, "
                  f"Sharpe {s['sharpe']:+.2f}, P(edge>0) {s['p_pos']*100:.0f}%")


if __name__ == "__main__":
    main()
