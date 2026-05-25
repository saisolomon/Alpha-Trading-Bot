"""
List all symbols available on the connected MT5 broker, grouped by
category, so we can map our generic names (US500, XAUUSD, etc.) to
broker-specific names (SPX500_USD, XAU_USD, etc.).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()


def main():
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to {cfg.server}...")
    with MT5Client.from_config(cfg) as client:
        symbols = mt5.symbols_get()
        print(f"\nBroker has {len(symbols)} symbols total.\n")

        # Group by path/category
        by_path = {}
        for s in symbols:
            path = s.path.split("\\")[0] if "\\" in s.path else "ROOT"
            by_path.setdefault(path, []).append(s.name)

        for path, syms in sorted(by_path.items()):
            print(f"=== {path} ({len(syms)} symbols) ===")
            for sym in sorted(syms):
                print(f"  {sym}")
            print()


if __name__ == "__main__":
    main()
