// Report builders: pure-ish functions that read recent data and produce
// summary strings. Called by the cron jobs in crons.ts.
//
// Kept separate from crons.ts so the logic can be unit-tested via Convex
// dashboard (run the query/action manually) without waiting 24h.

import { internalQuery, internalAction } from "./_generated/server";
import { v } from "convex/values";
import { internal, api } from "./_generated/api";

const STALE_THRESHOLD_MS = 10 * 60 * 1000;          // 10 min
const DAILY_REPORT_WINDOW_MS = 24 * 60 * 60 * 1000; // 24 h
const CORR_WINDOW_DAYS = 60;
const CORR_ALERT_THRESHOLD = 0.30;

// ---------------------------------------------------------------------------
// Heartbeat staleness
// ---------------------------------------------------------------------------

export const checkHeartbeatStaleness = internalAction({
  args: {},
  handler: async (ctx): Promise<{ alertedAccounts: number }> => {
    const stale: Array<{
      accountId: string;
      brokerLogin: number;
      lastHeartbeatAt: number | null;
      gapMs: number;
    }> = await ctx.runQuery(api.heartbeats.findStaleAccounts, {
      staleThresholdMs: STALE_THRESHOLD_MS,
    });
    if (stale.length === 0) return { alertedAccounts: 0 };

    for (const s of stale) {
      const gapMin = Math.round(s.gapMs / 60_000);
      const lastSeenStr = s.lastHeartbeatAt
        ? new Date(s.lastHeartbeatAt).toISOString()
        : "never";
      const subject = `Heartbeat STALE on account ${s.brokerLogin}`;
      const body =
        `The local paper_trade_monitor has not reported in ${gapMin} minutes.\n` +
        `Last heartbeat: ${lastSeenStr}\n` +
        `Threshold: ${STALE_THRESHOLD_MS / 60_000} min\n` +
        `\n` +
        `Likely causes:\n` +
        `  - Windows machine asleep / rebooted (At-logon scheduled task didn't restart)\n` +
        `  - paper_trade_monitor.py crashed (check logs/ftmo_bot.log)\n` +
        `  - MT5 disconnected from broker\n` +
        `\n` +
        `Action: SSH/RDP to the Windows machine and run\n` +
        `  uv run python scripts/paper_trade_monitor.py --poll-seconds 60`;

      // Persist to alerts table (deduplicated within 1h)
      const emitRes = await ctx.runMutation(api.alerts.emit, {
        accountId: s.accountId as any,
        severity: "critical",
        kind: "heartbeat_stale",
        message: subject,
        context: JSON.stringify({
          lastHeartbeatAt: s.lastHeartbeatAt,
          gapMinutes: gapMin,
        }),
      });
      if (!emitRes.deduplicated) {
        // Only fan out to sinks on first emission, not on repeated firings
        await ctx.runAction(internal.sinks.dispatchAlert, {
          subject,
          body,
          severity: "critical",
        });
      }
    }
    return { alertedAccounts: stale.length };
  },
});

// ---------------------------------------------------------------------------
// Daily report
// ---------------------------------------------------------------------------

