"""
End-of-day reconciliation — compares internal P&L tracking against MT5's
confirmed deal history.

Usage:
    reconciler = Reconciler(client)
    report = reconciler.run(
        date=datetime.now(UTC).date(),
        internal_trades=[...],   # from your internal trade log
    )
    if report.discrepancies:
        log.error("reconcile.mismatch", discrepancies=report.discrepancies)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from utils.log import Events, get_logger

log = get_logger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Deal record (normalised from MT5 HistoryDeal)
# ---------------------------------------------------------------------------


@dataclass
class DealRecord:
    """Normalised MT5 historical deal."""
    ticket: int
    order: int
    symbol: str
    entry: int        # DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=2
    type: int         # DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1
    volume: float
    price: float
    profit: float     # in account currency
    commission: float
    swap: float
    time: datetime    # UTC


# ---------------------------------------------------------------------------
# Internal trade stub (what the strategy log records)
# ---------------------------------------------------------------------------


@dataclass
class InternalTrade:
    """Minimal internal trade record for reconciliation."""
    symbol: str
    direction: int    # +1 long, -1 short
    volume: float
    entry_price: float
    exit_price: float
    net_pnl: float    # after commission
    commission: float
    entry_time: datetime
    exit_time: datetime


# ---------------------------------------------------------------------------
# Reconciliation report
# ---------------------------------------------------------------------------


@dataclass
class ReconcileReport:
    """Result of one reconciliation run."""
    date: date
    broker_deal_count: int
    internal_trade_count: int
    broker_net_pnl: float
    internal_net_pnl: float
    pnl_discrepancy: float       # broker - internal (positive = broker has more)
    discrepancies: list[str]     # human-readable mismatch descriptions
    passed: bool                 # True if discrepancy < tolerance

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"Reconcile {self.date} [{status}] "
            f"broker={self.broker_net_pnl:.2f} internal={self.internal_net_pnl:.2f} "
            f"discrepancy={self.pnl_discrepancy:+.4f}"
        )


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


class Reconciler:
    """Pulls MT5 deal history and reconciles against internal trade log.

    Parameters
    ----------
    client:
        Connected MT5Client. If None, the reconciler runs in dry-run mode
        (returns an empty broker deal list).
    tolerance:
        Maximum allowed P&L discrepancy in account currency. Default $0.01.
    """

    def __init__(
        self,
        client: object | None = None,
        tolerance: float = 0.01,
    ) -> None:
        self._client = client
        self._tolerance = tolerance

    def fetch_deals(self, from_dt: datetime, to_dt: datetime) -> list[DealRecord]:
        """Pull deal history from MT5 for the given time window."""
        if self._client is None:
            log.warning("reconcile.no_client", reason="dry_run")
            return []

        try:
            import MetaTrader5 as mt5  # type: ignore[import]
            raw_deals = mt5.history_deals_get(from_dt, to_dt)
            if raw_deals is None:
                err = mt5.last_error()
                log.error("reconcile.fetch_error", error=err)
                return []

            records = []
            for d in raw_deals:
                # Skip balance, credit, and other non-trade deals
                if d.type not in (0, 1):  # DEAL_TYPE_BUY, DEAL_TYPE_SELL
                    continue
                records.append(DealRecord(
                    ticket=d.ticket,
                    order=d.order,
                    symbol=d.symbol,
                    entry=d.entry,
                    type=d.type,
                    volume=d.volume,
                    price=d.price,
                    profit=d.profit,
                    commission=d.commission,
                    swap=d.swap,
                    time=datetime.fromtimestamp(d.time, tz=UTC),
                ))
            return records
        except Exception as exc:
            log.error("reconcile.fetch_exception", error=str(exc))
            return []

    def run(
        self,
        trade_date: date,
        internal_trades: list[InternalTrade],
        tolerance: float | None = None,
    ) -> ReconcileReport:
        """Reconcile internal trades against MT5 deal history for one day.

        Parameters
        ----------
        trade_date:
            The trading day to reconcile (date, not datetime).
        internal_trades:
            Internal trade records for this day.
        tolerance:
            Override instance tolerance for this run.
        """
        tol = tolerance if tolerance is not None else self._tolerance
        from_dt = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
        to_dt = from_dt + timedelta(days=1)

        deals = self.fetch_deals(from_dt, to_dt)

        # Compute broker net P&L (closing deals only, entry=OUT or entry=INOUT)
        broker_net = sum(
            d.profit + d.commission + d.swap
            for d in deals
            if d.entry in (1, 2)  # OUT or INOUT
        )
        # Add commissions on opening deals (some brokers charge on open)
        broker_net += sum(
            d.commission
            for d in deals
            if d.entry == 0  # IN
        )

        internal_net = sum(t.net_pnl for t in internal_trades)

        discrepancy = broker_net - internal_net
        discrepancies: list[str] = []

        if abs(discrepancy) > tol:
            discrepancies.append(
                f"P&L mismatch: broker={broker_net:.4f} internal={internal_net:.4f} "
                f"diff={discrepancy:+.4f} (tolerance={tol})"
            )

        # Count check
        closing_deals = [d for d in deals if d.entry in (1, 2)]
        if len(closing_deals) != len(internal_trades):
            discrepancies.append(
                f"Trade count mismatch: broker={len(closing_deals)} "
                f"internal={len(internal_trades)}"
            )

        passed = len(discrepancies) == 0

        report = ReconcileReport(
            date=trade_date,
            broker_deal_count=len(deals),
            internal_trade_count=len(internal_trades),
            broker_net_pnl=broker_net,
            internal_net_pnl=internal_net,
            pnl_discrepancy=discrepancy,
            discrepancies=discrepancies,
            passed=passed,
        )

        log.info(
            "reconcile.complete",
            date=str(trade_date),
            passed=passed,
            broker_net=broker_net,
            internal_net=internal_net,
            discrepancy=discrepancy,
            discrepancy_count=len(discrepancies),
        )

        return report
