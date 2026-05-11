# Tasks.md — FTMO MT5 Quant Trading System

> The actionable to-do list. Tasks are grouped by milestone and ordered by dependency. Mark items complete by changing `- [ ]` to `- [x]` and adding a one-line note (`# done YYYY-MM-DD — note`). Add new tasks at the bottom of the relevant milestone, not in random places.

**Conventions:**
- Tasks should be small enough to complete in one sitting (rough rule: < 4 hours of focused work).
- If a task is bigger, break it down before starting.
- Every task has an **acceptance criterion** — what does "done" look like.
- Tasks blocking others are marked `[BLOCKER]`.
- New decisions made while completing a task → log them in `Memory.md`.

---

## Milestone 0 — Foundations

### Repo Scaffolding
- [ ] **[BLOCKER] Initialize repo structure** per `Planning.md` Section 2.
  *Acceptance:* `data/`, `research/`, `strategies/`, `backtest/`, `execution/`, `risk/`, `utils/`, `tests/`, `configs/`, `logs/` directories exist with `__init__.py` where needed and `.gitkeep` in empty ones.
- [ ] Add `.gitignore` covering `logs/`, `data/cache/`, `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`.
- [ ] Add `README.md` with project overview, setup steps, and pointers to the four context files.
- [ ] Add `LICENSE` (decide: MIT vs. proprietary; default proprietary for now — log decision in Memory.md).

### Dependency Setup
- [ ] **[BLOCKER] Set up `pyproject.toml`** with `uv` or `poetry`. Pin Python 3.11+.
  *Acceptance:* `uv sync` (or equivalent) installs cleanly on a fresh machine.
