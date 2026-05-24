// Scheduled jobs for the FTMO MT5 bot backend.
//
// Convex runs these on its server (no Windows scheduled task involved),
// so they survive reboots, crashes, and weekends. This is what
// finally closes the "monitor died and we didn't know for 2 days"
// failure mode that motivated the whole Convex build.
//
// All three actions are idempotent and safe to re-run.

import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

const crons = cronJobs();

// 1) HEARTBEAT STALENESS — every 5 minutes
//
//    Checks each registered account for the latest heartbeat. If the
//    gap exceeds the threshold (10 min, defined in reports.ts), emits
//    a critical alert and fans out to all configured sinks (email,
//    SMS, push). De-duplicated within 1h so a hung monitor doesn't
//    spam you 12 times an hour.
crons.interval(
  "heartbeat-staleness-check",
  { minutes: 5 },
  internal.reports.checkHeartbeatStaleness,
);

// 2) DAILY REPORT — once per day at 22:30 UTC
//
//    22:30 UTC chosen to land AFTER the US cash close (21:00 UTC) but
//    BEFORE midnight Prague (23:00 UTC in summer / 22:00 UTC in winter)
//    so the report reflects today's complete trading day. Pulls the
//    last 24h of snapshots, computes P&L, FTMO distances, per-EA
//    breakdown, and dispatches as an info-severity alert.
crons.daily(
  "daily-report",
  { hourUTC: 22, minuteUTC: 30 },
  internal.reports.sendDailyReport,
);

// 3) CORRELATION MONITOR — once per day at 23:00 UTC
//
//    Computes pairwise rolling-60-day correlation between EAs' daily
//    P&L (attributed via order comment / eaName). Alerts (warning
//    severity) if any pair exceeds rho = +0.30 — that's the threshold
//    above which the regime-diversification thesis between the carry
//    EAs and the other strategies starts to break down.
//
//    Will silently no-op for the first ~14 days while we accumulate
//    enough data; that's intentional. See buildCorrelationMatrix in
//    reports.ts for the data-sufficiency check.
crons.daily(
  "correlation-monitor",
  { hourUTC: 23, minuteUTC: 0 },
  internal.reports.checkCorrelation,
);

export default crons;
