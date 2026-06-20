"""Empirical broker->UTC alignment + feed divergence (harness prereq, 2026-06-20).

The MT5 spine is stored in RAW BROKER time; Dukascopy is native UTC. Instead of GUESSING
the broker offset (the auto-detect corrupted stamps), recover it EMPIRICALLY: for each
candidate hour shift, align the two close series on matched bar-opens and pick the shift
that minimizes mean abs price difference. The residual difference at the best shift IS the
feed divergence (different liquidity providers) — a cost/parity input.

Usage: python backtest/align_feeds.py --symbol EURUSD --tf M15
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
H = REPO / "data" / "history"
PIP = {"EURUSD": 1e-4, "GBPUSD": 1e-4, "EURGBP": 1e-4, "AUDJPY": 1e-2, "XAUUSD": 1e-1}


def _load(src, sym, tf):
    f = H / src / f"{sym}_{tf}.parquet"
    if not f.exists():
        return None
    s = pd.read_parquet(f).set_index("time")["close"].sort_index()
    # normalize to tz-NAIVE wall-clock (MT5=naive broker, Dukascopy=aware UTC);
    # the shift search treats the values as wall-clock and recovers the offset.
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def align(symbol: str, tf: str, max_off: int = 6):
    mt5 = _load("mt5", symbol, tf)
    duk = _load("dukascopy", symbol, tf)
    if mt5 is None or duk is None:
        raise SystemExit(f"need BOTH feeds for {symbol} {tf} "
                         f"(mt5={mt5 is not None}, dukascopy={duk is not None})")
    lo, hi = max(mt5.index.min(), duk.index.min()), min(mt5.index.max(), duk.index.max())
    mt5 = mt5[(mt5.index >= lo) & (mt5.index <= hi)]
    duk = duk[(duk.index >= lo) & (duk.index <= hi)]
    pip = PIP[symbol]
    rows, best = [], None
    for h in range(-max_off, max_off + 1):
        s = mt5.copy()
        s.index = s.index - pd.Timedelta(hours=h)        # broker - h = UTC candidate
        j = pd.concat([s.rename("mt5"), duk.rename("duk")], axis=1, join="inner").dropna()
        if len(j) < 20:
            continue
        mad_pips = float((j["mt5"] - j["duk"]).abs().mean() / pip)
        corr = float(j["mt5"].corr(j["duk"]))
        rows.append((h, len(j), mad_pips, corr))
        if best is None or mad_pips < best[2]:
            best = (h, len(j), mad_pips, corr)
    return best, rows, (lo, hi)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--tf", default="M15")
    a = p.parse_args()
    best, rows, (lo, hi) = align(a.symbol, a.tf)
    print(f"# Feed alignment — {a.symbol} {a.tf}")
    print(f"overlap: {lo} .. {hi}\n")
    print("| broker->UTC shift (h) | matched bars | mean abs dclose (pips) | corr |")
    print("|---|---|---|---|")
    for h, n, mad, corr in rows:
        mark = "  <- BEST" if (h, n, mad, corr) == best else ""
        print(f"| {h:+d} | {n} | {mad:.2f} | {corr:.5f} |{mark}")
    h, n, mad, corr = best
    print(f"\n**Recovered broker offset = UTC+{h}** (min divergence {mad:.2f} pips, "
          f"corr {corr:.5f}, n={n}).")
    print(f"Residual {mad:.2f}-pip divergence at the best shift = OANDA-vs-Dukascopy "
          f"feed difference (liquidity-provider variance) — a cost/parity input.")
    print(f"\nSanity: OANDA-Demo summer is expected ~UTC+3. Recovered = UTC+{h} to "
          f"{'MATCHES expectation' if h == 3 else 'DIFFERS from the +3 assumption — investigate'}.")


if __name__ == "__main__":
    main()
