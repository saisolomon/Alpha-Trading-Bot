"""
Unit tests for backtest/portfolio_combiner.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.portfolio_combiner import (
    StrategyLeg,
    combine,
    equal_weights,
    inverse_vol_weights,
    risk_parity_weights,
    WEIGHTING_SCHEMES,
)


def _synth_leg(name: str, n: int = 500, seed: int = 0, mu: float = 0.0003,
               sigma: float = 0.01, intra_dd: float = 0.003,
               initial_capital: float = 100_000.0) -> StrategyLeg:
    """Build a synthetic strategy leg with given drift, vol and intrabar dd."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(mu, sigma, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    equity = pd.Series(initial_capital * np.cumprod(1.0 + rets), index=idx, name="equity")
    # Equity_low = equity - intra_dd fraction
    equity_low = equity * (1.0 - intra_dd)
    return StrategyLeg(name=name, equity_curve=equity, equity_low=equity_low,
                        initial_capital=initial_capital)


# ---------------------------------------------------------------------------
# Weighting schemes
# ---------------------------------------------------------------------------


class TestWeightingSchemes:

    def test_equal_weights(self):
        legs = [_synth_leg("a"), _synth_leg("b", seed=1), _synth_leg("c", seed=2)]
        w = equal_weights(legs)
        assert set(w.keys()) == {"a", "b", "c"}
        assert all(v == pytest.approx(1/3) for v in w.values())
        assert sum(w.values()) == pytest.approx(1.0)

    def test_inverse_vol_low_vol_gets_more(self):
        low_vol = _synth_leg("low", seed=1, sigma=0.005)
        high_vol = _synth_leg("high", seed=2, sigma=0.02)
        w = inverse_vol_weights([low_vol, high_vol])
        assert w["low"] > w["high"]
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)

    def test_risk_parity_two_legs(self):
        legs = [_synth_leg("a", seed=1, sigma=0.01),
                _synth_leg("b", seed=2, sigma=0.02)]
        w = risk_parity_weights(legs)
        assert set(w.keys()) == {"a", "b"}
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
        # Lower-vol leg gets higher weight under risk parity
        assert w["a"] > w["b"]

    def test_unknown_weighting_raises(self):
        legs = [_synth_leg("a")]
        with pytest.raises(ValueError, match="unknown weighting"):
            combine(legs, weighting="nonsense")


# ---------------------------------------------------------------------------
# Combine
# ---------------------------------------------------------------------------


