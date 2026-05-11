# Planning.md — FTMO MT5 Quant Trading System Architecture

> Architectural plan, milestone roadmap, and current phase. Updated as the project evolves. If you are about to start a piece of work, confirm the current phase here first.

---

## 1. Project Vision

Build a production-grade systematic trading platform on **MetaTrader 5** that ingests market data, generates alpha signals, sizes positions risk-adjusted, executes via MT5's order API, and runs unattended with hard risk controls — purpose-built to **pass FTMO's evaluations and trade FTMO funded capital long-term without rule violations**.

**Why MT5:** FTMO supports MT4, MT5, and cTrader. MT5 is the deployment target because it has the best Python API of the three and the broadest broker / build availability. FTMO is the constraint that locks the engine to MT5; if and when the system migrates to self-funded capital, the engine should move to NautilusTrader on Interactive Brokers (see Memory.md "Stack Decision").

**Non-goals (explicit):** This is not a discretionary tool, not a backtesting library for sale, not a UI product. No GUI. No web dashboard in v1 — log files and CLI reports only. No multi-account copy trading (FTMO forbids it).

---

## 2. System Architecture

### High-Level Component Diagram

```
                ┌──────────────────────────────────────────────┐
                │              Config Layer (YAML)             │
                │  strategies, symbols, risk limits, env vars  │
                └──────────────────┬───────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌──────────────┐          ┌──────────────┐          ┌──────────────────┐
│  Data Layer  │          │ Strategy Eng │          │  Risk Manager    │
│              │          │              │          │                  │
│ MT5 ticks +  │ ───────► │ Signal gen,  │ ───────► │ Pre-trade checks │
│ OHLCV cache, │          │ ensemble,    │          │ position limits, │
│ parquet      │          │ regime filter│          │ DD ladder, kill  │
└──────────────┘          └──────────────┘          └─────────┬────────┘
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │ Execution Engine │
                                                    │                  │
                                                    │ Order routing,   │
                                                    │ TWAP/VWAP slicer,│
                                                    │ retry & errors   │
                                                    └─────────┬────────┘
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │  MT5 Terminal    │
                                                    └──────────────────┘

                Cross-cutting: Logging, Metrics, Backtest Engine
```

### Module Responsibilities

| Module          | Responsibility                                                           | Key Files                                           |
| --------------- | ------------------------------------------------------------------------ | --------------------------------------------------- |
| `data/`         | MT5 data fetch, parquet cache, point-in-time queries                     | `mt5_client.py`, `cache.py`, `symbols.py`           |
| `strategies/`   | One folder per strategy — signal logic, regime filter, params            | `<strategy>/signal.py`, `<strategy>/config.yaml`    |
| `backtest/`     | Walk-forward engine, performance reporting, FTMO-rule simulator          | `engine.py`, `metrics.py`, `walk_forward.py`, `ftmo_sim.py` |
| `execution/`    | Order construction, MT5 routing, slicing, retry logic, reconciliation    | `router.py`, `slicer.py`, `mt5_orders.py`, `reconcile.py` |
| `risk/`         | FTMO limits, internal gates, equity-tick watcher, kill switches          | `ftmo.py`, `gates.py`, `equity_watcher.py`, `kill_switch.py`, `news_blackout.py` |
| `utils/`        | Logging, config loader, time utilities (Prague TZ), math helpers         | `log.py`, `config.py`, `timeutils.py`               |
| `tests/`        | Unit + integration                                                       | mirrors `src/` layout                               |

---

## 3. Technology Stack

| Concern              | Choice                              | Why                                                   |
| -------------------- | ----------------------------------- | ----------------------------------------------------- |
| Language             | Python 3.11+                        | MT5 API is Python; ecosystem for quant is mature      |
| Broker connectivity  | `MetaTrader5` (official package)    | Required — only Python interface to MT5               |
| Data storage         | Parquet via `pyarrow`               | Columnar, compressed, fast for time series            |
| Numerics             | `numpy`, `pandas`, `numba` (hot)    | Standard. Numba only after profiling.                 |
| Stats / ML           | `scipy`, `statsmodels`, `sklearn`   | Statsmodels for econometrics, sklearn for ML signals  |
| Backtest engine      | Custom (built in `backtest/`)       | Off-the-shelf engines hide assumptions; we own them   |
| Config               | YAML via `pydantic`                 | Type-safe, validated, env-aware                       |
| Logging              | `structlog` → JSON                  | Machine-parseable, structured                         |
| Testing              | `pytest`, `hypothesis` for property | Property tests for risk gates and signal math         |
| Scheduling           | `APScheduler` or systemd timers     | TBD — depends on deployment target                    |
| Secrets              | `.env` + `python-dotenv`            | Standard. Never commit credentials.                   |
| Dependency mgmt      | `uv` or `poetry`                    | Pin exact versions; reproducibility is critical       |

