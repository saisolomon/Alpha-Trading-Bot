// Snapshot ingestion + queries.
//
// The local monitor calls `record` every poll (default 60s). One row per
// poll, with positions in a separate table for query flexibility.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const record = mutation({
  args: {
    accountId: v.id("accounts"),
    balance: v.number(),
    equity: v.number(),
    profit: v.number(),
    marginUsed: v.number(),
    marginFree: v.number(),
    dailyLimitDistance: v.number(),
    maxLimitDistance: v.number(),
    ftmoStatus: v.number(),
    carryToday: v.number(),
    positions: v.array(v.object({
      ticket: v.number(),
      symbol: v.string(),
      side: v.string(),
      volume: v.number(),
      priceOpen: v.number(),
      priceCurrent: v.number(),
      profit: v.number(),
      swap: v.number(),
      eaName: v.optional(v.string()),
    })),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    const snapshotId = await ctx.db.insert("snapshots", {
      accountId: args.accountId,
      recordedAt: now,
      balance: args.balance,
      equity: args.equity,
      profit: args.profit,
      marginUsed: args.marginUsed,
      marginFree: args.marginFree,
      dailyLimitDistance: args.dailyLimitDistance,
      maxLimitDistance: args.maxLimitDistance,
      ftmoStatus: args.ftmoStatus,
      openPositionCount: args.positions.length,
      carryToday: args.carryToday,
    });
    // Insert each position
    for (const p of args.positions) {
      await ctx.db.insert("positions", {
        ...p,
        accountId: args.accountId,
        snapshotId,
        recordedAt: now,
      });
    }
    // Update denormalised cache on account row
    await ctx.db.patch(args.accountId, {
      latestBalance: args.balance,
      latestEquity: args.equity,
      latestSnapshotAt: now,
    });
    return { snapshotId, snapshotCount: 1, positionCount: args.positions.length };
  },
});

export const latest = query({
  args: { accountId: v.id("accounts") },
  handler: async (ctx, args) => {
    const snap = await ctx.db
      .query("snapshots")
      .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", args.accountId))
      .order("desc")
      .first();
    if (!snap) return null;
    const positions = await ctx.db
      .query("positions")
      .withIndex("bySnapshot", (q) => q.eq("snapshotId", snap._id))
      .collect();
    return { ...snap, positions };
  },
});

export const recentRange = query({
  args: {
    accountId: v.id("accounts"),
    sinceMs: v.number(),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const rows = await ctx.db
      .query("snapshots")
      .withIndex("byAccount_recordedAt", (q) =>
        q.eq("accountId", args.accountId).gte("recordedAt", args.sinceMs)
      )
      .order("desc")
      .take(args.limit ?? 500);
    return rows;
  },
});
