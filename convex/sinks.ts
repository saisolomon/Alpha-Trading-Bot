// Alert sinks.
//
// Strategy decided 2026-05-24:
//   - PRIMARY sink: the dashboard (https://clever-malamute-966.convex.site/).
//     Crons write alerts to the `alerts` table; the dashboard polls every
//     15s and shows them with sound + browser notification.
//   - SECONDARY sink: Pushover (push notifications). Useful for "tab not
//     open, phone in pocket, screen off" scenarios. Unconfigured by
//     default; enable by setting the env vars below.
//
// Resend (email) and Twilio (SMS) sinks were removed -- the dashboard
// covers the common case and Pushover covers the rest with one $5 fee.
// If you ever need email/SMS specifically, restore from git history at
// commit before 2026-05-24.
//
// To enable Pushover:
//   1. Sign up at https://pushover.net (free 30-day trial, $5 one-time)
//   2. Install the Pushover app on your phone
//   3. Create an Application on the dashboard → get API token
//   4. Set the env vars:
//        npx convex env set PUSHOVER_API_TOKEN axxxxxxxxx
//        npx convex env set PUSHOVER_USER_KEY  uxxxxxxxxx
//
// If neither env var is set, dispatchAlert silently skips (logs "SKIP
// not configured" to Convex function logs). Crons still write to the
// alerts table, so nothing is lost -- you just rely on the dashboard.

import { internalAction } from "./_generated/server";
import { v } from "convex/values";

type DispatchResult = {
  sink: string;
  ok: boolean;
  detail?: string;
};

async function postForm(
  url: string,
  body: Record<string, string>,
): Promise<{ ok: boolean; status: number; text: string }> {
  try {
    const form = new URLSearchParams(body);
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    const text = await resp.text();
    return { ok: resp.ok, status: resp.status, text: text.slice(0, 300) };
  } catch (e: any) {
    return { ok: false, status: 0, text: String(e?.message ?? e) };
  }
}

async function sendPushover(
  subject: string,
  body: string,
  priority: number,
): Promise<DispatchResult> {
  const token = process.env.PUSHOVER_API_TOKEN;
  const user = process.env.PUSHOVER_USER_KEY;
  if (!token || !user) return { sink: "pushover", ok: false, detail: "not configured" };
  const r = await postForm("https://api.pushover.net/1/messages.json", {
    token,
    user,
    title: `[FTMO Bot] ${subject}`,
    // Pushover truncates at 1024 chars
    message: body.slice(0, 1024),
    priority: String(priority),
  });
  return {
    sink: "pushover",
    ok: r.ok,
    detail: r.ok ? undefined : `HTTP ${r.status}: ${r.text}`,
  };
}

/**
 * Dispatch an alert to all configured sinks (currently just Pushover).
 *
 * severity → Pushover priority mapping:
 *   info     -> -1 (quiet; no sound on phone)
 *   warning  ->  0 (normal; default sound)
 *   critical -> +1 (high; bypasses Pushover quiet hours)
 *
 * Returns the per-sink result array so callers (and the alerts table
 * audit trail) know which sinks fired.
 */
export const dispatchAlert = internalAction({
  args: {
    subject: v.string(),
    body: v.string(),
    severity: v.string(), // "info" | "warning" | "critical"
  },
  handler: async (_ctx, args): Promise<DispatchResult[]> => {
    const priority =
      args.severity === "critical" ? 1 : args.severity === "info" ? -1 : 0;
    const results = await Promise.all([
      sendPushover(args.subject, args.body, priority),
    ]);
    for (const r of results) {
      const tag = r.ok ? "OK" : r.detail === "not configured" ? "SKIP" : "FAIL";
      console.log(`[sink:${r.sink}] ${tag} ${r.detail ?? ""}`);
    }
    return results;
  },
});
