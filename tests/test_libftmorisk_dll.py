"""
Smoke test: load the FTMO rule engine via Python ctypes through the live
MQL5 ABI (cpp/libquant.dll), and verify it behaves exactly as the OCaml
spec does.

Background:
  The FTMO rule logic exists in TWO implementations:
    - ocaml/lib/ftmo_rules.ml  -- formal spec + qcheck-proven invariants
    - cpp/src/ftmo_rules.cpp   -- production C++ port that ships in libquant.dll
  The C++ port runs in MQL5 because the OCaml shared lib on Windows has a
  flexdll DLL-init issue (see Memory.md / commit history). The two are
  kept in sync by tests/test_ocaml_cpp_parity.py which runs identical
  tick sequences through both and asserts the same status codes.

If this test passes, MQL5's live calls to libquant.dll produce the same
status codes the OCaml spec defines.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DLL_PATH = REPO_ROOT / "cpp" / "build" / "libquant.dll"


def _find_mingw_bin() -> Path | None:
    """Locate the MinGW bin dir that libftmorisk.dll's libgcc_s_seh-1.dll lives in."""
    gcc = shutil.which("gcc")
    if gcc:
        return Path(gcc).parent
    # Common winget install path
    fallback = Path(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT"
        r"_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin"
    ))
    return fallback if fallback.exists() else None


def _load_dll():
    if not DLL_PATH.exists():
        pytest.skip(f"libquant.dll not built -- run cmake build first")
    # On Python 3.8+ Windows, ctypes.WinDLL doesn't search PATH for
    # dependency DLLs. Register the MinGW bin dir for libgcc_s_seh-1.dll.
    if sys.platform == "win32":
        mingw_bin = _find_mingw_bin()
        if mingw_bin is not None:
            os.add_dll_directory(str(mingw_bin))
    # WinDLL = stdcall ABI on Windows (matches QUANT_CALL = __stdcall)
    return ctypes.WinDLL(str(DLL_PATH))


@pytest.fixture(scope="module")
def dll():
    lib = _load_dll()
    # Bind signatures so ctypes does the right marshaling
    lib.ftmo_new_account.argtypes = [ctypes.c_int, ctypes.c_double]
    lib.ftmo_new_account.restype = ctypes.c_long
    lib.ftmo_free_account.argtypes = [ctypes.c_long]
    lib.ftmo_free_account.restype = None
    lib.ftmo_apply_tick.argtypes = [ctypes.c_long, ctypes.c_double, ctypes.c_double]
    lib.ftmo_apply_tick.restype = ctypes.c_int
    lib.ftmo_check_pretrade.argtypes = [ctypes.c_long, ctypes.c_double, ctypes.c_double]
    lib.ftmo_check_pretrade.restype = ctypes.c_int
    lib.ftmo_daily_reset.argtypes = [ctypes.c_long, ctypes.c_double, ctypes.c_double]
    lib.ftmo_daily_reset.restype = ctypes.c_int
    lib.ftmo_status.argtypes = [ctypes.c_long]
    lib.ftmo_status.restype = ctypes.c_int
    return lib


# Status codes -- must match the OCaml side:
STATUS_ACTIVE = 0
STATUS_IMMINENT = 1
STATUS_INTERNAL_KILLED = 2
STATUS_FTMO_FAILED = 3

# Decision codes:
DECISION_ALLOW = 0
DECISION_DENY = 1
DECISION_IMMINENT = 2

# Account types:
ACCT_2STEP_PHASE1 = 1


# ---------------------------------------------------------------------------
# Basic load and round-trip
# ---------------------------------------------------------------------------


def test_dll_loads(dll):
    assert dll is not None


def test_new_account_returns_valid_handle(dll):
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    assert handle > 0
    dll.ftmo_free_account(handle)


def test_status_after_new_is_active(dll):
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        assert dll.ftmo_status(handle) == STATUS_ACTIVE
    finally:
        dll.ftmo_free_account(handle)


# ---------------------------------------------------------------------------
# Tick behaviour
# ---------------------------------------------------------------------------


def test_active_after_small_drawdown(dll):
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        s = dll.ftmo_apply_tick(handle, 0.0, 99_500.0)
        assert s == STATUS_ACTIVE, f"expected ACTIVE, got {s}"
    finally:
        dll.ftmo_free_account(handle)


def test_internal_kill_fires_at_internal_threshold(dll):
    """On 2-Step Phase 1 the internal daily kill = -3% of $100k = $97k."""
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        s = dll.ftmo_apply_tick(handle, 0.0, 97_000.0)
        assert s == STATUS_INTERNAL_KILLED, f"expected INTERNAL_KILLED, got {s}"
    finally:
        dll.ftmo_free_account(handle)


def test_ftmo_fail_fires_below_ftmo_daily(dll):
    """FTMO daily line = -5% = $95k. Equity at $94k triggers Ftmo_failed
    (FTMO line beats internal kill in priority)."""
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        s = dll.ftmo_apply_tick(handle, 0.0, 94_000.0)
        assert s == STATUS_FTMO_FAILED, f"expected FTMO_FAILED, got {s}"
    finally:
        dll.ftmo_free_account(handle)


def test_terminal_status_doesnt_revert(dll):
    """Once killed, subsequent ticks must not return ACTIVE."""
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        s1 = dll.ftmo_apply_tick(handle, 0.0, 96_000.0)  # internal kill
        assert s1 == STATUS_INTERNAL_KILLED
        s2 = dll.ftmo_apply_tick(handle, 1.0, 99_500.0)  # would be active if not killed
        assert s2 == STATUS_INTERNAL_KILLED
    finally:
        dll.ftmo_free_account(handle)


# ---------------------------------------------------------------------------
# Headroom check (pre-trade gate)
# ---------------------------------------------------------------------------


def test_pretrade_allow_small_order(dll):
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        d = dll.ftmo_check_pretrade(handle, 100_000.0, 300.0)
        assert d == DECISION_ALLOW
    finally:
        dll.ftmo_free_account(handle)


def test_pretrade_deny_large_order(dll):
    handle = dll.ftmo_new_account(ACCT_2STEP_PHASE1, 100_000.0)
    try:
        # $4000 worst-case loss would put equity at $96k, below internal kill ($97k)
        d = dll.ftmo_check_pretrade(handle, 100_000.0, 4_000.0)
        assert d == DECISION_DENY
    finally:
        dll.ftmo_free_account(handle)
