"""
Unit tests for data/cache.py — no MT5 connection required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.cache import (
    CacheIntegrityError,
    ParquetCache,
    _month_range,
    _sha256,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(start: str, periods: int, freq: str = "h") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with a UTC DatetimeIndex."""
    idx = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = 1.1000 + rng.standard_normal(periods).cumsum() * 0.0005
    return pd.DataFrame(
        {
            "open": close - rng.uniform(0, 0.0002, periods),
            "high": close + rng.uniform(0, 0.0005, periods),
            "low": close - rng.uniform(0, 0.0005, periods),
            "close": close,
            "tick_volume": rng.integers(100, 1000, periods).astype(float),
            "spread": rng.integers(1, 5, periods).astype(float),
            "real_volume": rng.integers(0, 10, periods).astype(float),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# _month_range helper
# ---------------------------------------------------------------------------


def test_month_range_single_month() -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    assert _month_range(start, end) == [(2026, 5)]


def test_month_range_multi_month() -> None:
    start = datetime(2026, 3, 15, tzinfo=UTC)
    end = datetime(2026, 6, 10, tzinfo=UTC)
    assert _month_range(start, end) == [(2026, 3), (2026, 4), (2026, 5), (2026, 6)]


def test_month_range_year_boundary() -> None:
    start = datetime(2025, 11, 1, tzinfo=UTC)
    end = datetime(2026, 2, 28, tzinfo=UTC)
    assert _month_range(start, end) == [
        (2025, 11), (2025, 12), (2026, 1), (2026, 2)
    ]


# ---------------------------------------------------------------------------
# Write → read round-trip
# ---------------------------------------------------------------------------


def test_write_read_roundtrip(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 168)  # one week of hourly bars

    cache.write("EURUSD", "H1", df)

    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    result = cache.read("EURUSD", "H1", start, end)

    assert result is not None
    assert len(result) == len(df)
    pd.testing.assert_frame_equal(result, df, check_freq=False)


def test_write_creates_parquet_file(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 24)
    cache.write("GBPUSD", "H1", df)

    parquet_path = tmp_path / "GBPUSD" / "H1" / "2026" / "05.parquet"
    sha_path = parquet_path.with_suffix(".sha256")
    assert parquet_path.exists()
    assert sha_path.exists()


def test_read_returns_none_when_no_cache(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    assert cache.read("EURUSD", "H1", start, end) is None


def test_read_range_slicing(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 168)
    cache.write("EURUSD", "H1", df)

    # Read only first 24 hours
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 1, 23, 0, 0, tzinfo=UTC)
    result = cache.read("EURUSD", "H1", start, end)

    assert result is not None
    assert len(result) == 24
    assert result.index[0] == df.index[0]
    assert result.index[-1] <= pd.Timestamp(end)


def test_write_spans_month_boundary(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    # 48 hours starting on April 30 — will span April and May
    df = _make_ohlcv("2026-04-30", 48)
    cache.write("EURUSD", "H1", df)

    apr_path = tmp_path / "EURUSD" / "H1" / "2026" / "04.parquet"
    may_path = tmp_path / "EURUSD" / "H1" / "2026" / "05.parquet"
    assert apr_path.exists()
    assert may_path.exists()


def test_has_returns_true_when_all_months_present(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 168)
    cache.write("EURUSD", "H1", df)

    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    assert cache.has("EURUSD", "H1", start, end) is True


def test_has_returns_false_when_month_missing(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 24)
    cache.write("EURUSD", "H1", df)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    assert cache.has("EURUSD", "H1", start, end) is False


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_invalidate_single_month(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-04-30", 48)
    cache.write("EURUSD", "H1", df)

    removed = cache.invalidate("EURUSD", "H1", 2026, 4)
    assert removed == 1

    apr_path = tmp_path / "EURUSD" / "H1" / "2026" / "04.parquet"
    assert not apr_path.exists()

    # May should still be there
    may_path = tmp_path / "EURUSD" / "H1" / "2026" / "05.parquet"
    assert may_path.exists()


def test_invalidate_all(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-04-30", 48)
    cache.write("EURUSD", "H1", df)

    removed = cache.invalidate("EURUSD", "H1")
    assert removed == 2  # April + May

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    assert cache.read("EURUSD", "H1", start, end) is None


def test_invalidate_nonexistent_returns_zero(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    removed = cache.invalidate("EURUSD", "H1", 2020, 1)
    assert removed == 0


# ---------------------------------------------------------------------------
# Hash integrity
# ---------------------------------------------------------------------------


def test_hash_mismatch_raises(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 24)
    cache.write("EURUSD", "H1", df)

    parquet_path = tmp_path / "EURUSD" / "H1" / "2026" / "05.parquet"
    sha_path = parquet_path.with_suffix(".sha256")
    sha_path.write_text("deadbeef" * 8, encoding="ascii")  # corrupt the hash

    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    with pytest.raises(CacheIntegrityError):
        cache.read("EURUSD", "H1", start, end)


def test_missing_sha_sidecar_is_tolerated(tmp_path: Path) -> None:
    """Files written without a sidecar (legacy) should still be readable."""
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 24)
    cache.write("EURUSD", "H1", df)

    sha_path = tmp_path / "EURUSD" / "H1" / "2026" / "05.sha256"
    sha_path.unlink()

    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 31, tzinfo=UTC)
    result = cache.read("EURUSD", "H1", start, end)
    assert result is not None


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_write_rejects_naive_index(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    idx = pd.date_range("2026-05-01", periods=10, freq="h")  # no tz
    df = pd.DataFrame({"close": range(10)}, index=idx)
    with pytest.raises(TypeError, match="timezone-aware"):
        cache.write("EURUSD", "H1", df)


def test_write_rejects_non_datetime_index(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = pd.DataFrame({"close": range(10)}, index=range(10))
    with pytest.raises(TypeError, match="DatetimeIndex"):
        cache.write("EURUSD", "H1", df)


# ---------------------------------------------------------------------------
# Timeframe name resolution
# ---------------------------------------------------------------------------


def test_timeframe_int_resolves(tmp_path: Path) -> None:
    cache = ParquetCache(cache_dir=tmp_path)
    df = _make_ohlcv("2026-05-01", 24)
    cache.write("EURUSD", 16385, df)  # 16385 = TIMEFRAME_H1

    h1_path = tmp_path / "EURUSD" / "H1" / "2026" / "05.parquet"
    assert h1_path.exists()


def test_timeframe_unknown_int_raises(tmp_path: Path) -> None:
    from data.cache import _tf_name
    with pytest.raises(ValueError, match="Unknown MT5 timeframe"):
        _tf_name(99999)


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------


def test_sha256_stable(tmp_path: Path) -> None:
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    assert _sha256(f) == _sha256(f)


def test_sha256_differs_on_change(tmp_path: Path) -> None:
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    h1 = _sha256(f)
    f.write_bytes(b"hello world!")
    h2 = _sha256(f)
    assert h1 != h2
