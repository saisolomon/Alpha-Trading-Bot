// Account registry: idempotent upsert + lookups.
//
// The local monitor calls registerAccount once at startup. It's idempotent
// (returns existing id if the brokerLogin already exists) so safe to call
// on every restart.

import { mutation, query, internalQuery } from "./_generated/server";
import { v } from "convex/values";

export const registerAccount = mutation({
  args: {
    brokerLogin: v.number(),
    brokerServer: v.string(),
    accountType: v.string(),
    initialCapital: v.number(),
    currency: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("accounts")
      .withIndex("byBrokerLogin", (q) => q.eq("brokerLogin", args.brokerLogin))
      .first();
    if (existing) {
      // Patch fields that legitimately change (e.g. account type bumped
      // after passing a phase) -- but NEVER initialCapital. BUG FIX
      // 2026-06-11: initialCapital was being overwritten with the
      // current balance on every monitor restart, which (a) corrupted
      // the trial's headline P&L for a day ($201,840 -> $200,167 across
      // the 6/10 reboot) and (b) silently shifts FTMO limit math, which
      // keys off initial capital. Immutable after first registration;
      // the snapshot/jsonl series is the only P&L ground truth.
      await ctx.db.patch(existing._id, {
        brokerServer: args.brokerServer,
        accountType: args.accountType,
        currency: args.currency,
      });
      return existing._id;
    }
    return await ctx.db.insert("accounts", {
      ...args,
      createdAt: Date.now(),
    });
  },
});

export const getByBrokerLogin = query({
  args: { brokerLogin: v.number() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("accounts")
      .withIndex("byBrokerLogin", (q) => q.eq("brokerLogin", args.brokerLogin))
      .first();
  },
});

export const listAll = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("accounts").collect();
  },
});

// Internal-only variant used by cron jobs in convex/reports.ts.
// Keeping cron access via internal* prevents accidentally exposing
// account-list reads on the public WebSocket surface.
export const listAllInternal = internalQuery({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("accounts").collect();
  },
});

// Pause/resume cron monitoring for an account WITHOUT deleting any data.
// Used when an account is retired (e.g. trial expired) but its history must
// survive for post-mortems. The alternative -- deleteByBrokerLogin -- nukes
// all child rows, which is wrong for accounts we still want to analyse.
// Call via:
//   npx convex run accounts:setMonitoringPaused '{"brokerLogin":..., "paused":true}'
export const setMonitoringPaused = mutation({
  args: { brokerLogin: v.number(), paused: v.boolean() },
  handler: async (ctx, args) => {
    const account = await ctx.db
      .query("accounts")
      .withIndex("byBrokerLogin", (q) => q.eq("brokerLogin", args.brokerLogin))
      .first();
    if (!account) return { found: false };
    await ctx.db.patch(account._id, { monitoringPaused: args.paused });
    return { found: true, brokerLogin: args.brokerLogin, monitoringPaused: args.paused };
  },
});

// Delete an account + all its associated heartbeats, snapshots,
// positions, and deals. Used to clean up stale accounts after a broker
// migration (e.g. when we switched from MetaQuotes-Demo -> OANDA-Demo-1
// the old account stayed in the table and started triggering
// heartbeat-stale Pushover spam). Public so we can call via
// `npx convex run accounts:deleteByBrokerLogin '{"brokerLogin":...}'`.
export const deleteByBrokerLogin = mutation({
  args: { brokerLogin: v.number() },
  handler: async (ctx, args) => {
    const account = await ctx.db
      .query("accounts")
      .withIndex("byBrokerLogin", (q) => q.eq("brokerLogin", args.brokerLogin))
      .first();
    if (!account) return { found: false };
    // Delete child rows first
    const heartbeats = await ctx.db
      .query("heartbeats")
      .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", account._id))
      .collect();
    for (const h of heartbeats) await ctx.db.delete(h._id);
    const snapshots = await ctx.db
      .query("snapshots")
      .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", account._id))
      .collect();
    for (const s of snapshots) await ctx.db.delete(s._id);
    const positions = await ctx.db
      .query("positions")
      .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", account._id))
      .collect();
    for (const p of positions) await ctx.db.delete(p._id);
    const deals = await ctx.db
      .query("deals")
      .withIndex("byAccount_dealTime", (q) => q.eq("accountId", account._id))
      .collect();
    for (const d of deals) await ctx.db.delete(d._id);
    // Then delete the account itself
    await ctx.db.delete(account._id);
    return {
      found: true,
      deletedHeartbeats: heartbeats.length,
      deletedSnapshots: snapshots.length,
      deletedPositions: positions.length,
      deletedDeals: deals.length,
    };
  },
});
