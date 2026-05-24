// Alert emission + querying.
//
// Alerts are emitted from cron jobs (heartbeat-stale, FTMO-imminent,
// pnl-anomaly) and read by a dashboard / phone push-notification handler.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const emit = mutation({
  args: {
    accountId: v.optional(v.id("accounts")),
    severity: v.string(),
    kind: v.string(),
    message: v.string(),
    context: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    // De-dup: don't emit the same kind for the same account within 1h
    // (otherwise a 5-min cron would spam alerts every fire while the
    // condition persists).
    const oneHourAgo = Date.now() - 60 * 60 * 1000;
    const existing = await ctx.db
      .query("alerts")
      .withIndex("byRecordedAt", (q) => q.gte("recordedAt", oneHourAgo))
      .collect();
    const dup = existing.find(
      (a) =>
        a.kind === args.kind &&
        a.accountId === args.accountId &&
        !a.acknowledged
    );
    if (dup) return { deduplicated: true, alertId: dup._id };
    const id = await ctx.db.insert("alerts", {
      ...args,
      recordedAt: Date.now(),
      acknowledged: false,
    });
    return { deduplicated: false, alertId: id };
  },
});

export const recent = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("alerts")
      .withIndex("byRecordedAt")
      .order("desc")
      .take(args.limit ?? 50);
  },
});

export const acknowledge = mutation({
  args: { alertId: v.id("alerts") },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.alertId, {
      acknowledged: true,
      acknowledgedAt: Date.now(),
    });
  },
});

// Used by the dashboard's "Ack all" button when a user clears a backlog.
// Only acks UNACKNOWLEDGED alerts to avoid clobbering acknowledgedAt
// timestamps from earlier acks.
export const acknowledgeAll = mutation({
  args: { upToMs: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const cutoff = args.upToMs ?? Date.now();
    const unacked = await ctx.db
      .query("alerts")
      .withIndex("byRecordedAt", (q) => q.lte("recordedAt", cutoff))
      .collect();
    let n = 0;
    for (const a of unacked) {
      if (!a.acknowledged) {
        await ctx.db.patch(a._id, {
          acknowledged: true,
          acknowledgedAt: Date.now(),
        });
        n++;
      }
    }
    return { acknowledged: n };
  },
});
