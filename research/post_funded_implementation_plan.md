# Post-Funded Implementation Plan — Nautilus + Multi-Venue Migration

> Created: 2026-06-04 mid-trial. Combines: NautilusTrader research (scrape of nautilustrader.io + adapters docs), the M11 infrastructure spec already in Tasks.md, the M11 Alpha Factory spec, the multi-venue VPS architecture, and the cross-venue risk aggregator design.
>
> **Trigger to execute:** FTMO Funded account is live + first profit payout received.
>
> **Not before:** the paid 2-step Challenge passes, the M10 post-trial hardening is complete, and there is at least one month of stable funded operation on the current MT5 stack.

---

## Core decision: NautilusTrader becomes the unified engine

### Why Nautilus (defensible reasons)

1. **Research-to-live parity** — the single highest-value architectural property. The same Python strategy code runs in backtest, paper, and live. **This eliminates the entire class of "backtest assumed X, live does Y" bugs** that have cost us this trial — the GBPUSD ORDER_FILLING_IOC → FOK bug, the EA broker-state-recovery bug, the BTCUSD dry-run-never-flipped bug. MT5 does NOT provide this; we wrote separate Python monitors + MQL5 EAs that drift out of sync, and we paid the price four times in this trial alone.

2. **Multi-venue native** — modular adapters mean adding Hyperliquid + Bybit + IBKR + Polymarket is *configuration*, not new engine code. With MT5 we're broker-locked. Nautilus's `INTERACTIVE_BROKERS`, `HYPERLIQUID`, `BYBIT`, `POLYMARKET` adapters are all marked STABLE as of 2026-06-04 (confirmed via official docs scrape).

3. **Asset-class agnostic** — single engine handles equities, futures, options, FX, crypto spot, crypto perps, prediction markets, even tokenized RWA. Our portfolio already spans 4 asset classes; supporting all in one engine eliminates polyglot complexity.

4. **Rust core, Python edge** — microsecond execution where it matters (matching, risk gates) while keeping Python for strategy logic (where our MQL5 EAs port cleanly via line-by-line refactor). Nautilus claims 5M rows/sec for backtest replay, vs our current Convex query at ~25 deals/sec.

5. **Event sourcing / deterministic replay** — every market event, order event, time event flows through a durable log. We can replay any past session bit-for-bit. **This is exactly the substrate the ai-quant-researcher's bootstrap reality check needs** (per Sullivan-Timmermann-White 1999, paper #8 in `research/academic_review_2026-06.md`). Today our ai-quant-researcher would have to reconstruct state from Convex snapshots; with Nautilus, event replay is first-class.

6. **Maturity signals** — v1.227.0 (active versioning, 16-day-old release at time of research), 23,000+ GitHub stars, 1.3M+ PyPI downloads, 5,000+ Discord members, commercial backer (Nautech Systems Pty Ltd, ABN88 609 589 237, Australia), SLSA Build L3 supply-chain attestation. Not vaporware; not abandonware.

### Why "stay on MT5" is the wrong long-term answer

MT5 is appropriate for the current FTMO Phase 1 trial (one venue, one asset class to focus). Post-funded:
- We need **IBKR** for self-funded FX/equities (FTMO via OANDA is a different relationship and capital pool)
- We need a **real crypto exchange** (OANDA's `BTCUSD.sim` isn't 24/7 — proven mid-trial 2026-05-31)
- We need **event replay** for the ai-quant-researcher bootstrap pipeline
- We want to **escape MQL5** (write strategies in Python, with proper testing, CI, type-checking)

MT5 + 4 venues = 4 different integration paths, 4 different SDKs, 4 different state machines. Nautilus + 4 venues = same Python code, 4 adapter configs.

---

## Local source recon (2026-06-11, post-trial — repo cloned and verified)

> Shallow clone at `C:\Users\saisolomon\nautilus_trader` (source version 1.229.0-dev; PyPI latest 1.228.0). Findings that adjust the plan:

