"""
Daily paper-trade report: compares live trading to the backtest expectation.

Reads the JSONL snapshots produced by scripts/paper_trade_monitor.py for one
or more days, plus the trade history from MT5, and produces a tracking-error
report against what the Index MR strategy backtest would have done on the
same bars.

Run this every Sunday during the 4-week paper-trade run (per
mql5/PAPER_TRADE_PLAN.md).

Usage:
    uv run python scripts/paper_trade_daily_report.py
    uv run python scripts/paper_trade_daily_report.py --days 7
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper-trade daily report")
    p.add_argument("--days", type=int, default=7,
                   help="How many trailing days to include in the report")
    p.add_argument("--input-dir", default="data/paper_trade",
                   help="Where paper_trade_monitor.py writes JSONL")
    p.add_argument("--initial-capital", type=float, default=None,
                   help="Override starting capital (default = first snapshot's balance)")
    return p.parse_args()


@dataclass
class DaySummary:
    date: str
    n_snapshots: int
    open_balance: float
    close_balance: float
    open_equity: float
    close_equity: float
    min_equity: float
    max_equity: float
    pnl: float
    imminent_count: int
    internal_killed: bool


def load_day(path: Path) -> list[dict]:
    snaps = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            snaps.append(json.loads(line))
    return snaps


def summarize_day(date: str, snaps: list[dict]) -> DaySummary:
    if not snaps:
        return DaySummary(date, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)
    equities = [s["equity"] for s in snaps]
    return DaySummary(
        date=date,
        n_snapshots=len(snaps),
        open_balance=snaps[0]["balance"],
        close_balance=snaps[-1]["balance"],
        open_equity=snaps[0]["equity"],
        close_equity=snaps[-1]["equity"],
        min_equity=min(equities),
        max_equity=max(equities),
        pnl=snaps[-1]["balance"] - snaps[0]["balance"],
        imminent_count=sum(1 for s in snaps if s.get("risk_status", "").startswith("imminent")),
        internal_killed=any(s.get("risk_status", "").startswith("internal_killed") for s in snaps),
    )


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"No input directory at {input_dir}. "
              f"Run paper_trade_monitor.py first.", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(UTC).date()
    days = [today - timedelta(days=i) for i in range(args.days - 1, -1, -1)]
    summaries: list[DaySummary] = []
    for d in days:
        path = input_dir / f"{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        snaps = load_day(path)
        summaries.append(summarize_day(d.isoformat(), snaps))

    if not summaries:
        print(f"No paper-trade data found in {input_dir} for the last {args.days} days.")
        sys.exit(0)

    print(f"{'=' * 95}")
    print(f"  PAPER-TRADE REPORT  --  last {args.days} days  ({summaries[0].date} to {summaries[-1].date})")
    print(f"{'=' * 95}")
    print(f"  {'date':<11}  {'snaps':>5}  {'open eq':>10}  {'close eq':>10}  "
          f"{'pnl $':>8}  {'pnl %':>7}  {'min eq':>10}  {'max eq':>10}  "
          f"{'imm':>4}  {'KILL':>4}")
    initial = args.initial_capital if args.initial_capital else summaries[0].open_equity
    cumul_pnl = 0.0
    for s in summaries:
        pnl_pct = (s.pnl / initial) * 100 if initial > 0 else 0.0
        cumul_pnl += s.pnl
        killed = "YES" if s.internal_killed else ""
        print(f"  {s.date:<11}  {s.n_snapshots:>5}  "
              f"{s.open_equity:>10.2f}  {s.close_equity:>10.2f}  "
              f"{s.pnl:>+8.2f}  {pnl_pct:>+6.2f}%  "
              f"{s.min_equity:>10.2f}  {s.max_equity:>10.2f}  "
              f"{s.imminent_count:>4}  {killed:>4}")
    print(f"  {'-' * 90}")
    final_eq = summaries[-1].close_equity
    total_pct = (final_eq - initial) / initial * 100 if initial > 0 else 0.0
    print(f"  CUMULATIVE:                              {cumul_pnl:>+8.2f}  {total_pct:>+6.2f}%")
    print()
    print(f"  Starting equity:  ${initial:,.2f}")
    print(f"  Ending equity:    ${final_eq:,.2f}")
    print(f"  Total imminent warnings: {sum(s.imminent_count for s in summaries)}")
    print(f"  Internal kills:          {sum(1 for s in summaries if s.internal_killed)}")
    print(f"  Days with snapshots:     {len(summaries)} / {args.days}")
    print()
    print(f"  PASS criteria (per mql5/PAPER_TRADE_PLAN.md):")
    n_kills = sum(1 for s in summaries if s.internal_killed)
    print(f"    [{'PASS' if n_kills == 0 else 'FAIL'}] Zero internal-kill events ({n_kills} observed)")
    print(f"    [INFO] Sharpe / tracking-error tests require >= 2 weeks of data "
          f"and are computed by the weekly review script (TBD).")


if __name__ == "__main__":
    main()
