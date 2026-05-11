"""
MT5 smoke tests — require a running MT5 terminal and a valid demo account.

These are skipped by default in CI. Run with:
    pytest -m live tests/test_mt5_smoke.py

Preconditions:
  - MT5 terminal installed and running on this Windows machine.
  - .env file with MT5_LOGIN, MT5_PASSWORD, MT5_SERVER populated.
  - Demo account (do NOT run smoke tests against a live funded account).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Skip entire module if MT5 package is unavailable (Linux CI, etc.)
# ---------------------------------------------------------------------------
try:
    import MetaTrader5 as mt5  # type: ignore[import]

    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

if not _MT5_AVAILABLE:
    pytest.skip("MetaTrader5 package not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():  # type: ignore[return]
    from dotenv import load_dotenv

    load_dotenv()

    from utils.config import MT5Config
    from data.mt5_client import MT5Client

    cfg = MT5Config()
    c = MT5Client.from_config(cfg)
    c.connect()
    yield c
    c.disconnect()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_connect_succeeds(client) -> None:  # type: ignore[no-untyped-def]
    """Connection must be alive after connect()."""
    assert client.is_connected(), "Expected is_connected() == True after connect()"


def test_account_info_returns_data(client) -> None:  # type: ignore[no-untyped-def]
    info = client.account_info()
    assert info is not None
    assert info.login > 0  # type: ignore[attr-defined]
    assert info.balance >= 0  # type: ignore[attr-defined]
    assert isinstance(info.currency, str)  # type: ignore[attr-defined]


def test_symbol_info_eurusd(client) -> None:  # type: ignore[no-untyped-def]
    info = client.symbol_info("EURUSD")
    assert info is not None
    assert info.trade_contract_size > 0  # type: ignore[attr-defined]
    assert info.point > 0  # type: ignore[attr-defined]


def test_fetch_ohlcv_eurusd_h1(client) -> None:  # type: ignore[no-untyped-def]
    """Fetch 100 H1 bars and verify shape and types."""
    import MetaTrader5 as mt5

    end = datetime.now(tz=timezone.utc)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    # Go back 7 days to guarantee enough bars across weekends
    from datetime import timedelta

    start = end - timedelta(days=7)

    df = client.fetch_ohlcv("EURUSD", mt5.TIMEFRAME_H1, start, end)

    assert len(df) >= 1, "Expected at least 1 bar returned"
    assert list(df.columns[:4]) == ["open", "high", "low", "close"]
    assert df.index.tzinfo is not None, "Index must be timezone-aware"
    assert not df[["open", "high", "low", "close"]].isnull().any().any(), "No NaNs in OHLC"
    assert (df["high"] >= df["low"]).all(), "high >= low for every bar"


def test_disconnect_cleans_up(client) -> None:  # type: ignore[no-untyped-def]
    """After disconnect the client reports not connected."""
    client.disconnect()
    assert not client.is_connected()
    # Reconnect for any remaining tests in the module
    client.connect()