export const buildDailyReport = internalQuery({
  args: { accountId: v.id("accounts") },
  handler: async (ctx, args) => {
    const now = Date.now();
    const sinceMs = now - DAILY_REPORT_WINDOW_MS;

    const account = await ctx.db.get(args.accountId);
    if (!account) return null;

    const snaps = await ctx.db
      .query("snapshots")
      .withIndex("byAccount_recordedAt", (q) =>
        q.eq("accountId", args.accountId).gte("recordedAt", sinceMs),
      )
      .collect();

    if (snaps.length === 0) {
      return { account, snapshotCount: 0, narrative: "no snapshots in the last 24h -- monitor likely down" };
    }

    snaps.sort((a, b) => a.recordedAt - b.recordedAt);
    const first = snaps[0];
    const last = snaps[snaps.length - 1];

    const pnlAbs = last.equity - first.equity;
    const pnlPct = (pnlAbs / first.equity) * 100;
    const peakEq = snaps.reduce((m, s) => Math.max(m, s.equity), -Infinity);
    const troughEq = snaps.reduce((m, s) => Math.min(m, s.equity), +Infinity);
    const minDailyDistance = snaps.reduce(
      (m, s) => Math.min(m, s.dailyLimitDistance),
      Infinity,
    );
    const minMaxDistance = snaps.reduce(
      (m, s) => Math.min(m, s.maxLimitDistance),
      Infinity,
    );
    const imminentTicks = snaps.filter((s) => s.ftmoStatus >= 1).length;

    // Per-EA breakdown from positions in last snapshot
    const lastPositions = await ctx.db
      .query("positions")
      .withIndex("bySnapshot", (q) => q.eq("snapshotId", last._id))
      .collect();
    const byEA = new Map<string, { count: number; profit: number; swap: number }>();
    for (const p of lastPositions) {
      const ea = p.eaName ?? p.symbol;
      const cur = byEA.get(ea) ?? { count: 0, profit: 0, swap: 0 };
      cur.count++;
      cur.profit += p.profit;
      cur.swap += p.swap;
      byEA.set(ea, cur);
    }

    // EA signal events parsed from MT5 logs in the last 24h
    // (DRY-RUN signals show up here even when no broker fill occurs)
    const signals = await ctx.db
      .query("eaSignals")
      .withIndex("byAccount_eventTime", (q) =>
        q.eq("accountId", args.accountId).gte("eventTimeMs", sinceMs),
      )
      .order("desc")
      .collect();

    // Count signal events per EA + type
    const signalsByEA = new Map<string, { entries: number; skips: number; trails: number; ranges: number; other: number }>();
    for (const s of signals) {
      const cur = signalsByEA.get(s.eaName) ?? { entries: 0, skips: 0, trails: 0, ranges: 0, other: 0 };
      if (s.eventType === "entry") cur.entries++;
      else if (s.eventType === "skip") cur.skips++;
      else if (s.eventType === "trail") cur.trails++;
      else if (s.eventType === "range_locked") cur.ranges++;
      else cur.other++;
      signalsByEA.set(s.eaName, cur);
    }

    // Closed deals in the last 24h (the actual TRADES made today)
    const deals = await ctx.db
      .query("deals")
      .withIndex("byAccount_dealTime", (q) =>
        q.eq("accountId", args.accountId).gte("dealTimeMs", sinceMs),
      )
      .order("desc")
      .collect();
    // Per-EA realised P&L (sum of profit+swap+commission across exits)
    const realisedByEA = new Map<string, { count: number; realisedPnl: number }>();
    let realisedPnlTotal = 0;
    for (const d of deals) {
      // Only count EXIT fills towards realised P&L (entries have profit=0)
      if (d.entry === "OUT" || d.entry === "OUT_BY" || d.entry === "INOUT") {
        const ea = d.eaName ?? d.symbol;
        const cur = realisedByEA.get(ea) ?? { count: 0, realisedPnl: 0 };
        cur.count++;
        cur.realisedPnl += d.profit + d.swap + d.commission;
        realisedByEA.set(ea, cur);
        realisedPnlTotal += d.profit + d.swap + d.commission;
      }
    }

    return {
      account,
      snapshotCount: snaps.length,
      firstRecordedAt: first.recordedAt,
      lastRecordedAt: last.recordedAt,
      startEquity: first.equity,
      endEquity: last.equity,
      pnlAbs,
      pnlPct,
      peakEquity: peakEq,
      troughEquity: troughEq,
      minDailyDistance,
      minMaxDistance,
      imminentTicks,
      openPositions: last.openPositionCount,
      byEA: Array.from(byEA.entries()).map(([name, v]) => ({ name, ...v })),
      // NEW: per-EA SIGNAL counts from MT5 logs (works in dry-run too)
      signalsByEA: Array.from(signalsByEA.entries()).map(([name, v]) => ({ name, ...v })),
      totalSignalCount: signals.length,
      // NEW: closed trades today
      dealCount: deals.length,
      realisedPnlTotal,
      realisedByEA: Array.from(realisedByEA.entries()).map(([name, v]) => ({ name, ...v })),
      // Top 10 most recent deals for the digest body
      recentDeals: deals.slice(0, 10).map((d) => ({
        time: d.dealTimeMs,
        symbol: d.symbol,
        side: d.side,
        entry: d.entry,
        volume: d.volume,
        price: d.price,
        profit: d.profit,
        swap: d.swap,
        eaName: d.eaName,
      })),
    };
  },
});