---

## 4. Data Strategy

### Sources
- **Primary:** MT5 historical and tick data via `MetaTrader5` package.
- **Secondary (later):** External fundamental / macro data feeds if a strategy requires them.

### Storage
- All MT5 pulls cached to local parquet files keyed by `(symbol, timeframe, date_range)`.
- Tick data stored separately due to volume — daily parquet partitions.
- Cache invalidation: explicit refresh command, never silent.

### Frequencies Supported
- Tick (microstructure strategies)
- M1, M5, M15 (intraday)
- H1, H4 (swing)
- D1 (positional)

Pick frequency from the signal hypothesis, not from convenience.

### Universe Filters (default)
- Average daily volume above strategy-specific floor
- Spread below 5 bps for liquid pairs, strategy-specific otherwise
- No symbols within 24h of contract roll (futures CFDs)
- No symbols flagged by broker as "limit close only" or non-tradeable

---

## 5. Strategy Roster (Planned)

This is the working pipeline. Each strategy gets its own folder under `strategies/` and goes through Phases 1–4 from `CLAUDE.md`. Order is rough priority, not strict sequence.

| #  | Strategy                          | Asset class       | Hypothesis (one line)                                                              | Status      |
| -- | --------------------------------- | ----------------- | ---------------------------------------------------------------------------------- | ----------- |
| 1  | FX Cross-Sectional Momentum       | Major + EM FX     | Trends in FX persist over 1–3 month horizon due to slow capital rebalancing        | Planned     |
| 2  | Index Mean Reversion (overnight)  | Equity index CFDs | Intraday selling pressure overshoots; reverts overnight                            | Planned     |
| 3  | Volatility Risk Premium           | Index options/CFDs| Implied > realized vol on average; harvest the premium with risk controls          | Planned     |
| 4  | Pairs / Stat-Arb                  | Equity CFDs       | Cointegrated pairs revert to spread mean over short horizons                       | Planned     |
| 5  | Microstructure Order Flow         | FX majors         | Tick imbalance predicts short-horizon (seconds-to-minutes) returns                 | Planned     |
| 6  | Macro Carry                       | FX                | Higher-yield currencies outperform lower-yield ex-ante, with regime filter         | Planned     |

Strategies are added to this table as they are scoped. **Before any strategy moves past planning, it must have a written hypothesis doc in its folder.**

---

## 6. Risk Architecture

### Layered Risk Controls (FTMO-aware)

```
Layer 0: FTMO outer limits (hardcoded, never crossed)
         5% daily loss (2-Step) / 3% (1-Step) — equity-based, Prague midnight reset
         10% max loss — static (Challenge) or trailing-up only (Funded Rewards)
         Best Day Rule (1-Step), news windows, copy-trading prohibition

Layer 1: Internal limits (the bot's actual operating box)
         3% / 2% internal daily kill — well below FTMO's lines
         7% internal max kill — well below FTMO's 10%
         Headroom check on every order: simulate worst-case fill, reject if too close

Layer 2: Strategy-level — per-trade risk (0.5%–1%), signal-side filters

Layer 3: Portfolio-level — aggregate open risk, correlation cluster caps, Best Day governor

Layer 4: System-level — equity-tick monitor, heartbeat, broker disconnect, news-blackout gate, kill switch
```

Each layer can independently halt trading. They are not redundant — they catch different failure modes.

### FTMO Limit Enforcement (the most important code in the repo)

The FTMO compliance module (`risk/ftmo.py`) is the single source of truth for what FTMO is currently measuring against the account. It exposes:

- `ftmo_state()` — current daily-loss limit (in account currency), current max-loss limit, distance to each, current Prague day, current Best Day ratio.
- `headroom_check(intended_order)` — given an intended order, simulate worst-case adverse fill and return `(allowed, reason)`. Rejects if breach would put equity within the safety buffer of either limit.
- `daily_reset(now_prague)` — recomputes the day's daily-loss anchor from `account_info().balance` at 00:00 Europe/Prague.
- `equity_tick(now, equity)` — called on every poll; raises `FTMOBreach` if the bot's internal limits are touched (which itself is far from the FTMO line, so this is a soft kill, not a fail).

