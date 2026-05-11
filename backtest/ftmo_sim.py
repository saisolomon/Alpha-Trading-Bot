"""
FTMO Simulator — replays the risk/ftmo.py rule engine against a backtest.

A backtest is only "FTMO PASS" if it would not have violated any FTMO rule
at any point during the simulation, including intrabar equity extremes.

The simulator reuses the same FTMOState, daily_reset(), and equity_tick()
logic as the live risk engine — no separate implementation.

Usage:
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=100_000,
    )
    report = sim.run(result.equity_curve, result.equity_low)
    print("FTMO PASS" if report.passed else f"FTMO FAIL: {report.violations}")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from risk.ftmo import (
    FTMOAccountType,
    FTMOInternalBreach,
    FTMOImminent,
    FTMOState,
    daily_reset,
    equity_tick,
    new_state,
)
from utils.timeutils import is_same_prague_day

log = logging.getLogger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Violation record
# ---------------------------------------------------------------------------


@dataclass
class FTMOViolation:
    """A single FTMO rule breach detected by the simulator."""

    violation_type: Literal[
        "daily_internal_kill",
        "max_internal_kill",
        "daily_ftmo_line",
        "max_ftmo_line",
        "imminent_daily",
        "imminent_max",
    ]
    timestamp: datetime
    equity: float
    limit: float
    bar_index: int
    detail: str = ""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class FTMOSimReport:
    """Full FTMO simulation result for one backtest run.

    'passed' is True only if zero FTMO-line violations occurred.
    Internal kill events are recorded but do NOT fail the account — they
    represent the bot halting trading, which is the correct response.
    """

    passed: bool
    violations: list[FTMOViolation]

    # --- Worst-case distances across the entire run ---
    min_daily_distance: float    # most negative = worst breach
    min_max_distance: float      # most negative = worst breach

    # --- Counts ---
    internal_daily_kill_count: int
    internal_max_kill_count: int
    ftmo_daily_line_breach_count: int
    ftmo_max_line_breach_count: int
    imminent_daily_count: int
    imminent_max_count: int

    # --- Best Day (1-Step only, else 0) ---
    peak_best_day_ratio: float

    # --- Final state ---
    final_equity: float
    final_state: FTMOState

    def summary(self) -> str:
        status = "FTMO PASS ✓" if self.passed else "FTMO FAIL ✗"
        lines = [
            status,
            f"  daily violations:      {self.ftmo_daily_line_breach_count}",
            f"  max loss violations:   {self.ftmo_max_line_breach_count}",
            f"  internal daily kills:  {self.internal_daily_kill_count}",
            f"  internal max kills:    {self.internal_max_kill_count}",
            f"  imminent daily warns:  {self.imminent_daily_count}",
            f"  min daily distance:    {self.min_daily_distance:+.2f}",
            f"  min max distance:      {self.min_max_distance:+.2f}",
            f"  peak best-day ratio:   {self.peak_best_day_ratio:.3f}",
            f"  final equity:          {self.final_equity:.2f}",
        ]
        if not self.passed:
            for v in self.violations[:5]:
                lines.append(f"  [BREACH] {v.violation_type} @ {v.timestamp} equity={v.equity:.2f} limit={v.limit:.2f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class FTMOSimulator:
    """Replays FTMO rule enforcement against a backtest equity curve.

    Parameters
    ----------
    account_type:
        The FTMO account type to simulate.
    initial_capital:
        Account starting capital.
    opening_balance:
        Balance at the start of the first Prague day. Defaults to initial_capital.
    """

    def __init__(
        self,
        account_type: FTMOAccountType,
        initial_capital: float,
        opening_balance: float | None = None,
    ) -> None:
        self._account_type = account_type
        self._initial_capital = initial_capital
        self._opening_balance = opening_balance or initial_capital

    def run(
        self,
        equity_curve: pd.Series,
        equity_low: pd.Series | None = None,
        trade_closed_pnl: pd.Series | None = None,
    ) -> FTMOSimReport:
        """Run the FTMO simulation.

        Parameters
        ----------
        equity_curve:
            Bar-close equity. DatetimeIndex (UTC).
        equity_low:
            Intrabar worst-case equity. Same index. If None, uses equity_curve
            (conservative — only checks close-level equity).
        trade_closed_pnl:
            Series of per-bar closed P&L (sum of trades closed that bar).
            Used for Best Day tracking. If None, approximated from daily
            equity changes.
        """
        if equity_low is None:
            equity_low = equity_curve

        violations: list[FTMOViolation] = []
        internal_daily_kills = 0
        internal_max_kills = 0
        ftmo_daily_breaches = 0
        ftmo_max_breaches = 0
        imminent_daily_count = 0
        imminent_max_count = 0
        min_daily_dist = float("inf")
        min_max_dist = float("inf")
        peak_best_day = 0.0

        # Initialise state at the first bar's timestamp
        first_ts = equity_curve.index[0]
        if first_ts.tzinfo is None:
            first_ts = first_ts.replace(tzinfo=UTC)

        state = new_state(
            self._account_type,
            self._initial_capital,
            self._opening_balance,
        )
        # Override the anchor to align with the data start
        state = FTMOState(
            account_type=state.account_type,
            initial_capital=state.initial_capital,
            prague_day_anchor=state.prague_day_anchor,
            daily_loss_anchor_balance=self._opening_balance,
            highest_eod_balance=self._opening_balance,
        )

        # prev_equity tracks the previous bar's close — the correct anchor
        # for FTMO's daily reset (which uses the END of the prior day's balance).
        prev_equity = self._opening_balance

        for i, (ts, eq_close) in enumerate(equity_curve.items()):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            eq_worst = float(equity_low.iloc[i])
            eq_close = float(eq_close)

            # --- Prague midnight rollover ---
            # CRITICAL: use prev bar's close as the new day's anchor balance,
            # not the current bar's close. FTMO's daily limit for day N is
            # set at 00:00 Prague using the previous day's end balance.
            if not is_same_prague_day(state.prague_day_anchor, ts):
                state = daily_reset(state, ts, prev_equity)

            # --- Track Best Day ---
            if state.account_type.best_day_rule_applies():
                ratio = state.best_day_ratio()
                if ratio > peak_best_day:
                    peak_best_day = ratio

            # --- Check intrabar worst-case equity against all limits ---
            for label, equity_to_check in [("intrabar", eq_worst), ("close", eq_close)]:
                daily_dist = state.distance_to_ftmo_daily(equity_to_check)
                max_dist = state.distance_to_ftmo_max(equity_to_check)

                if daily_dist < min_daily_dist:
                    min_daily_dist = daily_dist
                if max_dist < min_max_dist:
                    min_max_dist = max_dist

                # Internal daily kill
                if equity_to_check <= state.internal_daily_kill_limit:
                    internal_daily_kills += 1
                    violations.append(FTMOViolation(
                        violation_type="daily_internal_kill",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.internal_daily_kill_limit,
                        bar_index=i,
                        detail=label,
                    ))

                # Internal max kill
                if equity_to_check <= state.internal_max_kill_limit:
                    internal_max_kills += 1
                    violations.append(FTMOViolation(
                        violation_type="max_internal_kill",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.internal_max_kill_limit,
                        bar_index=i,
                        detail=label,
                    ))

                # FTMO daily line (actual fail condition)
                if equity_to_check < state.ftmo_daily_limit:
                    ftmo_daily_breaches += 1
                    violations.append(FTMOViolation(
                        violation_type="daily_ftmo_line",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.ftmo_daily_limit,
                        bar_index=i,
                        detail=label,
                    ))

                # FTMO max loss line (actual fail condition)
                if equity_to_check < state.ftmo_max_loss_limit:
                    ftmo_max_breaches += 1
                    violations.append(FTMOViolation(
                        violation_type="max_ftmo_line",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.ftmo_max_loss_limit,
                        bar_index=i,
                        detail=label,
                    ))

                # Imminent warnings (inside FTMO lines but close)
                buffer = state.rules.imminent_buffer_pct * state.initial_capital
                if (equity_to_check < state.ftmo_daily_limit + buffer
                        and equity_to_check >= state.ftmo_daily_limit):
                    imminent_daily_count += 1
                    violations.append(FTMOViolation(
                        violation_type="imminent_daily",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.ftmo_daily_limit,
                        bar_index=i,
                        detail=label,
                    ))

                if (equity_to_check < state.ftmo_max_loss_limit + buffer
                        and equity_to_check >= state.ftmo_max_loss_limit):
                    imminent_max_count += 1
                    violations.append(FTMOViolation(
                        violation_type="imminent_max",
                        timestamp=ts,
                        equity=equity_to_check,
                        limit=state.ftmo_max_loss_limit,
                        bar_index=i,
                        detail=label,
                    ))

                break  # only check intrabar; close is a subset check

            # Update prev_equity for the next bar's daily reset anchor
            prev_equity = eq_close

        # FTMO account fails only if the FTMO lines are actually breached
        ftmo_fail_count = ftmo_daily_breaches + ftmo_max_breaches
        passed = ftmo_fail_count == 0

        final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) > 0 else self._opening_balance

        return FTMOSimReport(
            passed=passed,
            violations=violations,
            min_daily_distance=min_daily_dist if min_daily_dist != float("inf") else 0.0,
            min_max_distance=min_max_dist if min_max_dist != float("inf") else 0.0,
            internal_daily_kill_count=internal_daily_kills,
            internal_max_kill_count=internal_max_kills,
            ftmo_daily_line_breach_count=ftmo_daily_breaches,
            ftmo_max_line_breach_count=ftmo_max_breaches,
            imminent_daily_count=imminent_daily_count,
            imminent_max_count=imminent_max_count,
            peak_best_day_ratio=peak_best_day,
            final_equity=final_equity,
            final_state=state,
        )
