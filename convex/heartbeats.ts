// Heartbeat ingestion + staleness detector.
//
// Local monitor pings every 60s. A cron checks every 5 min: if the
// latest heartbeat for any account is older than 10 min, emits an alert.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const record = mutation({
  args: {
    accountId: v.id("accounts"),
    monitorVersion: v.string(),
    mtConnected: v.boolean(),
    eaStates: v.optional(v.array(v.object({
      name: v.string(),
      symbol: v.string(),
      dryRun: v.boolean(),
      lastLog: v.optional(v.string()),
    }))),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("heartbeats", {
      ...args,
      recordedAt: Date.now(),
    });
  },
});

export const latest = query({
  args: { accountId: v.id("accounts") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("heartbeats")
      .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", args.accountId))
      .order("desc")
      .first();
  },
});

export const findStaleAccounts = query({
  args: { staleThresholdMs: v.number() },
  handler: async (ctx, args) => {
    const cutoff = Date.now() - args.staleThresholdMs;
    const accounts = await ctx.db.query("accounts").collect();
    const stale: Array<{
      accountId: string;
      brokerLogin: number;
      lastHeartbeatAt: number | null;
      gapMs: number;
    }> = [];
    for (const acc of accounts) {
      const last = await ctx.db
        .query("heartbeats")
        .withIndex("byAccount_recordedAt", (q) => q.eq("accountId", acc._id))
        .order("desc")
        .first();
      const lastAt = last?.recordedAt ?? null;
      if (lastAt === null || lastAt < cutoff) {
        stale.push({
          accountId: acc._id,
          brokerLogin: acc.brokerLogin,
          lastHeartbeatAt: lastAt,
          gapMs: lastAt === null ? Date.now() - acc.createdAt : Date.now() - lastAt,
        });
      }
    }
    return stale;
  },
});