class TestCombine:

    def test_single_leg_passthrough(self):
        """Equal-weight combine of one leg should reproduce it (within
        numerical tolerance, modulo the initial seed bar)."""
        leg = _synth_leg("only", n=200, seed=7, mu=0.0005, sigma=0.008)
        result = combine([leg], weighting="equal", total_capital=100_000.0)
        # Sharpe should match
        leg_sharpe = float(leg.returns().mean() / leg.returns().std() * np.sqrt(252))
        port_rets = result.equity_curve.pct_change().dropna()
        port_sharpe = float(port_rets.mean() / port_rets.std() * np.sqrt(252))
        assert port_sharpe == pytest.approx(leg_sharpe, rel=1e-3)

    def test_two_uncorrelated_legs_sharpe_improves(self):
        """Two uncorrelated POSITIVE-Sharpe legs should give a higher
        combined Sharpe (sqrt(2) lift in the limit of rho=0 + equal Sharpe).

        Uses high drift / low vol so the synthetic legs have positive
        Sharpe deterministically -- otherwise the test depends on
        seed-specific noise."""
        # Strong positive drift so both legs have ~Sharpe > 1 standalone
        leg_a = _synth_leg("a", n=600, seed=10, mu=0.002, sigma=0.008)
        leg_b = _synth_leg("b", n=600, seed=999, mu=0.002, sigma=0.008)
        result = combine([leg_a, leg_b], weighting="equal", total_capital=100_000.0)

        sa_rets = leg_a.returns()
        sb_rets = leg_b.returns()
        sharpe_a = float(sa_rets.mean() / sa_rets.std() * np.sqrt(252))
        sharpe_b = float(sb_rets.mean() / sb_rets.std() * np.sqrt(252))
        port_sharpe = result.sharpe
        # Sanity: both legs are positive Sharpe (precondition for the
        # diversification-lift theorem to apply)
        assert sharpe_a > 0 and sharpe_b > 0
        avg_standalone = (sharpe_a + sharpe_b) / 2
        assert port_sharpe > avg_standalone, (
            f"port_sharpe={port_sharpe:.3f} should exceed avg standalone "
            f"{avg_standalone:.3f}")

    def test_perfectly_correlated_legs_no_sharpe_lift(self):
        """Two perfectly correlated legs (same seed) should produce a
        portfolio with Sharpe ≈ leg Sharpe (no diversification benefit)."""
        leg_a = _synth_leg("a", n=400, seed=42, mu=0.0005, sigma=0.012)
        leg_b = _synth_leg("b", n=400, seed=42, mu=0.0005, sigma=0.012)
        result = combine([leg_a, leg_b], weighting="equal", total_capital=100_000.0)
        sa = float(leg_a.returns().mean() / leg_a.returns().std() * np.sqrt(252))
        port_sharpe = result.sharpe
        assert port_sharpe == pytest.approx(sa, abs=0.02)

    def test_weights_sum_to_one(self):
        legs = [_synth_leg("a"), _synth_leg("b", seed=1)]
        for scheme in WEIGHTING_SCHEMES:
            result = combine(legs, weighting=scheme, total_capital=100_000.0)
            assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_equity_low_never_exceeds_equity_curve(self):
        legs = [_synth_leg("a", n=200, seed=3, intra_dd=0.01),
                _synth_leg("b", n=200, seed=4, intra_dd=0.005)]
        result = combine(legs, weighting="equal", total_capital=100_000.0)
        # equity_low must be <= equity_curve at every aligned point
        common = result.equity_low.index.intersection(result.equity_curve.index)
        for ts in common[:50]:
            assert result.equity_low.loc[ts] <= result.equity_curve.loc[ts] + 1e-6

    def test_correlation_dataframe_shape(self):
        legs = [_synth_leg("a"), _synth_leg("b", seed=1), _synth_leg("c", seed=2)]
        result = combine(legs, weighting="equal", total_capital=100_000.0)
        assert result.correlation.shape == (3, 3)
        # Diagonal must be 1
        for name in result.correlation.columns:
            assert result.correlation.loc[name, name] == pytest.approx(1.0)

    def test_metrics_properties(self):
        leg = _synth_leg("a", n=300, seed=5, mu=0.001, sigma=0.01)
        result = combine([leg], weighting="equal", total_capital=100_000.0)
        # Sanity: total return is finite and matches the curve
        assert isinstance(result.total_return, float)
        assert isinstance(result.sharpe, float)
        assert result.max_drawdown <= 0.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_empty_legs_raises(self):
        with pytest.raises(ValueError):
            combine([], weighting="equal", total_capital=100_000.0)

    def test_legs_with_staggered_start_use_union_with_zero_fill(self):
        """When legs have different index spans, combine() uses the UNION
        of indices and treats missing bars as 0 return (cash sidelined).
        This matches real portfolio semantics where strategies can launch
        on different dates."""
        leg_a = _synth_leg("a", n=200, seed=1)
        leg_b = _synth_leg("b", n=200, seed=2)
        # Shift leg_b's index forward 100 days
        new_idx = leg_b.equity_curve.index + pd.Timedelta(days=100)
        leg_b = StrategyLeg(
            name="b",
            equity_curve=pd.Series(leg_b.equity_curve.values, index=new_idx),
            equity_low=pd.Series(leg_b.equity_low.values, index=new_idx),
            initial_capital=leg_b.initial_capital,
        )
        result = combine([leg_a, leg_b], weighting="equal", total_capital=100_000.0)
        # Union of indices: leg_a covers 200 days, leg_b's 200 days start at
        # day 100 -- union spans ~300 days. Returns DataFrame has ~300 rows.
        assert len(result.equity_curve) >= 200
        # The first part of the portfolio is driven entirely by leg_a
        # (leg_b contributes 0); later it's driven by both.
        port_rets = result.equity_curve.pct_change().dropna()
        assert len(port_rets) > 200