export const sendDailyReport = internalAction({
  args: {},
  handler: async (ctx): Promise<{ sent: number }> => {
    const accounts = await ctx.runQuery(internal.accounts.listAllInternal, {});
    let sent = 0;
    for (const acc of accounts) {
      const r: any = await ctx.runQuery(internal.reports.buildDailyReport, {
        accountId: acc._id,
      });
      if (!r) continue;
      const subject =
        r.snapshotCount === 0
          ? `Daily digest: NO DATA for ${acc.brokerLogin}`
          : `Daily digest ${acc.brokerLogin}: ${r.pnlPct >= 0 ? "+" : ""}${r.pnlPct.toFixed(2)}%`;

      const eaLines = (r.byEA ?? [])
        .map((e: any) => `  - ${e.name}: ${e.count} open, P&L $${e.profit.toFixed(2)}, swap $${e.swap.toFixed(2)}`)
        .join("\n") || "  (no open positions)";

      // Trade activity (closed deals in the last 24h)
      const realisedByEALines = (r.realisedByEA ?? [])
        .map((e: any) => `  - ${e.name}: ${e.count} closed, realised $${e.realisedPnl.toFixed(2)}`)
        .join("\n") || "  (no closed trades today)";
      const dealLines = (r.recentDeals ?? [])
        .map((d: any) => {
          const t = new Date(d.time).toISOString().slice(11, 16);  // HH:MM
          const tag = d.entry === "IN" ? "OPEN " : "CLOSE";
          const pnl = (d.entry !== "IN" && d.profit !== 0)
            ? `  P&L $${d.profit.toFixed(2)}`
            : "";
          return `  ${t} ${tag} ${d.side.padEnd(4)} ${d.volume.toFixed(2)} ${d.symbol} @ ${d.price.toFixed(4)}${pnl}${d.eaName ? `  [${d.eaName}]` : ""}`;
        })
        .join("\n") || "  (no fills today)";

      const body = r.snapshotCount === 0
        ? r.narrative
        : [
            `Account: ${acc.brokerLogin} (${acc.accountType})`,
            `Window: 24h ending ${new Date(r.lastRecordedAt).toISOString()}`,
            `Snapshots: ${r.snapshotCount}`,
            ``,
            `── EQUITY ──`,
            `Equity: $${r.startEquity.toFixed(2)} → $${r.endEquity.toFixed(2)}`,
            `Floating P&L: $${r.pnlAbs.toFixed(2)} (${r.pnlPct >= 0 ? "+" : ""}${r.pnlPct.toFixed(2)}%)`,
            `Realised P&L (closed today): $${(r.realisedPnlTotal ?? 0).toFixed(2)}`,
            `Peak:   $${r.peakEquity.toFixed(2)}`,
            `Trough: $${r.troughEquity.toFixed(2)}`,
            ``,
            `── FTMO ──`,
            `Daily-line headroom (min): $${r.minDailyDistance.toFixed(2)}`,
            `Max-line headroom (min):   $${r.minMaxDistance.toFixed(2)}`,
            `Imminent ticks:            ${r.imminentTicks}`,
            ``,
            `── EA SIGNALS (${r.totalSignalCount ?? 0} events in last 24h, includes DRY-RUN) ──`,
            ((r.signalsByEA ?? []).length === 0
              ? "  (no signal events — check MT5 Experts tab)"
              : (r.signalsByEA ?? [])
                  .map((e: any) => `  - ${e.name}: ${e.entries} entries, ${e.skips} skips, ${e.ranges} ranges, ${e.trails} trail-adjusts`)
                  .join("\n")),
            ``,
            `── BROKER FILLS (${r.dealCount ?? 0} in last 24h; only fires after live-flip) ──`,
            dealLines,
            ``,
            `── REALISED P&L BY EA ──`,
            realisedByEALines,
            ``,
            `── OPEN POSITIONS (${r.openPositions}) ──`,
            eaLines,
          ].join("\n");

      await ctx.runMutation(api.alerts.emit, {
        accountId: acc._id,
        // "warning" -> Pushover priority 0 -> normal sound + banner.
        // (Was "info" / priority -1 / silent; that's the right semantic
        //  for chatter logs but wrong for an end-of-day digest the user
        //  intentionally wants to see.)
        severity: "warning",
        kind: "daily_digest",
        message: subject,
        context: JSON.stringify({
          pnlPct: r.pnlPct,
          snapshotCount: r.snapshotCount,
        }),
      });
      await ctx.runAction(internal.sinks.dispatchAlert, {
        subject,
        body,
        severity: "warning",
      });
      sent++;
    }
    return { sent };
  },
});

// ---------------------------------------------------------------------------
// Correlation monitor (per-EA daily P&L)
// ---------------------------------------------------------------------------

