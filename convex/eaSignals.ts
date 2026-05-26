// EA signal-event ingestion + queries.
//
// Local monitor parses MT5's Experts-tab log file every poll and
// POSTs any new EA events (ENTRY, range_locked, skip, trail, close)
// to this table. The daily-digest cron then queries the past 24h to
// report what each EA actually did during the trading day (since
// DRY-RUN signals never become broker fills).
//
// Dedup: events are identified by (accountId, eaName, eventTimeMs,
// eventType). Re-posting the same event is a no-op.

import { mutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";

export const recordBatch = mutation({
  args: {
    accountId: v.id("accounts"),
    events: v.array(v.object({
      eaName: v.string(),
      symbol: v.string(),
      eventType: v.string(),
      side: v.optional(v.union(v.string(), v.null())),
      price: v.optional(v.union(v.number(), v.null())),
      volume: v.optional(v.union(v.number(), v.null())),
      eventTimeMs: v.number(),
      rawLine: v.string(),
    })),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    let inserted = 0;
    let skipped = 0;
    for (const e of args.events) {
      // Dedup: same EA + same event time + same type
      const existing = await ctx.db
        .query("eaSignals")
        .withIndex("byAccount_ea_eventTime", (q) =>
          q.eq("accountId", args.accountId).eq("eaName", e.eaName)
            .eq("eventTimeMs", e.eventTimeMs),
        )
        .collect();
      if (existing.some((row) => row.eventType === e.eventType)) {
        skipped++;
        continue;
      }
      // Normalise null -> omit so optional fields validate
      const row: any = { ...e, accountId: args.accountId, recordedAt: now };
      if (row.side === null) delete row.side;
      if (row.price === null) delete row.price;
      if (row.volume === null) delete row.volume;
      await ctx.db.insert("eaSignals", row);
      inserted++;
    }
    return { inserted, skipped };
  },
});

// Used by daily-digest cron + dashboard to count what each EA did
// in the past N hours.
export const recentByAccount = internalQuery({
  args: { accountId: v.id("accounts"), sinceMs: v.number() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("eaSignals")
      .withIndex("byAccount_eventTime", (q) =>
        q.eq("accountId", args.accountId).gte("eventTimeMs", args.sinceMs),
      )
      .order("desc")
      .collect();
  },
});