- **Python requirement: `>=3.12,<3.15`.** Our box (and the ftmo-bot venv) runs **3.11** → Nautilus will NOT install into any current environment. Local exploration requires installing Python 3.12 or 3.13 first and creating a separate venv. **Action wired into M11 Phase 1: the nautilus-exec VPS AND the local research box both provision Python 3.13.**
- **Native Windows wheels EXIST** (cp312/cp313/cp314 win_amd64 on PyPI) — local research/backtests on the Windows desktop work natively, **no WSL required**. (The execution VPS stays Ubuntu per the original plan.)
- **All three target adapters confirmed in source** (`nautilus_trader/adapters/`): `interactive_brokers` (plus a Rust-backed `interactive_brokers_pyo3` variant), `bybit`, `hyperliquid` — plus `sandbox` (paper-trade against live data; useful for the Alpha Factory quarantine arm) and `_template` (for any custom adapter).
- **Porting references located:**
  - `examples/backtest/crypto_ema_cross_ethusdt_trailing_stop.py` — structurally near-identical to our Donchian trend EAs (signal + trailing stop, no fixed TP). **The Phase-1 porting template.**
  - `examples/backtest/example_01…08+` — numbered tutorial series (custom CSV bars → clock/timers → bar aggregation → data catalog → portfolio → cache → indicators). The on-ramp, in order.
  - `examples/live/{bybit,hyperliquid,interactive_brokers,interactive_brokers_v2}/` — per-venue live scaffolds for Phase 1-2.
  - `examples/backtest/bitmex_grid_market_maker.py` + `crypto_orderbook_imbalance.py` — starting points for the M11 crypto-MM strategy class.

---

## Confirmed Nautilus venue adapters (scraped 2026-06-04)

| Venue | Status | Type | Our intended use |
|---|---|---|---|
| **Interactive Brokers** | STABLE | Brokerage (multi-venue) | **Primary self-funded FX/indices/equities** |
| **Hyperliquid** | STABLE | Crypto DEX (on-chain orderbook on HyperCore) | **Primary 24/7 crypto** — finally a real home for BTCUSD_M15_TrendFollow |
| **Bybit** | STABLE | Crypto CEX | **Alternative/parallel crypto** — deeper liquidity, but CEX counterparty risk (post-Feb-2025 hack — we documented this concern in the Upcomers analysis) |
| Polymarket | STABLE | Prediction market DEX | Optional: prediction-market strategies if we ever build them |
| Databento | STABLE | Institutional data provider | Optional: high-quality data for the Alpha Factory searcher |
| Binance | STABLE | Crypto CEX | Alternative if Bybit/HL underperform |
| Coinbase | BETA | Crypto CEX | Skip until STABLE |
| Betfair | STABLE | Sports betting exchange | Skip — different game |
| Tardis | STABLE | Crypto data | Optional |
| OKX / Kraken / dYdX / BitMEX / Deribit | STABLE | Various crypto | Available if needed |

**Implication:** the M11 multi-venue architecture we specced in Tasks.md is buildable today on Nautilus with zero adapter-development work. We pick venues, write configs, ship.

---

## Target architecture (how Nautilus integrates with what we already have)

```
[Local Gladiator X3D desktop]                    [Cloud / VPS tier]
=========================================         ==============================
- Nautilus research + backtest                    - nautilus-exec VPS (Hetzner CCX23)
- Jupyter notebook strategy dev                     ↳ runs Nautilus LIVE engine
- Alpha Factory searcher (overnight cron)           ↳ adapters: IBKR + HL + Bybit
- Local data cache (Parquet)                        ↳ single process, single config
- ai-quant-researcher validation                    ↳ event sourcing → S3/R2 archive
- Convex queries for telemetry
                                                  - Convex backend (UNCHANGED!)
                                                    ↳ accounts, snapshots, deals
                                                    ↳ alerts, eaSignals
                                                    ↳ cross-venue risk aggregator (NEW)
                                                    ↳ daily digest cron
                                                    ↳ Pushover alerts

                                                  - mt5-exec VPS (during transition)
                                                    ↳ legacy FTMO MT5 stack
                                                    ↳ retired after Phase 4

                                                  - hot-spare VPS (cold standby)
                                                
[Pushover on phone]
- daily digests, critical alerts
```

**Key insight:** Convex stays as our observability backbone. We don't rebuild observability when moving to Nautilus — we just point Nautilus's event-sourced log to push events to Convex. Our existing schema (accounts, snapshots, deals, alerts, eaSignals) maps directly to Nautilus's event taxonomy.

---

## Architecture: hot / warm / cold path layering (the scheduling paradigm)

