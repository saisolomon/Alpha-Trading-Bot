"""
Load and inspect cached parquet data.

Usage:
    uv run python scripts/load_cached_data.py --symbol EURUSD --timeframe D1
    uv run python scripts/load_cached_data.py --symbol EURUSD --years 2
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc

_TF_MAP: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="D1", choices=list(_TF_MAP.keys()))
    p.add_argument("--years", type=int, default=5)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    from data.cache import ParquetCache

    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * args.years)
    tf_int = _TF_MAP[args.timeframe]

    df = cache.read(args.symbol, tf_int, start, end)

    if df is None or df.empty:
        print(f"No cached data for {args.symbol} {args.timeframe}. Run fetch_backtest_data.py first.")
        return

    print(f"\n{args.symbol} {args.timeframe} — {len(df)} bars")
    print(f"  From: {df.index[0]}")
    print(f"  To:   {df.index[-1]}")
    print(f"  Columns: {list(df.columns)}")
    print(f"\nFirst 3 bars:")
    print(df.head(3).to_string())
    print(f"\nLast 3 bars:")
    print(df.tail(3).to_string())


if __name__ == "__main__":
    main()
