"""
Probe the connected MT5 broker for available equity-index CFD symbols.

Tries common naming conventions, reports which ones the broker exposes,
and prints contract spec + recent spread + a sample bar. The output of
this script tells us which symbols to actually backtest against.

Usage:
    uv run python scripts/probe_indices.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

UTC = timezone.utc

# Common naming variants per index, in priority order. The probe stops at the
# first variant that returns valid data.
INDEX_CANDIDATES: dict[str, list[str]] = {
    "S&P 500":      ["US500", "SPX500", "SP500", "US500.cash", ".SPX",   "USA500"],
    "NASDAQ 100":   ["NAS100", "USTEC", "NDX100", "NAS100.cash", ".NDX", "USATEC"],
    "Dow Jones 30": ["US30",  "WS30",  "DJ30",  "US30.cash",  ".DJI",   "USA30"],
    "DAX 40":       ["GER40", "DE40",  "GER30", "DAX40",      ".DAX",   "DE30"],
    "FTSE 100":     ["UK100", "FTSE100", "FTSE", "UK100.cash", ".FTSE", "UKX"],
    "Nikkei 225":   ["JP225", "JPN225", "JAP225", "JP225.cash", ".N225"],
}

D1 = 16408


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client, MT5Error

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...")
    with MT5Client.from_config(cfg) as client:
        print("Connected.\n")

        end = datetime.now(UTC)
        start = end - timedelta(days=30)

        print(f"{'Index':<14} {'Symbol':<14} {'spread(pts)':>11}  "
              f"{'point':>10}  {'tick_value':>10}  "
              f"{'contract':>9}  {'recent_close':>13}  status")
        print("-" * 110)

        confirmed: dict[str, dict] = {}

        for index_name, candidates in INDEX_CANDIDATES.items():
            picked = None
            for sym in candidates:
                try:
                    info = client.fetch_symbol_info(sym)
                except MT5Error:
                    continue

                # Try to fetch a few recent bars to confirm tradeable history
                try:
                    df = client.fetch_ohlcv(sym, D1, start, end)
                except MT5Error as exc:
                    print(f"{index_name:<14} {sym:<14} "
                          f"{'-':>11}  {'-':>10}  {'-':>10}  {'-':>9}  "
                          f"{'-':>13}  exists but no bars ({exc})")
                    continue

                if df.empty:
                    continue

                last_close = float(df["close"].iloc[-1])
                print(f"{index_name:<14} {sym:<14} "
                      f"{int(info['spread']):>11}  "
                      f"{info['point']:>10.5f}  "
                      f"{info['tick_value']:>10.4f}  "
                      f"{info['contract_size']:>9.0f}  "
                      f"{last_close:>13.2f}  OK ({len(df)} bars in 30d)")

                confirmed[index_name] = {
                    "symbol": sym,
                    "info": info,
                    "last_close": last_close,
                    "bars_30d": len(df),
                }
                picked = sym
                break

            if picked is None:
                print(f"{index_name:<14} {'(none)':<14} "
                      f"{'-':>11}  {'-':>10}  {'-':>10}  {'-':>9}  "
                      f"{'-':>13}  no variant found on this broker")

        # Summary block
        print(f"\n{'=' * 70}")
        print(f"  Confirmed tradeable indices: {len(confirmed)}")
        print(f"{'=' * 70}")
        for name, rec in confirmed.items():
            spec = rec["info"]
            spread_pct = spec["spread"] * spec["point"] / rec["last_close"] * 100
            print(f"  {name:<14} -> {rec['symbol']:<10}  "
                  f"spread {spec['spread']} pts ({spread_pct:.4f}% of price), "
                  f"$/point/lot ~ {spec['tick_value']:.4f}")

        if confirmed:
            print(f"\n  Suggested universe for backtest:")
            print(f"    {[r['symbol'] for r in confirmed.values()]}")
        else:
            print("\n  No index CFDs available on this broker. Strategy not viable here.")


if __name__ == "__main__":
    main()