The single most important architectural principle for the funded-account era: **don't pick one paradigm for everything — pick the right paradigm per tempo of work.** Cron is correct for some things, catastrophic for others. Event-driven is the same.

```
HOT PATH (microseconds – seconds)         | Engine: Nautilus event bus
─────────────────────────────────────────  | Pattern: Actor model, no polling
- Market data ticks                       | Substrate: In-process Rust
- Order placement / cancel / fill         |
- Position state updates                  |
- Strategy signal generation              |
- Local risk gates (per-EA)               |

WARM PATH (seconds – minutes)             | Engine: Cross-process event bus
─────────────────────────────────────────  | Pattern: Pub/sub stream
- Cross-venue risk aggregation            | Substrate: NATS (recommended)
- Reconciliation between venues           |            or Redis Streams
- Telemetry forwarding to Convex          |
- Strategy ↔ risk-engine RPC              |

COLD PATH (hours – days)                  | Engine: Cron + durable execution
─────────────────────────────────────────  | Pattern: Scheduled batch
- Daily P&L reports                       | Substrate: Convex crons
- Weekly summaries                        |            +  Temporal/Inngest for
- Tax/regulatory batch jobs               |               multi-step workflows
- Database snapshots, backups             |
- Long-running EOD reconciliation         |
```

**Cron is correct for the cold path.** Don't event-drive a daily digest (Convex's daily-report cron is the right shape). Don't cron-poll a position update (5-min polling adds latency for nothing). The migration plan honors this: most existing Convex crons (heartbeat-staleness, daily-report, correlation-monitor) stay as crons; the polling-based parts (5-min Python monitor, hourly git push) get replaced by event-driven equivalents.

### Pre-Nautilus interim upgrades (FTMO funded, still on MT5)
> **Wired into Tasks.md M10 Tier 1 (2026-06-08)** as "Phase-A event-driven upgrades" — the three sub-items below are now committed tasks, not just plan text.

While we're still on MT5 + OANDA with real funded capital but **before** Nautilus migration begins, three pragmatic event-driven upgrades that don't require ripping out the stack:

1. **MT5 `OnTradeTransaction` event handler in every EA.** MQL5 has native event callbacks beyond `OnTick`: `OnTradeTransaction` fires the moment a trade event happens (order placed, filled, position closed, SL triggered). Today our EAs detect closed positions via polling `if(g_open_ticket != 0 && !PositionSelect(_Symbol))` on each new bar — can be 15 min late on H4. With `OnTradeTransaction`, state recovery is instant. This also closes the EA broker-state-recovery bug (M10 task) by reacting to the event instead of polling for it.

2. **Dedicated `EquityWatchdog.mq5` EA with `OnTimer(1s)`.** CLAUDE.md §3 mandates sub-second equity monitoring; today `libftmorisk.dll` runs inside OnTick which is sparse during quiet markets. A standalone EA running `OnTimer(1)` polls `AccountInfoDouble(ACCOUNT_EQUITY)` every second independent of any chart's tick stream — true sub-second protection of the FTMO daily line.

3. **OANDA webhook → Convex HTTP action.** OANDA supports position-change webhooks. Convex has native HTTP actions. Replace the 5-min Python polling monitor with a webhook listener — position changes land in Convex in ~100ms instead of up to 5 min. **Keep the cron heartbeat-staleness check** as the "did webhook stop?" detector. (Belt and suspenders: event-driven for the hot signal, cron for the watchdog-of-the-watchdog.)

These three changes buy us tighter latency in the highest-stakes phase (real funded capital, legacy stack) without forcing the Nautilus migration before we're ready.

### Post-Nautilus layered tooling (M11 Phase 1+)

Once Nautilus migration begins, the architecture by layer:

**Hot path (FREE with the Nautilus migration):**
- Built-in event bus (Rust, in-process, nanosecond resolution)
- Native WebSocket adapters for IBKR, Hyperliquid, Bybit, Polymarket
- Actor-style strategy isolation with supervision (each Strategy is a separate component; one crashing doesn't take down the others — replaces BotOrchestrator's manual EA-reattach polling)
- Event sourcing — every event durably logged for replay