The module is monitored by an **equity-tick watcher** running on a sub-second poll of `mt5.account_info().equity` — independent of bar-driven strategy logic. The watcher is the only thing standing between a fast adverse move and a failed account.

### Internal Limits (the bot operates here, not at FTMO's edge)
- **Per-trade risk:** 0.5%–1% of initial sim capital. Hard cap at 1%. Default 0.5% on Phase 2 / Funded.
- **Aggregate open risk:** 2% of initial sim capital across all open stops.
- **Correlated cluster cap:** 3% aggregate open risk on any rolling-correlation cluster (>0.6, 60-day window).
- **Internal daily kill:** flatten and halt on −3% (2-Step) or −2% (1-Step) intraday equity.
- **Internal max kill:** full shutdown on −7% from initial sim capital.
- **Best Day governor (1-Step):** throttle/halt new entries when today's closed profit would push the Best Day ratio above 40%.

### Daily Reset Logic
- Day boundary = **00:00 Europe/Prague (CE(S)T)**. The bot uses `zoneinfo.ZoneInfo("Europe/Prague")`, never broker time, never UTC.
- At Prague midnight: snapshot `account_info().balance`, recompute the daily-loss anchor, log the new day's limit, reset the Best Day day-counter.
- Positions held over Prague midnight contribute to the new day's starting equity at the close-of-day mark — be aware of overnight gap risk into the new day's tighter limit.

