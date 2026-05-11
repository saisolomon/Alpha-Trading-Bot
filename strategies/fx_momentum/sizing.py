"""
Position sizing for FX Cross-Sectional Momentum.

Method: Fractional Kelly (¼ Kelly), capped at the FTMO per-trade risk limit.

The Kelly fraction is computed from:
  - Historical win rate and average win/loss ratio (updated on each rebalance)
  - Scaled by kelly_fraction (default 0.25 — conservative)
  - Hard-capped at per_trade_risk_pct of equity

Stop placement: 1.5× ATR(14) from entry price. The stop distance determines
the lot size given the fixed risk budget (risk = lots × stop_distance × tick_value).

Usage:
    sizer = MomentumSizer(config, spec)
    lot_size = sizer.compute_lots(
        equity=100_000,
        stop_distance_pips=25.0,
        win_rate=0.52,
        avg_win_loss_ratio=1.3,
    )
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backtest.costs import SymbolSpec


@dataclass(frozen=True)
class SizingConfig:
    """Position sizing parameters."""

    per_trade_risk_pct: float = 0.005    # 0.5% of equity per trade (hard cap)
    kelly_fraction: float = 0.25         # ¼ Kelly
    min_lots: float = 0.01               # broker minimum
    max_lots: float = 10.0               # absolute ceiling

    @classmethod
    def from_dict(cls, d: dict) -> "SizingConfig":
        risk = d.get("risk", {})
        return cls(
            per_trade_risk_pct=risk.get("per_trade_risk_pct", 0.005),
            kelly_fraction=risk.get("kelly_fraction", 0.25),
        )


class MomentumSizer:
    """Computes lot sizes for momentum trades.

    Parameters
    ----------
    config:
        SizingConfig — per-trade risk budget.
    spec:
        SymbolSpec — contract size and tick value for the symbol being traded.
    """

    def __init__(self, config: SizingConfig, spec: SymbolSpec) -> None:
        self._cfg = config
        self._spec = spec

    def kelly_fraction(
        self,
        win_rate: float,
        avg_win_loss_ratio: float,
    ) -> float:
        """Compute the fractional Kelly fraction.

        Parameters
        ----------
        win_rate:
            Historical win rate [0, 1].
        avg_win_loss_ratio:
            avg_win / avg_loss (must be > 0).

        Returns
        -------
        Scaled Kelly fraction (between 0 and per_trade_risk_pct).
        Uses: f* = W - (1-W)/R, scaled by kelly_fraction and capped.
        """
        if win_rate <= 0 or avg_win_loss_ratio <= 0:
            return self._cfg.per_trade_risk_pct  # fall back to fixed sizing

        full_kelly = win_rate - (1.0 - win_rate) / avg_win_loss_ratio
        if full_kelly <= 0:
            # Breakeven/negative Kelly (e.g. priors W=0.5, R=1.0): no Kelly edge
            # estimable yet — fall back to fixed per-trade risk so the strategy
            # can begin sampling. Live updates will refine once trades close.
            return self._cfg.per_trade_risk_pct

        return min(full_kelly * self._cfg.kelly_fraction, self._cfg.per_trade_risk_pct)

    def compute_lots(
        self,
        equity: float,
        stop_distance_price: float,
        win_rate: float = 0.50,
        avg_win_loss_ratio: float = 1.0,
    ) -> float:
        """Compute position size in lots for a single trade.

        Parameters
        ----------
        equity:
            Current account equity in account currency.
        stop_distance_price:
            Distance from entry to stop-loss in price units (e.g. 0.0025 for EURUSD).
        win_rate:
            Estimated win rate (from walk-forward OOS history).
        avg_win_loss_ratio:
            Estimated avg_win / avg_loss ratio.

        Returns
        -------
        Position size in lots, clipped to [min_lots, max_lots].
        """
        if stop_distance_price <= 0 or equity <= 0:
            return self._cfg.min_lots

        risk_fraction = self.kelly_fraction(win_rate, avg_win_loss_ratio)
        if risk_fraction <= 0:
            return 0.0

        risk_amount = equity * risk_fraction  # $$ to risk on this trade

        # P&L per lot per 1 price unit move = tick_value / point.
        # tick_value is already the account-currency value of one point per lot,
        # so multiplying by 1/point converts to value per full price unit.
        # EURUSD: 1.0 / 0.00001 = 100,000 → 1 pip (0.0001) on 1 lot = $10. ✓
        pnl_per_lot_per_price_unit = self._spec.tick_value / self._spec.point
        risk_per_lot = stop_distance_price * pnl_per_lot_per_price_unit

        if risk_per_lot <= 0:
            return self._cfg.min_lots

        raw_lots = risk_amount / risk_per_lot
        # Round to nearest 0.01 (standard broker minimum increment)
        lots = math.floor(raw_lots * 100) / 100.0
        return float(min(max(lots, self._cfg.min_lots), self._cfg.max_lots))

    def atr_stop_distance(self, atr: float, multiple: float = 1.5) -> float:
        """Compute stop-loss distance using ATR multiple.

        Parameters
        ----------
        atr:
            Average True Range in price units (from ATR(14)).
        multiple:
            ATR multiple for the stop (default 1.5).
        """
        return atr * multiple


def compute_atr(high: "pd.Series", low: "pd.Series", close: "pd.Series", period: int = 14) -> float:  # type: ignore[name-defined]
    """Compute the most recent ATR value.

    Parameters
    ----------
    high, low, close:
        pandas Series of bar data (must have at least `period + 1` bars).
    period:
        ATR period (default 14).

    Returns
    -------
    Most recent ATR value, or 0.0 if insufficient data.
    """
    import pandas as pd

    if len(close) < period + 1:
        return 0.0

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
