# 4-Week Paper-Trade Plan

Per CLAUDE.md §10 ("Doubt about a deployment? Paper trade for at least two
weeks before any live capital"), this document specifies the protocol for
the mandatory paper-trade run before the first FTMO Challenge purchase.

This is NOT optional. Skipping this and going straight to a paid Challenge
is the single biggest unforced error pattern in retail prop trading.

## Goals

1. **Validate live tracking error** vs. the backtest equity curve.
2. **Confirm the OCaml risk engine** never authorises an order that breaches
   internal kill in the live MT5 environment.
3. **Measure execution slippage** at real broker spreads (the demo broker
   reports spread=0 — see Memory.md for why we don't believe that).
4. **Catch operational failure modes** (network drops, MT5 restarts, daylight
   savings transitions across Prague midnight) before they happen on paid
   capital.

## Setup

### MT5 demo account
Use the existing MetaQuotes-Demo account (login 5050327497). For better
broker realism, also open a free demo on a real FTMO-compatible broker
(IC Markets, Pepperstone, OANDA) and run the EA on BOTH in parallel.

### EA deployment
1. Build the DLLs once:
   ```powershell
   cd cpp && cmake -S . -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
   cd ../ocaml && dune build
   ```
2. Copy artefacts into MT5 data folder (File > Open Data Folder > MQL5):
   ```
   cp cpp/build/libquant.dll          <terminal>/MQL5/Libraries/
   cp ocaml/_build/.../libftmorisk.dll <terminal>/MQL5/Libraries/
   cp mql5/Include/QuantLib.mqh       <terminal>/MQL5/Include/
   cp mql5/Include/FTMORisk.mqh       <terminal>/MQL5/Include/
   cp mql5/Experts/FTMOBot.mq5        <terminal>/MQL5/Experts/
   ```
3. In MetaEditor, F7 to compile FTMOBot.mq5.
4. In MT5: Tools > Options > Expert Advisors > "Allow DLL imports" = ON.
5. Drag FTMOBot onto a US500 (or USTEC, US30, DE40) D1 chart. Set inputs:
   - `InpAccountType = "CHALLENGE_2STEP_PHASE1"`
   - `InpDryRun = false`  (we want REAL paper fills)
   - leave the other inputs at defaults

### Logging
- All EA `Print()` output goes to `<terminal>/MQL5/Logs/<date>.log` — keep
  these for the duration of the run.
- Snapshot `account_info()` to a JSON file every 5 minutes (separate
  Expert or scheduled task on the host).

## Daily protocol (every trading day for 4 weeks)

1. **Morning (pre-market or before D1 close on the EA's symbol):**
   - Confirm EA still attached and AutoTrading enabled (green button).
   - Check the journal for any DLL load errors or `ftmo_apply_tick` failures.

2. **At each bar close on the symbol** (the EA fires automatically):
   - Log line should show `SIGNAL: z=... atr=...` or no log if no entry.
   - If an order fires: log includes the OCaml decision (Allow/Deny/Imminent).

3. **At end of trading day (US 4pm ET = ~10pm Prague):**
   - Pull the day's EA log.
   - Compare today's trades against what the backtest would have done
     (run `scripts/run_meanrev_backtest.py --years 0.1 --no-plots` for the
     same window and compare entries/exits).
   - Record any divergence.

## Weekly review (every Sunday)

### Quantitative metrics

Track all of these in a spreadsheet:

| Metric | Live | Backtest | Delta |
|---|---|---|---|
| Trades opened | | | |
| Trades closed | | | |
| Cumulative P&L (% of equity) | | | |
| Win rate | | | |
| Avg slippage on entry (vs bar open) | | n/a | |
| Avg slippage on exit (vs SL/TP) | | n/a | |
| Max drawdown | | | |
| Number of internal-kill triggers | | | should always be 0 |
| Number of FTMO-imminent warnings | | | |

### Qualitative checks

- Did the EA reconnect cleanly after any MT5 restart / network drop?
- Did the FTMO state correctly reset at 00:00 Europe/Prague? (Check the
  `daily.reset` log entries.)
- Did the OCaml `ftmo_check_pretrade` ever DENY an order? If yes, was the
  denial reasonable?
- Are real spreads materially different from the 50-100pt assumed in the
  backtest cost model? If yes, re-run `scripts/meanrev_spread_stress.py`
  with the measured spread.

## Pass / fail criteria (week 4 review)

To consider the EA ready for a paid FTMO Challenge:

- **PASS criteria (all required):**
  - Zero internal-kill events.
  - Zero FTMO-line breaches (the rule engine ensures this, but verify).
  - Live tracking error vs. backtest: realised return within ±50% of the
    backtest's annualised expectation. (A wide tolerance because the
    paper-trade window is 4 weeks of a Sharpe ~0.5 strategy — variance is
    huge at that horizon. The point is to detect SYSTEMIC drift, not noise.)
  - Live Sharpe (4 weeks) within ±1.0 of the backtest's expected window
    Sharpe (~0.5).
  - At least 4 trades fired (minimum for any statistical signal).
  - All EA log lines parse cleanly — no NaN / -1 / "INTERNAL" error codes.

- **FAIL criteria (any one ⇒ do NOT purchase a Challenge yet):**
  - Any internal-kill event triggered.
  - Any unexplained DLL crash or order-send loop.
  - Live tracking error > 100% deviation from backtest (likely a sizing
    or pricing bug).
  - OCaml engine status code disagrees with the Python backtest on the same
    bar (run the parity test fresh on the new data).

## After the paper-trade run

If PASS: proceed to FTMO purchase (start with the cheapest $25K
2-Step Phase 1 — Memory.md has the rationale).

If FAIL: diagnose the failure, fix, paper-trade for another 2 weeks.
DO NOT purchase a Challenge until the failure mode is understood AND
fixed AND a clean 2-week run confirms the fix.

## What this paper-trade plan does NOT replace

- It does not establish profitability. The strategy's expected CAGR at 0.5%
  risk-per-trade is ~1.2% (Memory.md 2026-05-11 entry). Passing FTMO Phase 1
  (10% target) takes ~8 years on average at this size. Paper-trading just
  verifies the bot's INFRASTRUCTURE works, not that the strategy is fast
  enough to pass.
- It does not validate the strategy ALONE is FTMO-pass-able in a reasonable
  time. Per Memory.md, this is a satellite alpha; deploying it without a
  second uncorrelated leg is operationally fine but won't pass Phase 1 fast.
