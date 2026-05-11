"""
FTMO Compliance Core — the single source of truth for FTMO rule enforcement.

This module encodes FTMO's rule set for every account variant and provides:
  - FTMOAccountType   — enum of all six account types
  - FTMORules         — rule parameters per account type
  - FTMOState         — live accounting state (limits, balances, Best Day)
  - headroom_check()  — pre-trade gate: rejects orders too close to any limit
  - daily_reset()     — Prague-midnight boundary handler
  - equity_tick()     — called on every sub-second equity poll

CRITICAL: All monetary values are in account currency (USD, EUR, etc.).
All percentage limits are expressed as fractions (0.05 = 5%).

Read CLAUDE.md §3 before modifying anything here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from utils.timeutils import prague_midnight_of, to_prague, utc_now

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FTMOInternalBreach(RuntimeError):
    """Raised when equity crosses the bot's internal kill threshold.

    This is well inside FTMO's own line. The account is NOT failed — but
    trading must halt immediately and positions must be flattened.
    """

    def __init__(self, breach_type: str, equity: float, limit: float) -> None:
        super().__init__(
            f"Internal {breach_type} kill triggered: equity={equity:.2f}, limit={limit:.2f}"
        )
        self.breach_type = breach_type
        self.equity = equity
        self.limit = limit


class FTMOImminent(RuntimeWarning):
    """Raised when equity is within the imminent-warning buffer of an FTMO line.

    Not a hard kill — reduces position sizing and fires an alert.
    """

    def __init__(self, line_type: str, equity: float, ftmo_limit: float, distance: float) -> None:
        super().__init__(
            f"FTMO {line_type} imminent: equity={equity:.2f}, "
            f"ftmo_limit={ftmo_limit:.2f}, distance={distance:.4f}"
        )
        self.line_type = line_type
        self.equity = equity
        self.ftmo_limit = ftmo_limit
        self.distance = distance


# ---------------------------------------------------------------------------
# Account types
# ---------------------------------------------------------------------------


class FTMOAccountType(str, Enum):
    CHALLENGE_1STEP = "CHALLENGE_1STEP"
    CHALLENGE_2STEP_PHASE1 = "CHALLENGE_2STEP_PHASE1"
    CHALLENGE_2STEP_PHASE2 = "CHALLENGE_2STEP_PHASE2"
    FUNDED_STANDARD = "FUNDED_STANDARD"
    FUNDED_SWING = "FUNDED_SWING"
    FUNDED_REWARDS_1STEP = "FUNDED_REWARDS_1STEP"

    def is_1step(self) -> bool:
        return self in (
            FTMOAccountType.CHALLENGE_1STEP,
            FTMOAccountType.FUNDED_REWARDS_1STEP,
        )

    def is_funded(self) -> bool:
        return self in (
            FTMOAccountType.FUNDED_STANDARD,
            FTMOAccountType.FUNDED_SWING,
            FTMOAccountType.FUNDED_REWARDS_1STEP,
        )

    def news_restriction_applies(self) -> bool:
        """News window restriction only applies to standard funded accounts."""
        return self == FTMOAccountType.FUNDED_STANDARD

    def weekend_hold_allowed(self) -> bool:
        return self == FTMOAccountType.FUNDED_SWING

    def best_day_rule_applies(self) -> bool:
        return self.is_1step()

    def max_loss_is_trailing(self) -> bool:
        """On Funded Rewards (1-Step), max loss floor trails up with end-of-day highs."""
        return self == FTMOAccountType.FUNDED_REWARDS_1STEP


# ---------------------------------------------------------------------------
# Rule parameters per account type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FTMORules:
    """Immutable FTMO rule parameters for one account type."""

    account_type: FTMOAccountType

    # --- FTMO outer limits (fractions of initial_capital) ---
    ftmo_daily_loss_pct: float       # 0.05 (2-Step) or 0.03 (1-Step)
    ftmo_max_loss_pct: float         # 0.10 always
    profit_target_pct: float         # 0.10 Phase1, 0.05 Phase2/1Step, 0 Funded

    # --- Internal bot limits (fractions of initial_capital, inside FTMO lines) ---
    internal_daily_kill_pct: float   # 0.03 (2-Step) or 0.02 (1-Step)
    internal_max_kill_pct: float     # 0.07 always

    # --- Headroom safety buffer ---
    headroom_buffer_pct: float = 0.01   # reject if worst-case fill within 1% of FTMO line

    # --- Best Day rule (1-Step only) ---
    best_day_limit_ratio: float = 0.50   # FTMO limit: single day ≤ 50% of total profitable
    best_day_throttle_ratio: float = 0.40  # internal throttle at 40%

    # --- Warnings ---
    imminent_buffer_pct: float = 0.005  # FTMOImminent fires within 0.5% of FTMO line


_RULES: dict[FTMOAccountType, FTMORules] = {
    FTMOAccountType.CHALLENGE_1STEP: FTMORules(
        account_type=FTMOAccountType.CHALLENGE_1STEP,
        ftmo_daily_loss_pct=0.03,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.10,
        internal_daily_kill_pct=0.02,
        internal_max_kill_pct=0.07,
    ),
    FTMOAccountType.CHALLENGE_2STEP_PHASE1: FTMORules(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        ftmo_daily_loss_pct=0.05,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.10,
        internal_daily_kill_pct=0.03,
        internal_max_kill_pct=0.07,
    ),
    FTMOAccountType.CHALLENGE_2STEP_PHASE2: FTMORules(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE2,
        ftmo_daily_loss_pct=0.05,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.05,
        internal_daily_kill_pct=0.03,
        internal_max_kill_pct=0.07,
    ),
    FTMOAccountType.FUNDED_STANDARD: FTMORules(
        account_type=FTMOAccountType.FUNDED_STANDARD,
        ftmo_daily_loss_pct=0.05,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.0,
        internal_daily_kill_pct=0.03,
        internal_max_kill_pct=0.07,
    ),
    FTMOAccountType.FUNDED_SWING: FTMORules(
        account_type=FTMOAccountType.FUNDED_SWING,
        ftmo_daily_loss_pct=0.05,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.0,
        internal_daily_kill_pct=0.03,
        internal_max_kill_pct=0.07,
    ),
    FTMOAccountType.FUNDED_REWARDS_1STEP: FTMORules(
        account_type=FTMOAccountType.FUNDED_REWARDS_1STEP,
        ftmo_daily_loss_pct=0.03,
        ftmo_max_loss_pct=0.10,
        profit_target_pct=0.0,
        internal_daily_kill_pct=0.02,
        internal_max_kill_pct=0.07,
    ),
}


def get_rules(account_type: FTMOAccountType) -> FTMORules:
    return _RULES[account_type]


# ---------------------------------------------------------------------------
# Headroom check input/output
# ---------------------------------------------------------------------------


@dataclass
class IntendedOrder:
    """Minimal description of an order the strategy wants to send."""

    symbol: str
    volume: float         # lots
    stop_loss_distance: float   # in account currency (abs value, always positive)
    worst_case_loss: float      # in account currency — max possible loss on this trade


class HeadroomResult(NamedTuple):
    allowed: bool
    reason: str


# ---------------------------------------------------------------------------
# FTMO State — live accounting
# ---------------------------------------------------------------------------


@dataclass
class FTMOState:
    """In-memory FTMO accounting state. Persisted to JSON between sessions.

    All monetary values are in account currency.
    """

    account_type: FTMOAccountType
    initial_capital: float              # never changes after account creation

    # --- Daily loss tracking ---
    prague_day_anchor: datetime         # Prague midnight that started the current day
    daily_loss_anchor_balance: float    # account balance at that midnight (basis for daily limit)

    # --- Max loss tracking ---
    highest_eod_balance: float          # for trailing max loss (Funded Rewards 1-Step only)

    # --- Best Day tracking (1-Step only) ---
    today_closed_pnl: float = 0.0      # closed P&L in the current Prague day
    sum_profitable_day_pnl: float = 0.0  # sum of all profitable-day closed P&L

    # --- Rules (derived from account_type) ---
    rules: FTMORules = field(init=False)

    def __post_init__(self) -> None:
        self.rules = get_rules(self.account_type)

    # ------------------------------------------------------------------ #
    # Derived limits (account currency)                                    #
    # ------------------------------------------------------------------ #

    @property
    def ftmo_daily_limit(self) -> float:
        """Equity must NOT go below this (FTMO's actual line)."""
        return self.daily_loss_anchor_balance - (
            self.rules.ftmo_daily_loss_pct * self.initial_capital
        )

    @property
    def ftmo_max_loss_limit(self) -> float:
        """Equity must NOT go below this (FTMO's total drawdown line)."""
        if self.account_type.max_loss_is_trailing():
            # Funded Rewards: trailing up only
            floor_base = max(self.highest_eod_balance, self.initial_capital)
        else:
            floor_base = self.initial_capital
        return floor_base - (self.rules.ftmo_max_loss_pct * self.initial_capital)

    @property
    def internal_daily_kill_limit(self) -> float:
        """Bot's internal daily kill level — well above FTMO's daily line."""
        return self.daily_loss_anchor_balance - (
            self.rules.internal_daily_kill_pct * self.initial_capital
        )

    @property
    def internal_max_kill_limit(self) -> float:
        """Bot's internal total kill level — well above FTMO's max line."""
        return self.initial_capital - (
            self.rules.internal_max_kill_pct * self.initial_capital
        )

    # ------------------------------------------------------------------ #
    # Distances (positive = safe, negative = breached)                    #
    # ------------------------------------------------------------------ #

    def distance_to_ftmo_daily(self, equity: float) -> float:
        return equity - self.ftmo_daily_limit

    def distance_to_ftmo_max(self, equity: float) -> float:
        return equity - self.ftmo_max_loss_limit

    def distance_to_internal_daily(self, equity: float) -> float:
        return equity - self.internal_daily_kill_limit

    def distance_to_internal_max(self, equity: float) -> float:
        return equity - self.internal_max_kill_limit

    # ------------------------------------------------------------------ #
    # Best Day ratio                                                        #
    # ------------------------------------------------------------------ #

    def best_day_ratio(self, projected_additional_pnl: float = 0.0) -> float:
        """Current Best Day ratio, optionally projecting one more trade's P&L.

        Ratio = today_closed_pnl / sum_of_profitable_day_pnl.
        Returns 0.0 if no profitable days yet (avoids division by zero).
        """
        if not self.account_type.best_day_rule_applies():
            return 0.0

        today = self.today_closed_pnl + projected_additional_pnl
        denom = self.sum_profitable_day_pnl
        if today > 0:
            denom += today
        if denom <= 0:
            return 0.0
        return today / denom

    def would_breach_best_day(self, projected_pnl: float) -> bool:
        """True if adding projected_pnl would push Best Day ratio above the throttle."""
        if not self.account_type.best_day_rule_applies():
            return False
        return self.best_day_ratio(projected_pnl) > self.rules.best_day_throttle_ratio

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def to_json(self) -> str:
        return json.dumps(
            {
                "account_type": self.account_type.value,
                "initial_capital": self.initial_capital,
                "prague_day_anchor": self.prague_day_anchor.isoformat(),
                "daily_loss_anchor_balance": self.daily_loss_anchor_balance,
                "highest_eod_balance": self.highest_eod_balance,
                "today_closed_pnl": self.today_closed_pnl,
                "sum_profitable_day_pnl": self.sum_profitable_day_pnl,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "FTMOState":
        d = json.loads(text)
        return cls(
            account_type=FTMOAccountType(d["account_type"]),
            initial_capital=d["initial_capital"],
            prague_day_anchor=datetime.fromisoformat(d["prague_day_anchor"]),
            daily_loss_anchor_balance=d["daily_loss_anchor_balance"],
            highest_eod_balance=d["highest_eod_balance"],
            today_closed_pnl=d.get("today_closed_pnl", 0.0),
            sum_profitable_day_pnl=d.get("sum_profitable_day_pnl", 0.0),
        )

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")
        log.debug("ftmo_state.saved", extra={"path": str(path)})

    @classmethod
    def load(cls, path: Path) -> "FTMOState":
        return cls.from_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def new_state(
    account_type: FTMOAccountType,
    initial_capital: float,
    opening_balance: float | None = None,
) -> FTMOState:
    """Create a fresh FTMOState at the start of a trading session.

    opening_balance defaults to initial_capital (first day of the challenge).
    """
    now = utc_now()
    balance = opening_balance if opening_balance is not None else initial_capital
    return FTMOState(
        account_type=account_type,
        initial_capital=initial_capital,
        prague_day_anchor=prague_midnight_of(now),
        daily_loss_anchor_balance=balance,
        highest_eod_balance=balance,
    )


# ---------------------------------------------------------------------------
# daily_reset — Prague midnight boundary
# ---------------------------------------------------------------------------


def daily_reset(state: FTMOState, now: datetime, balance: float) -> FTMOState:
    """Recompute daily limits at the Prague midnight boundary.

    Called by the equity watcher when it detects a new Prague day.
    Returns a new FTMOState with updated anchors.

    The old day's P&L is rolled into Best Day tracking before reset.
    """
    # Roll Best Day tracking
    new_sum = state.sum_profitable_day_pnl
    if state.today_closed_pnl > 0:
        new_sum += state.today_closed_pnl

    # Update trailing max-loss floor for Funded Rewards
    new_highest = max(state.highest_eod_balance, balance)

    new_state = FTMOState(
        account_type=state.account_type,
        initial_capital=state.initial_capital,
        prague_day_anchor=prague_midnight_of(now),
        daily_loss_anchor_balance=balance,
        highest_eod_balance=new_highest,
        today_closed_pnl=0.0,
        sum_profitable_day_pnl=new_sum,
    )

    log.info(
        "daily.reset",
        extra={
            "account_type": state.account_type.value,
            "new_anchor_balance": balance,
            "new_daily_limit": new_state.ftmo_daily_limit,
            "new_max_limit": new_state.ftmo_max_loss_limit,
            "best_day_sum": new_sum,
        },
    )
    return new_state


# ---------------------------------------------------------------------------
# headroom_check — pre-trade gate
# ---------------------------------------------------------------------------


def headroom_check(
    order: IntendedOrder,
    equity: float,
    state: FTMOState,
) -> HeadroomResult:
    """Gate every order through FTMO and internal limit checks.

    Simulates worst-case fill (equity − order.worst_case_loss) and rejects
    if that puts equity within the safety buffer of any limit line.

    Returns HeadroomResult(allowed=True, reason="ok") or
    HeadroomResult(allowed=False, reason="<why>").

    This is called BEFORE mt5.order_check() — FTMO compliance gates the
    broker's own validation.
    """
    worst_case_equity = equity - abs(order.worst_case_loss)
    buffer = state.rules.headroom_buffer_pct * state.initial_capital

    # Check FTMO daily line
    ftmo_daily = state.ftmo_daily_limit
    if worst_case_equity < ftmo_daily + buffer:
        return HeadroomResult(
            allowed=False,
            reason=(
                f"headroom_daily: worst_case_equity={worst_case_equity:.2f} would be within "
                f"{buffer:.2f} of FTMO daily limit {ftmo_daily:.2f}"
            ),
        )

    # Check FTMO max loss line
    ftmo_max = state.ftmo_max_loss_limit
    if worst_case_equity < ftmo_max + buffer:
        return HeadroomResult(
            allowed=False,
            reason=(
                f"headroom_max: worst_case_equity={worst_case_equity:.2f} would be within "
                f"{buffer:.2f} of FTMO max loss limit {ftmo_max:.2f}"
            ),
        )

    # Check internal daily kill
    internal_daily = state.internal_daily_kill_limit
    if worst_case_equity < internal_daily:
        return HeadroomResult(
            allowed=False,
            reason=(
                f"headroom_internal_daily: worst_case_equity={worst_case_equity:.2f} < "
                f"internal daily kill {internal_daily:.2f}"
            ),
        )

    # Check internal max kill
    internal_max = state.internal_max_kill_limit
    if worst_case_equity < internal_max:
        return HeadroomResult(
            allowed=False,
            reason=(
                f"headroom_internal_max: worst_case_equity={worst_case_equity:.2f} < "
                f"internal max kill {internal_max:.2f}"
            ),
        )

    # Best Day governor (1-Step only)
    if state.account_type.best_day_rule_applies():
        projected_pnl = order.worst_case_loss * -1  # optimistic: assume a win
        if state.would_breach_best_day(projected_pnl):
            ratio = state.best_day_ratio(projected_pnl)
            return HeadroomResult(
                allowed=False,
                reason=(
                    f"headroom_best_day: projected ratio={ratio:.3f} would exceed "
                    f"throttle={state.rules.best_day_throttle_ratio}"
                ),
            )

    log.debug(
        "risk.gate_passed",
        extra={
            "symbol": order.symbol,
            "worst_case_equity": worst_case_equity,
            "ftmo_daily_limit": ftmo_daily,
            "ftmo_max_limit": ftmo_max,
        },
    )
    return HeadroomResult(allowed=True, reason="ok")


# ---------------------------------------------------------------------------
# equity_tick — sub-second monitor
# ---------------------------------------------------------------------------


def equity_tick(
    equity: float,
    state: FTMOState,
    now: datetime | None = None,
) -> None:
    """Process one equity sample from the sub-second watcher.

    Raises FTMOInternalBreach  if equity ≤ internal kill limit.
    Raises FTMOImminent        if equity is within imminent buffer of FTMO line.

    Callers must catch both and act: FTMOInternalBreach → flatten + halt;
    FTMOImminent → alert + reduce sizing.

    Does NOT raise if equity is healthy — designed for tight loops.
    """
    buffer_amt = state.rules.imminent_buffer_pct * state.initial_capital

    # --- Internal daily kill ---
    if equity <= state.internal_daily_kill_limit:
        raise FTMOInternalBreach("daily", equity, state.internal_daily_kill_limit)

    # --- Internal max kill ---
    if equity <= state.internal_max_kill_limit:
        raise FTMOInternalBreach("max", equity, state.internal_max_kill_limit)

    # --- FTMO daily imminent warning ---
    if equity < state.ftmo_daily_limit + buffer_amt:
        raise FTMOImminent(
            "daily",
            equity,
            state.ftmo_daily_limit,
            equity - state.ftmo_daily_limit,
        )

    # --- FTMO max imminent warning ---
    if equity < state.ftmo_max_loss_limit + buffer_amt:
        raise FTMOImminent(
            "max",
            equity,
            state.ftmo_max_loss_limit,
            equity - state.ftmo_max_loss_limit,
        )
