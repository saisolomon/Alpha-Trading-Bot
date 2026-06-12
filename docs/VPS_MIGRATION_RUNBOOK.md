# VPS Migration Runbook — local box → Contabo (pre-Challenge)

> Written 2026-06-11 (M10). Execute BEFORE the paid Challenge. Every step is a checklist
> item; do them in order; nothing here is improvised on the day. Assumes the stack is in
> its current stood-down state (MT5 stopped, monitor sentinel in place, trial account paused).
>
> **BLOCKED ON USER:** step 0 (purchase). Everything after is mechanical.

## 0. Purchase (user action, ~$14/mo)
- [ ] Contabo **Cloud VPS S** (or current equivalent ≥ 2 vCPU / 4 GB / 80 GB NVMe), **Windows Server 2022** image.
- [ ] **Region: US East preferred, Nuremberg (EU) acceptable.** CORRECTED 2026-06-11: the original "EU, near OANDA's UK/EU infra" premise was an assumption; the trial's own MT5 logs show the terminal connecting via **"Access Server – NY"** (ping ~40ms), so US East minimizes hops to the observed access layer. Latency is irrelevant at M15+ either way — the criterion is routing stability + cost (non-EU regions carry a small Contabo surcharge; Nuremberg is the budget pick). Do not pick Asia/Oceania. Note: the paid Challenge's actual server is assigned by FTMO post-purchase and may differ from the trial's.
- [ ] Record RDP credentials in the password manager (NOT in the repo).
- [ ] *Acceptable alternatives (2026-06-11):* **Vultr New Jersey** (~$35-40/mo — better network consistency, one-click snapshots, hourly billing; the upgrade pick if cost is no object) or **AWS Lightsail us-east-1** (~$22-26/mo). Contabo remains the value default: its known weaknesses (oversold CPU, support) don't touch an idle MT5 workload, and our resilience stack absorbs network blips. NOT Hetzner for this box (no Windows images; it's the M11 Linux pick). This box is transitional (retired at the Nautilus migration) — don't over-invest.

