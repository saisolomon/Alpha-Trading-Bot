"""Multi-asset DAILY universe puller (yfinance) for the momentum study (2026-06-20).

Cross-sectional / time-series momentum (Moskowitz-Ooi-Pedersen TSMOM, Asness) is a
monthly-rebalanced, broad-universe anomaly. The clean way to test whether it's REAL is a
diversified liquid-ETF + crypto universe with decades of daily history (not gappy yfinance
=X FX). If it survives the gatekeeper here, we map it onto FTMO-tradable instruments (FX,
gold, indices CFDs, crypto) for deployment — validate the anomaly first, deploy second.

Output: data/history/daily/universe.parquet (wide, adjusted Close, business-day index).
Run: python backtest/fetch_universe.py
"""
from __future__ import annotations
import io
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = Path(__file__).resolve().parents[1] / "data" / "history" / "daily"

# Diversified multi-asset universe (the classic TSMOM replication set), liquid + long history.
UNIVERSE = {
    # equities (regions/caps)
    "SPY": "US large cap", "QQQ": "US tech", "IWM": "US small cap",
    "EFA": "Dev intl eq", "EEM": "EM equity",
    # rates / credit
    "TLT": "US 20y treasury", "IEF": "US 7-10y treasury", "LQD": "US IG credit", "HYG": "US HY credit",
    # commodities / metals
    "GLD": "Gold", "SLV": "Silver", "USO": "WTI oil", "DBC": "Broad commodity",
    # real assets / fx
    "VNQ": "US REIT", "UUP": "US dollar index",
    # crypto
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
}


def main():
    tickers = list(UNIVERSE)
    raw = yf.download(tickers, period="max", interval="1d", progress=False, auto_adjust=True)
    close = raw["Close"].copy()
    # business-day index, forward-fill small gaps (<=3d holidays), keep NaN before an asset exists
    close = close.asfreq("B").ffill(limit=3)
    OUT.mkdir(parents=True, exist_ok=True)
    close.to_parquet(OUT / "universe.parquet")
    print(f"# Daily universe — {len(close.columns)} assets, {len(close)} business days")
    print(f"span: {close.index[0].date()} .. {close.index[-1].date()}\n")
    print("| ticker | what | first valid | days |")
    print("|---|---|---|---|")
    for t in tickers:
        s = close[t].dropna()
        fv = s.index[0].date() if len(s) else "—"
        print(f"| {t} | {UNIVERSE[t]} | {fv} | {len(s):,} |")
    print(f"\nwrote {OUT/'universe.parquet'}")


if __name__ == "__main__":
    main()
