"""
Probe additional broker symbols not covered by probe_universe.py:
  - Government bond CFDs (Bund, US Treasury notes)
  - Single-stock CFDs (top US megacaps + a few EU/JP names)
  - Additional crypto (DOGE, ADA, AVAX, MATIC, DOT)
  - Volatility products (VIX cash + futures CFDs)
  - Agricultural commodities not in probe_universe (Wheat, Corn, Soy)

Uses the same "try each name variant, keep the first the broker accepts"
pattern. Output: a clean confirmed-tradeable list per category.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

UTC = timezone.utc

CANDIDATES = {
    "Bond CFDs (rate-differential / TSMOM)": [
        ("Bund10Y",       ["BUND", "Bund", "DE10YB", "GERMAN10Y", "BUND10Y"]),
        ("US10Y",         ["US10Y", "USTNote10Y", "UST10Y", "USNote", "USB10Y"]),
        ("US30Y",         ["US30Y", "USTBond", "UST30Y", "USB30Y", "USBOND"]),
        ("UK10Y_Gilt",    ["GILT", "UK10Y", "GiltLong"]),
    ],
    "Single-stock CFDs (cross-sectional momentum / sector pairs)": [
        ("Apple",         ["AAPL", "#AAPL", "AAPL.US", "Apple"]),
        ("Microsoft",     ["MSFT", "#MSFT", "MSFT.US"]),
        ("NVIDIA",        ["NVDA", "#NVDA", "NVDA.US"]),
        ("Tesla",         ["TSLA", "#TSLA", "TSLA.US"]),
        ("Meta",          ["META", "#META", "META.US"]),
        ("Alphabet",      ["GOOGL", "#GOOGL", "GOOGL.US"]),
        ("Amazon",        ["AMZN", "#AMZN", "AMZN.US"]),
        ("Berkshire",     ["BRK.B", "#BRK.B", "BRKB"]),
        ("JPMorgan",      ["JPM", "#JPM", "JPM.US"]),
        ("ExxonMobil",    ["XOM", "#XOM", "XOM.US"]),
    ],
    "Additional crypto (TSMOM / cross-sectional momentum)": [
        ("Dogecoin",      ["DOGEUSD", "DOGE/USD"]),
        ("Cardano",       ["ADAUSD",  "ADA/USD"]),
        ("Avalanche",     ["AVAXUSD", "AVAX/USD"]),
        ("Polkadot",      ["DOTUSD",  "DOT/USD"]),
        ("Polygon",       ["MATICUSD","MATIC/USD"]),
        ("Chainlink",     ["LINKUSD", "LINK/USD"]),
        ("Algorand",      ["ALGOUSD", "ALGO/USD"]),
    ],
    "Volatility products (VIX-spike / VRP)": [
        ("VIX",           ["VIX", "VIX.cash", "VIXIndex", "USVIX"]),
    ],
    "Agricultural commodities (TSMOM / weather seasonality)": [
        ("Wheat",         ["WHEAT", "WTI_WHEAT", "ZW", "WheatCBOT"]),
        ("Corn",          ["CORN", "ZC", "CornCBOT"]),
        ("Soybeans",      ["SOYBEAN", "ZS", "SoybeansCBOT"]),
        ("Lumber",        ["LUMBER", "LBR"]),
        ("Cattle",        ["CATTLE", "LE", "LiveCattle"]),
    ],
    "FX additional (carry/momentum baskets)": [
        ("USDPLN",        ["USDPLN"]),  # Polish zloty - EM carry candidate
        ("USDHUF",        ["USDHUF"]),  # Hungarian forint
        ("USDCZK",        ["USDCZK"]),  # Czech koruna
        ("EURTRY",        ["EURTRY"]),  # EUR-TRY carry
        ("EURSEK",        ["EURSEK"]),
        ("GBPSGD",        ["GBPSGD"]),
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
        all_confirmed = {}
        for category, items in CANDIDATES.items():
            print(f"\n=== {category} ===")
            print(f"  {'name':<14} {'broker':<14} {'spread':>7} {'point':>10} "
                  f"{'tickval':>9} {'last':>13}  status")
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
                    print(f"  {label:<14} {sym:<14} {int(info['spread']):>7} "
                          f"{info['point']:>10.6f} {info['tick_value']:>9.4f} "
                          f"{last:>13.4f}  OK ({len(df)} bars/30d)")
                    all_confirmed[label] = {"category": category, "symbol": sym}
                    picked = sym
                    break
                if picked is None:
                    print(f"  {label:<14} {'(none)':<14}  --not on broker--")

        print(f"\n{'=' * 70}")
        print(f"  {len(all_confirmed)} additional symbols confirmed")
        print(f"{'=' * 70}")
        by_cat = {}
        for label, rec in all_confirmed.items():
            by_cat.setdefault(rec["category"], []).append((label, rec["symbol"]))
        for cat, items in by_cat.items():
            sym_list = ", ".join(f"{l}->{s}" for l, s in items)
            print(f"  {cat}")
            print(f"    {sym_list}")


if __name__ == "__main__":
    main()