**Warm path (build when 2nd venue goes live):**
- **NATS** — recommended for cross-venue message bus. Lightweight (~5MB RSS), sub-millisecond pub/sub, JetStream for durability, single binary deploy. Production-grade (Stripe, Mastercard, GE use it).
- Alternative: **Redis Streams** if Redis is already in the stack.
- **Don't use Kafka** at our scale — overkill, ops burden is real.
- Pattern: each venue's Nautilus instance publishes position events to NATS subject `risk.position.{venue}`. The cross-venue risk aggregator subscribes to `risk.position.>` (wildcard, all venues) and emits `risk.command.kill.{venue}` if aggregate-risk breached. Typical round-trip latency: 10-50ms across geographic VPS — much faster than any cron, much simpler than custom RPC.

**Continuous risk computation (build when >5 strategies live):**
- **Materialize** or **RisingWave** — streaming SQL databases maintaining always-fresh materialized views. Query like `SELECT SUM(notional) FROM positions WHERE last_update > now() - INTERVAL '1 second'` is continuously up-to-date with millisecond latency.
- Simpler alternative for our scale: hand-rolled Rust subscriber on NATS. Lower ops burden, full control. Pick when complexity-vs-control trade-off becomes real.

**Durable workflows (build when first multi-step process exists):**
- **Temporal** or **Inngest** — durable execution platforms. Express things cron can't: "place order → wait for fill → update Convex → notify Pushover; on any step failure retry with backoff; escalate after 1 hour."
- Inngest free tier covers expected volumes through the first year of funded operation.
- Use cases: capital reallocation across venues, periodic rebalancing, multi-step margin moves, end-of-month profit-split calculation with retries.

**Time-series with continuous queries (build when Alpha Factory searcher is live):**
- **QuestDB** or **TimescaleDB** — ingest every tick, query in real-time, materialized views for rolling indicators.
- Replaces "compute correlation nightly via cron" with "correlation is a continuous view, always current."
- Only worth building once the Alpha Factory generates enough metrics that Convex's query model starts to strain — likely 3-6 months into M11.

**Cold path (stays as Convex crons, correctly):**
- Daily digest 22:30 UTC ✓
- Weekly P&L summary ✓
- Monthly profit-split calculation ✓
- Database cold backup ✓
- Tax-relevant aggregations ✓
- Heartbeat-staleness check ✓ (the watchdog of the watchdog)

### Anti-patterns specific to event-driven post-funded

Each of these has blown real money for real quant operations. Captured here so future-me doesn't repeat them:

1. **Kafka for a 1-person quant op.** Hammer for a problem you don't have. NATS does the same job with 1/100th the ops burden.
2. **Microservices per strategy.** Each strategy is a Nautilus Actor in one process. Don't split into "5 services calling each other over HTTP" — that's a distributed monolith with all the latency and none of the reliability.
3. **Event sourcing without snapshots.** Nautilus does snapshot+compaction for you. If you build your own event-sourced system, plan for snapshot/compaction from day 1 or replays will take hours when the log grows past a few GB.
4. **"Exactly once" delivery promises.** They don't exist over a network. Build idempotent consumers instead and stop chasing the impossible.
5. **Custom message broker.** Don't. Use NATS or Redis. The 200-line Python pubsub you'll write in an afternoon will eat your weekends for months.
6. **Polling Convex from Nautilus.** Wrong direction. Convex subscribes to Nautilus events, not the reverse. Trade engine is the source of truth; observability layer is downstream.
7. **Building it all at once.** Add NATS only when 2nd venue goes live. Add Materialize only when streaming-SQL questions actually arise. Add Temporal only when the first multi-step durable workflow appears. Building infrastructure ahead of the pain it solves is the most expensive mistake at this stage.

### Sequencing of event-driven upgrades

```
Pre-Nautilus (FTMO funded, still on MT5):
  1. OnTradeTransaction handler in all EAs (fast fill detection)
  2. EquityWatchdog.mq5 with OnTimer(1s) (sub-second FTMO-line protection)
  3. OANDA webhook → Convex HTTP action (replaces 5-min Python polling)

M11 Phase 1-2 (Nautilus paper-only, 1 venue):
  4. Nautilus event bus as hot path           [FREE with migration]
  5. WebSocket adapters per venue             [FREE with migration]

M11 Phase 3 (first live venue + 2nd venue):
  6. NATS cross-venue bus deployed
  7. Cross-venue risk aggregator subscribes to NATS, fires kill commands as events

M11 Phase 4-5 (multi-venue + Alpha Factory):
  8. Streaming risk aggregator (Materialize OR hand-rolled Rust on NATS)
  9. Temporal/Inngest for durable multi-step workflows
  10. QuestDB/TimescaleDB for Alpha Factory metrics

What stays as cron throughout (correctly):
  - Daily/weekly/monthly reports
  - Backups
  - Tax/regulatory batch
  - Heartbeat-staleness check (the watchdog of the watchdog)
```

