"""
Probe the connected MT5 broker for commodity CFD symbols.

Tries common naming conventions for the major tradable commodities
(precious metals, energy, base metals) and reports what's available
with contract specs and a sample bar.

Usage:
    uv run python scripts/probe_commodities.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

UTC = timezone.utc

CANDIDATES: dict[str, list[str]] = {
    "Gold":      ["XAUUSD", "GOLD", "GOLD.cash", "XAU/USD"],
    "Silver":    ["XAGUSD", "SILVER", "SILVER.cash", "XAG/USD"],
    "Platinum":  ["XPTUSD", "PLATINUM"],
    "Palladium": ["XPDUSD", "PALLADIUM"],
    "WTI Oil":   ["XTIUSD", "USOIL", "WTI", "CL", "OIL.WTI"],
    "Brent Oil": ["XBRUSD", "UKOIL", "BRENT", "OIL.BRENT"],
    "Nat Gas":   ["XNGUSD", "NATGAS", "NG", "NGAS"],
    "Copper":    ["XCUUSD", "COPPER", "HG"],
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

        print(f"{'Commodity':<11} {'Symbol':<14} {'spread':>6}  "
              f"{'point':>9}  {'tick_value':>10}  "
              f"{'contract':>9}  {'recent':>11}  status")
        print("-" * 105)

        confirmed: dict[str, dict] = {}
        for name, candidates in CANDIDATES.items():
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
                print(f"{name:<11} {sym:<14} {int(info['spread']):>6}  "
                      f"{info['point']:>9.5f}  {info['tick_value']:>10.4f}  "
                      f"{info['contract_size']:>9.0f}  {last:>11.2f}  "
                      f"OK ({len(df)} bars/30d)")
                confirmed[name] = {"symbol": sym, "info": info, "last": last}
                picked = sym
                break
            if picked is None:
                print(f"{name:<11} {'(none)':<14} {'-':>6}  {'-':>9}  "
                      f"{'-':>10}  {'-':>9}  {'-':>11}  not on broker")

        print(f"\n{'=' * 60}")
        print(f"  {len(confirmed)} commodities confirmed tradeable")
        if confirmed:
            print(f"  Suggested: {[r['symbol'] for r in confirmed.values()]}")


if __name__ == "__main__":
    main()
