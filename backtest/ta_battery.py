"""Classic retail-TA battery through the gatekeeper — does 'normal' TA actually work? (2026-06-20)

User's fair challenge: regular traders use EMA/RSI/MACD/Bollinger; did we really test that?
This runs the standard retail TA signals on crypto + liquid assets (daily), each as a
long/short strategy net of cost, then corrects the WHOLE battery for multiple testing via
White's Reality Check (STW 1999). If retail TA has edge it survives; if not, definitive.

Signals: EMA(20/50) cross, EMA(50/200) cross, RSI(14) fade, RSI(14) trend, MACD(12/26/9),
Bollinger(20,2) fade, Bollinger breakout, price>SMA200 trend.
Universe: crypto (BTC, ETH) + SPY/QQQ/GLD for breadth.

Run: python backtest/ta_battery.py
"""
from __future__ import annotations
import io
import sys
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ASSETS = ["BTC-USD", "ETH-USD", "SPY", "QQQ", "GLD"]
COST_BPS = 5.0      # per position flip (round-trip-ish); crypto wider, stressed below
RNG = np.random.default_rng(42)


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def signals(px: pd.Series) -> dict[str, pd.Series]:
    out = {}
    out["EMA20/50"] = np.sign(ema(px, 20) - ema(px, 50))
    out["EMA50/200"] = np.sign(ema(px, 50) - ema(px, 200))
    r = rsi(px, 14)
    out["RSI14-fade"] = pd.Series(np.where(r < 30, 1, np.where(r > 70, -1, np.nan)), index=px.index).ffill().fillna(0)
    out["RSI14-trend"] = pd.Series(np.where(r > 50, 1, -1), index=px.index)
    macd = ema(px, 12) - ema(px, 26)
    out["MACD"] = np.sign(macd - ema(macd, 9))
    ma, sd = px.rolling(20).mean(), px.rolling(20).std()
    out["Boll-fade"] = pd.Series(np.where(px < ma - 2*sd, 1, np.where(px > ma + 2*sd, -1, np.nan)), index=px.index).ffill().fillna(0)
    out["Boll-break"] = pd.Series(np.where(px > ma + 2*sd, 1, np.where(px < ma - 2*sd, -1, np.nan)), index=px.index).ffill().fillna(0)
    out["px>SMA200"] = np.sign(px - px.rolling(200).mean())
    return out


def strat_returns(px, pos, cost_bps):
    ret = px.pct_change()
    pos = pos.reindex(px.index).fillna(0.0)
    turn = pos.diff().abs().fillna(0)
    return (pos.shift(1) * ret - turn * (cost_bps / 1e4)).dropna()


def sharpe(r): return r.mean() / r.std() * np.sqrt(252) if len(r) and r.std() > 0 else 0.0


def boot_p(r):
    r = np.asarray(r)
    if len(r) < 30: return float("nan")
    return float((RNG.choice(r, size=(3000, len(r)), replace=True).mean(axis=1) > 0).mean())


def whites_rc(mat, b=3000):
    X = mat.fillna(0.0).values
    T = len(X); means = X.mean(axis=0); stat = np.sqrt(T) * means
    k = int(np.argmax(stat)); V = float(stat[k])
    Vs = np.array([(np.sqrt(T)*(X[RNG.integers(0,T,T)].mean(0)-means)).max() for _ in range(b)])
    return float((Vs >= V).mean()), list(mat.columns)[k]


def main():
    px = yf.download(ASSETS, period="max", interval="1d", progress=False, auto_adjust=True)["Close"]
    print(f"# Retail-TA battery — {len(ASSETS)} assets, daily, {px.index[0].date()}..{px.index[-1].date()}\n")
    print(f"(long/short, {COST_BPS:.0f}bps/flip, White's RC across the whole battery)\n")
    series = {}
    print("| signal x asset | Sharpe | ann% | P(edge>0) |")
    print("|---|---|---|---|")
    best_rows = []
    for a in ASSETS:
        s = px[a].dropna()
        for name, pos in signals(s).items():
            r = strat_returns(s, pos, COST_BPS)
            if len(r) < 100:
                continue
            key = f"{name} @ {a}"
            series[key] = r
            best_rows.append((key, sharpe(r), r.mean()*252*100, boot_p(r.values)))
    # show only the TOP 12 by Sharpe to keep it readable + the crypto ones
    for key, sh, ann, p in sorted(best_rows, key=lambda x: -x[1])[:12]:
        print(f"| {key} | {sh:+.2f} | {ann:+.1f}% | {p*100:.0f}% |")
    print(f"| ... ({len(best_rows)-12} more) | | | |")

    mat = pd.concat(series, axis=1, sort=True)
    p_all, best_all = whites_rc(mat)
    crypto_cols = [c for c in series if "BTC" in c or "ETH" in c]
    p_cr, best_cr = whites_rc(mat[crypto_cols])

    print(f"\n## White's Reality Check")
    print(f"- WHOLE battery ({mat.shape[1]} strategies): best = {best_all}, "
          f"multiplicity-corrected p = **{p_all:.3f}** -> "
          f"{'SURVIVES' if p_all<=0.05 else 'nothing survives'}")
    print(f"- CRYPTO-only ({len(crypto_cols)} strategies): best = {best_cr}, p = **{p_cr:.3f}** -> "
          f"{'SURVIVES' if p_cr<=0.05 else 'nothing survives'}")
    print(f"\n## Cost sensitivity of the single best raw performer ({best_all})")
    # recompute best at higher costs
    a = best_all.split(" @ ")[1]; nm = best_all.split(" @ ")[0]
    s = px[a].dropna(); pos = signals(s)[nm]
    for c in (5, 10, 20):
        r = strat_returns(s, pos, c)
        print(f"- @{c}bps/flip: Sharpe {sharpe(r):+.2f}, P(edge>0) {boot_p(r.values)*100:.0f}%")


if __name__ == "__main__":
    main()