- [ ] Add core dependencies: `MetaTrader5`, `numpy`, `pandas`, `pyarrow`, `scipy`, `statsmodels`, `scikit-learn`, `pydantic`, `pyyaml`, `python-dotenv`, `structlog`.
- [ ] Add dev dependencies: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `ipykernel`.
- [ ] Add `.env.example` with placeholder MT5 credentials (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`).

### MT5 Connection Smoke Test
- [ ] **[BLOCKER] Implement `data/mt5_client.py`** — thin wrapper around `mt5.initialize()` / `mt5.shutdown()` with retry-on-failure and credential loading from env.
  *Acceptance:* Calling `MT5Client().connect()` against a demo account succeeds; logs structured connection event.
- [ ] Write smoke test: connect, fetch account info, fetch 100 bars of EURUSD H1, disconnect cleanly.
  *Acceptance:* `pytest tests/test_mt5_smoke.py` passes against a demo MT5 instance.

### Logging Skeleton
- [ ] Implement `utils/log.py` with `structlog` configured for JSON output to file + human-readable to stderr.
- [ ] Define standard event names: `mt5.connect`, `mt5.disconnect`, `signal.generated`, `risk.gate_passed`, `risk.gate_blocked`, `order.sent`, `order.filled`, `order.rejected`, `position.opened`, `position.closed`, `risk.dd_threshold`, `risk.kill_switch`.
  *Acceptance:* Single canonical list in `utils/log.py`; everything else imports from there.

### Config Layer
- [ ] Implement `utils/config.py` with pydantic models for: `MT5Config`, `RiskConfig`, `StrategyConfig`, `BacktestConfig`.
- [ ] Add `configs/default.yaml` with global risk limits (5% / 20% / 2% / DD ladder) per `CLAUDE.md` Section 3.
- [ ] Loader resolves env vars in YAML values (e.g. `${MT5_LOGIN}`).

### Repo Hygiene
- [ ] Add `ruff` config in `pyproject.toml` (line length 100, common ignores).
- [ ] Add `mypy` config — strict on `strategies/`, `risk/`, `execution/`; lenient on `research/`.
- [ ] Add pre-commit hook for `ruff check`, `ruff format`, `mypy`, and `pytest -q`.

---

## Milestone 1 — Data Layer

### MT5 Data Fetch
- [ ] Implement `data/mt5_client.py::fetch_ohlcv(symbol, timeframe, start, end)` returning a typed DataFrame with UTC timestamps, no NaNs in OHLC.
  *Acceptance:* Round-trip test on EURUSD H1 across a 30-day window.
- [ ] Implement `data/mt5_client.py::fetch_ticks(symbol, start, end)` for tick-level data.
- [ ] Implement `data/mt5_client.py::fetch_symbol_info(symbol)` returning contract size, tick size, freeze level, stops level, point value.

### Cache Layer
- [ ] Implement `data/cache.py` — read/write parquet keyed by `(symbol, timeframe, year, month)`.
  *Acceptance:* Repeated fetches for the same window are served from cache and >100× faster than MT5 round-trip.
- [ ] Implement explicit cache invalidation CLI: `python -m data.cache invalidate --symbol EURUSD --timeframe H1`.
- [ ] Add cache integrity check — hash of fetched data vs. recomputed on read.

### Symbol Universe
- [ ] Implement `data/symbols.py` — load broker symbol list, apply liquidity and spread filters from config.
  *Acceptance:* `get_universe('fx_majors')` returns the expected 7 majors with broker-specific suffixes resolved.

### Tests
- [ ] Unit test cache (round-trip, invalidation, corrupted-file handling).
- [ ] Integration test fetch → cache → fetch on a frozen demo dataset.

---

## Milestone 2 — Backtest Engine v1

### Engine Core
- [ ] Implement `backtest/engine.py` — event-driven, bar-by-bar loop.
  *Acceptance:* Replays a sample dataset and produces deterministic equity curve given fixed seed.
- [ ] Define `Strategy` protocol: `generate_signal(state) -> SignalAction`. Same interface used in live.
- [ ] Define `BacktestState` — bar timestamp, current bar, history window, open positions, cash, equity.

### Cost Model
- [ ] Implement `backtest/costs.py` with spread, commission, and slippage models.
- [ ] Default slippage: 0.5× spread, scaled up linearly above 1% of bar volume.
- [ ] Configurable per-strategy via `BacktestConfig`.

### Metrics & Reporting
- [ ] Implement `backtest/metrics.py` — full metrics suite from `CLAUDE.md` Section 6.
- [ ] Implement `backtest/report.py` — equity curve PNG, drawdown plot, monthly returns heatmap, rolling Sharpe.
- [ ] Output trade-by-trade CSV with entry/exit timestamps, prices, sizes, P&L, signal value.

### Walk-Forward Harness
- [ ] Implement `backtest/walk_forward.py` — rolling IS/OOS splits, configurable window sizes.
  *Acceptance:* Walk-forward run on a sample strategy produces a sequence of OOS results with no leakage (verified by injection test: a future-leaking signal must score perfectly IS but break OOS).

### Tests
- [ ] Unit tests on `metrics.py` against hand-calculated examples (known Sharpe values, known DD values).
- [ ] Determinism test: same seed + same data → identical equity curve.
- [ ] Look-ahead detector test: a deliberately-leaking signal must be flagged.

### Prague-Time Utilities (in M0/M1, but called out here)
- [ ] Implement `utils/timeutils.py::prague_now()` and `utils/timeutils.py::prague_midnight_of(dt)` using `zoneinfo.ZoneInfo("Europe/Prague")`.
  *Acceptance:* Property tests confirm Prague midnight handling across DST transitions (last Sunday of March / October).

---

## Milestone 2 — FTMO Compliance Core (BLOCKER for all live work)

This is the most safety-critical module in the repo. No order goes to MT5 without passing through these gates. Property-tested heavily.

### Account Type Modeling
- [ ] **[BLOCKER] Implement `risk/ftmo.py::FTMOAccountType`** — enum of account variants: `CHALLENGE_1STEP`, `CHALLENGE_2STEP_PHASE1`, `CHALLENGE_2STEP_PHASE2`, `FUNDED_STANDARD`, `FUNDED_SWING`, `FUNDED_REWARDS_1STEP`.
- [ ] Implement `risk/ftmo.py::FTMORules` — rule set per account type: daily loss %, max loss %, max loss type (static / trailing-up), profit target, news restrictions, weekend allowed, Best Day rule applies.
  *Acceptance:* Unit tests cover all six account variants against published FTMO rule values.

### State Tracking
- [ ] Implement `risk/ftmo.py::FTMOState` — in-memory + persisted state: initial sim capital, current Prague day, daily-loss anchor balance (set at last Prague midnight), current daily limit (account currency), current max-loss limit, today's closed P&L, sum of profitable-day closed P&L (for Best Day), highest end-of-day balance ever (for trailing max loss).
- [ ] Implement `risk/ftmo.py::daily_reset(now_prague, balance)` — recompute daily anchor and limits at Prague midnight; persist state.
  *Acceptance:* Replay test on synthetic equity curve produces correct daily limits across DST transitions and weekends.

### Headroom Check
- [ ] **[BLOCKER] Implement `risk/ftmo.py::headroom_check(intended_order, account, ftmo_state) -> (allowed: bool, reason: str)`** — simulates worst-case adverse fill (entry slippage + max stop distance) and returns block reason if it would breach internal limits OR put equity within 1% of FTMO's daily/max lines.
  *Acceptance:* Hypothesis-based property tests prove no generated order can pass the gate if its worst-case fill would touch an FTMO line.

### Equity-Tick Watcher
- [ ] **[BLOCKER] Implement `risk/equity_watcher.py`** — sub-second poll of `mt5.account_info().equity`. Computes distance to daily-loss limit and max-loss limit on every tick. Logs distances; raises `FTMOInternalBreach` when internal kill triggers; raises `FTMOImminent` when within 0.5% of an FTMO line.
  *Acceptance:* Synthetic equity-stream test forces internal breach exactly at the −3% (or −2%) threshold; FTMOImminent fires before FTMOInternalBreach.
- [ ] Decide poll frequency vs. CPU cost (default 250ms — log decision in Memory.md).

### Best Day Governor (1-Step Only)
- [ ] Implement `risk/ftmo.py::best_day_ratio(state)` — current ratio of today's closed profit to sum of profitable-day closed profits (denominator includes today's projection).
- [ ] Implement throttle in `headroom_check`: when ratio would project above 40% with the new order's expected profit, reject or shrink size.

### News Blackout
- [ ] Implement `risk/news_blackout.py` — load high-impact economic-calendar feed at session start (default source: ForexFactory weekly export; alternative: Trading Economics API).
- [ ] Implement `news_blackout.is_blackout(symbol, now)` — returns True if `now` is within ±2 minutes of a high-impact event affecting the symbol's currencies/markets.
- [ ] Wire into pre-trade gate for `FUNDED_STANDARD` only — `FUNDED_SWING`, Challenge phases, and Verification are exempt.
  *Acceptance:* Test fixture: a EURUSD trade attempted 90 seconds before NFP on a `FUNDED_STANDARD` account is blocked; same trade on `FUNDED_SWING` is allowed.

### Kill Switches
- [ ] Implement `risk/kill_switch.py` — three independent switches: `daily_kill` (resets at Prague midnight), `max_kill` (full shutdown, manual restart only), `manual_kill` (file/signal-based, persistent).
- [ ] All kill switches flatten open positions before halting. Use `mt5.positions_get()` then send opposite market orders.
  *Acceptance:* Synthetic test trips each switch independently; positions are flat within one tick of trip.

### Property Tests (the safety net)
- [ ] **[BLOCKER]** Hypothesis property test: across a fuzzed space of account states + intended orders + simulated adverse fills, **no order that crosses an FTMO line ever passes `headroom_check`**.
- [ ] Property test: across fuzzed sequences of equity ticks, the equity watcher raises `FTMOInternalBreach` no later than the first tick at-or-below the internal limit.
- [ ] Replay test: feed FTMO's published example timelines (from the Academy lessons) into the state machine and verify the daily/max limits match FTMO's documented values to the cent.

---

## Milestone 3 — Backtest Engine v1 with FTMO Simulator

### Engine Core
- [ ] Implement `backtest/engine.py` — event-driven, bar-by-bar loop.
  *Acceptance:* Replays a sample dataset and produces deterministic equity curve given fixed seed.
- [ ] Define `Strategy` protocol: `generate_signal(state) -> SignalAction`. Same interface used in live.
- [ ] Define `BacktestState` — bar timestamp, current bar, history window, open positions, cash, equity.

### Cost Model
- [ ] Implement `backtest/costs.py` with spread, commission, and slippage models.
- [ ] Default slippage: 0.5× spread, scaled up linearly above 1% of bar volume.
- [ ] Configurable per-strategy via `BacktestConfig`.

### FTMO Simulator (mandatory)
- [ ] **[BLOCKER] Implement `backtest/ftmo_sim.py`** — replays the same `risk/ftmo.py` rule machine against the backtest's equity curve. Reports: max intraday equity drawdown vs. daily limit, max total drawdown vs. max loss, Best Day ratio at end, count of would-be daily failures, count of would-be max-loss failures, count of would-be news-window violations.
  *Acceptance:* A backtest report explicitly states "FTMO PASS" or "FTMO FAIL" with breach details. A strategy is not promoted past M5 if its backtest is FTMO FAIL.

### Metrics & Reporting
- [ ] Implement `backtest/metrics.py` — full metrics suite from `CLAUDE.md` Section 6.
- [ ] Implement `backtest/report.py` — equity curve PNG, drawdown plot (with FTMO daily/max lines overlaid), monthly returns heatmap, rolling Sharpe.
- [ ] Output trade-by-trade CSV with entry/exit timestamps, prices, sizes, P&L, signal value.

### Walk-Forward Harness
- [ ] Implement `backtest/walk_forward.py` — rolling IS/OOS splits, configurable window sizes.
  *Acceptance:* Walk-forward run on a sample strategy produces a sequence of OOS results with no leakage (verified by injection test: a future-leaking signal must score perfectly IS but break OOS).

### Tests
- [ ] Unit tests on `metrics.py` against hand-calculated examples (known Sharpe values, known DD values).
- [ ] Determinism test: same seed + same data → identical equity curve.
- [ ] Look-ahead detector test: a deliberately-leaking signal must be flagged.
- [ ] FTMO-sim replay test: feed a known-bad equity curve (engineered to breach the daily limit on day 5) and verify the simulator reports exact breach time.

---

## Milestone 4 — Execution Skeleton

### MT5 Execution
- [ ] Implement `execution/mt5_orders.py::send_order(request)` wrapping `mt5.order_send()` with retry on retryable errors (requote, off-quotes, server-busy).
  *Acceptance:* Sends a small market order on demo, validates `result.retcode == TRADE_RETCODE_DONE`, position appears in `mt5.positions_get()`. Handles `result is None` (connection failure) explicitly.
- [ ] Implement `execution/mt5_orders.py::check_order(request)` wrapping `mt5.order_check()` — must be called before every `send_order` in production paths.
- [ ] Implement margin/profit pre-flight helpers using `mt5.order_calc_margin()` and `mt5.order_calc_profit()`.
- [ ] Implement `execution/router.py` — orchestrates: strategy signal → FTMO `headroom_check` → news-blackout gate → margin pre-check → `order_check` → slicer → `order_send` → log.
  *Critical:* `headroom_check` is called BEFORE `order_check`. FTMO compliance is enforced even if the broker would accept the order.
- [ ] Implement `execution/slicer.py::twap_slice(order, n_slices, interval_seconds)` for orders > 1% of average bar volume. (VWAP can come later.)

### Reconciliation
- [ ] Implement `execution/reconcile.py` — pulls `mt5.history_deals_get()` for the trading day and reconciles internal P&L tracking against broker-recorded deals.
  *Acceptance:* End-of-day reconciliation report flags any P&L discrepancy > $0.01.

### Integration Tests
- [ ] End-to-end test on demo MT5: place market order, verify fill, close position, verify P&L.
- [ ] FTMO gate stress test: synthetic equity adverse-move forces internal kill correctly; FTMOImminent fires before internal kill.
- [ ] Kill switch test: tripping the switch flattens all positions within one tick; new orders rejected immediately after.
- [ ] News-blackout test: scheduled high-impact event blocks orders in the window; allows orders outside it.

---

## Milestone 5 — First Strategy End-to-End on FTMO Demo

### Strategy Selection
- [ ] **Decide:** Pick first strategy from `Planning.md` Section 5. Default candidate: **#1 FX Cross-Sectional Momentum** (most documented in academic literature, simplest microstructure assumptions, FTMO supports all majors).
  *Acceptance:* Decision logged in `Memory.md` with rationale, including why the strategy is FTMO-compatible (max per-trade loss << internal daily kill, holding period compatible with weekend / Swing constraint, news exposure manageable).

### Phase 1 — Alpha Research (the strategy gets its own folder under `strategies/`)
- [ ] Write `strategies/<name>/HYPOTHESIS.md` — one-line hypothesis, reasoning, expected horizon, references.
- [ ] Define universe filters in `strategies/<name>/config.yaml`.
- [ ] Implement `strategies/<name>/signal.py::compute_signal(data)` — primary signal construction.
- [ ] Run signal half-life analysis in `research/<name>_halflife.ipynb`.

### Phase 2 — Model Development
- [ ] Walk-forward backtest using `backtest/walk_forward.py`.
- [ ] Parameter sensitivity analysis — heatmap of Sharpe vs. ±20% on key parameters.
- [ ] Add secondary confirming signal (per `CLAUDE.md` constraint: no single-signal strategies).
- [ ] Re-run walk-forward with ensemble.

### Phase 3 — Portfolio Construction
- [ ] Implement position sizing (start with fractional Kelly, ¼ Kelly default).
- [ ] Confirm aggregate exposure stays within caps under historical scenarios.

### Phase 4 — Execution & Risk
- [ ] Wire strategy into `execution/router.py`.
- [ ] Define regime filter — when does this strategy go silent? Code it in `signal.py::is_active(state)`.
- [ ] Run on an **FTMO trial / free-demo MT5 account** for at least 14 days.
- [ ] Daily reconciliation: paper P&L vs. backtest expectation given that day's signals.
- [ ] Daily FTMO compliance check: zero internal-kill events, zero FTMOImminent events, zero rule violations in the simulator's replay of the day.

### Promotion Decision
- [ ] After 14 days on FTMO demo, compare paper Sharpe to backtest Sharpe AND verify zero rule violations. Decide: promote to paid Challenge, iterate, or kill.
  *Acceptance:* Decision logged in `Memory.md` with metrics snapshot and FTMO compliance summary.

---

## Milestone 6 — FTMO Challenge (paid evaluation)

This is the first milestone with real money on the line (the Challenge fee).

### Pre-Challenge Checklist
- [ ] Choose Challenge type: 1-Step or 2-Step. Default: 2-Step (more headroom on daily loss). Log decision in Memory.md.
- [ ] Choose account size. Default: $25K tier (€155 fee for 2-Step at $10K, ~€250 at $25K — meaningful but recoverable). Log decision in Memory.md.
- [ ] Choose Standard vs. Swing. Default: Swing if any strategy holds overnight or near news. Log decision in Memory.md.
- [ ] Confirm `FTMOAccountType` config matches purchased Challenge.
- [ ] Run final dry-run on demo account configured identically to the Challenge tier (same starting capital, same rules) for 7 days. Verify zero violations.

### Phase 1 (Challenge)
- [ ] Connect bot to the FTMO Challenge MT5 credentials.
- [ ] Run the bot. Monitor daily.
- [ ] Track daily: distance to daily loss limit, distance to max loss, Best Day ratio (1-Step only), profit progress vs. target.
  *Acceptance:* Phase 1 passes — 10% (or 1-Step target) profit reached without rule violation. **Halt the bot** before Phase 2 begins; review the run before continuing.

### Phase 2 (Verification, 2-Step only)
- [ ] Resume bot on Verification credentials.
- [ ] Strategy parameters frozen — no tweaks between phases. Tweaks would be data-snooping on the Phase 1 result.
- [ ] Run to 5% target.
  *Acceptance:* Phase 2 passes. **Halt and review** before going live on the Funded account.

### Funded Account Onboarding
- [ ] Sign FTMO Funded contract. Confirm rule set for the funded tier (note: funded accounts have some rule changes vs. Challenge — verify against current FTMO docs at onboarding).
- [ ] Update `FTMOAccountType` to `FUNDED_STANDARD` or `FUNDED_SWING`.
- [ ] Run for 30 days at minimum viable per-trade size, then review.

---

## Milestone 7 — Multi-Strategy Portfolio (post-funded)

- [ ] Add second strategy (full Phase 1–4 pipeline, including FTMO sim pass).
- [ ] Add third strategy (full Phase 1–4 pipeline, including FTMO sim pass).
- [ ] Implement `risk/portfolio.py` — aggregates exposure across strategies under one FTMO account; enforces correlated-cluster cap (3% aggregate open risk).
- [ ] Risk budget allocation: equal-vol-contribution by default; risk parity as upgrade.
- [ ] Cross-strategy correlation monitor — alert if rolling 60-day correlation between strategies exceeds 0.5.
- [ ] Joint demo for 2 weeks before activation on the funded account.
  *Note:* Multi-strategy stays on **one** FTMO account. Running the same bot on multiple FTMO accounts is copy trading and forbidden.

---

## Milestone 8 — Production Hardening

- [ ] Watchdog process — restarts main bot on crash, with backoff cap.
- [ ] Heartbeat: bot writes a heartbeat file every 60s; external monitor alerts if stale > 5 min.
- [ ] MT5 disconnect handling: on `terminal_info().connected == False`, halt new entries, attempt reconnect with exponential backoff.
- [ ] Alerting: email or webhook (Discord/Slack) on: kill switch trip, FTMOImminent, MT5 disconnect, daily P&L + FTMO-distance summary, news-blackout block.
- [ ] Runbook in `docs/RUNBOOK.md`: how to start, stop, inspect logs, force flatten, override kill switch, recover from a desynced FTMO state.
- [ ] Dependency security audit (`pip-audit` or equivalent in CI).
- [ ] Disaster recovery: if the bot crashes mid-day with open positions, the recovery procedure must reconstruct FTMO state from `account_info()` and `history_deals_get()` without manual intervention.

---

## Milestone 9 — Scaling and / or Migration Decision

Two paths to evaluate. Decision logged in Memory.md.

### Path A: Scale on FTMO
- [ ] Pursue FTMO Scaling Plan (size-up at consistent profitability).
- [ ] If running multiple FTMO accounts, each runs its OWN bot instance with different strategy parameters (no copy trading).
- [ ] Monthly review of profit splits and payout cadence.

### Path B: Migrate to self-funded (NautilusTrader + Interactive Brokers)
- [ ] Withdraw FTMO profits to fund personal capital runway.
- [ ] Open Interactive Brokers account.
- [ ] Port strategies to NautilusTrader (Rust-native engine, research-to-live parity, no MT5 dependency).
- [ ] Add Databento as data layer if scope expands to CME futures or full order-book microstructure.
- [ ] Retire MT5 stack. Archive repo, start a new one for the Nautilus build.

---

## Backlog (unscoped, parking lot)

These are real ideas but not yet promoted to a milestone. Promote when ready.

- [ ] VWAP slicer (currently only TWAP in M3).
- [ ] Combinatorial Purged CV implementation for ML-based signals.
- [ ] Tick-data strategy stack (separate timeframe class in engine).
- [ ] Multi-broker support (currently MT5-only by mandate).
- [ ] Alternative data integration (e.g. macro release calendar feed).
- [ ] CLI dashboard for live state inspection.
- [ ] Prometheus metrics exporter + Grafana panels (Milestone 6 question).
- [ ] Strategy decay monitor — auto-detects when live Sharpe diverges from backtest beyond a threshold.

---

## Working Notes for Claude Code

- **Never invent a task** — if you find missing scaffolding mid-way through another task, add it here, then decide whether to do it now or defer.
- **Acceptance criteria are non-negotiable.** "It runs" is not done. The criterion in the task is done.
- **Update Memory.md** every time a non-obvious decision is made or a non-obvious bug is fixed. Future-you will need it.
- **Do not skip the BLOCKER tag** — those tasks gate everything downstream.
- **One task at a time.** No half-finished work in `main`.
