"""
Parquet cache for MT5 historical data.

Key scheme: data/cache/<SYMBOL>/<TIMEFRAME>/<YEAR>/<MONTH>.parquet
            e.g. data/cache/EURUSD/H1/2026/05.parquet

Each parquet file stores all bars/ticks for that (symbol, timeframe, year, month).
A SHA-256 sidecar file (<name>.sha256) lets us detect silent corruption.

Usage:
    from data.cache import ParquetCache
    cache = ParquetCache()
    cache.write("EURUSD", "H1", df)
    df = cache.read("EURUSD", "H1", start, end)
    cache.invalidate("EURUSD", "H1")            # drop all months for symbol+tf
    cache.invalidate("EURUSD", "H1", 2026, 5)   # drop one month
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeframe tag → human-readable folder name (must be stable — keys on disk)
# ---------------------------------------------------------------------------
# MT5 TIMEFRAME_* constants are ints; we map them to short strings for paths.
# Import MetaTrader5 lazily so the cache works without it (tests, analysis).

_TF_NAMES: dict[int, str] = {
    1: "M1",
    5: "M5",
    15: "M15",
    30: "M30",
    16385: "H1",
    16386: "H2",
    16388: "H4",
    16390: "H6",
    16392: "H8",
    16396: "H12",
    16408: "D1",
    32769: "W1",
    49153: "MN1",
}


def _tf_name(timeframe: int | str) -> str:
    if isinstance(timeframe, str):
        return timeframe
    name = _TF_NAMES.get(timeframe)
    if name is None:
        raise ValueError(f"Unknown MT5 timeframe integer: {timeframe}. Add it to _TF_NAMES.")
    return name


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheIntegrityError(RuntimeError):
    """Raised when a parquet file's hash doesn't match its sidecar."""


class ParquetCache:
    """Read/write parquet-based cache for OHLCV and tick DataFrames.

    Thread-safety: reads are safe; concurrent writes to the same
    (symbol, timeframe, year, month) are not protected — don't do that.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        if cache_dir is None:
            cache_dir = Path(__file__).resolve().parent.parent / "data" / "cache"
        self._root = cache_dir
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def write(
        self,
        symbol: str,
        timeframe: int | str,
        df: pd.DataFrame,
    ) -> None:
        """Write df into the cache, splitting by (year, month) automatically.

        df must have a timezone-aware DatetimeIndex.
        Existing months are overwritten entirely — no partial merges.
        """
        self._assert_index(df)
        tf = _tf_name(timeframe)
        for (year, month), chunk in df.groupby(
            [df.index.year, df.index.month]  # type: ignore[attr-defined]
        ):
            path = self._path(symbol, tf, int(year), int(month))
            path.parent.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(path, engine="pyarrow", index=True)
            self._write_hash(path)
            log.debug(
                "cache.write",
                extra={
                    "symbol": symbol,
                    "tf": tf,
                    "year": year,
                    "month": month,
                    "rows": len(chunk),
                    "path": str(path),
                },
            )

    def read(
        self,
        symbol: str,
        timeframe: int | str,
        start: datetime,
        end: datetime,
    ) -> Optional[pd.DataFrame]:
        """Read bars between start and end (inclusive) from cache.

        Returns None if no cached data exists for the range.
        Returns a DataFrame (may be empty) if the months exist but contain no rows in range.
        Raises CacheIntegrityError if a hash mismatch is detected.
        """
        tf = _tf_name(timeframe)
        months = _month_range(start, end)
        chunks: list[pd.DataFrame] = []

        for year, month in months:
            path = self._path(symbol, tf, year, month)
            if not path.exists():
                continue
            self._verify_hash(path)
            chunk = pd.read_parquet(path, engine="pyarrow")
            chunks.append(chunk)

        if not chunks:
            return None

        df = pd.concat(chunks).sort_index()

        # Ensure timezone-aware index after round-trip
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")

        # Slice to the requested range
        start_utc = _to_utc(start)
        end_utc = _to_utc(end)
        df = df.loc[start_utc:end_utc]
        return df

    def has(
        self,
        symbol: str,
        timeframe: int | str,
        start: datetime,
        end: datetime,
    ) -> bool:
        """True if ALL months in [start, end] have a cache file (hash not checked)."""
        tf = _tf_name(timeframe)
        for year, month in _month_range(start, end):
            if not self._path(symbol, tf, year, month).exists():
                return False
        return True

    def invalidate(
        self,
        symbol: str,
        timeframe: int | str,
        year: int | None = None,
        month: int | None = None,
    ) -> int:
        """Delete cached files. Returns the number of parquet files removed.

        invalidate("EURUSD", "H1")         → removes all months for EURUSD H1
        invalidate("EURUSD", "H1", 2026)   → removes all months in 2026
        invalidate("EURUSD", "H1", 2026, 5) → removes May 2026 only
        """
        tf = _tf_name(timeframe)
        base = self._root / symbol / tf

        if year is None:
            targets = list(base.rglob("*.parquet")) if base.exists() else []
        elif month is None:
            year_dir = base / str(year)
            targets = list(year_dir.rglob("*.parquet")) if year_dir.exists() else []
        else:
            path = self._path(symbol, tf, year, month)
            targets = [path] if path.exists() else []

        removed = 0
        for p in targets:
            p.unlink(missing_ok=True)
            sha = p.with_suffix(".sha256")
            sha.unlink(missing_ok=True)
            removed += 1
            log.debug("cache.invalidate", extra={"path": str(p)})

        return removed

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _path(self, symbol: str, tf: str, year: int, month: int) -> Path:
        return self._root / symbol / tf / str(year) / f"{month:02d}.parquet"

    def _write_hash(self, path: Path) -> None:
        digest = _sha256(path)
        path.with_suffix(".sha256").write_text(digest, encoding="ascii")

    def _verify_hash(self, path: Path) -> None:
        sha_path = path.with_suffix(".sha256")
        if not sha_path.exists():
            # No sidecar — written before hashing was introduced; allow it.
            return
        expected = sha_path.read_text(encoding="ascii").strip()
        actual = _sha256(path)
        if actual != expected:
            raise CacheIntegrityError(
                f"Hash mismatch for {path}: expected {expected[:12]}…, got {actual[:12]}…"
            )

    @staticmethod
    def _assert_index(df: pd.DataFrame) -> None:
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("DataFrame must have a DatetimeIndex.")
        if df.index.tzinfo is None:
            raise TypeError("DatetimeIndex must be timezone-aware (UTC).")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_utc(dt: datetime) -> pd.Timestamp:
    if dt.tzinfo is None:
        return pd.Timestamp(dt, tz="UTC")
    return pd.Timestamp(dt.astimezone(timezone.utc))


def _month_range(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """All (year, month) pairs that overlap [start, end]."""
    s = start if start.tzinfo is None else start.astimezone(timezone.utc)
    e = end if end.tzinfo is None else end.astimezone(timezone.utc)

    result: list[tuple[int, int]] = []
    year, month = s.year, s.month
    while (year, month) <= (e.year, e.month):
        result.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return result
