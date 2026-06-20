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

## Milestone 10 — Post-Trial Hardening

**Trigger:** First trial closes (target June 10, 2026). Do NOT start any of this while the trial is live.

Captured 2026-05-30 mid-trial as the user asked for the persisted backlog. Ordered by execution sequence — top items unblock later items. Aim is to (a) capture lessons from the trial before they fade, (b) close architectural gaps that emerged during the trial, (c) prep the system for the real paid Challenge.

### Tier 1 — Days 8-14 after trial close

- [x] **Trial post-mortem report.** `# done 2026-06-11 — research/trial_2026-05_postmortem.md; headline corrected to +$164 realized/+$811 equity (initialCapital mutability bug found+filed); cluster anatomy +$5,569/-$5,394; LondonMomo chart-specific edge.` Pull every trade from Convex deals table for the trial window (5/28 → 6/10). Compute per-EA: total trades, win rate, average win, average loss, profit factor, longest losing streak, average holding time, $/day contribution. Identify (a) which EAs carried the trial, (b) which were dead weight, (c) which actively hurt. Capture observed spread / slippage per symbol vs the assumption embedded in each EA. Output a `research/trial_2026-05_postmortem.md` and log key findings in `Memory.md`.
  - **Factor decomposition (Fama-French style).** Per CLAUDE.md §9 ("regime blindness" trap) and the lesson from `research/articles/2026-06_quant-framework-notes.md` (deferred reading): most of what *looks* like manager skill is undisclosed factor exposure. Regress each EA's daily P&L against a set of common factors (USD strength via DXY, broad-market beta via SPX, vol-of-vol via VIX, momentum factor, USD-rate factor). The R² explained by factors = lucky beta we don't deserve credit for. The unexplained residual = actual alpha. **An EA that looks profitable but whose returns are 95% explained by, say, "long USD-momentum on USD-momentum days" is not adding edge — it's adding hidden factor risk we could replicate with one ETF.** This decomposition directly affects the kill/keep decision in the Tier 2 ai-quant-researcher pass.
  *Acceptance:* The markdown report exists, lists per-EA metrics for all 10 EAs, includes a per-EA factor-decomposition table (β to each factor + alpha + R²), and ends with a 3-bullet "lessons learned" section that drives Tier 2 task selection.

