// HTTP Actions: the public REST surface for the trading bot.
//
// Endpoints (all under https://clever-malamute-966.convex.site):
//
//   POST /heartbeat   -- local monitor pings every 60s
//                        body: { brokerLogin, brokerServer, accountType,
//                                initialCapital, currency, monitorVersion,
//                                mtConnected, eaStates }
//
//   POST /snapshot    -- local monitor sends full account+positions snapshot
//                        body: { brokerLogin, balance, equity, profit, ...,
//                                positions: [...] }
//
//   GET  /status?brokerLogin=NNN
//                     -- public read of latest snapshot + recent alerts.
//                        Used by phone/dashboard.
//
// Auth: ALL write endpoints require an HTTP header
//   X-Ftmo-Bot-Secret: <value of process.env.FTMO_BOT_SHARED_SECRET>
// Set via `npx convex env set FTMO_BOT_SHARED_SECRET <random-uuid>`.
// Without it, anyone with the site URL could pollute the database.

import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { api } from "./_generated/api";

const http = httpRouter();

function checkSecret(request: Request): Response | null {
  const supplied = request.headers.get("X-Ftmo-Bot-Secret");
  const expected = process.env.FTMO_BOT_SHARED_SECRET;
  if (!expected) {
    return new Response(
      JSON.stringify({
        error: "server misconfigured: FTMO_BOT_SHARED_SECRET not set in Convex env",
      }),
      { status: 500, headers: { "content-type": "application/json" } },
    );
  }
  if (supplied !== expected) {
    return new Response(
      JSON.stringify({ error: "unauthorized" }),
      { status: 401, headers: { "content-type": "application/json" } },
    );
  }
  return null;
}

http.route({
  path: "/heartbeat",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const authErr = checkSecret(request);
    if (authErr) return authErr;
    const body = await request.json();
    const accountId = await ctx.runMutation(api.accounts.registerAccount, {
      brokerLogin: body.brokerLogin,
      brokerServer: body.brokerServer,
      accountType: body.accountType,
      initialCapital: body.initialCapital,
      currency: body.currency,
    });
    await ctx.runMutation(api.heartbeats.record, {
      accountId,
      monitorVersion: body.monitorVersion,
      mtConnected: body.mtConnected,
      eaStates: body.eaStates,
    });
    return new Response(JSON.stringify({ ok: true, accountId }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }),
});

http.route({
  path: "/snapshot",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const authErr = checkSecret(request);
    if (authErr) return authErr;
    const body = await request.json();
    const accountId = await ctx.runMutation(api.accounts.registerAccount, {
      brokerLogin: body.brokerLogin,
      brokerServer: body.brokerServer ?? "unknown",
      accountType: body.accountType ?? "CHALLENGE_2STEP_PHASE1",
      initialCapital: body.initialCapital ?? body.balance,
      currency: body.currency ?? "USD",
    });
    const result = await ctx.runMutation(api.snapshots.record, {
      accountId,
      balance: body.balance,
      equity: body.equity,
      profit: body.profit,
      marginUsed: body.marginUsed,
      marginFree: body.marginFree,
      dailyLimitDistance: body.dailyLimitDistance,
      maxLimitDistance: body.maxLimitDistance,
      ftmoStatus: body.ftmoStatus,
      carryToday: body.carryToday ?? 0,
      positions: body.positions ?? [],
    });
    return new Response(JSON.stringify({ ok: true, accountId, ...result }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }),
});

http.route({
  path: "/deals",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const authErr = checkSecret(request);
    if (authErr) return authErr;
    const body = await request.json();
    // body: { brokerLogin, deals: [...] }
    const account = await ctx.runQuery(api.accounts.getByBrokerLogin, {
      brokerLogin: body.brokerLogin,
    });
    if (!account) {
      return new Response(
        JSON.stringify({ error: "account not found; POST /heartbeat first" }),
        { status: 404, headers: { "content-type": "application/json" } },
      );
    }
    const result = await ctx.runMutation(api.deals.recordBatch, {
      accountId: account._id,
      deals: body.deals ?? [],
    });
    return new Response(JSON.stringify({ ok: true, ...result }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }),
});

