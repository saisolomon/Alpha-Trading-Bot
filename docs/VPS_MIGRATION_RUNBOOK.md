# VPS Migration Runbook — local box → Contabo (pre-Challenge)

> Written 2026-06-11 (M10). Execute BEFORE the paid Challenge. Every step is a checklist
> item; do them in order; nothing here is improvised on the day. Assumes the stack is in
> its current stood-down state (MT5 stopped, monitor sentinel in place, trial account paused).
>
> **BLOCKED ON USER:** step 0 (purchase). Everything after is mechanical.

## 0. Purchase (user action, ~$14/mo)
- [ ] Contabo **Cloud VPS S** (or current equivalent ≥ 2 vCPU / 4 GB / 80 GB NVMe), **Windows Server 2022** image, **EU region (Nuremberg)** — near OANDA's UK/EU infrastructure; latency is irrelevant at M15+, region choice is for routing stability.
- [ ] Record RDP credentials in the password manager (NOT in the repo).

## 1. Base box hardening (15 min)
- [ ] RDP in; change the default admin password.
- [ ] Windows Update: run once to current, then set **active hours** + pause updates for 7 days before any go-live window (lesson: the 6/10 reboot).
- [ ] `powercfg /change standby-timeout-ac 0` + `powercfg /change hibernate-timeout-ac 0` (server images are usually fine; verify anyway).
- [ ] Timezone: leave the box on **UTC** (cleaner logs than the local box's EDT confusion during the replay; MT5 logs will then be UTC).
- [ ] Install: Git, Python 3.11 (monitor venv) — `winget install Git.Git Python.Python.3.11`.

## 2. Repo + secrets (10 min)
- [ ] `git clone https://github.com/saisolomon/Alpha-Trading-Bot.git C:\ftmo-bot`
- [ ] Copy `.env` from the password manager / local box (NEVER via the repo). Verify it contains: MT5 creds (NEW Challenge account once purchased), `CONVEX_SITE_URL`, `FTMO_BOT_SHARED_SECRET`, Pushover keys.
- [ ] `cd C:\ftmo-bot && uv sync` (or `python -m venv .venv` + install per pyproject).
- [ ] **Do NOT create `logs/MONITOR_DISABLED`** — fresh box starts enabled. (On the OLD box that sentinel stays until decommission.)

## 3. MT5 install + account (15 min)
- [ ] Install MT5 (MetaQuotes installer or FTMO's). Log in with the **paid Challenge credentials** (from FTMO dashboard after purchase). Confirm bottom-right shows connected + correct server.
- [ ] Options → Expert Advisors: enable algorithmic trading; allow DLL imports (libquant/libftmorisk need it).
- [ ] Copy DLLs: repo `cpp/`-built `libquant.dll` + `libftmorisk.dll` → `<MT5 data>\MQL5\Libraries\` (grab the built DLLs from the old box's MT5 tree — they are not in git).
- [ ] Deploy MQL5 files: repo `mql5\Include\*.mqh` → `MQL5\Include\`; repo `mql5\Experts\*.mq5` → `MQL5\Experts\`; repo `mql5\bot_manifest.txt` → `MQL5\Files\bot_manifest.txt` (**C2 roster — verify it lists exactly: EURUSD_M15_LondonMomo, XAUUSD_M15_LondonFix, AUDJPY_H4_TrendFollow**).
- [ ] Compile all in MetaEditor (F7 each, or CLI `/compile`). Expect 0 errors (warning 68 about version format is benign).

## 4. Charts + EAs (20 min) — the chicken-and-egg step
BotOrchestrator can only auto-heal EAs it has templates for; first attach is manual:
- [ ] Open charts: **GBPUSD M15** (LondonMomo — GBPUSD chart ONLY, per C2; do NOT open an EURUSD instance), **XAUUSD M15** (LondonFix), **AUDJPY H4** (TrendFollow), plus any utility chart for BotOrchestrator (e.g. USDNOK H1 as before).
- [ ] Attach each EA to its chart. **Inputs: leave `InpDryRun = true`** (the dry-run week runs first). Set `InpAccountType = CHALLENGE_2STEP_PHASE1`.
- [ ] Attach BotOrchestrator to the utility chart. Within 60s it should log `ok (running)` per manifest EA and auto-save templates.
- [ ] File → Profiles → Save As → `FTMOBot` (survives restarts).
- [ ] MT5 auto-start: put an MT5 shortcut in `shell:startup`; enable auto-login in MT5 settings (lesson: the 6/10 reboot recovered in 3 min BECAUSE of this on the old box).

## 5. Convex registration (5 min) — initialCapital is now IMMUTABLE
- [ ] First monitor start auto-registers — but do it deliberately instead: when the Challenge account's TRUE starting balance is on screen (e.g. exactly 200000.00), start the monitor once and verify:
      `npx convex run accounts:getByBrokerLogin '{"brokerLogin": <NEW>}'` → `initialCapital` equals the true start **to the cent**. It can never be corrected later (by design).
- [ ] Old trial account stays paused (`monitoringPaused: true`) — do NOT delete it; its data is the post-mortem corpus.

## 6. Scheduled tasks (10 min)
Recreate the four FTMOBot tasks (elevated PowerShell; mirror old-box settings):
- [ ] `FTMOBot Paper-Trade Monitor` — every 5 min, `uv run python scripts/paper_trade_monitor.py --poll-seconds 60`, **ExecutionTimeLimit 4h**, MultipleInstances=IgnoreNew, "run whether logged in or not". *Open issue from 6/10: the 4h limit failed to recycle a hung instance once — after go-live, verify a manual `Stop-ScheduledTask` + auto-restart cycle works.*
- [ ] `FTMOBot Paper-Trade Push` — hourly git add/commit/push of `data/paper_trade/`.
- [ ] Daily/Weekly Review tasks — optional, recreate if still wanted.
- [ ] Reboot the box once; verify: MT5 relaunches + logs in, BotOrchestrator reattaches all 3 EAs, monitor task fires, heartbeat lands in Convex (<2 min).

## 7. Telemetry sanity (5 min)
- [ ] `curl https://clever-malamute-966.convex.site/status?brokerLogin=<NEW>` → fresh snapshot, `mtConnected: true`, 3 eaStates **with `dryRun: true` visible**.
- [ ] `npx convex run sinks:dispatchAlert '{"severity":"info","subject":"VPS live","body":"New box reporting."}'` → arrives on phone.

## 8. The 7-day dry-run gate (the week that earns go-live)
- [ ] Run the full stack in dry-run for 7 trading days. **Pass criteria (all must hold):**
  - Zero internal-kill / FTMOImminent events; zero monitor gaps > 10 min.
  - LondonMomo + LondonFix produce dry-run signals on most sessions; AUDJPY trail logs appear on H4 bars.
  - **News-clock validation:** FOMC **6/17 18:00 UTC** and BoE **6/18 11:00 UTC** fall in this week. Verify (a) the survivors' logs show blackout skips AT those true UTC times, and (b) if NewsReaction is attached for observation, it evaluates the TRUE post-release bar (the 2026-06-11 TimeGMT fix's live test).
  - Benched-EA evidence collection: RSIFade signal frequency, NewsReaction behavior → rejoin decisions per `research/silent_ea_replay_2026-06.md`.
- [ ] **Go-live flip procedure (after the gate passes):** for each roster chart: Properties → `InpDryRun = false` → OK. Then the HARD CHECK (the dry-run-miss bug class killer): pull the latest heartbeat's `eaStates` from Convex and confirm **every roster EA reports `dryRun: false`**. No green light while any roster EA says true. Save profile again.

## 9. Old box decommission (after 48h of clean VPS operation)
- [ ] Old box: leave `logs/MONITOR_DISABLED` in place; disable/delete the four scheduled tasks (elevated); MT5 stays closed. Box becomes dev/research only.
- [ ] Update `Memory.md`: VPS live date, new account login, dry-run results.

## Rollback
Any step fails badly → the local box is a known-good fallback: delete its sentinel, relaunch MT5 (old profile restores), re-enable monitor task. Decommission only after the VPS survives a reboot + 48h clean.

---
## Addendum 2026-06-11 (EquityWatchdog + alert independence)
- **§2 .env additions:** `PUSHOVER_API_TOKEN` + `PUSHOVER_USER_KEY` are now REQUIRED in the local `.env` — the monitor's cross-channel degradation alert posts to Pushover directly (the one alert that must survive a Convex outage).
- **§4 extra chart:** attach **EquityWatchdog** manually to the utility chart (NOT in the manifest — it has no symbol). Set `InpInitialCapital` to the account's TRUE initial sim capital (init refuses 0). Defaults: 3% daily / 7% max internal kills, 1s poll.
- **§8 extra drills (dry-run week):**
  - **Kill drill:** temporarily set the watchdog's `InpDailyKillPct` to `0.0001` on the demo → verify flatten-within-1s + `FTMO_KILL_ACTIVE=1` + alert → restore real inputs. Do NOT skip; this is the synthetic trip test from Tasks.md.
  - **Outbox drill:** block the box's network ~10 min mid-session → verify snapshots queue to `logs/convex_outbox.jsonl` and drain in order on recovery (zero data loss).
