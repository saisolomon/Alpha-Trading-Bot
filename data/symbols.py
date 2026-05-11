"""
Symbol universe management.

Responsibilities:
  - Define named universes (e.g. 'fx_majors', 'index_cfds').
  - Resolve broker-specific symbol suffixes (EURUSD vs EURUSD.r vs EURUSDx).
  - Apply liquidity and spread filters before returning tradeable symbols.
  - Never hardcode a raw symbol name anywhere else — always call get_universe()
    or resolve_symbol() so broker-suffix differences stay in one place.

Usage (with live MT5 client):
    from data.symbols import SymbolUniverse
    universe = SymbolUniverse(client)
    symbols = universe.get("fx_majors")   # returns broker-resolved names

Usage (offline / testing):
    universe = SymbolUniverse(client=None)
    canonical = universe.resolve_offline("EURUSD", ["EURUSD", "EURUSD.r"])
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.mt5_client import MT5Client

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical universe definitions
# Each entry is a list of base names (without broker suffixes).
# ---------------------------------------------------------------------------

_UNIVERSE_BASES: dict[str, list[str]] = {
    "fx_majors": [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD",
    ],
    "fx_minors": [
        "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
        "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
        "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
        "CADJPY", "CADCHF", "NZDJPY", "NZDCHF", "NZDCAD",
        "CHFJPY",
    ],
    "index_cfds": [
        "US30", "US500", "US100", "DE40", "UK100", "JP225", "AU200",
        # Broker aliases — resolved to whichever exists
        "USTEC", "SPX500", "NAS100", "DAX40", "FTSE100",
    ],
    "gold_oil": [
        "XAUUSD", "XAGUSD", "USOIL", "UKOIL",
        # Broker aliases
        "GOLD", "SILVER", "WTI", "BRENT",
    ],
}

# Common broker suffix patterns, tried in order when resolving a base name.
_BROKER_SUFFIXES: list[str] = [
    "",       # exact match first
    ".r",
    "x",
    ".pro",
    ".c",
    "m",
    "+",
    "_micro",
]

# ---------------------------------------------------------------------------
# Filter defaults (overridden via SymbolFilter config)
# ---------------------------------------------------------------------------

MAX_SPREAD_BIPS_DEFAULT: float = 5.0     # 5 basis points for liquid FX


@dataclass
class SymbolFilter:
    max_spread_bips: float = MAX_SPREAD_BIPS_DEFAULT
    require_tradeable: bool = True       # skip "close only" or non-tradeable symbols
    exclude_near_roll: bool = True       # skip CFDs within 24h of contract expiry


@dataclass
class SymbolMeta:
    """Resolved symbol with key contract parameters."""
    broker_name: str
    canonical_name: str                  # base name without broker suffix
    spread_bips: float
    contract_size: float
    tick_size: float
    point: float
    stops_level: int
    freeze_level: int
    tradeable: bool


# ---------------------------------------------------------------------------
# SymbolUniverse
# ---------------------------------------------------------------------------


class SymbolUniverse:
    """Resolves canonical universe names to broker-specific, filtered symbols.

    Parameters
    ----------
    client:
        An initialized MT5Client. Pass None to operate in offline mode
        (only resolve_offline() works without a client).
    symbol_filter:
        Spread and tradeability filter applied to every get() call.
    """

    def __init__(
        self,
        client: "MT5Client | None" = None,
        symbol_filter: SymbolFilter | None = None,
    ) -> None:
        self._client = client
        self._filter = symbol_filter or SymbolFilter()
        self._broker_symbols: set[str] | None = None   # lazily loaded

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, universe_name: str) -> list[SymbolMeta]:
        """Return filtered, broker-resolved symbols for the named universe.

        Requires a live MT5 client.
        """
        if self._client is None:
            raise RuntimeError("SymbolUniverse.get() requires a live MT5Client.")

        bases = _UNIVERSE_BASES.get(universe_name)
        if bases is None:
            raise ValueError(
                f"Unknown universe '{universe_name}'. "
                f"Available: {list(_UNIVERSE_BASES.keys())}"
            )

        self._ensure_broker_symbols()
        results: list[SymbolMeta] = []

        for base in bases:
            broker_name = self._resolve(base)
            if broker_name is None:
                log.warning("symbols.not_found", extra={"base": base})
                continue

            meta = self._build_meta(broker_name, base)
            if meta is None:
                continue

            if not self._passes_filter(meta):
                log.debug(
                    "symbols.filtered_out",
                    extra={"symbol": broker_name, "spread_bips": meta.spread_bips},
                )
                continue

            results.append(meta)

        log.info(
            "symbols.universe_loaded",
            extra={
                "universe": universe_name,
                "count": len(results),
                "names": [m.broker_name for m in results],
            },
        )
        return results

    def resolve_symbol(self, base_name: str) -> str | None:
        """Return the broker-specific name for a canonical base name, or None."""
        if self._client is None:
            raise RuntimeError("resolve_symbol() requires a live MT5Client.")
        self._ensure_broker_symbols()
        return self._resolve(base_name)

    @staticmethod
    def resolve_offline(base_name: str, available: list[str]) -> str | None:
        """Resolve a base name against a provided list (no MT5 required).

        Useful in tests and analysis notebooks.
        """
        for suffix in _BROKER_SUFFIXES:
            candidate = base_name + suffix
            if candidate in available:
                return candidate
        return None

    @staticmethod
    def list_universes() -> list[str]:
        return list(_UNIVERSE_BASES.keys())

    @staticmethod
    def universe_bases(universe_name: str) -> list[str]:
        """Return the canonical base names for a universe (no MT5 needed)."""
        bases = _UNIVERSE_BASES.get(universe_name)
        if bases is None:
            raise ValueError(f"Unknown universe: {universe_name!r}")
        return list(bases)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _ensure_broker_symbols(self) -> None:
        if self._broker_symbols is None:
            assert self._client is not None
            try:
                import MetaTrader5 as mt5  # type: ignore[import]

                self._client.ensure_connected()
                all_syms = mt5.symbols_get()
                self._broker_symbols = (
                    {s.name for s in all_syms} if all_syms else set()
                )
            except ImportError:
                self._broker_symbols = set()

    def _resolve(self, base: str) -> str | None:
        assert self._broker_symbols is not None
        for suffix in _BROKER_SUFFIXES:
            candidate = base + suffix
            if candidate in self._broker_symbols:
                return candidate
        return None

    def _build_meta(self, broker_name: str, canonical: str) -> SymbolMeta | None:
        assert self._client is not None
        try:
            info = self._client.symbol_info(broker_name)
            tick = self._client.symbol_tick(broker_name)
        except Exception as exc:
            log.warning(
                "symbols.info_error",
                extra={"symbol": broker_name, "error": str(exc)},
            )
            return None

        spread_bips = _calc_spread_bips(tick.ask, tick.bid, info.point)  # type: ignore[attr-defined]
        tradeable = getattr(info, "trade_mode", 0) not in (
            0,   # SYMBOL_TRADE_MODE_DISABLED
            4,   # SYMBOL_TRADE_MODE_CLOSEONLY
        )

        return SymbolMeta(
            broker_name=broker_name,
            canonical_name=canonical,
            spread_bips=spread_bips,
            contract_size=float(info.trade_contract_size),  # type: ignore[attr-defined]
            tick_size=float(info.trade_tick_size),  # type: ignore[attr-defined]
            point=float(info.point),  # type: ignore[attr-defined]
            stops_level=int(info.trade_stops_level),  # type: ignore[attr-defined]
            freeze_level=int(info.trade_freeze_level),  # type: ignore[attr-defined]
            tradeable=tradeable,
        )

    def _passes_filter(self, meta: SymbolMeta) -> bool:
        if self._filter.require_tradeable and not meta.tradeable:
            return False
        if meta.spread_bips > self._filter.max_spread_bips:
            return False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _calc_spread_bips(ask: float, bid: float, point: float) -> float:
    """Spread in basis points (1 bip = 0.0001 for FX majors)."""
    if bid <= 0:
        return float("inf")
    spread_points = (ask - bid) / point
    # Convert points to bips: for a 5-decimal pair (pip = 10 points),
    # 1 pip = 1 bip, so bips = spread_points / 10.
    # This is a reasonable approximation across FX and CFDs.
    return spread_points / 10.0
