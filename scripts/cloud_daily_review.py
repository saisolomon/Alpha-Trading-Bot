"""
Cloud-friendly daily review of paper-trade snapshots.

Designed to be invoked by a scheduled Claude routine (or any cron job).
The routine wakes around Prague midnight, pulls the latest snapshots,
generates a markdown daily report, and commits it to reports/paper_trade/.

This script:
  1. Reads the latest paper-trade JSONL snapshots in data/paper_trade/
  2. Runs the same tracking-error analysis as paper_trade_daily_report.py
  3. Generates a markdown report at reports/paper_trade/<YYYY-MM-DD>.md
  4. Sets exit code 0 (PASS) / 1 (FAIL with concrete reason) so the
     calling routine can decide whether to alert.

Usage (the routine calls this directly):
    uv run python scripts/cloud_daily_review.py
    uv run python scripts/cloud_daily_review.py --days 1 --output reports/paper_trade

Exit codes:
    0: clean (no internal kills, monitor live, no data gaps > 4h)
    1: WARN -- gap in monitor data > 4 hours OR no snapshots today
    2: FAIL -- internal kill event detected
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cloud-side paper-trade daily review")
    p.add_argument("--days", type=int, default=1,
                   help="How many trailing days to include (default 1)")
    p.add_argument("--input-dir", default="data/paper_trade")
    p.add_argument("--output-dir", default="reports/paper_trade")
    p.add_argument("--max-gap-hours", type=float, default=4.0,
                   help="WARN if any monitor-data gap exceeds this")
    return p.parse_args()


def load_snapshots(input_dir: Path, days: int) -> list[dict]:
    today = datetime.now(UTC).date()
    snaps: list[dict] = []
    for i in range(days):
        d = today - timedelta(days=i)
        path = input_dir / f"{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                snaps.append(json.loads(line))
    snaps.sort(key=lambda s: s["ts_utc"])
    return snaps


def detect_gaps(snaps: list[dict], max_gap_hours: float) -> list[tuple[str, str, float]]:
    """Return [(prev_ts, this_ts, gap_hours), ...] for gaps exceeding max."""
    gaps = []
    for prev, cur in zip(snaps, snaps[1:]):
        t0 = datetime.fromisoformat(prev["ts_utc"])
        t1 = datetime.fromisoformat(cur["ts_utc"])
        gap_h = (t1 - t0).total_seconds() / 3600
        if gap_h > max_gap_hours:
            gaps.append((prev["ts_utc"], cur["ts_utc"], gap_h))
    return gaps


def build_markdown(snaps: list[dict], gaps: list, killed: bool) -> str:
    if not snaps:
        return "# Paper-trade daily review\n\n**NO DATA FOR THIS WINDOW.**\n"
    first, last = snaps[0], snaps[-1]
    pnl = last["balance"] - first["balance"]
    pnl_pct = (pnl / first["balance"]) * 100 if first["balance"] > 0 else 0
    n_imminent = sum(1 for s in snaps if s.get("risk_status", "").startswith("imminent"))
    min_eq = min(s["equity"] for s in snaps)
    max_eq = max(s["equity"] for s in snaps)
    min_dist_daily = min(s["risk_distance"]["to_ftmo_daily"] for s in snaps)
    min_dist_max = min(s["risk_distance"]["to_ftmo_max"] for s in snaps)

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    md = [f"# Paper-trade daily review -- {today_str}", ""]
    md.append(f"- Snapshots: **{len(snaps)}**")
    md.append(f"- Period: {first['ts_utc']} -> {last['ts_utc']}")
    md.append(f"- Opening balance: ${first['balance']:,.2f}")
    md.append(f"- Closing balance: ${last['balance']:,.2f}")
    md.append(f"- Equity range: ${min_eq:,.2f} -- ${max_eq:,.2f}")
    md.append(f"- P&L: **${pnl:+,.2f} ({pnl_pct:+.3f}%)**")
    md.append(f"- Imminent warnings: {n_imminent}")
    md.append(f"- Min distance to FTMO daily line: ${min_dist_daily:,.0f}")
    md.append(f"- Min distance to FTMO max line:   ${min_dist_max:,.0f}")
    md.append("")
    md.append("## Open positions snapshot (most recent)")
    pos = last.get("open_positions", [])
    if not pos:
        md.append("_None_")
    else:
        md.append("| Ticket | Symbol | Type | Lots | Open | Current | P&L |")
        md.append("|---|---|---|---|---|---|---|")
        for p in pos:
            if "error" in p:
                md.append(f"| _error: {p['error']}_ |")
                continue
            md.append(f"| {p['ticket']} | {p['symbol']} | "
                      f"{'BUY' if p['type']==0 else 'SELL'} | "
                      f"{p['volume']:.2f} | {p['price_open']:.2f} | "
                      f"{p['price_current']:.2f} | ${p['profit']:+,.2f} |")
    md.append("")
    md.append("## Monitor health")
    if gaps:
        md.append(f"**WARN: {len(gaps)} data gaps exceeding 4h:**")
        for prev, cur, gap_h in gaps[:5]:
            md.append(f"  - {prev} -> {cur}  ({gap_h:.1f}h gap)")
    else:
        md.append("- No data gaps > 4h.")
    md.append("")
    md.append("## Verdict")
    if killed:
        md.append("**FAIL -- internal-kill event detected. Strategy halted on at least one snapshot.**")
        md.append("Action: review the EA logs and the snapshot history. Do NOT purchase a Challenge yet.")
    elif gaps:
        md.append("**WARN -- monitor missed data. Verify MT5 terminal stayed running.**")
    else:
        md.append("**OK -- no kill events, no significant data gaps.**")
    return "\n".join(md) + "\n"


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    snaps = load_snapshots(input_dir, args.days)
    gaps = detect_gaps(snaps, args.max_gap_hours)
    killed = any(s.get("risk_status", "").startswith("internal_killed") for s in snaps)

    md = build_markdown(snaps, gaps, killed)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = output_dir / f"{today}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")
    # Echo to stdout so the routine can capture / forward to chat
    print()
    print(md)

    if killed:
        sys.exit(2)
    if not snaps or gaps:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