## 1. Base box hardening (15 min)
- [ ] RDP in; change the default admin password.
- [ ] Windows Update: run once to current, then set **active hours** + pause updates for 7 days before any go-live window (lesson: the 6/10 reboot).
- [ ] `powercfg /change standby-timeout-ac 0` + `powercfg /change hibernate-timeout-ac 0` (server images are usually fine; verify anyway).
- [ ] Timezone: leave the box on **UTC** (cleaner logs than the local box's EDT confusion during the replay; MT5 logs will then be UTC).
- [ ] Install: Git, Python 3.11, uv. **Server 2022 has NO winget** (confirmed on the Vultr box 2026-06-11) — use direct installers: Git via the git-for-windows latest-release API asset (`/VERYSILENT /NORESTART`), Python via `python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe` (`/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1`), uv via `irm https://astral.sh/uv/install.ps1 | iex`. Open a NEW shell afterwards (PATH), verify all three `--version`s.

## 2. Repo + secrets (10 min)
- [ ] `git clone https://github.com/saisolomon/Alpha-Trading-Bot.git C:\ftmo-bot`
- [ ] Copy `.env` from the password manager / local box (NEVER via the repo). Verify it contains: MT5 creds (NEW Challenge account once purchased), `CONVEX_SITE_URL`, `FTMO_BOT_SHARED_SECRET`, Pushover keys.
- [ ] `cd C:\ftmo-bot && uv sync` (or `python -m venv .venv` + install per pyproject).
- [ ] **Do NOT create `logs/MONITOR_DISABLED`** — fresh box starts enabled. (On the OLD box that sentinel stays until decommission.)

## 3. MT5 install + account (15 min)
- [ ] Install MT5 (MetaQuotes installer or FTMO's). Log in with the **paid Challenge credentials** (from FTMO dashboard after purchase). Confirm bottom-right shows connected + correct server.
- [ ] Options → Expert Advisors: enable algorithmic trading; allow DLL imports (libquant/libftmorisk need it).
- [ ] Copy DLLs: **`libquant.dll` + `libgcc_s_seh-1.dll`** → `<MT5 data>\MQL5\Libraries\` (source: old box's MT5 Libraries dir, via RDP drive redirection `\tsclient\C\...`; not in git). CORRECTED 2026-06-11: `libftmorisk.dll` is NOT needed at runtime — FTMORisk.mqh imports `libquant.dll` (the risk functions live there); the OCaml DLL in `ocaml/_build` is a parity-test artifact. `libgcc_s_seh-1.dll` is libquant's MinGW runtime dependency and IS required.
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
Run the portable installer (elevated PowerShell): `powershell -ExecutionPolicy Bypass -File scripts\setup_windows_tasks.ps1` (reworked 2026-06-11: paths derive from the script location; registers Monitor + Push only, reviews via `-IncludeReviews`).
- [ ] `FTMOBot Paper-Trade Monitor` — at-logon + 5-min watchdog fire, `.venv` python directly, **ExecutionTimeLimit 4h**, MultipleInstances=IgnoreNew. The 5-min IgnoreNew fire restarts a dead instance; the 4h limit recycles a HUNG one (the 6/10 lesson — the old at-logon/RestartCount design couldn't).
- [ ] `FTMOBot Paper-Trade Push` — hourly git add/commit/push of `data/paper_trade/`.
- [ ] **CORRECTED 2026-06-11 — tasks use the interactive token ("run only when user is logged on"), NOT "run whether logged in or not":** the MetaTrader5 Python API attaches to the terminal in the SAME session; a cross-session (S4U/service) task silently launches a SECOND terminal instance. The pairing that makes this safe across reboots is **Windows auto-logon** (`netplwiz` → uncheck "Users must enter a user name and password" → enter the Administrator credentials; stored as an LSA secret, not plaintext registry). RDP **disconnect** (X button) keeps the console session logged on; never Sign Out.
- [x] Reboot the box once; verify: auto-logon lands on the desktop, MT5 relaunches + logs in, BotOrchestrator reattaches all 3 EAs, monitor task fires, heartbeat lands in Convex (<2 min). **PASSED 2026-06-11: 88-second total outage** (shutdown → first post-reboot heartbeat); first heartbeat carried full eaStates from the `logs/ea_states.json` sidecar before MT5 had even finished loading.
- [ ] **Reboot commands MUST be forced — discovered the hard way (6 failed attempts 2026-06-11):** `shutdown /r /t 5` without `/f`, Start-menu Restart, etc. get **silently VETOED by MT5** at the closing-apps stage — Windows gives up, the session survives, nothing reboots. Telltale scar in the logs: a full simultaneous EA re-init generation WITH NO heartbeat gap (MT5 reloads charts after absorbing the close request). Always use **`shutdown /r /f /t 5`** (or the Vultr panel / `Restart-Computer -Force`). Auto-logon via **Sysinternals Autologon** (netplwiz's checkbox is hidden on this image); Domain field = `MT5-EXEC`.

## 7. Telemetry sanity (5 min)
- [ ] `curl https://clever-malamute-966.convex.site/status?brokerLogin=<NEW>` → fresh snapshot, `mtConnected: true`, **4 eaStates: the 3 roster EAs + EquityWatchdog, dry-run flags matching the intended mode for this account** (USER DECISION 2026-06-11: the free-trial week runs **LIVE** — `dryRun: false` ×3 — see §8; the watchdog always shows false, it has no dry-run mode). *FIXED 2026-06-11, found live on the VPS: eaStates had NEVER been wired (monitor never passed `ea_states` to post_heartbeat) AND the MT5 logs dir was hardcoded to the old box's path. Now: logs dir auto-discovered from `mt5.terminal_info().data_path`; init lines (`dry_run=true|false`) parsed into per-EA state, persisted to `logs/ea_states.json` so flags survive monitor restarts.*
- [ ] `npx convex run sinks:dispatchAlert '{"severity":"info","subject":"VPS live","body":"New box reporting."}'` → arrives on phone.

## 8. The live-fire trial gate (the week that earns the paid Challenge)
> REDEFINED 2026-06-11 (user decision): this section was written as a 7-day DRY-RUN
> gate when the next account was going to be the paid Challenge. A fresh FREE trial
> sits in between, so the week runs **LIVE on the trial** (`InpDryRun=false` ×3) —
> strictly more evidence at $0 risk: real fills, real news-gate blocks, real watchdog
> interplay. The C2 live config was telemetry-verified 2026-06-11 (sizes 0.50/0.50/0.25%,
> watchdog 3%/7% on exactly 200000.00).
- [ ] Run the full stack LIVE for 7 trading days. **Pass criteria (all must hold):**
  - Zero internal-kill / FTMOImminent events; zero monitor gaps > 10 min.
  - LondonMomo + LondonFix produce signals on most sessions; AUDJPY trail logs appear on H4 bars.
  - **News-clock validation:** FOMC **6/17 18:00 UTC** and BoE **6/18 11:00 UTC** fall in this week. Verify the survivors' logs show blackout skips AT those true UTC times — live, the gate must actually BLOCK real orders (the 2026-06-11 TimeGMT fix's live exam).
  - **Execution evidence (live-only bonus):** per-fill slippage vs signal price, SafeFillingMode retcodes (no 10030/10031), OnTradeTransaction state resets firing on every close, cluster-cap gate logs when >1 EA holds risk.
  - Benched-EA evidence collection: RSIFade signal frequency, NewsReaction behavior → rejoin decisions per `research/silent_ea_replay_2026-06.md`. **RATIFIED 2026-06-11 — both attach DRY-RUN at the 6/12 drill visit:** open EURUSD M15 (RSIFade) + XAUUSD H1 (NewsReaction) charts, drag EAs with defaults untouched (compiled default IS dry-run; verify `dryRun: true` ×2 in eaStates after), deliberately NOT in the manifest (probationers don't get orchestrator resurrection). NewsReaction's exam = FOMC 6/17 + BoE 6/18 on the fixed clock.
- [ ] **Paid-Challenge arming procedure (moved from "go-live flip" — rehearse it AT purchase):** on the paid account the EAs attach dry-run-first during setup verification, then flip: per roster chart Properties → `InpDryRun = false` → OK. Then the HARD CHECK (the dry-run-miss bug class killer): pull the latest heartbeat's `eaStates` from Convex and confirm **every TRADING roster EA reports `dryRun: false`** (EquityWatchdog always shows false; it has no dry-run mode). The flip re-inits each EA → fresh init line → eaStates reflects it within ~1 poll. No green light while any roster EA says true. Save profile after. *The eaStates pathway caught a real plan-vs-box mismatch on its first run (2026-06-11) — trust telemetry, never the Experts-tab eyeball.*

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
  - **Kill drill:** temporarily set the watchdog's **`InpMaxKillPct` to `0.0001`** → verify flatten + `FTMO_KILL_ACTIVE=1` + **phone page within ≤60s** → restore `0.07` AND delete the `FTMO_KILL_ACTIVE` global (F3) or EAs refuse entries. Do NOT skip. *(CORRECTED 2026-06-12 from the first live drill: (1) use the MAX line, not daily — when flat, equity sits exactly at the daily anchor and a hair-trigger daily pct can't trip, while the max line keys off the $200k initial; (2) the EA's `Alert()` is a VPS-SCREEN POPUP ONLY — the first drill's kill flattened and latched correctly but no human was paged. Fixed: the monitor parses watchdog kill lines ("Alert: EquityWatchdog *_KILL"/"FLATTENED"/"FLATTEN FAILED") and fires the direct-Pushover path, 15-min freshness window so restarts re-reading old logs don't re-page.)* Run while flat (pre-session ~03:00 UTC or post-14:00 UTC).
  - **Outbox drill:** block the box's network ~10 min mid-session → verify snapshots queue to `logs/convex_outbox.jsonl` and drain in order on recovery (zero data loss).
- **Vultr API key:** NOT needed for this runbook (console + RDP covers everything at one-box scale). If created later (automated snapshots / M11 fleet IaC): **never store it on the VPS itself** — a trading box must not hold the credential that controls its own infrastructure. Password manager only, and IP-restrict the key to home IP in Vultr's API settings.
