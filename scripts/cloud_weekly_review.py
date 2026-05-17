"""
Cloud-friendly weekly tracking-error review.

Run by the cloud routine every Sunday. Aggregates the last 7 days of
paper-trade snapshots and benchmarks them against the backtest's
expected weekly performance distribution. The output is the gate that
determines whether the 4-week paper-trade run should continue OR be
halted for diagnosis.

Compares LIVE metrics to BACKTEST expected metrics (from the 12y
walk-forward of the equal-weight portfolio). Reports the deviation
in standard-deviation units.

Usage:
    uv run python scripts/cloud_weekly_review.py

Exit codes:
    0: clean
    1: WARN -- tracking error > 2 sigma (within noise but at the edge)
    2: FAIL -- tracking error > 3 sigma OR any internal-kill event
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc

# Backtest expected weekly metrics (from the 12y equal-weight portfolio
# walk-forward; see Memory.md 2026-05-16 entry).
EXPECTED_WEEKLY_RETURN_MEAN = 0.0014   # ~0.14% per week (0.72% CAGR / 52 wk)
EXPECTED_WEEKLY_RETURN_STD  = 0.0070   # rough estimate from portfolio vol
EXPECTED_WEEKLY_MAXDD_P95   = 0.012    # 95th percentile weekly DD


def load_week_snapshots(input_dir: Path, n_days: int = 7) -> list[dict]:
    today = datetime.now(UTC).date()
    snaps = []
    for i in range(n_days):
        d = today - timedelta(days=i)
        path = input_dir / f"{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                snaps.append(json.loads(line))
    snaps.sort(key=lambda s: s["ts_utc"])
    return snaps


def main() -> None:
    input_dir = Path("data/paper_trade")
    output_dir = Path("reports/paper_trade")
    output_dir.mkdir(parents=True, exist_ok=True)
    snaps = load_week_snapshots(input_dir)
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = output_dir / f"week_ending_{today_str}.md"

    if not snaps:
        md = (f"# Weekly review -- {today_str}\n\n"
              "**NO DATA THIS WEEK.** Check that the local monitor is running.\n")
        out_path.write_text(md, encoding="utf-8")
        print(md)
        sys.exit(1)

    first, last = snaps[0], snaps[-1]
    weekly_return = (last["balance"] - first["balance"]) / first["balance"]

    # Weekly intra-week max drawdown
    running_max = first["equity"]
    max_dd = 0.0
    for s in snaps:
        running_max = max(running_max, s["equity"])
        dd = (s["equity"] - running_max) / running_max
        max_dd = min(max_dd, dd)

    kills = [s for s in snaps if s.get("risk_status", "").startswith("internal_killed")]
    imminents = sum(1 for s in snaps if s.get("risk_status", "").startswith("imminent"))

    # Tracking-error in sigma units
    return_z = (weekly_return - EXPECTED_WEEKLY_RETURN_MEAN) / EXPECTED_WEEKLY_RETURN_STD

    md_lines = [f"# Weekly tracking-error review -- {today_str}", ""]
    md_lines.append(f"- Snapshots:       {len(snaps)}")
    md_lines.append(f"- Period:          {first['ts_utc']} -> {last['ts_utc']}")
    md_lines.append(f"- Opening balance: ${first['balance']:,.2f}")
    md_lines.append(f"- Closing balance: ${last['balance']:,.2f}")
    md_lines.append(f"- Weekly return:   **{100*weekly_return:+.3f}%**  "
                    f"(expected {100*EXPECTED_WEEKLY_RETURN_MEAN:+.2f}% / "
                    f"sigma {100*EXPECTED_WEEKLY_RETURN_STD:.2f}%)")
    md_lines.append(f"- Tracking-error z: **{return_z:+.2f} sigma**")
    md_lines.append(f"- Intraweek max DD: **{100*max_dd:+.3f}%**  "
                    f"(95th-percentile expected: {100*EXPECTED_WEEKLY_MAXDD_P95:.2f}%)")
    md_lines.append(f"- Imminent warnings: {imminents}")
    md_lines.append(f"- Internal-kill events: **{len(kills)}**")
    md_lines.append("")

    # Verdict
    exit_code = 0
    if kills:
        verdict = ("**FAIL -- internal-kill event(s) detected this week. "
                   "Halt paper-trade. Diagnose before continuing.**")
        exit_code = 2
    elif abs(return_z) > 3.0:
        verdict = ("**FAIL -- weekly return more than 3 sigma from backtest "
                   f"expectation ({return_z:+.2f} sigma). Live and backtest "
                   "have diverged materially.**")
        exit_code = 2
    elif abs(return_z) > 2.0:
        verdict = (f"**WARN -- weekly return {return_z:+.2f} sigma from "
                   "backtest expectation. Within noise but worth watching.**")
        exit_code = 1
    else:
        verdict = "**OK -- live performance within 2 sigma of backtest expectation.**"
    md_lines.append("## Verdict")
    md_lines.append(verdict)
    md = "\n".join(md_lines) + "\n"
    out_path.write_text(md, encoding="utf-8")
    print(md)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
