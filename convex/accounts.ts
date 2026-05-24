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
      // Patch any fields that changed (e.g. account type bumped after passing phase)
      await ctx.db.patch(existing._id, {
        brokerServer: args.brokerServer,
        accountType: args.accountType,
        initialCapital: args.initialCapital,
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