http.route({
  path: "/latest-deal-ticket",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    // No auth: returns just a number, no sensitive data
    const url = new URL(request.url);
    const brokerLogin = Number(url.searchParams.get("brokerLogin"));
    const account = await ctx.runQuery(api.accounts.getByBrokerLogin, {
      brokerLogin,
    });
    if (!account) {
      return new Response(JSON.stringify({ latestTicket: 0 }), {
        status: 200, headers: { "content-type": "application/json" },
      });
    }
    const t = await ctx.runQuery(api.deals.latestTicket, {
      accountId: account._id,
    });
    return new Response(JSON.stringify({ latestTicket: t }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }),
});

http.route({
  path: "/acknowledge",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    // No auth: acknowledging an alert is low-risk (it just hides it
    // from the unack'd-count). If you want this gated, add checkSecret.
    const body = await request.json();
    if (body.alertId) {
      await ctx.runMutation(api.alerts.acknowledge, { alertId: body.alertId });
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (body.all) {
      const r = await ctx.runMutation(api.alerts.acknowledgeAll, {
        upToMs: body.upToMs,
      });
      return new Response(JSON.stringify({ ok: true, ...r }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(
      JSON.stringify({ error: "supply either alertId or all:true" }),
      { status: 400, headers: { "content-type": "application/json" } },
    );
  }),
});

http.route({
  path: "/status",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    // GET endpoint is read-only -- no secret required (publicly visible
    // bot status is acceptable; positions/equity are not sensitive for
    // a paper-trade demo account). If you want to lock this down later,
    // add checkSecret(request) here.
    const url = new URL(request.url);
    const brokerLoginStr = url.searchParams.get("brokerLogin");
    if (!brokerLoginStr) {
      return new Response(
        JSON.stringify({ error: "missing brokerLogin query param" }),
        { status: 400, headers: { "content-type": "application/json" } },
      );
    }
    const brokerLogin = Number(brokerLoginStr);
    const account = await ctx.runQuery(api.accounts.getByBrokerLogin, {
      brokerLogin,
    });
    if (!account) {
      return new Response(
        JSON.stringify({ error: "account not found", brokerLogin }),
        { status: 404, headers: { "content-type": "application/json" } },
      );
    }
    const latest = await ctx.runQuery(api.snapshots.latest, {
      accountId: account._id,
    });
    const heartbeat = await ctx.runQuery(api.heartbeats.latest, {
      accountId: account._id,
    });
    const alerts = await ctx.runQuery(api.alerts.recent, { limit: 10 });
    return new Response(
      JSON.stringify({
        account: {
          brokerLogin: account.brokerLogin,
          brokerServer: account.brokerServer,
          accountType: account.accountType,
          initialCapital: account.initialCapital,
          currency: account.currency,
        },
        latestSnapshot: latest,
        latestHeartbeat: heartbeat
          ? {
              recordedAt: heartbeat.recordedAt,
              ageSeconds: Math.round((Date.now() - heartbeat.recordedAt) / 1000),
              mtConnected: heartbeat.mtConnected,
              eaStates: heartbeat.eaStates,
            }
          : null,
        recentAlerts: alerts,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }),
});

// ---------------------------------------------------------------------------
// GET /  -- live dashboard webpage (vanilla HTML+JS, mobile-friendly)
// ---------------------------------------------------------------------------
// No build step, no framework. Just an HTML shell that polls /status
// every 15 seconds via fetch() and re-renders the DOM. Designed to be
// open in a phone browser tab while you're away from the Windows machine.
//
// Default brokerLogin = 5050327497 (the demo account). Override via
// ?brokerLogin=NNN in the URL when you switch to FTMO.

const DASHBOARD_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FTMO Bot Status</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%233fb950' rx='3'/%3E%3C/svg%3E">
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font: 14px -apple-system, system-ui, sans-serif; margin: 0; padding: 16px;
         background: #0d1117; color: #e6edf3; }
  h1 { font-size: 18px; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
  h2 { font-size: 13px; margin: 20px 0 6px; color: #7d8590; text-transform: uppercase;
       letter-spacing: 0.05em; display: flex; justify-content: space-between; align-items: center; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
  .stat { display: flex; flex-direction: column; padding: 8px 12px;
          background: #161b22; border-radius: 6px; border: 1px solid #30363d; }
  .stat .l { color: #7d8590; font-size: 11px; }
  .stat .v { color: #e6edf3; font-size: 18px; font-weight: 600; margin-top: 2px;
             font-variant-numeric: tabular-nums; }
  .stat .v.pos { color: #3fb950; }
  .stat .v.neg { color: #f85149; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px;
          font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #30363d;
           font-size: 12px; }
  th { color: #7d8590; font-weight: normal; }
  td.num { text-align: right; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; font-weight: 600; }
  .pill.ok { background: #1f3a26; color: #3fb950; }
  .pill.warn { background: #3b2e0c; color: #d29922; }
  .pill.crit { background: #4a1e1e; color: #f85149; }
  .pill.stale { background: #4a1e1e; color: #f85149; animation: pulse 2s infinite; }
  @keyframes pulse { 50% { opacity: 0.5; } }
  .footer { color: #7d8590; font-size: 11px; margin-top: 24px; line-height: 1.6; }
  a { color: #2f81f7; }
  button { font: inherit; padding: 4px 10px; border-radius: 4px; cursor: pointer;
           background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  button:hover { background: #30363d; }
  button:disabled { opacity: 0.4; cursor: default; }
  #err { color: #f85149; padding: 8px; background: #1a0e0e; border-radius: 6px;
         margin: 12px 0; display: none; }
  /* Critical-alert banner */
  #banner { display: none; padding: 12px 16px; background: #4a1e1e; color: #f85149;
            border: 2px solid #f85149; border-radius: 6px; margin-bottom: 16px;
            animation: pulse 2s infinite; font-weight: 600; }
  #banner.shown { display: block; }
  /* Notification-permission CTA */
  #notifCta { display: none; padding: 8px 12px; background: #1f2a3b; color: #58a6ff;
              border: 1px solid #2f81f7; border-radius: 6px; margin-bottom: 12px;
              font-size: 12px; }
  #notifCta.shown { display: flex; justify-content: space-between; align-items: center; }
  .alert-row { background: #161b22; }
  .alert-row.ack { opacity: 0.5; }
  .alert-row.crit { background: #2a1414; }
  .ackbtn { font-size: 10px; padding: 2px 6px; }
</style>
</head>
<body>
<h1>
  <span id="loginPill" class="pill ok">…</span>
  FTMO Bot
</h1>

<div id="notifCta">
  <span>🔔 Enable browser notifications to get critical alerts when this tab is in the background.</span>
  <button onclick="requestNotificationPerm()">Enable</button>
</div>

<div id="banner"></div>
<div id="err"></div>

<div id="root">Loading…</div>

<div class="footer">
  Polls every 15s · Last update: <span id="updated">never</span> · Alerts seen this session: <span id="alertCount">0</span><br>
  Convex backend · <a href="https://github.com/saisolomon/Alpha-Trading-Bot" target="_blank">repo</a> · <a href="#" onclick="testAlert();return false;">🔊 test sound</a>
</div>

<script>
const PARAMS = new URLSearchParams(location.search);
const BROKER_LOGIN = PARAMS.get("brokerLogin") || "5050327497";
const POLL_MS = 15_000;

// Track which alert IDs we've already shown so we only notify on NEW ones
const seenAlertIds = new Set();
let alertsSeenThisSession = 0;
let isFirstRefresh = true;

document.getElementById("loginPill").textContent = "#" + BROKER_LOGIN;

// ---------------- Browser notifications --------------------------------------
function maybeShowNotifCta() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    document.getElementById("notifCta").classList.add("shown");
  }
}
function requestNotificationPerm() {
  if (!("Notification" in window)) {
    alert("Notifications are not supported in this browser.");
    return;
  }
  Notification.requestPermission().then(p => {
    document.getElementById("notifCta").classList.toggle("shown", p === "default");
    if (p === "granted") {
      new Notification("FTMO Bot", { body: "Notifications enabled. You'll be alerted on critical events.", silent: false });
    }
  });
}
function notify(title, body, isCritical) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(title, {
      body,
      tag: title,
      requireInteraction: isCritical,  // critical: persist until user dismisses
      silent: false,
    });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) { /* noop */ }
}

// ---------------- Beep sound (no audio file needed; Web Audio API) ----------
let audioCtx = null;
function beep(freqHz, durationMs, volume = 0.2) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = "sine"; o.frequency.value = freqHz;
    g.gain.value = volume;
    o.connect(g); g.connect(audioCtx.destination);
    o.start();
    setTimeout(() => { o.stop(); }, durationMs);
  } catch (e) { /* noop */ }
}
function alertSound(severity) {
  if (severity === "critical") {
    beep(880, 200); setTimeout(() => beep(660, 200), 250); setTimeout(() => beep(880, 400), 500);
  } else if (severity === "warning") {
    beep(660, 150); setTimeout(() => beep(880, 150), 200);
  } else {
    beep(440, 100);
  }
}
function testAlert() { alertSound("critical"); notify("Test alert", "If you see this, notifications work.", true); }

// ---------------- Formatters -------------------------------------------------
function fmtMoney(n) {
  if (n == null) return "—";
  return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(n) {
  if (n == null) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(3) + "%";
}
function fmtAge(s) {
  if (s == null) return "—";
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}
function statPill(s) {
  if (s == null) return '<span class="pill warn">unknown</span>';
  if (s.ftmoStatus >= 2) return '<span class="pill crit">KILLED</span>';
  if (s.ftmoStatus === 1) return '<span class="pill warn">imminent</span>';
  return '<span class="pill ok">OK</span>';
}
function hbPill(hb) {
  if (!hb) return '<span class="pill crit">NO HEARTBEAT</span>';
  if (hb.ageSeconds > 600) return '<span class="pill stale">STALE ' + fmtAge(hb.ageSeconds) + '</span>';
  if (hb.ageSeconds > 120) return '<span class="pill warn">' + fmtAge(hb.ageSeconds) + '</span>';
  return '<span class="pill ok">' + fmtAge(hb.ageSeconds) + '</span>';
}

// ---------------- Acknowledge ------------------------------------------------
async function ackAlert(alertId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "..."; }
  try {
    const r = await fetch("/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alertId }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    refresh();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "ack"; }
    alert("Ack failed: " + e.message);
  }
}
async function ackAll() {
  if (!confirm("Acknowledge all alerts?")) return;
  try {
    const r = await fetch("/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ all: true }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    refresh();
  } catch (e) { alert("Ack failed: " + e.message); }
}

// ---------------- Main refresh loop -----------------------------------------
async function refresh() {
  try {
    const r = await fetch("/status?brokerLogin=" + encodeURIComponent(BROKER_LOGIN));
    if (!r.ok) {
      const e = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(e.error || r.statusText);
    }
    const d = await r.json();
    const snap = d.latestSnapshot;
    const hb = d.latestHeartbeat;
    const positions = snap?.positions ?? [];
    const alerts = d.recentAlerts ?? [];
    const equity = snap?.equity;
    const balance = snap?.balance;
    const profit = snap?.profit;
    const pnlPct = (equity != null && balance) ? ((equity - balance) / balance * 100) : null;

    // -- Detect NEW alerts since last poll (skip on very first refresh
    //    to avoid blasting notifications for old alerts already in DB)
    if (!isFirstRefresh) {
      for (const a of alerts) {
        if (!seenAlertIds.has(a._id) && !a.acknowledged) {
          alertsSeenThisSession++;
          alertSound(a.severity);
          notify(
            "[FTMO Bot] " + a.message,
            a.context || a.kind,
            a.severity === "critical",
          );
        }
      }
    }
    for (const a of alerts) seenAlertIds.add(a._id);
    isFirstRefresh = false;
    document.getElementById("alertCount").textContent = alertsSeenThisSession;

    // -- Critical-alert banner
    const unackedCritical = alerts.filter(a => !a.acknowledged && a.severity === "critical");
    const banner = document.getElementById("banner");
    if (unackedCritical.length > 0) {
      banner.innerHTML = "🚨 " + unackedCritical.length + " unacknowledged critical alert" + (unackedCritical.length === 1 ? "" : "s") + " — see below";
      banner.classList.add("shown");
    } else {
      banner.classList.remove("shown");
    }

    // -- Main body
    const html = \`
      <div class="grid">
        <div class="stat"><span class="l">Equity</span>
          <span class="v">\${fmtMoney(equity)}</span></div>
        <div class="stat"><span class="l">Balance</span>
          <span class="v">\${fmtMoney(balance)}</span></div>
        <div class="stat"><span class="l">Floating P&L</span>
          <span class="v \${profit > 0 ? 'pos' : profit < 0 ? 'neg' : ''}">
            \${fmtMoney(profit)}</span></div>
        <div class="stat"><span class="l">P&L vs balance</span>
          <span class="v \${pnlPct > 0 ? 'pos' : pnlPct < 0 ? 'neg' : ''}">
            \${fmtPct(pnlPct)}</span></div>
        <div class="stat"><span class="l">Daily-loss headroom</span>
          <span class="v">\${fmtMoney(snap?.dailyLimitDistance)}</span></div>
        <div class="stat"><span class="l">Max-loss headroom</span>
          <span class="v">\${fmtMoney(snap?.maxLimitDistance)}</span></div>
        <div class="stat"><span class="l">FTMO status</span>
          <span class="v">\${statPill(snap)}</span></div>
        <div class="stat"><span class="l">Monitor heartbeat</span>
          <span class="v">\${hbPill(hb)}</span></div>
      </div>

      <h2><span>Open positions (\${positions.length})</span></h2>
      \${positions.length === 0 ? '<p style="color:#7d8590">none</p>' : \`
        <table>
          <thead><tr>
            <th>Symbol</th><th>Side</th><th class="num">Vol</th>
            <th class="num">Open</th><th class="num">Now</th>
            <th class="num">P&L</th><th class="num">Swap</th>
          </tr></thead>
          <tbody>
            \${positions.map(p => \`
              <tr>
                <td>\${p.symbol}</td>
                <td>\${p.side}</td>
                <td class="num">\${p.volume.toFixed(2)}</td>
                <td class="num">\${p.priceOpen.toFixed(4)}</td>
                <td class="num">\${p.priceCurrent.toFixed(4)}</td>
                <td class="num \${p.profit > 0 ? 'pos' : p.profit < 0 ? 'neg' : ''}">
                  \${fmtMoney(p.profit)}</td>
                <td class="num">\${fmtMoney(p.swap)}</td>
              </tr>
            \`).join("")}
          </tbody>
        </table>\`}

      <h2>
        <span>Recent alerts (\${alerts.filter(a => !a.acknowledged).length} unacked / \${alerts.length} total)</span>
        \${alerts.some(a => !a.acknowledged) ? \`<button onclick="ackAll()">Ack all</button>\` : ''}
      </h2>
      \${alerts.length === 0 ? '<p style="color:#7d8590">none</p>' : \`
        <table>
          <thead><tr><th>When</th><th>Sev</th><th>Kind</th><th>Message</th><th></th></tr></thead>
          <tbody>
            \${alerts.slice(0, 20).map(a => \`
              <tr class="alert-row \${a.acknowledged ? 'ack' : ''} \${a.severity === 'critical' ? 'crit' : ''}">
                <td>\${new Date(a.recordedAt).toLocaleString()}</td>
                <td><span class="pill \${a.severity === 'critical' ? 'crit' : a.severity === 'warning' ? 'warn' : 'ok'}">\${a.severity}</span></td>
                <td>\${a.kind}</td>
                <td>\${a.message}</td>
                <td>\${a.acknowledged ? '<span style="color:#7d8590;font-size:10px">acked</span>' : \`<button class="ackbtn" onclick="ackAlert('\${a._id}', this)">ack</button>\`}</td>
              </tr>
            \`).join("")}
          </tbody>
        </table>\`}
    \`;

    document.getElementById("root").innerHTML = html;
    document.getElementById("err").style.display = "none";
    document.getElementById("updated").textContent = new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById("err").textContent = "Refresh failed: " + e.message;
    document.getElementById("err").style.display = "block";
  }
}

maybeShowNotifCta();
refresh();
setInterval(refresh, POLL_MS);

// Resume audio on first user interaction (browsers block autoplay otherwise)
document.addEventListener("click", () => { if (audioCtx?.state === "suspended") audioCtx.resume(); }, { once: true });
</script>
</body>
</html>`;

http.route({
  path: "/",
  method: "GET",
  handler: httpAction(async () => {
    return new Response(DASHBOARD_HTML, {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }),
});

export default http;