### News Blackout (standard funded accounts only)
- High-impact economic-calendar feed (e.g. ForexFactory scrape, Trading Economics API, or FTMO's own calendar export) loaded at session start.
- Pre-trade gate rejects opens within ±2 minutes of any high-impact event on traded symbols' currencies/markets.
- Closes inside the window are also blocked unless an emergency stop fires (kill-switch overrides news-blackout — surviving the day matters more than violating the news rule, but flag both in the log).

### Weekend Policy
- Default: flat by Friday 21:00 Europe/Prague unless explicitly running on a Swing account.
- If running on Swing, weekend exposure capped at half the in-week aggregate-risk limit.

---

## 7. Backtesting Architecture

### Engine Design
- Event-driven, bar-by-bar simulation. No vectorized "all-at-once" shortcuts that hide look-ahead.
- Same signal code path runs in backtest and live — strategies expose a `generate_signal(state)` function that doesn't know whether it's historical or real-time.
- Costs modeled: spread, commission, slippage. Slippage default 0.5× spread; configurable per strategy.

### Validation Methodology
- **Walk-forward:** rolling in-sample fit → out-of-sample test, repeated.
- **Combinatorial Purged CV** (López de Prado): for ML-based signals, mandatory.
- **Out-of-sample lockbox:** the most recent 20% of available history is locked. Touched only once per strategy at the very end.

### Reporting Output
- Equity curve PNG.
- Metrics JSON (full set from `CLAUDE.md` Section 6).
- Trade-by-trade CSV.
- Rolling Sharpe + DD plots.

---

## 8. Execution Architecture

### Order Lifecycle
1. Strategy emits signal + intended size.
2. Risk Manager applies pre-trade gates (position cap, daily loss check, DD ladder, kill switch).
3. If approved, Execution Engine constructs `OrderRequest`.
4. Slicer decides on market vs. TWAP/VWAP based on order size relative to recent volume.
5. `mt5.order_send()` with retry logic on retryable errors (requote, off-quotes).
6. Result validated — `TRADE_RETCODE_DONE` only.
7. Position recorded in internal state; logger emits structured event.

### Order Sizing for TWAP/VWAP
- Threshold: orders larger than 1% of average bar volume on the strategy's timeframe → sliced.
- Slice count and pacing tied to estimated participation rate (default cap: 10% of volume).

---

## 9. Deployment Plan

### Environments
- **dev** — local machine, demo MT5 account, full logging, all assertions on.
- **paper** — VPS or dedicated machine, demo MT5 account, production-equivalent config, ≥ 2-week minimum runtime per strategy before live.
- **live** — same machine as paper, swapped to live MT5 account, capital starting at minimum viable size.

### Promotion Criteria (paper → live)
A strategy is promoted to live capital only when **all** are true:
- ≥ 14 calendar days of paper-trade runtime with no engineering changes.
- Realized Sharpe within 0.5 of backtest Sharpe (allowing for the well-known live degradation).
- Zero unexplained execution errors.
- Risk gates verified via at least one synthetic stress test (forced DD breach, simulated disconnect).

---

## 10. Milestone Roadmap

### Milestone 0 — Foundations [CURRENT]
Repo scaffold, CLAUDE.md / Planning.md / Tasks.md / Memory.md, dependency setup, MT5 connection smoke test, logging skeleton, config loader, **Prague-timezone utilities**.

### Milestone 1 — Data Layer
MT5 client wrapper, parquet cache, symbol metadata loader, point-in-time query helpers, unit tests on a frozen sample dataset.

### Milestone 2 — FTMO Compliance Core (gating — blocks all live work)
The single most important module in the repo. `risk/ftmo.py` with full rule-set encoding for each account type (1-Step Challenge, 2-Step Phase 1/2, Funded Standard, Funded Swing, Funded Rewards). Equity-tick watcher polling `account_info().equity` sub-second. Headroom check, daily reset on Prague midnight, Best Day governor, news-blackout gate. Kill switches (internal daily, internal max, FTMO-distance early-warning). Property tests via `hypothesis` proving no order can ever cross an FTMO line.

### Milestone 3 — Backtest Engine v1 with FTMO Simulator
Event-driven engine, cost model, full metrics suite, equity-curve and trade-log outputs, walk-forward harness. **Must include `backtest/ftmo_sim.py` that replays the same FTMO rules as the live module against historical equity curves** — a backtest that would have failed FTMO is not a passing backtest.

### Milestone 4 — Execution Skeleton
MT5 order router with retry logic, `order_check` validation, slicer (TWAP only in v1), reconciliation against `history_deals_get`. Integration tests against demo MT5. Risk gate stress test: simulated DD breach forces internal kill correctly; FTMO-distance early-warning fires before internal kill.

### Milestone 5 — First Strategy End-to-End on FTMO Demo
Pick one strategy (likely FX Cross-Sectional Momentum or Index Overnight Reversion). Take it through all four strategy phases. Run on an FTMO **trial / demo** account for at least 2 weeks. Verify: zero rule violations, expected vs. realized Sharpe within tolerance, all equity-watcher events logged correctly.

### Milestone 6 — FTMO Challenge (real evaluation)
Purchase a 2-Step Challenge at a tier where the per-trade dollar risk is meaningful but the loss is tolerable (start at $10K-$25K tier). Run the bot on Phase 1. After Phase 1 passes, halt and review before Phase 2. After Phase 2, halt and review before going to funded.

### Milestone 7 — Multi-Strategy Portfolio (post-funded)
Add second and third strategies. `risk/portfolio.py` aggregates exposure across strategies under one FTMO account (still one account, no copy trading). Cross-strategy correlation monitor.

### Milestone 8 — Production Hardening
Watchdog process, heartbeat monitoring, automatic restart on broker disconnect, alerting (email/webhook on FTMO-distance warnings, kill switch trips, MT5 disconnects, daily summaries). Runbook documentation. Disaster-recovery procedure.

### Milestone 9 — Scaling and / or Migration Decision
Two paths to evaluate (log decision in Memory.md):
- **Scale on FTMO:** add accounts (separate bot instances, no copy trading), pursue scaling plan to higher capital tiers.
- **Migrate to self-funded:** withdraw FTMO profits as runway, port the bot to NautilusTrader on Interactive Brokers (different engine, different broker, but the strategy IP and risk discipline transfer). MT5 stack retired.

---

## 11. Open Architectural Questions

These are unresolved decisions. Track and resolve as the project progresses. Do not silently pick — surface them in Memory.md when decided.

1. **Scheduler:** APScheduler in-process vs. systemd timers vs. cron. Trade-off: in-process is simpler but couples scheduler lifetime to the bot process.
2. **Multi-strategy concurrency:** single process with thread-per-strategy vs. multi-process with IPC. Lean toward single process for simpler state management; revisit if CPU-bound.
3. **Tick data storage:** parquet daily partitions vs. a time-series DB (kdb+ overkill, DuckDB or QuestDB plausible). Default to parquet; revisit when a tick strategy is in scope.
4. **Walk-forward window sizes:** strategy-dependent; needs convention. Tentative default: 12-month in-sample, 3-month out-of-sample, rolled monthly.
5. **Live monitoring surface:** log tail vs. minimal CLI dashboard vs. Grafana off Prometheus metrics. v1 = log tail; revisit at Milestone 6.

---

## 12. Current Phase

**Milestone 0 — Foundations.** Active.

Next concrete step: see `Tasks.md`.
