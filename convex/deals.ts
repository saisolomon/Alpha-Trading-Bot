// Closed-trade (fill) ingestion + queries.
//
// MT5's history_deals_get() returns every fill across the account's
// lifetime. The local monitor polls it every minute and POSTs any
// ticket the backend hasn't seen yet. We dedupe by (accountId, ticket)
// so re-sending the same fill is a no-op.
//
// Used by the daily-report cron to list trades made today.

import { mutation, query, internalQuery } from "./_generated/server";
import { v } from "convex/values";

export const recordBatch = mutation({
  args: {
    accountId: v.id("accounts"),
    deals: v.array(v.object({
      ticket: v.number(),
      positionId: v.optional(v.number()),
      symbol: v.string(),
      side: v.string(),
      entry: v.string(),
      volume: v.number(),
      price: v.number(),
      profit: v.number(),
      swap: v.number(),
      commission: v.number(),
      dealTimeMs: v.number(),
      eaName: v.optional(v.string()),
    })),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    let inserted = 0;
    let skipped = 0;
    for (const d of args.deals) {
      const existing = await ctx.db
        .query("deals")
        .withIndex("byAccount_ticket", (q) =>
          q.eq("accountId", args.accountId).eq("ticket", d.ticket),
        )
        .first();
      if (existing) {
        skipped++;
        continue;
      }
      await ctx.db.insert("deals", {
        ...d,
        accountId: args.accountId,
        recordedAt: now,
      });
      inserted++;
    }
    return { inserted, skipped };
  },
});

// Used by the local monitor to know which ticket to start from on each
// poll (avoid re-sending the full history). Returns 0 if no deals seen.
export const latestTicket = query({
  args: { accountId: v.id("accounts") },
  handler: async (ctx, args) => {
    const latest = await ctx.db
      .query("deals")
      .withIndex("byAccount_dealTime", (q) => q.eq("accountId", args.accountId))
      .order("desc")
      .first();
    return latest?.ticket ?? 0;
  },
});

export const recentSince = internalQuery({
  args: {
    accountId: v.id("accounts"),
    sinceMs: v.number(),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("deals")
      .withIndex("byAccount_dealTime", (q) =>
        q.eq("accountId", args.accountId).gte("dealTimeMs", args.sinceMs),
      )
      .order("desc")
      .collect();
  },
});

export const recent = query({
  args: {
    accountId: v.id("accounts"),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("deals")
      .withIndex("byAccount_dealTime", (q) => q.eq("accountId", args.accountId))
      .order("desc")
      .take(args.limit ?? 50);
  },
});