### Honest verdict on event-driven complexity

The temptation post-funded is to immediately build a sophisticated streaming-everything stack. **Resist.** The single highest-leverage upgrade is the Nautilus migration itself — it gives event-driven hot path for free, replaces the 5-min polling monitor, and eliminates the need to write our own cross-venue risk aggregator in raw Python.

The other tools (NATS, Materialize, Temporal) are real upgrades but only earn their complexity once specific pain points have emerged. Migrate to Nautilus first, run it for 30+ days, see what genuinely breaks the cron model, then add NATS/Materialize/Temporal for the seams that actually leaked. **Building the infrastructure before you know which seams will leak is the most expensive architectural mistake at this stage.**

---

## Migration sequence: MT5 → Nautilus

**Not a hard cutover.** Parallel operation for 4-6 weeks minimum before retiring MT5. Each phase has its own paper period and acceptance criteria.

### Phase 0 — Prerequisites (already specced in M10)
- VPS provisioned (Contabo Cloud VPS S Windows for MT5) ✓ M10 task
- Local Gladiator X3D desktop with Python/Rust dev env
- ai-quant-researcher integrated, factor decomposition done on trial data ✓ M10 #1 + #5 enhanced
- Trial post-mortem complete, EA kill list applied
- Position-sizing calibration done with Kelly framework ✓ M10 #2

**Acceptance:** all M10 Tier 1 + Tier 2 items closed. No half-finished post-mortem work going into the migration.

### Phase 1 — Nautilus paper-only on IBKR (Weeks 1-2 post-funded)
- Provision second VPS: **Hetzner CCX23**, Ubuntu 24.04 LTS, 4 vCPU / 8 GB, Chicago region (low-latency to IBKR US data centers)
- Install Nautilus v1.227+ via `pip install -U nautilus_trader`
- Install IBKR Trader Workstation (TWS) + ibapi Python module
- Configure Nautilus IBKR adapter pointing to an IBKR PAPER account
- Port ONE surviving EA from MQL5 → Python Nautilus Strategy class
- Run Nautilus paper alongside live MT5 FTMO funded; **the two should generate signals at the same bars with the same prices.** Any divergence = port bug.

**Acceptance:** Nautilus paper signal matches MQL5 signal on the same EA for **5 consecutive trading days** with zero divergence > 1 tick. If they diverge, fix the Python port until they match.

### Phase 2 — Add Hyperliquid for 24/7 crypto (Weeks 3-4)
- Add Hyperliquid adapter to existing nautilus-exec VPS (same single process)
- Port BTCUSD_M15_TrendFollow from MQL5 → Python (the EA that NEVER fired real trades on OANDA due to broker weekend closure)
- Paper trade BTC perp 24/7
- Confirm signals fire over weekends (the entire reason for picking Hyperliquid over OANDA)

**Acceptance:** 7 consecutive 24-hour cycles of clean BTC paper trades, including 2 weekend cycles, no missed signals during weekend hours.

### Phase 3 — Live small-size on IBKR (Weeks 5-6)
- Flip the ported EA(s) from paper to live IBKR with **25% of standard sizing** (per CLAUDE.md §10: "Doubt about a deployment? Paper trade for at least two weeks before any live capital." and "Doubt about risk? Cut size in half.")
- FTMO funded account **continues running in parallel on MT5** — do not flip everything at once
- Daily reconciliation: Nautilus P&L vs IBKR statement vs Convex telemetry
- **Implement the cross-venue risk aggregator** (already specced in Tasks.md M11): Convex action polls each execution box every 10s, aggregates positions + equity, fires kill command to all venues if aggregate-risk cap breached

**Acceptance:** 14 consecutive days live on IBKR with zero reconciliation discrepancies > $1, zero unexpected positions, zero failed kill-switch drills.

