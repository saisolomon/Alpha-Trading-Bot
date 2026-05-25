"""
Diagnose the 'Terminal: Invalid params' error on M15 fetch.

Tries copy_rates_from on multiple timeframes to see which OANDA-Demo-1
has actually downloaded into MT5's local cache. The Python MT5 API can
only return bars that the terminal already has locally -- bars are
downloaded by opening a chart for that symbol+timeframe.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

TIMEFRAMES = [
    ("M1",  1),
    ("M5",  5),
    ("M15", 15),
    ("M30", 30),
    ("H1",  16385),
    ("H4",  16388),
    ("D1",  16408),
]

SYMBOLS = ["US500.sim", "EURUSD.sim", "XAUUSD.sim"]


def main():
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to {cfg.server}...\n")
    with MT5Client.from_config(cfg) as client:
        for sym in SYMBOLS:
            # Make sure symbol is selected (required for some MT5 versions)
            mt5.symbol_select(sym, True)
            print(f"=== {sym} ===")
            for label, tf in TIMEFRAMES:
                # Try copy_rates_from_pos first (uses local cache only,
                # doesn't request from server)
                rates = mt5.copy_rates_from_pos(sym, tf, 0, 100)
                if rates is None:
                    err = mt5.last_error()
                    print(f"  {label:<4}  None (err={err})")
                else:
                    print(f"  {label:<4}  {len(rates)} bars  first={datetime.fromtimestamp(rates[0]['time'], tz=timezone.utc)}  last={datetime.fromtimestamp(rates[-1]['time'], tz=timezone.utc)}")
            print()


if __name__ == "__main__":
    main()
