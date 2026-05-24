// Convex schema for the FTMO MT5 trading bot backend.
//
// Tables:
//   heartbeats  -- one row per local-monitor poll (so we can detect when
//                  the monitor stops). Trimmed to last 24h via daily cron.
//   snapshots   -- account+positions snapshot, one row per poll cycle.
//                  Replaces the data/paper_trade/*.jsonl files.
//   positions   -- a normalised view of open positions at snapshot time.
//                  Lets us query "all positions on AUDJPY in the last week"
//                  without parsing JSON blobs.
//   accounts    -- registry of accounts the bot is connected to (one row
//                  per FTMO account; supports future multi-account use).
//   alerts      -- emitted when heartbeat goes stale, FTMO line approached,
//                  P&L anomaly, etc. Read by a UI / phone notification.
//
// Design notes:
//   - Every table has a `recordedAt` (ms since epoch) so we can ORDER BY
//     time + cull old rows via cron.
//   - Indexes on (accountId, recordedAt) so dashboard queries are O(log n).
//   - All money values stored as numbers in account-currency units (USD
//     by default). No floating-point arithmetic in Convex functions;
//     formatting happens client-side.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  accounts: defineTable({
    // FTMO/MT5 broker account id (e.g. 5050327497)
    brokerLogin: v.number(),
    brokerServer: v.string(),
    // CHALLENGE_2STEP_PHASE1 | FUNDED_STANDARD | ...
    accountType: v.string(),
    initialCapital: v.number(),
    currency: v.string(),  // USD, EUR, etc.
    createdAt: v.number(),
    // Latest balance (denormalised cache; source of truth is latest snapshot)
    latestBalance: v.optional(v.number()),
    latestEquity: v.optional(v.number()),
    latestSnapshotAt: v.optional(v.number()),
  }).index("byBrokerLogin", ["brokerLogin"]),

  heartbeats: defineTable({
    accountId: v.id("accounts"),
    recordedAt: v.number(),
    // What the local monitor sees right now -- minimal payload for fast writes
    monitorVersion: v.string(),
    mtConnected: v.boolean(),
    // EA states (which bots are attached + dry-run status)
    // Recorded loosely so the schema doesn't need updating per new EA.
    eaStates: v.optional(v.array(v.object({
      name: v.string(),         // e.g. "AUDJPY_CHFJPY_Carry"
      symbol: v.string(),       // chart symbol it's attached to
      dryRun: v.boolean(),
      lastLog: v.optional(v.string()),
    }))),
  }).index("byAccount_recordedAt", ["accountId", "recordedAt"]),

  snapshots: defineTable({
    accountId: v.id("accounts"),
    recordedAt: v.number(),
    // Account totals
    balance: v.number(),
    equity: v.number(),
    profit: v.number(),         // floating P&L (equity - balance)
    marginUsed: v.number(),
    marginFree: v.number(),
    // FTMO-rule distances (so dashboards can render with no math)
    dailyLimitDistance: v.number(),   // equity - daily-loss line
    maxLimitDistance: v.number(),     // equity - max-loss line
    // FTMO state machine status code from libftmorisk
    //   0=ok, 1=imminent, 2=internal_killed, 3=ftmo_failed
    ftmoStatus: v.number(),
    // Open-position count (full details in positions table)
    openPositionCount: v.number(),
    // Aggregate carry P&L on the day (swap+commission summed across positions)
    carryToday: v.number(),
  }).index("byAccount_recordedAt", ["accountId", "recordedAt"]),

  positions: defineTable({
    accountId: v.id("accounts"),
    snapshotId: v.id("snapshots"),
    recordedAt: v.number(),
    // Per-position fields (mirror MT5 PositionGet*)
    ticket: v.number(),
    symbol: v.string(),
    side: v.string(),           // "BUY" or "SELL"
    volume: v.number(),         // lots
    priceOpen: v.number(),
    priceCurrent: v.number(),
    profit: v.number(),         // unrealised P&L
    swap: v.number(),           // accrued carry
    eaName: v.optional(v.string()),  // from MT5 order comment (e.g. "AUDJPY_CHFJPY_Carry")
  })
    .index("byAccount_recordedAt", ["accountId", "recordedAt"])
    .index("bySnapshot", ["snapshotId"])
    .index("bySymbol", ["symbol", "recordedAt"]),

  // Closed trades / fills from MT5's deal history. Ingested by the local
  // monitor calling mt5.history_deals_get() every poll and POSTing any
  // ticket the backend hasn't seen yet. Idempotent by (accountId, ticket).
  // Used by the daily-report cron to list "trades made today".
  deals: defineTable({
    accountId: v.id("accounts"),
    ticket: v.number(),          // unique per account per fill
    positionId: v.optional(v.number()),  // MT5 position-id (entry+exit share one)
    symbol: v.string(),
    side: v.string(),            // "BUY" or "SELL"
    entry: v.string(),           // "IN" | "OUT" | "INOUT" | "OUT_BY"
    volume: v.number(),
    price: v.number(),
    profit: v.number(),          // realised P&L on this fill (incl. partials)
    swap: v.number(),
    commission: v.number(),
    dealTimeMs: v.number(),      // MT5 deal time, ms since epoch
    eaName: v.optional(v.string()),  // from order comment
    recordedAt: v.number(),      // when WE saved it (server-side timestamp)
  })
    .index("byAccount_dealTime", ["accountId", "dealTimeMs"])
    .index("byAccount_ticket", ["accountId", "ticket"]),

  alerts: defineTable({
    accountId: v.optional(v.id("accounts")),
    recordedAt: v.number(),
    severity: v.string(),       // "info" | "warning" | "critical"
    kind: v.string(),           // "heartbeat_stale" | "ftmo_imminent" | "ea_error" | "pnl_anomaly"
    message: v.string(),
    // Free-form context (e.g. { lastHeartbeat: 1716544800000, gapMinutes: 47 })
    context: v.optional(v.string()),  // JSON-stringified
    acknowledged: v.boolean(),
    acknowledgedAt: v.optional(v.number()),
  })
    .index("byRecordedAt", ["recordedAt"])
    .index("byAccount_severity", ["accountId", "severity", "recordedAt"]),
});