### Phase 4 — Port remaining EAs, scale Nautilus, retire MT5 (Months 2-3)
- Port each surviving EA from MQL5 → Python Nautilus
- Each port goes: paper (1 week) → 25% live (2 weeks) → full size
- Once all EAs ported AND running stable on Nautilus, **decommission MT5 stack**
- FTMO funded account decision: either keep on MT5 indefinitely (one less thing to migrate, FTMO is a separate capital pool anyway) OR port to IBKR-equivalent if it makes economic sense (depends on profit-split delta + payout reliability)

**Acceptance:** All surviving EAs running on Nautilus for 30+ days with stability metrics matching or exceeding the MT5 equivalents. MT5 process can be cleanly stopped without missing any expected trades.

### Phase 5 — Alpha Factory feeds Nautilus directly (Months 3+)
This is where the architecture pays off. The M11 Alpha Factory plan (already specced in Tasks.md):
- The searcher outputs candidate strategies as **Python Nautilus Strategy classes**
- The paper-quarantine arm IS the Nautilus paper environment (zero new infrastructure)
- The live-graduation gate becomes a Nautilus config flag flip (paper account → live account)
- The bootstrap reality check (M10 #5 enhanced) runs against Nautilus event logs directly

**Acceptance:** First Alpha-Factory-generated candidate goes from ledger → ai-quant-researcher → paper quarantine → 25%-size live, all on Nautilus, no manual intervention beyond the human-ack at the live-graduation gate.

---

## What we KEEP from the MT5 era

- **Convex backend** — unchanged. Just point Nautilus events at it.
- **Pushover alerts** — unchanged.
- **Daily digest cron** — unchanged (read from Convex; Convex doesn't know or care that the data is now coming from Nautilus instead of `paper_trade_monitor.py`)
- **VPS resilience pattern** — translate Windows scheduled tasks to Linux systemd units
- **Risk framework discipline** — CLAUDE.md §3 limits port directly (5%/10% daily/max for FTMO-account; configurable for IBKR self-funded)
- **Trial post-mortem data + sizing calibration** — informs Nautilus per-EA sizing on day 1
- **ai-quant-researcher** — gains event-sourcing as a first-class input
- **`TRIAL_LOG.md`** format — continues as `POST_FUNDED_LOG.md`
- **All academic insights** from `research/academic_review_2026-06.md` — apply unchanged
- **Cross-venue risk aggregator design** — implemented in Convex as already specced

## What we RETIRE when MT5 goes away

- **MQL5 EA files (`.mq5`)** — archive in repo under `mql5/archived/` for reference, remove from build
- **BotOrchestrator EA + manifest** — Nautilus supervises strategies natively
- **`libquant.dll` / `libftmorisk.dll`** — Nautilus has built-in risk engine; we keep the FTMO-rule encoding as a Python module
- **`utils/mt5_log_parser.py`** — Nautilus emits structured events natively, no parsing needed
- **The 5-minute scheduled-task restart loop** — Nautilus is long-running by design
- **`utils/convex_client.py`** retry-warn-continue pattern — Nautilus has its own event-bus reliability; Convex push becomes a Nautilus message-bus subscriber

---

## Risks specific to this migration

1. **Nautilus IBKR adapter quirks.** IBKR's API is notoriously stateful and quirky (TWS auto-disconnect at 4am ET, paper account vs live account auth differences, market-data subscription pricing model). STABLE per Nautilus docs but **run paper for 2 weeks minimum** before any live capital.

2. **Strategy translation bugs.** Porting MQL5 → Python is *rewriting*, not transpiling. The Phase 1 parity check (5 consecutive days of identical signals) is the only thing that catches divergence. Don't skip it.

3. **Event-sourcing storage cost.** Every market event durably logged = GBs/day of telemetry. Plan for S3/R2 archival (we keep Convex hot for recent + alerts; cold storage for historical replay).

4. **IBKR commission model differs from OANDA spread-only.** IBKR has tiered commission + min-per-trade fees. Per-EA cost model must be recalibrated. This is already in M10 #9 (per-EA cost-model refinement); the calibration just gets a second pass with IBKR rates.

5. **Hyperliquid is a DEX → smart contract / on-chain risk.** Arbitrum L2 dependency. Funds at risk if Arbitrum sequencer goes down. **Cap Hyperliquid exposure at < 25% of total crypto allocation.** Bybit (CEX, deeper liquidity) covers the remainder if we want broader crypto coverage.

6. **Multi-venue == multi-instrument-id complications.** Same instrument (BTC perp) has different tick sizes, contract specs, margin requirements across HL/Bybit/Binance. Nautilus normalizes via its symbology layer but per-venue verification is needed before live.

7. **Cross-venue risk aggregator is genuinely new code.** Today's Convex schema doesn't have a `risk_aggregator` action. The 10-second poll + cross-venue equity sum + kill-broadcast logic is new and must be built, tested, drilled with synthetic breach scenarios before any live exposure. **This is the single biggest new architectural component in M11.**

---

## What we explicitly do NOT do in M11

(Defensive list — locks out scope creep.)

- **Don't port MT5 to Nautilus mid-trial or mid-paid-Challenge.** Wait for funded.
- **Don't add Polymarket adapter just because it's available.** Prediction markets are a different game (per the Upcomers analysis). Defer indefinitely.
- **Don't add Databento yet.** OANDA + Hyperliquid + Bybit free-tier data is sufficient until we hit a strategy that genuinely needs tick-level institutional data.
- **Don't migrate FTMO funded account to IBKR immediately.** FTMO via OANDA + MT5 is fine as-is; it's a separate capital pool. Migrate only if a clear economic case emerges.
- **Don't build a UI for Nautilus.** Convex dashboard + Pushover digest = sufficient. Defer Grafana to "if Convex UI becomes cramped" (already noted in M11).
- **Don't fork Nautilus.** Use upstream releases. Submit PRs for bugs we find; don't carry private patches.

---

## How M11 in Tasks.md should evolve

This document is the master spec. Tasks.md M11 should reference it but stay terse. The infrastructure architecture section already in Tasks.md M11 (the 4 VPS, the desktop, the Alpha Factory tier, the observability tier) **maps directly to Phase 1-5 above** — no contradiction, just more procedural detail here.

Specific work items that should be ADDED to Tasks.md M11 as sub-tasks (deferred until M11 actually starts):

- **M11.A:** Phase 1 build — provision nautilus-exec VPS, install Nautilus + IBKR adapter, port first EA, achieve 5-day paper parity.
- **M11.B:** Phase 2 build — add Hyperliquid adapter, port BTCUSD_M15_TrendFollow, validate 24/7 weekend operation.
- **M11.C:** Phase 3 build — first live 25%-size on IBKR + cross-venue risk aggregator implementation + 14-day reconciliation test.
- **M11.D:** Phase 4 build — port remaining EAs, decommission MT5.
- **M11.E:** Phase 5 build — Alpha Factory output as Nautilus Strategy classes; first auto-graduated candidate.

These are added to Tasks.md only when M11 actually starts (i.e., after funded + first payout). Adding them now is premature; the plan document is sufficient persistence.

---

## How to use this document

1. **At M11 start (post-funded, post-first-payout):** Read this whole document before opening Tasks.md M11. The Phase sequencing is the source of truth.
2. **At each Phase kickoff:** Re-read that phase's acceptance criteria. Do NOT proceed to the next phase until acceptance is met.
3. **When Convex schema changes are needed:** Coordinate with the cross-venue risk aggregator design (M11 Tasks.md item) — both touch Convex; one merge conflict will hurt.
4. **When new Nautilus adapters become available:** Check this list. If a new STABLE crypto adapter ships that's clearly better than our pick, evaluate before adding (don't just add).
5. **At each Phase close:** Update `POST_FUNDED_LOG.md` (analogous to `TRIAL_LOG.md`) with what shipped, what broke, what we learned.

---

## Cross-references

- **Tasks.md M11** — infrastructure architecture + searcher arm + live graduation arm + off-MT5 expansion (these are the work items; this document is the *why* and the sequencing)
- **Planning.md §10 / Milestone 10 — Alpha Factory** — the three-killers framework and the quarantine-pipeline architecture (orthogonal but applies)
- **research/academic_review_2026-06.md** — academic backing for the strategies that Nautilus will execute, plus the Sullivan-Timmermann-White bootstrap requirement that Nautilus event sourcing enables
- **CLAUDE.md §3** — risk framework that carries over unchanged
- **CLAUDE.md §5** — MT5 Python API surface, which we retire; replaced by Nautilus's Python API
- **CLAUDE.md §10** — "Doubt about a deployment? Paper trade for at least two weeks." The Phase 1 + Phase 3 paper periods are the operationalization of this rule.
