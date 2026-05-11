# FTMO MT5 Quant Trading Bot

Production-grade systematic trading platform on MetaTrader 5, purpose-built to
pass FTMO evaluations and trade FTMO funded capital without rule violations.

---

## Context files — read these first

| File | Purpose |
|---|---|
| `CLAUDE.md` | Identity, FTMO rules, MT5 API reference, engineering standards |
| `Planning.md` | Architecture, milestone roadmap, current phase |
| `Tasks.md` | Granular task list with acceptance criteria |
| `Memory.md` | Decision log, FTMO/MT5 gotchas, open questions |

> **Rule:** read all four before touching any code in a new session.

---

## Setup

### Prerequisites

- Windows (MT5 Python API is Windows-only)
- Python 3.11+
- MetaTrader 5 terminal installed ([download](https://www.metatrader5.com/en/download))
- `uv` package manager (`pip install uv`)

### Installation

```bash
# 1. Clone / open the repo
cd ftmo-bot

# 2. Install dependencies
uv sync --extra dev

# 3. Copy and fill in credentials
cp .env.example .env
# edit .env — set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, FTMO_ACCOUNT_TYPE, FTMO_INITIAL_CAPITAL

# 4. Run unit tests (no MT5 terminal required)
pytest -m "not live"

# 5. Run smoke test (requires a running MT5 terminal + demo account)
pytest -m live tests/test_mt5_smoke.py
```

---

## Directory layout

```
ftmo-bot/
├── data/           # MT5 data fetch, parquet cache, symbol metadata
├── strategies/     # One folder per strategy — signal logic, regime filter
├── backtest/       # Walk-forward engine, FTMO simulator, metrics, reports
├── execution/      # MT5 order routing, slicer, reconciliation
├── risk/           # FTMO limits, internal gates, equity watcher, kill switches
├── utils/          # Logging, config, Prague-TZ, math helpers
├── tests/          # Unit + integration tests
├── configs/        # YAML configs per strategy and environment
├── research/       # Notebooks, exploratory analysis (not production)
└── logs/           # Runtime logs (gitignored)
```

---

## Current milestone

**Milestone 0 — Foundations** (complete)

Next: **Milestone 1 — Data Layer** → see `Tasks.md`.

---

## Hard rules (abbreviated)

- FTMO daily loss limits are **equity-based** (floating P&L counts). Bar-close monitoring is insufficient.
- The FTMO day resets at **00:00 Europe/Prague**, not UTC, not broker time.
- The bot operates at **internal limits** (3%/2% daily, 7% max) well inside FTMO's lines (5%/3% daily, 10% max).
- No order reaches MT5 without passing `headroom_check` and `order_check` first.
- All datetimes in the codebase are **timezone-aware**. `datetime.now()` without `tz=` is forbidden.

See `CLAUDE.md` §3 for the full rule set.
