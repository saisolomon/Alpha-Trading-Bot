"""
Cost model for backtesting — spread, commission, and slippage.

All monetary values are in account currency (USD default).

P&L formula (standard FX, account in USD):
    pnl = direction * (exit_price - entry_price) / spec.point
            * spec.tick_value * volume

For EURUSD (contract_size=100_000, point=0.00001, tick_value=$1/lot/point):
    1 pip (0.0001) move on 1 lot = 0.0001/0.00001 * 1.0 * 1 = $10 ✓

For symbols quoted differently (e.g. USDJPY, XAUUSD) callers should supply
the correct tick_value from MT5 symbol_info at session initialisation.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolSpec:
    """Static market-microstructure data for one symbol.

    Populated from MT5 symbol_info() at session start. In backtests the
    values are typically pulled from cached symbol metadata.
    """

    symbol: str
    contract_size: float          # e.g. 100_000 for EURUSD
    point: float                  # smallest price increment, e.g. 0.00001
    tick_value: float             # account-currency value per 1 point per 1 lot
    commission_per_lot: float     # round-trip commission in account currency
    avg_spread_points: float      # average spread in points (for cost model)

    def pnl(self, entry: float, exit_price: float, direction: int, volume: float) -> float:
        """Compute realized P&L in account currency."""
        return direction * (exit_price - entry) / self.point * self.tick_value * volume


# ---------------------------------------------------------------------------
# Pre-defined specs for common symbols (for tests and quick prototypes)
# Real usage should pull from MT5 symbol_info.
# ---------------------------------------------------------------------------

EURUSD_SPEC = SymbolSpec(
    symbol="EURUSD",
    contract_size=100_000,
    point=0.00001,
    tick_value=1.0,       # $1 per point per lot (account in USD)
    commission_per_lot=3.5,
    avg_spread_points=1.5,
)

GBPUSD_SPEC = SymbolSpec(
    symbol="GBPUSD",
    contract_size=100_000,
    point=0.00001,
    tick_value=1.0,
    commission_per_lot=3.5,
    avg_spread_points=2.0,
)

USDJPY_SPEC = SymbolSpec(
    symbol="USDJPY",
    contract_size=100_000,
    point=0.001,
    tick_value=1.0,       # approx at 150 USDJPY; should be updated dynamically
    commission_per_lot=3.5,
    avg_spread_points=2.0,
)

XAUUSD_SPEC = SymbolSpec(
    symbol="XAUUSD",
    contract_size=100,    # 100 troy oz per lot
    point=0.01,
    tick_value=1.0,       # $1 per $0.01 move per lot
    commission_per_lot=5.0,
    avg_spread_points=30.0,
)


AUDJPY_SPEC = SymbolSpec(
    symbol="AUDJPY",
    contract_size=100_000,
    point=0.001,           # MT5 JPY-cross point (3-digit)
    tick_value=0.67,       # ~$ per point per lot at USDJPY~150 (APPROX; see note)
    commission_per_lot=3.0,
    avg_spread_points=5.0,
)
# NOTE on tick_value for sizing/edge: lots = risk$/(stop_dist/point*tick_value) and
# pnl = (exit-entry)/point*tick_value*lots, so tick_value CANCELS in the R-multiple —
# % returns / Sharpe / PF / win-rate are invariant to a tick_value approximation. It
# only scales the displayed lot count + the (second-order) commission/slippage cost.


@dataclass(frozen=True)
class CostModel:
    """Execution cost assumptions for backtesting.

    Parameters
    ----------
    slippage_multiplier:
        Slippage as a fraction of avg spread, applied on each fill.
        Default 0.5× (half spread). Scales up for large orders.
    volume_threshold_pct:
        Orders above this fraction of bar volume get extra slippage.
        Default 0.01 (1% of bar volume).
    volume_slippage_scale:
        Additional slippage per unit of volume/bar_volume above threshold.
        Linear. Default 0.5.
    """

    slippage_multiplier: float = 0.5
    volume_threshold_pct: float = 0.01
    volume_slippage_scale: float = 0.5

    def slippage_points(
        self,
        spec: SymbolSpec,
        volume: float,
        bar_volume: float | None = None,
    ) -> float:
        """Slippage in points for a fill of this size."""
        base = spec.avg_spread_points * self.slippage_multiplier
        if bar_volume and bar_volume > 0:
            frac = volume / bar_volume
            if frac > self.volume_threshold_pct:
                extra = (frac - self.volume_threshold_pct) * self.volume_slippage_scale
                base += spec.avg_spread_points * extra
        return base

    def fill_price(
        self,
        bar_open: float,
        direction: int,
        spec: SymbolSpec,
        volume: float = 1.0,
        bar_volume: float | None = None,
    ) -> float:
        """Simulated fill price at bar open, including spread + slippage."""
        slip = self.slippage_points(spec, volume, bar_volume) * spec.point
        return bar_open + direction * slip

    def round_trip_cost(self, volume: float, spec: SymbolSpec) -> float:
        """Total round-trip cost (commission both legs + spread cost on entry)."""
        commission = spec.commission_per_lot * volume
        spread_cost = spec.avg_spread_points * spec.point * spec.tick_value / spec.point * volume
        return commission + spread_cost * volume

    def commission(self, volume: float, spec: SymbolSpec) -> float:
        return spec.commission_per_lot * volume

    def slippage_cost(
        self,
        spec: SymbolSpec,
        volume: float,
        bar_volume: float | None = None,
    ) -> float:
        """Account-currency cost of one fill's slippage.

        For ATR-stop / ATR-TP exits the engine fills at the trigger price,
        not a slipped market price -- but in reality the bid-ask spread
        still costs you on exit. This helper computes that cost in $ so
        the engine can deduct it from gross P&L explicitly.

        For exit_z / time_stop exits the cost is already baked into
        `fill_price()` so callers should NOT double-charge.
        """
        slip_in_price = self.slippage_points(spec, volume, bar_volume) * spec.point
        pnl_per_lot_per_price = spec.tick_value / spec.point
        return slip_in_price * pnl_per_lot_per_price * volume


DEFAULT_COST_MODEL = CostModel()
