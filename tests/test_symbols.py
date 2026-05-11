"""
Unit tests for data/symbols.py — no MT5 connection required.
"""
from __future__ import annotations

import pytest

from data.symbols import (
    SymbolFilter,
    SymbolMeta,
    SymbolUniverse,
    _calc_spread_bips,
    _UNIVERSE_BASES,
)


# ---------------------------------------------------------------------------
# _calc_spread_bips
# ---------------------------------------------------------------------------


def test_spread_bips_eurusd_typical() -> None:
    # EURUSD: ask=1.08502, bid=1.08498, point=0.00001 → spread = 0.4 bips
    bips = _calc_spread_bips(ask=1.08502, bid=1.08498, point=0.00001)
    assert abs(bips - 0.4) < 0.01


def test_spread_bips_zero_bid_returns_inf() -> None:
    assert _calc_spread_bips(ask=1.0, bid=0.0, point=0.00001) == float("inf")


def test_spread_bips_wider_pair() -> None:
    # USDJPY: ask=149.502, bid=149.498, point=0.001 → spread_pts = 4 → 0.4 bips
    bips = _calc_spread_bips(ask=149.502, bid=149.498, point=0.001)
    assert abs(bips - 0.4) < 0.01


# ---------------------------------------------------------------------------
# resolve_offline
# ---------------------------------------------------------------------------


def test_resolve_offline_exact_match() -> None:
    available = ["EURUSD", "GBPUSD", "USDJPY"]
    assert SymbolUniverse.resolve_offline("EURUSD", available) == "EURUSD"


def test_resolve_offline_with_suffix() -> None:
    available = ["EURUSD.r", "GBPUSD.r"]
    assert SymbolUniverse.resolve_offline("EURUSD", available) == "EURUSD.r"


def test_resolve_offline_x_suffix() -> None:
    available = ["EURUSDx", "GBPUSDx"]
    assert SymbolUniverse.resolve_offline("EURUSD", available) == "EURUSDx"


def test_resolve_offline_not_found() -> None:
    assert SymbolUniverse.resolve_offline("EURUSD", ["AUDNZD", "XAUUSD"]) is None


def test_resolve_offline_prefers_exact_over_suffix() -> None:
    available = ["EURUSD", "EURUSD.r"]
    assert SymbolUniverse.resolve_offline("EURUSD", available) == "EURUSD"


# ---------------------------------------------------------------------------
# list_universes / universe_bases
# ---------------------------------------------------------------------------


def test_list_universes_returns_all() -> None:
    universes = SymbolUniverse.list_universes()
    assert "fx_majors" in universes
    assert "fx_minors" in universes
    assert "index_cfds" in universes
    assert "gold_oil" in universes


def test_universe_bases_fx_majors() -> None:
    bases = SymbolUniverse.universe_bases("fx_majors")
    assert "EURUSD" in bases
    assert "GBPUSD" in bases
    assert len(bases) == 7


def test_universe_bases_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown universe"):
        SymbolUniverse.universe_bases("nonexistent")


# ---------------------------------------------------------------------------
# SymbolFilter
# ---------------------------------------------------------------------------


def test_default_filter_max_spread() -> None:
    f = SymbolFilter()
    assert f.max_spread_bips == 5.0
    assert f.require_tradeable is True


# ---------------------------------------------------------------------------
# get() / resolve_symbol() without client raises
# ---------------------------------------------------------------------------


def test_get_without_client_raises() -> None:
    universe = SymbolUniverse(client=None)
    with pytest.raises(RuntimeError, match="MT5Client"):
        universe.get("fx_majors")


def test_resolve_symbol_without_client_raises() -> None:
    universe = SymbolUniverse(client=None)
    with pytest.raises(RuntimeError, match="MT5Client"):
        universe.resolve_symbol("EURUSD")


# ---------------------------------------------------------------------------
# SymbolMeta dataclass
# ---------------------------------------------------------------------------


def test_symbol_meta_fields() -> None:
    meta = SymbolMeta(
        broker_name="EURUSD",
        canonical_name="EURUSD",
        spread_bips=0.4,
        contract_size=100_000.0,
        tick_size=0.00001,
        point=0.00001,
        stops_level=0,
        freeze_level=0,
        tradeable=True,
    )
    assert meta.broker_name == "EURUSD"
    assert meta.spread_bips == 0.4
    assert meta.tradeable is True


# ---------------------------------------------------------------------------
# Universe base names sanity checks
# ---------------------------------------------------------------------------


def test_fx_majors_no_duplicates() -> None:
    bases = _UNIVERSE_BASES["fx_majors"]
    assert len(bases) == len(set(bases))


def test_all_universes_non_empty() -> None:
    for name, bases in _UNIVERSE_BASES.items():
        assert len(bases) > 0, f"Universe '{name}' is empty"
