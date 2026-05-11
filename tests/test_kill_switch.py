"""
Unit tests for risk/kill_switch.py — all three circuit breakers.
No MT5 connection required (client=None).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from risk.kill_switch import KillSwitchManager, KillSwitchTripped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ks(tmp_path: Path) -> KillSwitchManager:
    return KillSwitchManager(client=None, state_dir=tmp_path)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_all_switches_start_clear(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    assert ks.daily_tripped is False
    assert ks.max_tripped is False
    assert ks.manual_tripped is False
    assert ks.any_tripped is False


def test_check_passes_when_clear(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.check()  # should not raise


# ---------------------------------------------------------------------------
# Daily kill switch
# ---------------------------------------------------------------------------


def test_trip_daily_sets_flag(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_daily()
    assert ks.daily_tripped is True
    assert ks.any_tripped is True


def test_check_raises_when_daily_tripped(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_daily()
    with pytest.raises(KillSwitchTripped) as exc_info:
        ks.check()
    assert exc_info.value.switch == "daily"


def test_trip_daily_idempotent(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_daily("first")
    ks.trip_daily("second")  # should not error
    assert ks.daily_tripped is True


def test_reset_daily_clears_flag(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_daily()
    ks.reset_daily()
    assert ks.daily_tripped is False
    ks.check()  # should not raise now


def test_reset_daily_on_clear_state_is_noop(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.reset_daily()  # should not raise or error
    assert ks.daily_tripped is False


# ---------------------------------------------------------------------------
# Max kill switch
# ---------------------------------------------------------------------------


def test_trip_max_sets_flag(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_max()
    assert ks.max_tripped is True
    assert ks.any_tripped is True


def test_trip_max_writes_sentinel_file(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_max("exceeded 7% internal limit")
    sentinel = tmp_path / "MANUAL_KILL.lock"
    assert sentinel.exists()
    content = sentinel.read_text(encoding="utf-8")
    assert "max_kill" in content


def test_check_raises_when_max_tripped(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    # trip_max() also writes the manual sentinel, so check() would see "manual" first.
    # Set the flag directly to isolate the max-kill path.
    with ks._lock:  # noqa: SLF001
        ks._max_tripped = True
    with pytest.raises(KillSwitchTripped) as exc_info:
        ks.check()
    assert exc_info.value.switch == "max"


def test_trip_max_idempotent(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_max("first")
    ks.trip_max("second")
    assert ks.max_tripped is True


def test_max_kill_not_cleared_by_reset_daily(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_max()
    ks.reset_daily()  # must NOT clear the max switch
    assert ks.max_tripped is True


# ---------------------------------------------------------------------------
# Manual kill switch
# ---------------------------------------------------------------------------


def test_trip_manual_writes_sentinel(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_manual("operator halt")
    sentinel = tmp_path / "MANUAL_KILL.lock"
    assert sentinel.exists()
    assert "manual_kill" in sentinel.read_text(encoding="utf-8")


def test_manual_tripped_detects_existing_sentinel(tmp_path: Path) -> None:
    sentinel = tmp_path / "MANUAL_KILL.lock"
    sentinel.write_text("manual_kill tripped: test\nDelete this file to re-enable.", encoding="utf-8")
    ks = _ks(tmp_path)
    assert ks.manual_tripped is True
    assert ks.any_tripped is True


def test_check_raises_when_manual_sentinel_exists(tmp_path: Path) -> None:
    sentinel = tmp_path / "MANUAL_KILL.lock"
    sentinel.write_text("manual_kill tripped: test\nDelete this file to re-enable.", encoding="utf-8")
    ks = _ks(tmp_path)
    with pytest.raises(KillSwitchTripped) as exc_info:
        ks.check()
    assert exc_info.value.switch == "manual"


def test_manual_cleared_by_deleting_sentinel(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_manual("test")
    (tmp_path / "MANUAL_KILL.lock").unlink()
    assert ks.manual_tripped is False
    ks.check()  # should not raise


# ---------------------------------------------------------------------------
# check() priority ordering
# ---------------------------------------------------------------------------


def test_check_raises_manual_over_others(tmp_path: Path) -> None:
    """manual_kill is checked first in check()."""
    ks = _ks(tmp_path)
    ks.trip_manual()
    ks._daily_tripped = True  # noqa: SLF001 — bypass trip_daily to avoid flatten call
    with pytest.raises(KillSwitchTripped) as exc_info:
        ks.check()
    assert exc_info.value.switch == "manual"


def test_check_raises_max_before_daily(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    # Set both flags directly to avoid flatten (no client)
    with ks._lock:  # noqa: SLF001
        ks._max_tripped = True
        ks._daily_tripped = True
    with pytest.raises(KillSwitchTripped) as exc_info:
        ks.check()
    assert exc_info.value.switch == "max"


# ---------------------------------------------------------------------------
# Flatten skipped gracefully when client=None
# ---------------------------------------------------------------------------


def test_flatten_skipped_without_client(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_daily()  # should not raise even though client is None
    assert ks.daily_tripped is True


def test_max_trip_skipped_flatten_without_client(tmp_path: Path) -> None:
    ks = _ks(tmp_path)
    ks.trip_max()  # no client — flatten logs a warning, sentinel file is still written
    assert ks.max_tripped is True
    assert (tmp_path / "MANUAL_KILL.lock").exists()


# ---------------------------------------------------------------------------
# State dir creation
# ---------------------------------------------------------------------------


def test_state_dir_created_on_init(tmp_path: Path) -> None:
    new_dir = tmp_path / "nested" / "state"
    assert not new_dir.exists()
    _ks(new_dir)
    assert new_dir.exists()