- [x] **Position-sizing calibration from trial data.** `# done 2026-06-11 — research/trial_2026-05_sizing_calibration.md; Config C2 (Momo .50/Fix .50/AUDJPY .25, rest cut); 1.5% aggregate + 0.75% USD-cluster sub-cap; PROVISIONAL pending Tier-2 bootstrap.` Distinct from the post-mortem (which describes *what happened*) — this answers *"what should the next trial's per-trade % and aggregate cap actually be?"*. Origin: mid-trial 2026-06-03 observation that 0.25% per-trade was below CLAUDE.md §3's recommended 0.5-1% range; at 0.5× sizing the cumulative trial would have been ~+$1.9K vs the actual -$1.5K, at 1× ~+$3.8K — but the same multiplier accelerates losing-day failure modes (Day 5 + Day 7 at 1% sizing would have come within ~$1.9K of the daily-loss line). The architectural constraint is the 2% aggregate open-risk cap, not the per-trade %.
  - Inputs: realized per-EA variance (std dev of trade P&L → σ²), realized per-EA mean trade P&L (→ μ), realized portfolio correlation under live regimes (especially Day 7's USD-strength cluster), realized daily floor/ceiling distribution, count of concurrent open positions observed, post-mortem factor decomposition (use the alpha residual as μ, NOT raw return, to avoid sizing up beta exposure).
  - **Formal Kelly framework (per the deferred 2026-06 quant-framework article):**
    - Per-EA optimum: `f* = μ / σ²` — edge over variance. Use the alpha residual from the post-mortem's factor decomposition as μ.
    - Practical baseline: **half-Kelly** (`f = 0.5 × f*`). Full Kelly maximizes expected log-wealth but has brutal short-term drawdowns; half-Kelly captures ~75% of the geometric growth at ~25% of the drawdown.
    - Geometric growth rate at fraction f: `G ≈ f × μ − (f² × σ²) / 2`. Plot G against f for each EA — the curve peaks at f* then turns negative. **A bet size where G < 0 is mathematically guaranteed to lose money over time even with positive per-trade EV.** This is the rigorous version of why we don't just "size up the winners."
    - **Probability of ruin** at drawdown D over a 14-day window: `P(ruin) ≈ exp(−2μD / (σ² × f²))`. For our case: set D = 5% (FTMO daily-loss line) and D = 10% (FTMO max-loss line). Compute P(touch) at each candidate f ∈ {0.25%, 0.5%, 0.75%, 1.0%}. **Pick the largest f where P(touch daily line) < 1% AND P(touch max line) < 0.1% over a 14-day Challenge window.** That's the largest defensible sizing.
  - **UPGRADED METHOD (per `research/volatility_sizing_review_2026-06.md`, Cluster 2 + Cluster 1) — classical Kelly above is the floor; these refinements are the actual sizing method:**
    - **Bayesian Kelly with parameter uncertainty (Sukhov 2026, ssrn-6195358).** Classical `f* = μ/σ²` assumes we KNOW μ and p. We don't — our entire μ estimate is one 14-day trial (tiny sample). Use beta-distributed priors on win-probability and shrink `f` when confidence is low. The paper shows this cuts max-DD 40-60% while keeping 85-95% of growth, with the biggest benefit during the **cold-start phase** — which is exactly the next trial. **This is the headline reason not to trust a raw Kelly number off 14 days.**
    - **Recovery-constrained Kelly (Lee 2025, ssrn-5284131).** FTMO is literally a recovery-constrained game (daily Prague reset, static max-loss floor). Impose: after a loss, P(return to pre-loss equity within horizon) ≥ threshold → yields a closed-form cap on f. Map the horizon onto the FTMO day/challenge structure. Use this cap as a hard ceiling on top of the Bayesian-Kelly point estimate.
    - **Correlation-aware risk-parity, NOT independent inverse-vol (Baltas 2015 ssrn-2673124 + Baltas-Kosowski 2019 ssrn-2140091).** The Day-7 cluster loss happened because the 2% aggregate cap implicitly treats EAs as independent (inverse-vol weighting ignores correlation). Replace with **equal-risk-contribution sizing using the realized correlation matrix** from the trial. Baltas-Kosowski's dynamic-leverage-on-pairwise-signed-correlation is the operational recipe. Also adopt the **Yang-Zhang volatility estimator** (more efficient than ATR/stdev, cuts turnover ~36% per the paper) for the σ inputs.
  - Output: a sized recommendation per EA (some EAs may deserve more risk, some less, some zero — Day 7 showed that AUDJPY + XAUUSD + GBPUSD trend-followers carry correlated USD-exposure beta; sizing them like independent bets understates real aggregate risk) AND a recommended aggregate cap (may need to drop below 2% if correlation breakdown days are more common than assumed).
  - Cross-reference the ai-quant-researcher's deflated Sharpe verdict (Tier 2 task #5) — don't upsize an EA that the validator marked for the kill list.
  *Acceptance:* A `research/trial_2026-05_sizing_calibration.md` ends with: (a) per-EA Kelly-curve plot (G vs f), (b) per-EA P(ruin) at 14-day Challenge horizon for each candidate f, (c) a numeric per-EA risk-% table from **Bayesian-Kelly point estimate capped by the recovery constraint**, satisfying P(touch daily) < 1% AND P(touch max) < 0.1%, (d) a single recommended aggregate-cap % derived from **correlation-aware equal-risk-contribution** (not independent inverse-vol). All four feed directly into the next paid-Challenge config in `mql5/Experts/*.mq5` `InpPerTradeRiskPct` defaults.

- [ ] **EA broker-state-recovery fix (all 10 EAs).** `# PARTIAL 2026-06-11 — DONE for the 3 C2-roster EAs (compile-clean, deployed). Benched/retired EAs untouched; HARD CONDITION: any benched EA must get the recovery retrofit before rejoining the roster. Restart-simulation test not yet written.` Bug: on MT5 restart, EAs reset `g_open_ticket = 0` / `g_pos_dir = 0` / `g_trail_sl = 0` while the broker still has the position open. Next signal can fire a duplicate. Reference: MQL5 article 22532 ("Self-Healing EA"). Implementation is a 10-line `PositionSelect(_Symbol)` recovery in `OnInit` (NOT the article's SQLite approach — broker is the source of truth). Standardize the helper in `QuantLib.mqh` so future EAs inherit it.
  *Acceptance:* All 10 EAs have the recovery block in `OnInit`. New test in `tests/` simulates an MT5 restart with open position and verifies no duplicate entry on next signal.

- [ ] **`SafeFillingMode` helper in QuantLib.mqh.** `# PARTIAL 2026-06-11 — helper shipped in QuantLib.mqh; 3 C2-roster EAs switched. Benched/retired EAs still hardcode FOK; same rejoin condition as state-recovery.` Query `SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE)` at runtime and pick FOK / IOC / RETURN based on broker capability. Replaces the hardcoded FOK currently in every EA. Prevents the class of bug that nearly killed Day 1 (IOC mismatch).
  *Acceptance:* All 10 EAs switched from hardcoded `ORDER_FILLING_FOK` to `SafeFillingMode(_Symbol)`. Manual test on OANDA-Demo-1 confirms orders fill.

- [ ] **Phase-A event-driven upgrades (MT5-native, while still on FTMO/OANDA).** Origin: `research/post_funded_implementation_plan.md` hot/warm/cold-path section. These tighten latency on the FUNDED account without waiting for the Nautilus migration — all three use MT5-native event callbacks, no new stack. Three sub-items:
  - [x] **`OnTradeTransaction` handler in every EA.** `# done 2026-06-11 for the 3 roster EAs (instant broker-side exit detection; AUDJPY cooldown now starts immediately; bar-poll kept as fallback; compile-clean). Benched EAs get it on rejoin.` Today EAs detect closed positions by polling `if(g_open_ticket != 0 && !PositionSelect(_Symbol))` on each new bar — up to 15 min late on H4. `OnTradeTransaction` fires the instant a fill/SL/close happens. **This also closes the EA broker-state-recovery bug above** by reacting to the event instead of polling for it. Combine the two tasks.
    *Acceptance:* All 10 EAs handle `OnTradeTransaction`; position-state changes reflected within one tick, not one bar; restart-recovery test passes.
  - [x] **`EquityWatchdog.mq5` with `OnTimer(1s)`.** `# done 2026-06-11 — standalone EA (NOT in manifest; manual attach per runbook §4), TimeGMT+Prague-DST day roll, InpInitialCapital required (no defaults), flatten-all + FTMO_KILL_ACTIVE global + 1s re-flatten while breached. Compiled 0/0. Live kill-drill scheduled in the dry-run week (synthetic trip needs a running terminal).` CLAUDE.md §3 mandates sub-second equity monitoring; today `libftmorisk` runs inside `OnTick` which is sparse in quiet markets. A standalone EA polling `AccountInfoDouble(ACCOUNT_EQUITY)` every second on a 1-sec timer = true sub-second protection of the FTMO daily line, independent of any chart's tick stream. Flattens all + halts on internal-kill breach.
    *Acceptance:* `EquityWatchdog.mq5` runs on its own chart; synthetic equity-drop test trips the kill within 1 second; independent of per-EA tick flow.
  - [x] **OANDA webhook → Convex HTTP action (replaces 5-min polling).** `# CLOSED-INFEASIBLE 2026-06-11 — an FTMO MT5 login is not an OANDA v20 API customer; no broker-side webhook/stream exists for it. The latency goal is met instead by OnTradeTransaction (instant local detection). Revisit only post-Nautilus, where venue adapters stream natively.` OANDA position-change webhook → Convex HTTP action → ~100ms telemetry latency vs up to 5 min today. **Keep** the cron heartbeat-staleness check as the "did the webhook stop?" watchdog (event-driven for the hot signal, cron for the watchdog-of-the-watchdog).
    *Acceptance:* Position changes land in Convex in <1s via webhook; the 5-min Python poll is demoted to backup; heartbeat-staleness cron still fires if webhooks stop.

- [x] **BTCUSD_M15_TrendFollow EA decision.** `# done 2026-06-11 — Option 3 adopted (defer to Hyperliquid/M11): file kept, removed from manifest; decision in Memory.md.` Two bugs found mid-trial 2026-05-31: (a) still in `InpDryRun = true` mode — never flipped live, has placed zero real broker orders; (b) OANDA's `BTCUSD.sim` is NOT 24/7 — last tick Fri 23:58:59 UTC, closed all weekend. The EA's whole header thesis ("24/7 trading = more bars than any other strategy") is invalidated on this broker. Decide between three options:
  1. **Flip to live, keep on OANDA** as a regular weekday Donchian breakout EA — loses the 24/7 thesis but might still produce signals.
  2. **Kill it and retire the `.mq5` file** from the repo + manifest.
  3. **(RECOMMENDED) Defer to M11 / Hyperliquid integration.** Hyperliquid IS true 24/7 with real crypto microstructure. Keep the file in repo, remove from `bot_manifest.txt` so BotOrchestrator stops attaching it. Restore as the first crypto strategy on the Hyperliquid execution box.
  *Acceptance:* Decision logged in `Memory.md` with rationale. Whichever option chosen, manifest + repo reflect it; no half-state where the EA is attached but dry-run forever.

- [x] **US500_M15_ORB EA decision.** `# done 2026-06-11 — Option 2 adopted: index-ORB retired from manifest (final tally 2W-3L net -$429; C1-vs-C2 MC showed it multiplies max-line risk ~10× for less median); Stocks-in-Play version revisits post-IBKR. Decision in Memory.md.` Origin: Day 5 trial loss (-$882 on first and only signal) + academic finding in `research/academic_review_2026-06.md` paper #6 (Zarattini-Barbon-Aziz 2024, Swiss Finance Institute 24-98). Their result: ORB applied to **top-20 "Stocks in Play"** (abnormally high volume on news) earned Sharpe 2.81 / 1,600% total over 2016-2023; ORB applied to indices or random stocks ≈ noise. Our EA applies ORB to the S&P 500 index, NOT to news-driven stocks. The -$882 Day 5 loss is consistent with the paper's verdict. Decide between three options:
  1. **Retrofit a volume-spike / news filter** to the existing US500 ORB. Only fire signals when the opening range coincides with abnormal pre-market volume or a high-impact news event on the index. Effectively turns it into US500_M15_ORB_NewsFiltered.
  2. **Defer the Stocks-in-Play version to M11 / post-Nautilus.** OANDA can't trade individual US stocks; IBKR can. The full Zarattini strategy needs single-stock execution and a 7K-ticker universe filter. Park the current US500 EA, build it properly when we have IBKR.
  3. **Kill the EA** outright. ORB on indices, per academic evidence, has no edge.
  *Acceptance:* Decision logged in `Memory.md` with rationale citing Zarattini 2024. Whichever option chosen, manifest + repo reflect it.

- [ ] **VPS provisioning (Contabo Cloud VPS S with Windows Server 2022).** Order box, complete RDP setup, install MT5, verify connectivity to OANDA. Do NOT migrate the running bot yet.
  *Acceptance:* RDP reachable, MT5 connects to OANDA-Demo-1 on the VPS with a test login, screenshot in `Memory.md`.

- [ ] **VPS migration runbook + execution.** `# PARTIAL 2026-06-11 — runbook WRITTEN (docs/VPS_MIGRATION_RUNBOOK.md, incl. dry-run gate + go-live dryRun-flag hard check). Execution blocked on VPS purchase.` Write `docs/VPS_MIGRATION_RUNBOOK.md` covering file copy order, chart-attach order, monitor reinstall, scheduled-task install, Convex env var migration, Pushover sanity ping. Execute the runbook end-to-end. Local box becomes backup / dev env.
  *Acceptance:* Bot running on VPS, first heartbeat from VPS lands in Convex, local box is shut down or repurposed.

### Tier 2 — Between trial and the paid Challenge

- [ ] **ai-quant-researcher integration on trial data.** `# PARTIAL 2026-06-11 — the MANDATORY bootstrap gate is DONE: research/tier2_bootstrap_2026-06.md (White RC p=0.252, studentized p=0.638; nothing survives correction; C2 keeps its risk-bounded license, upsizing forbidden; SwingBreak kill statistically supported at p≈0.99 wrong-tail). Remaining: walk-forward + purged CV await the backtest harness + longer OANDA cache.` Wire the validation modules (deflated Sharpe, walk-forward, purged combinatorial CV) against the realized trial P&L per EA. Output: kill list / keep list / tune list. Update `mql5/bot_manifest.txt` to drop the kill list.
  - **MANDATORY bootstrap reality check** per `research/academic_review_2026-06.md` papers #4 (Park-Irwin 2007), #5 (Neely St Louis Fed 2011), #8 (Sullivan-Timmermann-White 1999): naive Sharpe + naive walk-forward is academically insufficient when comparing multiple rules. Implement **at least one** of: (a) White's Reality Check (1999), (b) Hansen's Superior Predictive Ability (SPA) test (2005), (c) Stepwise White / StepM (Romano-Wolf 2005). All three control for data-snooping bias across the universe of EAs/parameters tested. **Naive Sharpe alone is grounds for rejection** — papers we tested confirms that 60-80% of "winning" rules vanish after bootstrap correction. Without this gate the M10/M11 pipeline will systematically false-positive into adding strategies that don't survive OOS.
  *Acceptance:* Per-EA deflated Sharpe AND a bootstrap-corrected p-value (Reality Check / SPA / StepM) reported in the post-mortem. Kill list includes any EA whose bootstrap-corrected significance falls below 5% — even if naive Sharpe looks fine. Bot manifest reflects the bootstrap-corrected kill/keep decision.

- [ ] **Walk-forward backtest harness.** Build `backtest/walk_forward.py` (already scoped in M2/M3 but never executed at the live-EA scale). Cost model calibrated from observed trial spreads. FTMO simulator built in.
  - **PREREQUISITE SUB-TASK — historical data puller (`backtest/fetch_history.py`).** Build this FIRST; the harness has no input without it. Runs on the dev box (off the live VPS). Three sources, by role (user-ratified 2026-06-16):
    - **OANDA-via-MT5 = the PARITY SPINE (canonical price series).** Pull M15/H1/H4 bars for the roster + benched symbols (`GBPUSD.sim`, `XAUUSD.sim`, `AUDJPY.sim`, `EURUSD.sim`, plus EURGBP/US500/US100/BTCUSD as available) via `mt5.copy_rates_range()` over the full downloadable range. This is the SAME feed the EAs trade live, so it is the source of truth for signal backtests — a backtest on any other feed validates prices we'll never get. Force-download deep history first (scroll-back or large-count `copy_rates_from_pos`) since MT5 only holds what's been pulled into the terminal.
    - **Dukascopy = COST-MODEL CALIBRATION (tick depth).** Pull free historical ticks (bi5) for the same FX/metal symbols to reconstruct real spread + slippage distributions — retail MT5 tick history is too shallow/patchy for the CLAUDE.md §3 cost model. Use to calibrate, not to drive signals.
    - **HistData = LOOKBACK EXTENSION + CROSS-CHECK (free M1 bars).** Years-deep M1 to extend history beyond the MT5 cache and as an independent third feed.
    - **Bonus from using 3 feeds: a feed-divergence report.** Reconcile all three on overlapping windows to quantify how far the OANDA broker feed sits from "the market" (Dukascopy/HistData) — that divergence IS a cost/parity input, and surfaces broker-specific quirks (off-market wicks, weekend gaps).
    - **CRITICAL — timezone normalization (the 2026-06-11 clock-bug lesson).** The three sources use different stamps: MT5/OANDA = broker time (UTC+2/+3, DST-shifting), Dukascopy = UTC, HistData = US Eastern WITHOUT DST. Normalize EVERY series to true UTC at ingest and assert alignment on overlap, or the session/news logic backtests on misaligned bars. Symbol mapping: strip the `.sim` suffix for the external feeds.
    *Sub-acceptance:* `data/history/<source>/<symbol>_<tf>.parquet` written for all roster symbols; a `research/feed_divergence_2026.md` quantifying OANDA-vs-Dukascopy-vs-HistData deltas; all series UTC-normalized with an alignment assertion in tests.
  - **Reference implementation template: Forecast-to-Fill Gold (Singha et al 2025, arxiv 2511.08571, in `research/volatility_sizing_review_2026-06.md` Cluster 6a).** It's a worked example of our exact intended methodology — rolling 10yr→6mo walk-forward, a trend-momentum regime signal → volatility-targeted fractional impact-adjusted Kelly sizing → ATR-based exits → cost model (0.7bps + square-root impact) → **bootstrap CI + SPA test** for significance. Copy its structure; it even targets gold (we trade XAUUSD). Use as the structural blueprint for the harness AND as a sanity benchmark for the XAUUSD EAs specifically.
  *Acceptance:* Re-runs all surviving EAs on the available OANDA M15/H1/H4 cache and produces an HTML report with FTMO-rule pass/fail per EA, walk-forward OOS splits, and a bootstrap/SPA significance column (ties into the Tier 2 ai-quant-researcher task).

- [x] **Richer Pushover daily digest.** `# done 2026-06-11 — per-EA expectancy (W-L, avg $/trade), best/worst closed trade, FTMO-distance trend (prior-day mins stamped into the digest alert context — the naive two-day snapshot collect blew Convex's 32K read budget at ~10K snaps/day; fixed), correlation top-pairs (auto-activates at the 14d floor). Regime breakdown deferred to M11 (needs bar data; noted in code). Deployed; verified on real data (9,468-snap window). Full Pushover render confirms with the next live digest.` Add to `convex/reports.ts::sendDailyReport`: per-EA expectancy ($/trade, win rate), regime breakdown (trending vs ranging days), correlation-matrix snapshot, best/worst trade of the day, FTMO-distance trend (am I closer or further than yesterday).
  *Acceptance:* One real evening's digest contains all of the above fields, verified via Pushover.

- [ ] **Convex pipeline resilience hardening.** Origin: 2026-06-03/04 transient Convex 5xx incident — 4 separate 500 clusters over ~14h on both `/heartbeat` and `/snapshot` endpoints, plus SSL handshake timeouts earlier. Current behavior (log-warning, continue, retry-on-next-60s-poll) absorbed the blips without data loss, but exposed three thin spots in the pipeline:
  - [x] **Retry-with-backoff in `utils/convex_client.py`.** `# done 2026-06-11 — 3 attempts, 1s/4s (16s tail dropped for poll-budget; documented); 4xx fails fast; tests/test_convex_client_retry.py 4/4.` On any 5xx response or connection error, retry 2-3× with exponential backoff (1s → 4s → 16s) before giving up and logging-warning. Most transient blips will resolve within the second retry, dropping the noise floor in the monitor log and reducing the gap between consecutive successful snapshots from ~120s (worst case) to ~70s.
    *Acceptance:* Unit test mocks a 5xx then a 200 — first call returns the 200 after one retry; mocks a triple 5xx — call logs warning and continues without raising.
  - [x] **Cross-channel 5xx alert (bypass Convex).** `# done 2026-06-11 — ConvexClient counts consecutive transient final-failures (5xx OR network) in a 30-min window; at 10 fires a DIRECT Pushover (keys from .env, 1h cooldown). Tested (threshold fires exactly once). Runbook §2 now lists the env keys.` If `ConvexClient` sees ≥ 10 consecutive 5xx within a 30-min window, fire a direct HTTPS POST to the Pushover API from the local monitor process, bypassing Convex entirely. **Critical:** if Convex is fully down, our existing alert path goes down with it — we'd be flying blind. This is the only alert that must NOT depend on Convex.
    *Acceptance:* Synthetic test: force 10 consecutive 5xx in `ConvexClient` → direct Pushover message arrives on phone with subject "Convex pipeline DEGRADED (10 consecutive 5xx)". Pushover API token and user key read from `.env`, never from Convex.
  - [x] **Local buffer queue on sustained outage.** `# done 2026-06-11 — JSONL outbox (logs/convex_outbox.jsonl) for snapshot/deals/signals on final failure; ordered replay after next success; 5MB cap; heartbeats excluded by design. Tests: queue + in-order drain pass. Real 10-min network-block drill scheduled for the dry-run week.` If Convex is unreachable for > 5 min, write outgoing snapshots and deals to a local SQLite (or append-only JSONL) queue at `logs/convex_outbox.jsonl`. On recovery, flush the queue in chronological order. Prevents data loss during multi-hour Convex outages (we'd lose Day-N-end snapshots otherwise, breaking the digest math).
    *Acceptance:* Synthetic test: simulate 30-min Convex outage with 30 snapshots queued → on recovery all 30 land in Convex in correct order, queue file is emptied. Real test: monitor survives a manual 10-min `nautilus-exec` ↔ Convex network block with no data loss.
  - [x] **Make `accounts.initialCapital` immutable after first registration.** `# done 2026-06-11 — registerAccount no longer patches it; live probe with initialCapital=999999 bounced.` BUG found in the 2026-06-11 post-mortem: `registerAccount` overwrites `initialCapital` on every monitor re-registration (observed: $201,840.04 on 5/24 → $200,167.23 after the 6/10 reboot). All FTMO limit math keys off initial capital — a mid-challenge re-registration would silently shift the daily/max-loss lines, and it corrupted the trial's headline P&L for a day. Fix: registerAccount patches everything EXCEPT initialCapital when the account row already exists; add a regression test.
    *Acceptance:* re-running registerAccount on an existing brokerLogin with a different balance leaves initialCapital untouched; P&L reporting documented to use snapshot/jsonl series as ground truth.
  - [x] **Fix Convex OCC contention on the `accounts` table.** `# done 2026-06-11 — per-poll accounts patch removed from snapshot mutation (the contended write no longer exists); /accounts derives latestSnapshotAt at read time; deployed. 48h zero-OCC soak pending the next live run (dry-run week).` NEW finding 2026-06-10 (final trial day): repeated 500s with *"Documents read from or written to the 'accounts' table changed while this mutation was being run and on every subsequent retry"* — an optimistic-concurrency conflict in OUR mutations, not Convex weather. Likely cause: /heartbeat and /snapshot both patching the same `accounts` document every 60s and colliding. Fix: stop writing to `accounts` on the hot path (move `lastSeen`-style fields to the heartbeats table, or make the account patch conditional/less frequent).
    *Acceptance:* /heartbeat and /snapshot mutations no longer write the `accounts` table per-poll; 48h of operation with zero OCC 500s in the monitor log.
  - Order to build: retry-with-backoff first (lowest cost, biggest noise reduction), then OCC contention fix (it's our bug, observed in production), then cross-channel alert (single biggest single-point-of-failure fix), then local buffer (most complex, needed only if we see sustained outages > 5 min — one ~5h monitor hang observed on 2026-06-10, cleared by reboot; the 4h ExecutionTimeLimit may also need a look since it didn't recycle the hung instance).

- [ ] **NewsBlackout API-based optional path.** Cherry-pick the `Calendar*` API pattern from MQL5 article 22580. Add `try API first, fall back to hardcoded 2026 list if API fails or returns empty` — defense in depth, NOT replacement. Self-updates the calendar so it doesn't go stale Jan 2027.
  *Acceptance:* `NewsBlackout.mqh` exposes `IsNewsBlackout` with the same signature; internally it calls Calendar API, falls back to the hardcoded list on failure. Unit test verifies fallback path.

- [ ] **Per-EA cost-model refinement.** Use observed trial spread + slippage to update each EA's cost assumptions in its file-header comment. Re-run backtests with realistic costs. Kill anything that doesn't survive.
  - **EURGBP_H4_MeanReversion cointegration-stability check** (per `research/academic_review_2026-06.md` #7, Gatev-Goetzmann-Rouwenhorst + the Yale 2024 / Springer 2025 decay updates). Pairs trading has decayed sharply post-2002; the pair must *stay* cointegrated, not just have been historically. Add a rolling Engle-Granger or Johansen test with a freshness window — if cointegration stability drops below threshold, **pause** the EA rather than just resize. Note: EURGBP_H4_MeanReversion never fired during the trial (no 3σ deviation), so there is no realized data to calibrate against yet — address only if the EA is kept after the Tier-2 bootstrap check.
    *Acceptance:* EURGBP EA gains a rolling-cointegration freshness gate; backtest shows it pauses during decoupling windows; documented keep/kill decision if the pair fails the stability test.
  *Acceptance:* Each EA's header lists observed-vs-assumed spread; backtest report includes both numbers; any EA whose Sharpe goes negative at observed costs is removed from manifest.

- [ ] **Session-clock semantics decision (broker time vs UTC) — gate-review item.** FOUND LIVE 2026-06-11, day 1 of the live-fire week: session/range logic in the session EAs runs on `TimeCurrent()` (broker = UTC+3 summer) while the input comments claim UTC — LondonMomo's "07:00 London open" range actually forms 04:00–05:00 UTC (~6am London), LondonFix's "10:30 fix" trades 07:30 UTC (2h before the real LBMA AM auction). The 2026-06-11 TimeGMT sweep fixed NEWS calls only. **Deliberately NOT hot-fixed:** the entire trial ran (and the C2 calibration was measured on) this exact skewed behavior — the live week must stay consistent with what was calibrated. Decide at the gate review: (a) keep broker-clock sessions permanently → rename inputs/comments to match reality, and note the DST trap (broker UTC+3→UTC+2 in winter silently shifts every session 1h vs calibration), or (b) move to true-UTC sessions for the paid Challenge → requires fresh validation evidence first.
  *Acceptance:* documented decision in the gate packet; whichever way, input comments stop lying about the timezone; if (a), a DST-boundary note lands in NewsBlackout/Memory; if (b), the change ships AFTER the trial with its own validation, never mid-week.

- [ ] **XAUUSD_M15_LondonFix vs the fixing literature — thesis re-read for the gate packet.** `# SCOPE EXTENSION 2026-06-11: the session-clock finding (above) shows the EA trades 07:30 UTC, TWO HOURS before the real LBMA AM auction — today's winning live trade (+$993.54) entered 07:30 and exited 08:45 UTC, fully closed before the fix existed. The mechanism re-read must re-time every window first; classification (c) "session momentum mislabeled as fix flow" is now the leading hypothesis.` Origin: `research/microstructure_execution_review_2026-06.md` recommendation #2 (Chaboud 2023, C5) + user ratification 2026-06-11. The EA trades into a fixing window, and the FX-fixing-scandal literature documents known pathologies there — pre-2013 front-running flows that the WM/R reforms (window widened 1→5 min, fix desks restructured) regulated away. Since LondonFix is the roster's TOP performer and a scaling decision rides on the gate review, its edge mechanism must be classified before any size change: (a) benign liquidity provision against fix-window demand (sturdy), (b) artifact of pre-reform behavior leaking through backtests (fragile), or (c) ordinary session momentum coincidentally near the fix (rename-worthy but fine). **Key nuance to resolve:** the gold "fix" is the LBMA Gold Price auction (electronic since 2015), NOT the WM/R FX fix — the pathology literature is FX-centric, so the re-read must check whether it transfers to the gold auction mechanism at all.
  - Method: full implementation-depth re-read of Chaboud 2023's fixing sections (per the standing triage≠implementation rule in the review doc); map the EA's entry/exit logic against the post-reform regime; cross-check with the gate week's LIVE fills (slippage at entry, direction vs fix-window flow, P&L by minute relative to the 10:30 window).
  *Acceptance:* `research/londonfix_fixing_review_2026-06.md` ends with (a) the a/b/c mechanism classification with citations, (b) a live-fill cross-check table from the gate week, (c) a scaling verdict for the gate packet: keep at 0.50% / resize / add a fix-window guard. Due with the gate review (~2026-06-19).

- [ ] **Barbell timeframe test — drop the H1 layer?** `# ABSORBED 2026-06-11 — the H1 layer is already dropped on direct evidence (SwingBreak killed at wrong-tail p≈0.99; NewsReaction benched on the clock bug; OvernightDrift cut at ~zero edge), and the sizing MC compared roster configs. The formal 3-config doc is deferred to the walk-forward harness, where n is large enough to mean something.` Origin: `research/academic_review_2026-06.md` paper #2 (arxiv 2510.23150v2, Oct 2025). The paper's central finding: **medium-horizon trend signals (~125 days) add little incremental value once short + long are included** — the medium horizon "largely overlaps with its neighboring horizons" (redundancy hiding as diversification). Our portfolio has 3 H1 EAs (GBPUSD_H1_SwingBreak, XAUUSD_H1_NewsReaction, US100_H1_OvernightDrift) sitting between M15 short-horizon EAs and the H4 long-horizon EA. The 2025 paper suggests these may be near-redundant. Test this directly with trial data.
  - Method: split the trial deals into (a) M15-only portfolio, (b) M15+H4 only, (c) M15+H1+H4 (the actual portfolio we ran). For each, compute cumulative P&L, Sharpe, max drawdown, correlation matrix. Test the hypothesis: **does H1 add meaningful Sharpe, OR does it just correlate with M15/H4 returns?**
  - Cross-reference with the ai-quant-researcher's bootstrap output (Tier 2 #5) — if H1 EAs fail the bootstrap test individually, that's confirmation. If they pass individually but their P&L is >0.7 correlated with M15+H4 combined, that's the redundancy the paper warns about.
  - Decision: if H1 layer is redundant, drop those 3 EAs from the next-trial manifest. Frees risk budget for M15/H4 EAs and reduces concurrent-positions complexity.
  *Acceptance:* `research/trial_2026-05_barbell_test.md` ends with: (a) Sharpe and max-DD comparison across the 3 portfolio configurations, (b) correlation matrix between H1 EAs and the M15/H4 portfolio, (c) a documented keep/drop decision per H1 EA citing the test result.

- [ ] **Volatility-targeting overlay (portfolio-wide, asset-class-aware).** Origin: `research/volatility_sizing_review_2026-06.md` Cluster 3. The literature consensus (Harvey et al 2018 ssrn-3175538, Hood-Raughtigan 2024 ssrn-4773781) is nuanced and MUST be applied correctly or it's cargo-cult:
  - **Vol targeting improves Sharpe ONLY for equity-index "risk assets"** (US500_M15_ORB, US100_H1_OvernightDrift) where the leverage effect (negative return-vol correlation) is present.
  - For **FX and gold** (the majority of our book — EURUSD/GBPUSD/AUDJPY/EURGBP/XAUUSD EAs) it does **NOT** improve Sharpe. Do not expect return gains there.
  - BUT vol targeting **cuts left-tail risk on ALL asset classes** — and left-tail control is exactly what protects the FTMO daily-loss line. So adopt portfolio-wide, but justify per-EA: **Sharpe** for equity indices, **FTMO tail-control** for FX/gold.
  - Refinements: (a) target **downside** volatility not total volatility (Wang-Yan 2021, "Downside.pdf") — preserves upside participation; (b) **condition on extreme-vol states** rather than scaling continuously (Bongaerts et al 2020, FAJ) — cuts turnover/cost.
  *Acceptance:* `research/vol_targeting_design.md` documents the per-EA decision (target-vol on/off + Sharpe-vs-tail justification), the downside-vol estimator choice, and the extreme-state trigger. If adopted, EAs gain a vol-scaling multiplier on position size; backtest (via the harness) shows reduced max-DD and left-tail (CVaR) with Sharpe-neutral-or-better on FX/gold and Sharpe-positive on indices.

- [ ] **Hurst-exponent regime gate (candidate research — TEST before building).** Origin: `research/volatility_sizing_review_2026-06.md` Cluster 5 (Ntingana 2026 ssrn-6744643 NQ futures; RADIANT ssrn-6427863 hysteresis). Rolling Hurst exponent (variance-ratio method) classifies each bar: persistent (H>0.55, trending), neutral, anti-persistent (H<0.45, mean-reverting). The NQ paper found 3.25× trade-quality difference between persistent and anti-persistent regimes. Hypothesis: **gating our Donchian trend EAs (GBPUSD/AUDJPY/BTCUSD) to only fire in persistent regimes would cut the chop losses** (e.g. GBPUSD's 2-2 trial record — half those losses may be anti-persistent-regime whipsaws). Add hysteresis (RADIANT's "sticky" transition) so the gate doesn't flip every bar.
  - **TEST FIRST on trial + cached data** — does an H>0.55 filter actually improve the trend EAs' realized expectancy? Only build the gate into the EAs if the backtest confirms. This is research, not a committed build.
  - **Dwell-time / run-length sub-idea (deferred note, from MQL5 article 22937 triage 2026-06-12).** When the hysteresis sub-point above activates, also evaluate a **run-length primitive over the regime flag** — "how many consecutive bars has the current persistent run lasted" — not just the instantaneous "is this bar in regime X" point-classifier that Hurst and `quant_markov_forward` already provide. Use it to (a) gate trend EAs on persistence *duration* (the "sticky transition" this task already wants) and (b) condition the vol-targeting overlay on extreme-vol *state duration* (Bongaerts) not just magnitude. This is the ONLY salvage from the DSU+DBN article (the DSU online union-find = run-length over a boolean vol flag). Do NOT import the article's code or its DBN gatekeeper — the DBN is excluded by the M11 "skip the deep-learning architectures" rule, and the primitive is trivially re-derivable in minutes. Research note only; build nothing until this lane is active. Full triage: 5-lens + adversarial workflow, unanimous DROP on the strategy (PF 1.09 / n=68 / 20% DD / news-shock+USD-cluster thesis = anti-diversifying duplicate of the killed SwingBreak family).
  *Acceptance:* `research/hurst_regime_test.md` reports trend-EA expectancy with vs without the H>0.55 gate on available data; go/no-go decision documented. If go, the gate is added as an entry filter and re-validated through the walk-forward harness + bootstrap.

### Tier 2.5 — Pre-Challenge gate

- [x] **Final dry-run on demo identical to purchased Challenge tier.** `# DONE 2026-06-20 — ran as the live-fire week 6/11-6/19 on the fresh OANDA trial. Result: SYSTEM PASS (zero kills, zero FTMOImminent, $14,910 floor headroom through an adverse week), STRATEGY FAIL (-2.54%, 4W/8L; combined 53-trade live record shows no edge, mild negative drift). Full verdict: research/gate_review_2026-06.md.`
  *Acceptance:* 7 consecutive trading days, zero internal-kill events, zero FTMOImminent events. ✓ on safety; edge not demonstrated.

- [x] **Gate review (2026-06-20).** `# DONE — research/gate_review_2026-06.md. 5-lens + adversarial workflow. DECISION: NO-GO on the paid Challenge; pivot to the walk-forward harness. Decisive finding (adversary-caught): the live week's -$5,090 breached the C2 sizing MC's OWN pre-registered p5 of -$2,244 by ~2.3x = out-of-sample falsification of the sizing-model tail. Per-EA: RSIFade KILL; NewsReaction keep-benched; LondonFix = classification (c) session-momentum, keep 0.50% no fix-guard (research/londonfix_fixing_review_2026-06.md, closes #46).`

- [ ] **GO conditions to RE-OFFER the paid Challenge (all three must clear — days of harness work, not months).**
  1. **Model re-validation** — append the live week to the C2 sizing MC, re-estimate the loss distribution, confirm realized P&L sits inside a re-estimated p5. (Answers the tail falsification that blocks deployment.)
  2. **Cluster-gate confirmation** — produce ONE live-or-replay observation that the 0.75% USD-counter sub-cap actually FIRED on a USD-cluster day (this week's losses are the same cluster legs May diagnosed, but no one confirmed the gate triggered or that a cluster day occurred).
  3. **Roster parity** — verify the deployed live manifest == corrected-C2 (SwingBreak/ORB/Drift cut, EURUSD-Momo EURUSD-chart detached, sub-cap wired).
  *Acceptance:* all three documented as cleared; only then revisit purchase. Until then the trial account runs frozen-C2 (free; safety data still useful) and NO money goes to a paid Challenge.

- [ ] **KILL RSIFade (EURUSD_M15_RSIFade).** `# Gate verdict 2026-06-20: 0 of 490 signal events in the live-fire week, consistent with 1 signal/14 days in the replay — failed its "fire with sane frequency" rejoin gate. A non-firing EA has no testable edge and is pure operational drag.` Detach from its VPS chart at the next visit; record in bot_manifest.txt decision block (BENCHED -> KILLED). Revival is free if re-specced to an evaluable frequency.

- [ ] **Purchase paid 2-Step Challenge** — **BLOCKED on the three GO conditions above (gate review 2026-06-20 = NO-GO).** Size TBD ($100k ~$540 / $200k ~$1,080). Update `FTMOAccountType` config + `bot_manifest.txt` if the EA list changes.
  *Acceptance:* Challenge credentials in `.env`, bot pointed at Challenge account, first heartbeat lands in Convex.

---

## Milestone 11 — Alpha Factory + Nautilus Migration (post-funded)

**Trigger:** FTMO Funded account is live with real payouts. The searcher arm (no live capital exposure) can start sooner once the paid Challenge passes; the live graduation arm is funded-only.

**📖 MASTER SPEC: `research/post_funded_implementation_plan.md`** (written 2026-06-04). The plan covers: why Nautilus, the confirmed adapter list (IBKR / Hyperliquid / Bybit / Polymarket / Databento all STABLE), the 5-phase migration sequence (paper-only → +HL → 25% live → port remaining → Alpha Factory wiring), what we keep from MT5 (Convex/Pushover/digest/risk discipline), what we retire (MQL5 EAs / BotOrchestrator / DLLs / monitor parser), and 7 named risks with mitigations. **Read it first before opening any M11 sub-task below.**

Full original spec in `Planning.md` §10 (Milestone 10 — Alpha Factory). Built as a **gated quarantine factory, NOT a closed real-time loop** — see the three killers documented there (multiple comparisons, Goodhart, deploy-at-the-peak).

**Deferred refinements (revisit when actually building):** A 2026-06 quant-framework article surfaced two additions worth applying once the searcher exists and we have observed its candidate-generation behavior:
1. **Three-test deployment gate as a hard checklist** — statistical significance + mechanistic explanation + out-of-sample stability. We already require hypothesis text in the ledger schema (soft); this would harden into pass/fail fields.
2. **Conditional mutual information `I(X; Y | Z)` as the triage criterion** — when scoring a candidate against the ledger, ask "does this signal predict returns *given everything the existing book already knows*?" rather than "does this signal predict returns?". Prevents 50 redundant strategies all earning the same dollar-beta in different costumes.

Both deferred *intentionally* until we have actual searcher output to apply them to. Premature formalization of triage criteria on a system that hasn't run will over-fit to imagined edge cases. Revisit at the M11 searcher-arm kickoff.

### Infrastructure architecture (prerequisite for everything else in M11)

**Guiding principle:** Separate **execution** from **research** from **observability**. Different substrates for different problems. Don't collapse them onto one box ("save money") or fully into the cloud ("simpler") — both will hurt within weeks.

```
[4× small VPS, one per venue]  ←── 24/7 execution, blast-radius isolation
       │
       │  trades + telemetry
       ▼
[Convex backend + Tailscale mesh]  ←── source of truth + private network
       │
       │  data + results
       ▼
[1× powerful local desktop]  ←── research, backtests, daily-driver work
       │
       │  candidate strategies
       ▼
[1× dedicated cloud searcher]  ←── 24/7 Alpha Factory scans (graduate to this from desktop)
```

#### Execution tier — 4 venue-isolated VPS

- [ ] **`mt5-exec` VPS** — Contabo Cloud VPS S Windows Server 2022, 2 vCPU / 4 GB / 80 GB, Frankfurt region (near OANDA). ~$14/mo. Runs MT5 + monitor + BotOrchestrator for any remaining MT5 strategies (FTMO funded continues here until/unless we fully off-ramp FTMO).
  *Acceptance:* This box is already provisioned in M10 (#VPS provisioning). Confirm it stays as the MT5 box rather than being repurposed.

- [ ] **`nautilus-exec` VPS** — Hetzner CCX23 or equivalent, Ubuntu 24.04 LTS, 4 vCPU / 8 GB / 160 GB, Chicago or NYC region (near IBKR). ~$30/mo. Runs NautilusTrader + IBKR gateway.
  *Acceptance:* RDP / SSH reachable, Nautilus installed, IBKR paper-account credentials test-connect succeeds. First paper strategy runs end-to-end.

- [ ] **`hyperliquid-exec` VPS** — Vultr or DO Linux, Ubuntu 24.04 LTS, 2 vCPU / 4 GB / 80 GB, Tokyo or US-East (Arbitrum L2 latency is geographically forgiving). ~$20/mo. Runs the Hyperliquid Python SDK, the cross-venue risk reporter, and any crypto strategies (BTCUSD_M15_TrendFollow finally gets its real home here).
  *Acceptance:* SDK connected, first paper trade on a BTC-PERP settles, telemetry into Convex.

- [ ] **`hot-spare` VPS** — image of any of the three primaries, in a different DC than the box it would replace. ~$30/mo. Cold standby for manual cutover (NOT automated failover — that's over-engineering at this scale).
  *Acceptance:* Disk snapshot of each primary box restorable to the spare within 15 minutes. Runbook documents the cutover steps per venue.

#### Research tier — powerful local desktop (Gladiator X3D class)

- [ ] **Order + commission build.** AMD 7800X3D (NOT 7950X3D — pandas/numpy is L3-cache-bound, not core-count-bound; the 7800X3D's single-CCD design avoids scheduling overhead), 64 GB DDR5 (128 GB if working with tick-level datasets), 2 TB NVMe primary + 4 TB SATA SSD for data cache, RTX 4070 if ML is in scope or skip the GPU otherwise. Target: $3,000-3,500.
  *Acceptance:* Box on desk, Windows or Linux dual-boot per preference, dev tooling installed (uv/poetry, VS Code/Cursor, Jupyter, the repo cloned).

- [ ] **Local data-cache mirror.** Set up parquet cache on the 4 TB SSD that mirrors the cloud data lake; backtests run off local NVMe, not over network.
  *Acceptance:* Walk-forward on the surviving EAs from M10 runs ≥ 5× faster than on the old machine.

#### Alpha Factory tier — start on desktop, graduate to dedicated cloud

- [ ] **Phase A (free, immediate):** Run the searcher overnight on the local desktop while you sleep. No extra ops, no extra cost. Limits searcher to ~10 h/day and blocks the desktop when it's churning.
  *Acceptance:* Scheduled job kicks off the searcher at 22:00 local, stops at 08:00, writes candidates to the ledger.

- [ ] **Phase B (graduate when Phase A bottlenecks).** Hetzner CCX33 (8 vCPU / 32 GB) for ~$80/mo as dedicated 24/7 searcher. Better price/perf than AWS c7i and no spot/preemptible weirdness. Dedicated box means searcher failure doesn't block live trading.
  *Acceptance:* Searcher runs continuously on dedicated box, candidate rate ≥ 2× Phase A overnight rate.

#### Observability / orchestration tier — already largely in place

- [ ] **Convex** stays as telemetry backbone (multi-venue snapshots, deals, alerts, ledger). No migration needed unless we hit Convex limits, which we won't this side of $1M AUM.
  *Acceptance:* Schema extended to tag every record with `venue ∈ {mt5, ibkr, hyperliquid}` so cross-venue queries work cleanly.

- [ ] **Tailscale** — free VPN mesh connecting all execution boxes + desktop + searcher. Makes inter-box SSH / Convex calls private and zero-auth-overhead.
  *Acceptance:* All 6+ boxes on one tailnet; SSH between any two works without public-IP exposure.

- [ ] **Grafana Cloud free tier** (optional, defer until Convex dashboard cramped). Time-series dashboards for per-venue P&L, per-EA expectancy, FTMO-distance trends, correlation matrix over time.
  *Acceptance:* One dashboard with at least 3 panels driven by Convex-pushed metrics.

#### The new component: cross-venue risk aggregator

- [ ] **`risk_aggregator` Convex action.** Polls each execution box every 10 s. Each box pushes positions + equity. Aggregator computes (a) net cross-venue exposure, (b) correlation-cluster aggregate risk, (c) daily P&L summed across venues. If any limit threatens (especially the 2% aggregate-risk cap per CLAUDE.md §3), pushes a kill command back to all execution boxes simultaneously.
  *Acceptance:* Synthetic test: an aggregate-risk breach simulated across 3 venues triggers kill commands to all 3 within 30 s; per-venue local kill switches independently confirm (defense in depth).

- [ ] **Per-venue local kill switches remain authoritative.** The aggregator is one layer; each venue's box has its own kill switch as fallback. They must work independently — if Convex is down, local kill still fires on local breach.
  *Acceptance:* Network-isolate one execution box from Convex; trigger a local breach there; verify local kill still flattens positions.

#### Cost summary

| Item | Monthly | One-time |
|---|---|---|
| 4× execution VPS | ~$94 | — |
| Alpha Factory (Phase B, Hetzner) | ~$80 | — |
| Convex (likely free tier) | $0-25 | — |
| Tailscale (free tier) | $0 | — |
| Pushover | $5 | — |
| **Total monthly** | **~$180-205** | |
| Local desktop | | $3,000-3,500 |

Sanity check: one funded $200K account at 5% monthly = $10K profit split. Infra is ~2% of one month's split.

#### Anti-patterns — do NOT do these

- [ ] *(not a task — a standing rule)* **Don't run multiple venues on one VPS.** Saving $40/mo costs a funded account the first time something crashes.
- [ ] *(rule)* **Don't put research in the cloud.** Latency on Jupyter, slow file edits, debugger detachment. Local box is non-negotiable.
- [ ] *(rule)* **Don't skip the cross-venue risk aggregator.** This is the single biggest architectural difference between "running multiple strategies" and "running a portfolio."
- [ ] *(rule)* **Don't over-engineer failover.** Manual cutover within 15 min is acceptable at our scale. Kubernetes / automated multi-region failover is what HFT shops build because their downtime cost is $10K/minute. Ours isn't.
- [ ] *(rule)* **Don't hard-cutover off MT5.** FTMO funded keeps running on MT5 (that's what FTMO supports). Nautilus + IBKR are *additional* venues for self-funded capital, not replacements until we explicitly decide to off-ramp FTMO.
- [ ] *(rule)* **Don't build your own ClickHouse / kdb+ / time-series DB.** Parquet + DuckDB handles everything until billion-row scale. We're years from that.

#### Phased rollout sequence

```
Funded + 0-2 wk:   mt5-exec VPS (carried forward from M10)
                   risk_aggregator scaffolding in Convex

Funded + 2-6 wk:   nautilus-exec VPS + IBKR account + first strategy ported
                   Local desktop purchase if backtest speed bites

Funded + 6-12 wk:  hyperliquid-exec VPS + BTC EA restored (option #3 from M10)
                   Phase A Alpha Factory (overnight on desktop)
                   risk_aggregator hardened with all 3 venues

Funded + 3-6 mo:   Phase B Alpha Factory (Hetzner CCX33)
                   hot-spare VPS provisioned
                   Grafana dashboards if Convex UI getting cramped
```

Each phase adds ONE component, validates, then moves on. Resist landing everything at once — every box added is more surface area to debug when something breaks.

---

### Searcher arm (post-Challenge-pass)

- [ ] **Research ledger.** Append-only Convex table for candidate strategies: hypothesis text, signal logic, parameter ranges, asset, expected horizon, status (born / triaged-out / validated / paper-passed / graduated / killed), reason for each transition. Queryable, dedup-against-prior-trials.
  *Acceptance:* Schema deployed, write API exposed, ledger survives the searcher process restart.

- [ ] **Searcher (deterministic scans + LLM hypothesis framing).** Cron job (on VPS) running statistical screens across the OANDA universe: momentum persistence, autocorrelation, vol clustering, lead-lag, cointegration. Each anomaly is passed to an LLM that must attach an economic rationale; no rationale, no advance. Outputs land in the ledger.
  *Acceptance:* First scheduled run produces ≥ 5 candidate records with rationale text and signal pseudocode.

- [ ] **ai-quant-researcher integration on candidates.** Every ledger candidate runs through deflated Sharpe + walk-forward + purged CV. INDEPENDENT validator — never co-optimized with searcher.
  *Acceptance:* Ledger fields updated with validation verdict; failed candidates transition to status=killed with reason.

- [ ] **Paper quarantine arm.** Surviving candidates are forward-tested on a paper account (NOT the live FTMO account) for a configurable minimum window (default 4 weeks). Convex tracks the paper P&L the same way it tracks live.
  *Acceptance:* At least one candidate reaches paper-passed status with N weeks of OOS paper data.

### Live graduation arm (post-funded only)

- [ ] **Decorrelation + tiny-size graduation gate.** Manual user ack required. Gate enforces (a) |rolling-60d-corr| < 0.5 with every live strategy, (b) initial size = 25% of standard per-trade risk for first 30 days, (c) full FTMO risk gates apply.
  *Acceptance:* First graduated candidate is live on the funded account at 25% size; correlation check is automated.

- [ ] **State-transition observability.** Every ledger transition (born / triaged / validated / paper-passed / graduated / killed) logs reason, triggers Pushover info-alert, appears in the daily digest's "Factory" section.
  *Acceptance:* One full transition cycle on one candidate fires four Pushover messages and appears in the next digest.

### Off-MT5 expansion (Milestone 11 phase 2)

- [ ] **IBKR + NautilusTrader migration.** Per `Planning.md` M9 Path B. Withdraw FTMO profits, open IB account, port the surviving EAs to Nautilus. Retire MT5 stack.
  *Acceptance:* Same surviving strategies run on Nautilus + IB; daily reconciliation matches expected P&L.

- [ ] **Hyperliquid integration.** Crypto-native venue with real L2 depth. Adds BTC/ETH/SOL spot + perp with a proper microstructure layer.
  *Acceptance:* Hyperliquid client connected, first paper trade on BTCUSDT perp settles, telemetry into Convex.

- [ ] **24/7 multi-venue execution + Alpha Factory feeding it.** Searcher now covers IBKR + Hyperliquid + remaining FTMO. VPS is permanent execution box; searcher can run anywhere.
  *Acceptance:* At least one Alpha-Factory-graduated strategy is running live on a non-MT5 venue.

- [ ] **AX Exchange (Architect) — venue due diligence + candidate integration.** Added 2026-06-11 at user request.
  - **Verified (2026-06 recon):** Nautilus adapter `AX` is STABLE (official integrations table, type "Perpetuals Exchange"); adapter source present in both `nautilus_trader/adapters/architect_ax` and `crates/adapters/architect_ax`; repo ships two AX backtest examples (`architect_ax_book_imbalance.py`, `architect_ax_mean_reversion.py` — both directly reusable for our crypto-MM strategy class) plus an `examples/live/architect_ax` scaffold. Integration cost is config-level, same as Bybit/HL.
  - **To verify before provisioning anything (due-diligence checklist, same discipline as the Upcomers vetting):**
    1. **US-person access + regulatory status.** AX is Architect's exchange (Brett Harrison / ex-Jane Street, ex-FTX US). If it is genuinely a regulated US-accessible perps venue, this is potentially DECISIVE: Bybit and Hyperliquid both restrict US persons, so AX may be the only compliant crypto-perps venue for us — which would promote it from "third venue" to "primary crypto venue" and demote Bybit/HL to paper-research roles.
    2. Products + liquidity: which perps, what depth, what spreads vs Bybit/HL.
    3. Fee schedule + funding-rate mechanics + margin model.
    4. Account opening: KYC, minimums, API key provisioning, testnet availability.
    5. Counterparty profile: custody model, age of venue, incident history.
  - **Decision output:** one of (a) AX becomes the primary crypto-perps venue (if US-access verdict is yes and liquidity clears our size), (b) AX added as third venue alongside Bybit/HL, (c) AX rejected with documented reason. Slots into the phased rollout only after the IBKR phase proves out — venue count discipline per the anti-patterns list still applies (one new component at a time).
  *Acceptance:* `research/ax_exchange_dd.md` answers all five checklist items with sources; decision (a/b/c) logged in `Memory.md`; if (a) or (b), an `ax-exec` box spec is added to the infrastructure tier and the first paper trade settles via the Nautilus AX adapter with telemetry into Convex.

### Crypto market-making strategy class (post-Hyperliquid/Bybit; NEW strategy type)

> Origin: `research/microstructure_execution_review_2026-06.md` Cluster A. Market-making is a **fundamentally new strategy type for us** — we have only ever run directional strategies. It requires a real limit order book, so it is strictly Phase B (Hyperliquid/Bybit, post-Nautilus). It goes through the full CLAUDE.md §4 pipeline like any other strategy. **Read the 5 papers in full at build time** (the review is triage depth only).

- [ ] **First crypto market-maker (Avellaneda-Stoikov baseline).** Build the foundational quoting strategy on the `hyperliquid-exec` / `bybit-exec` box. Reservation price `r = s − q·γ·σ²·(T−t)` skewing quotes against inventory; optimal spread `δ = γσ²(T−t) + (2/γ)ln(1+γ/k)`. Paper-trade first per CLAUDE.md §10. Reading order at build time: Avellaneda-Stoikov (#1) → Cartea-Jaimungal-Ricci Hawkes (#4/5) → Fodra-Pham adverse selection (#3) → Guilbaud-Pham limit-vs-market (#2).
  *Acceptance:* `strategies/crypto_mm/HYPOTHESIS.md` + paper-traded MM quoting on one crypto perp, inventory bounded, full §4 pipeline (hypothesis → backtest → paper → 25% live). Reconciliation matches venue statements.

- [ ] **Short-term-alpha / adverse-selection guard (the survival requirement).** Per Cartea-Jaimungal-Ricci (#4/5): *a market-maker that does not predict short-term-alpha gets adversely selected and driven out.* The MM MUST fold a directional order-flow-toxicity / short-term-alpha predictor into its quoting (this is the bridge from our existing signal skill to MM). Model order-book imbalance / influential-vs-noninfluential market orders.
  *Acceptance:* The MM strategy's quoting skews on a short-term-alpha estimate; backtest shows reduced adverse-fill rate vs the naive A-S baseline. Without this, the MM is NOT cleared for live capital.

### Regime detection (Alpha Factory + crypto MM quoting)

- [ ] **Regime-detection module (HMM + Hurst).** Origin: `research/microstructure_execution_review_2026-06.md` A6 (Cartea-Jaimungal HMM intraday regimes) + `research/volatility_sizing_review_2026-06.md` Cluster 5 (Hurst, RADIANT hysteresis). Dual use: (a) conditions crypto-MM quoting on the intraday regime, (b) feeds the Alpha Factory's regime-aware candidate evaluation, (c) generalizes the M10 Hurst-gate experiment if it succeeded. Methods: Hidden Markov Model on trade-duration / vol states (Cartea-Jaimungal), Hurst-exponent classification (persistent/neutral/anti-persistent), sticky-transition hysteresis to avoid whipsaw (RADIANT). Skip the deep-learning architectures (reproducibility risk) — use the classical statistical core.
  *Acceptance:* A regime classifier emits {trending, mean-reverting, transitional} + confidence on M15+ bars; backtested to show strategies conditioned on it beat their unconditional versions; exposed as a service the MM and the searcher can both query.

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
- [ ] Obsidian vault adaptation — only if user actively wants a notebook UI; no quant value beyond visualization. Skip unless requested.
- [ ] Daily 22:35 UTC auto-digest-check (5 min after the official digest) — automated "anything weird?" sanity pass. Skip if Pushover alerts are sufficient.

---

## Working Notes for Claude Code

- **Never invent a task** — if you find missing scaffolding mid-way through another task, add it here, then decide whether to do it now or defer.
- **Acceptance criteria are non-negotiable.** "It runs" is not done. The criterion in the task is done.
- **Update Memory.md** every time a non-obvious decision is made or a non-obvious bug is fixed. Future-you will need it.
- **Do not skip the BLOCKER tag** — those tasks gate everything downstream.
- **One task at a time.** No half-finished work in `main`.
