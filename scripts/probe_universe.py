"""
Comprehensive broker probe: which symbols are actually tradeable on this
MT5 connection across the markets that matter for breakout/trend strategies.

Tries common naming conventions for:
  - FX crosses (the JPY crosses especially -- historically the cleanest
    intraday breakout markets per academic literature)
  - Energy commodities (WTI, Brent, NatGas)
  - Soft commodities (Coffee, Sugar, Cocoa)
  - Crypto (BTC, ETH if listed)
  - Asian + European indices we haven't probed yet (NIKKEI, HSI, ASX, CAC)

Output: a sorted list of confirmed-tradeable symbols with spec details,
ranked by which are most likely to support a breakout strategy.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

UTC = timezone.utc

# Per-category candidate symbol names. Probe tries each variant in order
# and keeps the FIRST one the broker accepts.
CANDIDATES = {
    "FX JPY-crosses (breakout-rich per Fox-Wilkinson 2011)": [
        ("GBPJPY",  ["GBPJPY", "GBP/JPY", "GBPJPY."]),
        ("EURJPY",  ["EURJPY", "EUR/JPY"]),
        ("AUDJPY",  ["AUDJPY", "AUD/JPY"]),
        ("NZDJPY",  ["NZDJPY", "NZD/JPY"]),
        ("CADJPY",  ["CADJPY", "CAD/JPY"]),
        ("CHFJPY",  ["CHFJPY", "CHF/JPY"]),
    ],
    "FX non-USD crosses": [
        ("EURGBP",  ["EURGBP", "EUR/GBP"]),
        ("EURAUD",  ["EURAUD", "EUR/AUD"]),
        ("GBPAUD",  ["GBPAUD", "GBP/AUD"]),
        ("EURCHF",  ["EURCHF", "EUR/CHF"]),
        ("GBPCHF",  ["GBPCHF", "GBP/CHF"]),
        ("AUDNZD",  ["AUDNZD", "AUD/NZD"]),
    ],
    "FX exotics (high carry, structural drift)": [
        ("USDMXN",  ["USDMXN", "USD/MXN"]),
        ("USDZAR",  ["USDZAR", "USD/ZAR"]),
        ("USDTRY",  ["USDTRY", "USD/TRY"]),
        ("USDSEK",  ["USDSEK", "USD/SEK"]),
        ("USDNOK",  ["USDNOK", "USD/NOK"]),
        ("USDHKD",  ["USDHKD", "USD/HKD"]),
        ("USDSGD",  ["USDSGD", "USD/SGD"]),
    ],
    "Energy + softs (trend candidates)": [
        ("WTI",      ["WTI", "USOIL", "XTIUSD", "CL", "USOIL.cash"]),
        ("Brent",    ["UKOIL", "XBRUSD", "BRENT", "BRT"]),
        ("NatGas",   ["NG", "XNGUSD", "NATGAS"]),
        ("Coffee",   ["COFFEE", "KC"]),
        ("Sugar",    ["SUGAR", "SB"]),
        ("Cocoa",    ["COCOA", "CC"]),
        ("Cotton",   ["COTTON", "CT"]),
    ],
    "Crypto (canonical trending markets)": [
        ("BTC",      ["BTCUSD", "BTC/USD", "BTCUSDT", "Bitcoin"]),
        ("ETH",      ["ETHUSD", "ETH/USD", "ETHUSDT", "Ethereum"]),
        ("LTC",      ["LTCUSD", "LTC/USD"]),
        ("XRP",      ["XRPUSD", "XRP/USD"]),
        ("SOL",      ["SOLUSD", "SOL/USD"]),
    ],
    "Asian/European indices not yet probed": [
        ("Nikkei",   ["JPN225", "JP225", "NIK225", ".N225", "Nikkei"]),
        ("HangSeng", ["HK50", "HKG33", "HSI", ".HSI"]),
        ("ASX200",   ["AUS200", "AU200", "SPI200"]),
        ("CAC40",    ["FRA40", "FR40", "CAC40"]),
        ("FTSE",     ["UK100", "FTSE100", "FTSE"]),
        ("STOXX",    ["EU50", "STOXX50", "EUSTX50"]),
    ],
}

D1 = 16408


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client, MT5Error

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...\n")
    with MT5Client.from_config(cfg) as client:
        end = datetime.now(UTC)
        start = end - timedelta(days=30)

        confirmed = {}
        for category, items in CANDIDATES.items():
            print(f"\n=== {category} ===")
            print(f"  {'name':<11} {'broker':<14} {'spread':>7} {'point':>10} "
                  f"{'tickval':>9} {'recent':>13}  status")
            print("  " + "-" * 95)
            for label, candidates in items:
                picked = None
                for sym in candidates:
                    try:
                        info = client.fetch_symbol_info(sym)
                    except MT5Error:
                        continue
                    try:
                        df = client.fetch_ohlcv(sym, D1, start, end)
                    except MT5Error:
                        continue
                    if df.empty:
                        continue
                    last = float(df["close"].iloc[-1])
                    print(f"  {label:<11} {sym:<14} {int(info['spread']):>7} "
                          f"{info['point']:>10.6f} {info['tick_value']:>9.4f} "
                          f"{last:>13.4f}  OK ({len(df)} bars/30d)")
                    confirmed[label] = {"symbol": sym, "category": category,
                                        "info": info, "last": last,
                                        "bars_30d": len(df)}
                    picked = sym
                    break
                if picked is None:
                    print(f"  {label:<11} {'(none)':<14}  --not on broker--")

        print(f"\n{'=' * 70}")
        print(f"  {len(confirmed)} symbols confirmed across categories")
        print(f"{'=' * 70}")
        by_cat = {}
        for label, rec in confirmed.items():
            by_cat.setdefault(rec["category"], []).append((label, rec["symbol"]))
        for cat, items in by_cat.items():
            sym_list = ", ".join(f"{l}->{s}" for l, s in items)
            print(f"  {cat}")
            print(f"    {sym_list}")


if __name__ == "__main__":
    main()
