"""
Fetch D1 historical data for the FX momentum universe from MT5 and cache to parquet.

Usage (from repo root, with MT5 terminal open):
    uv run python scripts/fetch_backtest_data.py

Optional flags:
    --years N       Years of history to fetch (default: 5)
    --symbols A B   Override symbol list
    --force         Re-fetch even if data already cached
    --timeframe TF  MT5 timeframe name: D1 (default), H4, H1

Output: data/cache/<SYMBOL>/D1/<YEAR>/<MONTH>.parquet
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure repo root is on path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

UTC = timezone.utc

UNIVERSE = [
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
]

# MT5 timeframe name → integer constant (avoids importing mt5 before connect)
_TF_MAP: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch MT5 historical data to parquet cache")
    p.add_argument("--years", type=int, default=5, help="Years of history (default: 5)")
    p.add_argument("--symbols", nargs="+", default=UNIVERSE, help="Symbol list")
    p.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    p.add_argument("--timeframe", default="D1", choices=list(_TF_MAP.keys()))
    return p.parse_args()


def main() -> None:
    args = parse_args()

    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    from data.cache import ParquetCache

    cfg = MT5Config()  # reads from .env
    cache = ParquetCache()

    end = datetime.now(UTC)
    start = end - timedelta(days=365 * args.years)
    tf_int = _TF_MAP[args.timeframe]
    tf_name = args.timeframe

    print(f"Fetching {tf_name} data for {len(args.symbols)} symbols, "
          f"{start.date()} to {end.date()} ({args.years} years)")

    with MT5Client.from_config(cfg) as client:
        for symbol in args.symbols:
            if not args.force and cache.has(symbol, tf_int, start, end):
                print(f"  {symbol}: already cached — skipping (use --force to refresh)")
                continue

            print(f"  {symbol}: fetching...", end=" ", flush=True)
            try:
                df = client.fetch_ohlcv(symbol, tf_int, start, end)
                cache.write(symbol, tf_int, df)
                print(f"{len(df)} bars cached")
            except Exception as exc:
                print(f"FAILED — {exc}")

    print("\nDone. Verify with:")
    print(f"  uv run python scripts/load_cached_data.py --symbol EURUSD --timeframe {tf_name}")


if __name__ == "__main__":
    main()