export const buildCorrelationMatrix = internalQuery({
  args: { accountId: v.id("accounts") },
  handler: async (ctx, args) => {
    const sinceMs = Date.now() - CORR_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    // Read all positions across the window. For each (day, eaName),
    // sum profit + swap to get the EA's contribution to P&L on that day.
    const positions = await ctx.db
      .query("positions")
      .withIndex("byAccount_recordedAt", (q) =>
        q.eq("accountId", args.accountId).gte("recordedAt", sinceMs),
      )
      .collect();

    if (positions.length === 0) return { eaNames: [], days: [], matrix: [] };

    // Bucket by (UTC date, eaName). For the correlation we use the
    // LAST observed P&L per day per EA -- this approximates end-of-day
    // floating P&L. Realised attribution is a future improvement.
    const dayKey = (ts: number) => new Date(ts).toISOString().slice(0, 10);
    const byDayEA = new Map<string, Map<string, number>>();
    for (const p of positions) {
      const d = dayKey(p.recordedAt);
      const ea = p.eaName ?? p.symbol;
      const eaMap = byDayEA.get(d) ?? new Map<string, number>();
      // Take the latest reading per (day, ea) -- positions are ordered by time
      eaMap.set(ea, p.profit + p.swap);
      byDayEA.set(d, eaMap);
    }
    const days = Array.from(byDayEA.keys()).sort();
    const eaSet = new Set<string>();
    for (const m of byDayEA.values()) for (const k of m.keys()) eaSet.add(k);
    const eaNames = Array.from(eaSet).sort();

    if (days.length < 14 || eaNames.length < 2) {
      // Need at least 2 EAs and 14 days of data before correlation is meaningful
      return { eaNames, days, matrix: [], note: "insufficient data" };
    }

    // Compute daily P&L change (diff) per EA
    const seriesByEA: Record<string, number[]> = {};
    for (const ea of eaNames) {
      const arr: number[] = [];
      let prev = 0;
      for (const d of days) {
        const v = byDayEA.get(d)?.get(ea) ?? prev;
        arr.push(v - prev);
        prev = v;
      }
      seriesByEA[ea] = arr;
    }

    function corr(x: number[], y: number[]): number {
      const n = Math.min(x.length, y.length);
      if (n < 3) return 0;
      let sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
      for (let i = 0; i < n; i++) {
        sx += x[i]; sy += y[i];
        sxx += x[i] * x[i]; syy += y[i] * y[i];
        sxy += x[i] * y[i];
      }
      const mx = sx / n, my = sy / n;
      const vx = sxx / n - mx * mx;
      const vy = syy / n - my * my;
      const cxy = sxy / n - mx * my;
      if (vx <= 0 || vy <= 0) return 0;
      return cxy / Math.sqrt(vx * vy);
    }

    const matrix: Array<{ a: string; b: string; rho: number }> = [];
    for (let i = 0; i < eaNames.length; i++) {
      for (let j = i + 1; j < eaNames.length; j++) {
        matrix.push({
          a: eaNames[i],
          b: eaNames[j],
          rho: corr(seriesByEA[eaNames[i]], seriesByEA[eaNames[j]]),
        });
      }
    }
    return { eaNames, days, matrix };
  },
});

export const checkCorrelation = internalAction({
  args: {},
  handler: async (ctx): Promise<{ checked: number; alerted: number }> => {
    const accounts = await ctx.runQuery(internal.accounts.listAllInternal, {});
    let alerted = 0;
    for (const acc of accounts) {
      const r: any = await ctx.runQuery(internal.reports.buildCorrelationMatrix, {
        accountId: acc._id,
      });
      if (!r || !r.matrix || r.matrix.length === 0) continue;
      const breaches = r.matrix.filter((m: any) => m.rho > CORR_ALERT_THRESHOLD);
      if (breaches.length === 0) continue;

      const subject = `Correlation breach: ${breaches.length} pairs above +${CORR_ALERT_THRESHOLD}`;
      const lines = breaches.map(
        (b: any) => `  ${b.a} ↔ ${b.b}: rho=${b.rho.toFixed(3)}`,
      );
      const body =
        `Account: ${acc.brokerLogin}\n` +
        `Window: ${CORR_WINDOW_DAYS} days (${r.days.length} days observed)\n` +
        `\n` +
        `Regime-diversification thesis: pairs should have rho < +${CORR_ALERT_THRESHOLD}.\n` +
        `The following pairs are above the threshold:\n` +
        lines.join("\n") +
        `\n\nFull matrix (${r.matrix.length} pairs):\n` +
        r.matrix
          .map((m: any) => `  ${m.a} ↔ ${m.b}: rho=${m.rho.toFixed(3)}`)
          .join("\n");

      await ctx.runMutation(api.alerts.emit, {
        accountId: acc._id,
        severity: "warning",
        kind: "correlation_breach",
        message: subject,
        context: JSON.stringify({ breaches }),
      });
      await ctx.runAction(internal.sinks.dispatchAlert, {
        subject,
        body,
        severity: "warning",
      });
      alerted++;
    }
    return { checked: accounts.length, alerted };
  },
});
