# IBKR Onboarding + Execution-Adapter Plan (2026-06-26)

> Self-funded momentum deployment (M11). Turns the `momentum_paper.py` recompute harness into a
> real paper-rebalance loop against a headless IB Gateway PAPER account via `ib_async`. Grounded in
> IBKR's official TWS API reference + ib_async docs (Campus pages were Cloudflare-blocked to fetch;
> facts cross-confirmed). Deploy the **15-ETF sleeve only** — crypto is not paper-testable/shortable on IBKR.

## Part A — Onboarding Runbook (user checklist, do once)

**Never paste IBKR username/password/2FA into chat.** All of this is done in the IBKR web portal and the Gateway GUI on your machine.

1. **Paper account.** Portal → Settings → Account Settings → confirm a **Paper Trading account** exists; note the **paper username** (distinct from live). Confirm it's a **margin** account (cash can't short — the long/short sleeve needs it).
2. **Install IB Gateway (not TWS).** Lighter Java app, no charting, accepts API sockets by default. Prefer the **offline/stable build** so auto-updates don't break unattended restart.
3. **Launch in Paper mode** (log in with the paper username).
4. **Enable & lock down the API socket** — Configure → Settings → API → Settings:
   - ✅ "Enable ActiveX and Socket Clients" (verify).
   - **Socket port = 4002** (Gateway paper. Ref: TWS live 7496 / TWS paper 7497 / Gateway live 4001 / **Gateway paper 4002**). Wrong port = silent TimeoutError — the #1 failure.
   - ❌ **UNCHECK "Read-Only API"** — it's **ON by default** and **silently blocks all order placement** while still allowing reads. The #2 failure.
   - ✅ Keep "Allow connections from localhost only" (adapter on same box). Different host later → uncheck + add its IP to Trusted IPs.
   - ✅ "Download open orders on connection" (idempotent reconcile after restart).
   - (Optional) Master API client ID if a monitor should see all clients' fills/commissions.
5. **Market data — skip paid subs.** Adapter calls `reqMarketDataType(3)` (delayed, free) — fine for monthly sizing. Only if you want tight fills: Account Settings → Paper Trading → "Share real-time subscriptions with paper" (up to 24h to activate; can't consume on live+paper simultaneously).
6. **Unattended running.** Global Config → Lock and Exit → enable **Auto restart** at a time outside the rebalance window. Disable OS sleep/forced reboot. **Honest caveat:** true headless-forever isn't native — IBKR forces **manual re-auth ~weekly (Sun ~01:00 ET)**. For hands-free between: wrap Gateway with **IBC** (auto-login) + ib_async **Watchdog** (relaunch/reconnect). Budget one manual login/week.
7. **Hand the developer (no secrets):** host `127.0.0.1`, port `4002`, a fixed unique `clientId` (e.g. `17`; monitor uses a different id; max 32 clients). Adapter resolves the account via `ib.managedAccounts()[0]`. Credentials live only in the Gateway/IBC store.
8. **Smoke test:** with Gateway up on paper, run `backtest/ibkr_smoketest.py` — it connects, prints the account code + NAV + positions + a delayed price for all 15 ETFs, and disconnects. Green = socket/port/Read-Only all correct.

## Part B — Adapter Build Plan (`ib_async`, 15-ETF monthly long/short)

**Universe (all `Stock(sym,'SMART','USD')`, secType STK — incl. USO/DBC/UUP, do NOT use FUT/CMDTY):**
SPY QQQ IWM EFA EEM TLT IEF LQD HYG GLD SLV USO DBC VNQ UUP.

**Env:** Python ≥3.10; `pip install ib_async` (2.1.0). Do NOT co-install `ibapi`/archived `ib_insync` (own wire protocol; mixing breaks imports).

**Lifecycle:** connect → warm caches → read NAV/positions → target weights (from the momentum model) → diff w/ no-trade band → route → await fills → reconcile → log → disconnect.

- **Connect:** `ib.connect('127.0.0.1',4002,clientId=17)` (blocks until ready); `ib.reqMarketDataType(3)`; `acct=ib.managedAccounts()[0]`. Warm with `ib.sleep(1-2)` (never `time.sleep`).
- **State:** NAV/cash from `ib.accountSummary()` (tags NetLiquidation/TotalCashValue); `{p.contract.symbol:p.position for p in ib.positions()}` — position is **signed Decimal** (neg=short).
- **Price:** `ib.qualifyContracts(*contracts)` once; `ib.reqTickers(*contracts)` one-shot batch; read `t.marketPrice()/t.last/t.close` and **guard NaN** (delayed bid/ask often NaN) before sizing.
- **Targets + no-trade band:** `target_shares=int(round(weight*nav/price))`; only emit when `abs(target-current)` exceeds a band (~1% NAV notional). Band + "Download open orders" + reconcile-by-diff ⇒ reruns/mid-run restarts converge, never double-trade.
- **Orders:** marketable **LimitOrder** (small aggressive offset) default for these liquid ETFs; MarketOrder acceptable (but sits PreSubmitted if market closed → run during RTH). Short legs native (`SELL` to open); verify shortable in paper (borrow can be restricted even in paper — handle rejections). `ib.placeOrder` returns Trade immediately; ib_async manages order ids + throttles (45 req/s < IB's 50).
- **Fills:** loop `while not trade.isDone(): ib.sleep(1)`; success=`Filled`/remaining 0; capture `trade.fills` in-session (`reqExecutions` only backfills same-day).
- **Reconcile+log:** re-read positions, diff vs targets; log intent/delta/fill/commission/post-positions; `ib.disconnect()`.

**Guardrails:** `--dry-run` (steps 1–4, log deltas, no placeOrder — run first each month); kill-switch on exception/sanity breach (turnover>X% NAV, NaN price, >N orders) → `ib.reqGlobalCancel()`; wait 1–2s after disconnect before reconnecting same clientId; use `...Async()` + `util.startLoop()` under async/Jupyter.

**Alongside the forward-paper task:** separate clients on one Gateway — adapter gets its own fixed clientId (17) ≠ the scheduler's. Schedule its monthly run at fixed RTH not overlapping auto-restart/Sunday re-auth.

**Honest caveats:** paper fills flatter (little slippage, idealized borrow — plumbing test, not perf estimate); delayed data ~15–20min (fine for monthly; don't drive tight limits off it); **15-ETF sleeve only — crypto BTC/ETH not paper-testable + non-shortable on IBKR, keep it out entirely**; weekly human re-auth unavoidable. Pin: Gateway 952.x+ (974+ auto-restart), ib_async 2.1.0, Python 3.10+.
