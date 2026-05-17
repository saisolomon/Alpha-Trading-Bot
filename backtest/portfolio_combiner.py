"""
Multi-strategy portfolio combiner.

Takes a list of strategy result objects (each with an equity_curve and
equity_low Series) and combines them under a weighting scheme, producing
a single portfolio equity curve plus combined-portfolio metrics.

Weighting schemes:
  - equal_weight       : 1/N to each strategy
  - inverse_vol        : weight ∝ 1/sigma_strategy (volatility parity)
  - risk_parity        : iterative weights so each strategy contributes
                         equal variance to the portfolio (with correlations)

Aggregation:
  - Each strategy starts with its own copy of `initial_capital`.
  - The combined equity at time T = sum of each leg's equity at T.
  - The combined equity_low at T uses the per-leg equity_low (sum of worst
    intrabar) -- conservative.

FTMO simulator is then run on the combined equity. The combined account
must pass FTMO as a whole; per-strategy passing is necessary but not
sufficient.

References:
  - Maillard, Roncalli, Teiletche (2010), "The Properties of Equally
    Weighted Risk Contribution Portfolios" -- risk parity reference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class StrategyLeg:
    """One leg of the portfolio (one strategy's backtest output)."""
    name: str
    equity_curve: pd.Series      # absolute USD equity over time
    equity_low: pd.Series         # absolute USD worst intrabar
    initial_capital: float
    trades: list = None            # optional, for diagnostic printing

    def returns(self) -> pd.Series:
        return self.equity_curve.pct_change().dropna()


@dataclass
class PortfolioResult:
    """Combined portfolio output."""
    equity_curve: pd.Series
    equity_low: pd.Series
    weights: dict[str, float]
    leg_returns: pd.DataFrame      # aligned, one column per leg
    correlation: pd.DataFrame

    @property
    def total_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return float(self.equity_curve.iloc[-1] / self.equity_curve.iloc[0] - 1.0)

    @property
    def sharpe(self) -> float:
        r = self.equity_curve.pct_change().dropna()
        if r.std() <= 0:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        eq = self.equity_curve
        return float(((eq - eq.cummax()) / eq.cummax()).min())


# ---------------------------------------------------------------------------
# Weighting schemes
# ---------------------------------------------------------------------------


def equal_weights(legs: list[StrategyLeg]) -> dict[str, float]:
    n = len(legs)
    return {leg.name: 1.0 / n for leg in legs}


def inverse_vol_weights(legs: list[StrategyLeg]) -> dict[str, float]:
    """Weight inversely proportional to each leg's annualised volatility."""
    vols = {leg.name: float(leg.returns().std() * np.sqrt(252)) for leg in legs}
    inv = {k: 1.0 / v if v > 0 else 0.0 for k, v in vols.items()}
    total = sum(inv.values())
    if total <= 0:
        return equal_weights(legs)
    return {k: v / total for k, v in inv.items()}


def risk_parity_weights(legs: list[StrategyLeg], iters: int = 50) -> dict[str, float]:
    """Iterative risk-parity (each leg contributes equal portfolio variance).

    Per Maillard et al. (2010), with covariance Σ and weights w:
      risk_contribution_i = w_i * (Σ w)_i / sqrt(w' Σ w)
    For equal risk contributions, fixed-point iteration:
      w_i_new ∝ 1 / (Σ w)_i
    Normalise and repeat.
    """
    df = pd.concat({leg.name: leg.returns() for leg in legs}, axis=1).dropna()
    if df.empty:
        return equal_weights(legs)
    cov = df.cov().to_numpy()
    n = cov.shape[0]
    if n == 0:
        return equal_weights(legs)
    w = np.ones(n) / n
    for _ in range(iters):
        Sw = cov @ w
        # Avoid divide-by-zero
        new_w = np.where(Sw > 1e-12, 1.0 / Sw, 1.0)
        new_w = new_w / new_w.sum()
        if np.allclose(new_w, w, atol=1e-8):
            break
        w = new_w
    names = list(df.columns)
    return {names[i]: float(w[i]) for i in range(n)}


WEIGHTING_SCHEMES = {
    "equal": equal_weights,
    "inverse_vol": inverse_vol_weights,
    "risk_parity": risk_parity_weights,
}


# ---------------------------------------------------------------------------
# Combiner
# ---------------------------------------------------------------------------


def combine(
    legs: list[StrategyLeg],
    weighting: str = "equal",
    total_capital: float = 100_000.0,
) -> PortfolioResult:
    """Combine N strategy legs into one portfolio equity curve.

    Each leg's per-period RETURN is multiplied by its weight; combined
    return = sum of weighted returns. Portfolio equity is compounded from
    those returns starting at `total_capital`.

    This treats each leg as receiving `weight * total_capital` of starting
    capital. The leg's existing equity_curve / equity_low (denominated in
    its own initial_capital) is scaled via per-period returns -- so the
    sizing differences between legs ARE preserved (a leg sized to deliver
    Sharpe 0.5 at initial_capital=$100k delivers the same Sharpe regardless
    of the weight assigned to it; the weight just changes the dollar
    allocation).
    """
    if not legs:
        raise ValueError("combine() needs at least one leg")
    if weighting not in WEIGHTING_SCHEMES:
        raise ValueError(f"unknown weighting={weighting!r}; "
                          f"choose from {list(WEIGHTING_SCHEMES)}")

    weights = WEIGHTING_SCHEMES[weighting](legs)

    # Align all legs on a shared index (intersection)
    leg_rets = {leg.name: leg.returns() for leg in legs}
    rets_df = pd.concat(leg_rets, axis=1).dropna(how="all").fillna(0.0)

    # Per-period portfolio return = sum of (weight * leg_return)
    w_array = np.array([weights[name] for name in rets_df.columns])
    port_rets = rets_df.to_numpy() @ w_array
    port_rets_s = pd.Series(port_rets, index=rets_df.index, name="portfolio_return")

    # Compounded equity curve
    eq = total_capital * (1.0 + port_rets_s).cumprod()
    # Prepend the initial bar
    first_ts = rets_df.index[0] - (rets_df.index[1] - rets_df.index[0])
    eq = pd.concat([pd.Series([total_capital], index=[first_ts]), eq])

    # equity_low approximation: at each bar, the portfolio's worst intrabar
    # equity is the close equity reduced by a weighted sum of per-leg
    # intrabar drawdowns. Conservative: assumes all legs hit their worst
    # intrabar simultaneously (which is unlikely at rho ~= 0, but we err
    # toward over-estimating drawdown for FTMO safety).
    leg_intra_dd: dict[str, pd.Series] = {}
    for leg in legs:
        close = leg.equity_curve.replace(0.0, np.nan)
        low = leg.equity_low.reindex(close.index).ffill()
        leg_intra_dd[leg.name] = ((low - close) / close).fillna(0.0)
    dd_df = pd.concat(leg_intra_dd, axis=1).reindex(eq.index).fillna(0.0)
    weighted_dd = dd_df.to_numpy() @ w_array        # always <= 0
    eq_low_series = eq * (1.0 + weighted_dd)
    # Guarantee equity_low <= equity_curve (defensive; weighted_dd is <= 0)
    eq_low_series = pd.concat([eq, eq_low_series], axis=1).min(axis=1)

    correlation = rets_df.corr() if rets_df.shape[1] > 1 else pd.DataFrame()

    return PortfolioResult(
        equity_curve=eq,
        equity_low=eq_low_series,
        weights=weights,
        leg_returns=rets_df,
        correlation=correlation,
    )
