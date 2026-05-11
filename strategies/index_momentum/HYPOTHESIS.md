# Strategy Hypothesis: Equity Index Time-Series Momentum (TSMOM)

## One-Line Hypothesis

Major equity index futures/CFDs exhibit persistent autocorrelation in their own past returns over
1–12 month horizons — when an index has trended up over the lookback window it tends to keep
trending up, and vice versa. The edge is captured by going long indices in their own uptrends
and short (or flat) in their own downtrends, sized so each position contributes equal volatility
to the portfolio.

This is **time-series momentum** (each symbol judged against its own history), not
cross-sectional momentum (each symbol ranked against the others). With only 3–5 tradeable index
CFDs on FTMO, the cross-section is too small for meaningful ranking — which is one reason the
previous FX cross-sectional momentum attempt failed at 7-symbol universe size.

---

## Why This Edge Exists

### The Economic Mechanism

1. **Slow diffusion of macro information.** Equity indices aggregate views on growth, earnings, and
   discount rates. Pension funds and 401(k) flows respond to economic signals with multi-week
   lags. Risk-on/risk-off regime changes propagate through allocator decisions over months, not
   days. The price drift over the diffusion window is what TSMOM captures.

2. **Behavioral under-reaction to news.** Investors anchor on recent levels and adjust positions
   incrementally. A surprise rate cut or earnings beat moves prices, but most participants chase
   the move over days/weeks rather than instantly recalibrating. The trend continues until the
   information is fully absorbed.

3. **Risk-management flows reinforce trends.** Volatility-targeting funds, risk-parity portfolios,
   and CTA strategies systematically buy on positive momentum and sell on negative momentum.
   This is mechanical positioning, not opinion — and it persists as long as realized volatility
   stays within the target band.

4. **Asymmetric institutional preference for long-only equity exposure.** Most large pools of
   capital (pension, insurance, sovereign wealth) cannot short equities. This creates an
   asymmetric flow pattern: positive trends attract larger inflows than negative trends attract
   short interest, which biases the unconditional payoff distribution to the long side.

### Academic Support

- **Moskowitz, Ooi, Pedersen (2012) — "Time Series Momentum" — JFE.**
  Sharpe ratios of 1.5+ on a diversified TSMOM portfolio across 58 equity indices, currencies,
  bonds, and commodities, 1965–2009. The equity-index component alone shows positive 12-month
  return autocorrelation in 95%+ of the asset-months tested. Position sizing by ex-ante volatility
  is essential — equal-dollar sizing degrades Sharpe by 30–50%.

- **Hurst, Ooi, Pedersen (2017) — "A Century of Evidence on Trend-Following Investing."**
  Time-series trend-following has delivered positive risk-adjusted returns in every decade since
  1880, across multiple asset classes. Out-of-sample post-2008 performance is positive but lower
  than the pre-2008 in-sample (Sharpe 0.5–0.8 vs 1.0+), reflecting tighter spreads and faster
  information diffusion.

- **Baltas and Kosowski (2013) — "Momentum Strategies in Futures Markets and Trend-Following Funds."**
  Confirms TSMOM is the dominant return driver for CTA-style funds. Shows that TSMOM works better
  on indices than on individual stocks (where short-term reversal dominates).

- **Asness, Moskowitz, Pedersen (2013) — "Value and Momentum Everywhere."**
  Cross-asset momentum, including equity indices. Robust factor in the equity-index slice
  specifically.

### Why TSMOM Is More Likely To Work Than FX Cross-Sectional Momentum (post-2008)

1. **Equity-index trends are reinforced by structural inflows** (passive index fund growth,
   401(k) contributions, central-bank QE bias toward risk assets). FX has no equivalent
   directional flow bias — capital just rotates between currencies.

2. **The 2010s+ regime favored risk-on equity beta.** Index momentum picked up most of the
   bull-market drift; FX momentum had no equivalent regime tailwind because rate dispersion
   collapsed (central banks coordinated near zero).

3. **Diversification across only 3–4 indices still works** for TSMOM because each is
   independently signaled — unlike cross-sectional where you need a wide rank. This matches
   what FTMO-MT5 actually provides.

4. **Index CFDs have tight spreads** on the major contracts (US500, NAS100, GER40 routinely
   <1 bp of price) compared to FX (>1 pip of price on majors). Transaction-cost drag — which
   killed the H4 FX-momentum sweep — is materially lower per-trade.

---

## Asset Universe (Subject to Broker Confirmation)

Target universe — must be confirmed against the FTMO/MT5 broker's actual symbol inventory
before backtesting:

| Region        | Index             | Likely MT5 symbol(s)      |
|---------------|-------------------|----------------------------|
| US large-cap  | S&P 500           | US500, SPX500, .SPX        |
| US tech       | NASDAQ 100        | NAS100, USTEC, .NDX        |
| US blue-chip  | Dow Jones 30      | US30, WS30, .DJI           |
| Europe — DE   | DAX 40            | GER40, DE40, .DAX          |
| Europe — UK   | FTSE 100          | UK100, FTSE100, .FTSE      |
| Asia          | Nikkei 225        | JP225, JPN225, .N225       |

**Selection criteria:**
- Spread ≤ 5 points on D1 close on the broker's data feed.
- Continuous quoting during the relevant session (skip Asia indices if our timeframe is D1
  and they have material session-close-only quoting).
- Liquidity: prefer the contract MT5 reports the lowest avg spread for.

Initial target: **US500, NAS100, GER40** as the core (high correlation among them but each adds
independent signal in different macro regimes); add UK100 / US30 / JP225 only if broker spreads
permit and they add cross-correlation diversification.

---

## Signal Construction

**Primary signal: Time-series momentum sign of formation-period return**

- Formation period: 60 D1 bars (≈ 3 calendar months), skipping the most recent 1 bar.
- For each symbol at time T independently:
  `return_60(T) = close(T-1) / close(T-61) - 1`
- Direction: `sign(return_60)` — long if positive, short if negative.

This is the "12-1 month" momentum form from MOP 2012, scaled to a 3-month formation that fits
FTMO timelines better (a 1-year formation would mean the strategy holds a single direction for
months at a time — a poor fit for a 1–4 month FTMO Challenge window).

**Secondary signal: Trend confirmation (ensemble — CLAUDE.md §3 forbids single-signal strategies)**

- EMA crossover: long requires `close > EMA(50)` AND `EMA(20) > EMA(50)`; mirror for short.
- This kills the worst whipsaw trades where the formation-period sign is positive but the
  short-term trend has already broken down.

**Regime filter (cross-asset risk-on/off):**

- Compute realized 20-day volatility of each index. If portfolio-average vol exceeds a threshold
  (calibrated to roughly the 75th percentile of historical), reduce position size by 50% or pause
  new entries. This is the Barroso-Santa-Clara momentum-crash defense, adapted from FX to indices.

**Position sizing: Volatility-targeted ¼ Kelly**

- Target per-position annualised volatility = `target_vol` (e.g. 8% of equity per leg).
- Lots = `(target_vol × equity) / (annualised_realized_vol × contract_size × spot)`.
- Cap at `per_trade_risk_pct` (0.5% via ATR stop, same as FX strategy) for FTMO compliance.
- Volatility targeting is the **key methodological difference** from the FX strategy — it
  equalises each leg's contribution to portfolio variance, which the MOP paper shows is
  essential for TSMOM to actually realise the Sharpe.

---

## Signal Decay / Half-Life Test (Phase 1 step 4)

Before committing to formation_bars=60, the implementation must measure return autocorrelation
at multiple lags (1d, 5d, 20d, 60d, 120d, 250d) on the index universe. Expected pattern:

- Lag 1d: weak (microstructure noise / overnight gaps).
- Lag 5–20d: positive but small (signal is strongest here for shorter-horizon momentum).
- Lag 20–120d: positive and meaningful — this is the TSMOM regime.
- Lag 250d+: positive but decaying; risk of mean-reversion overlay at very long horizons.

If the autocorrelation pattern does NOT match, the hypothesis is empirically rejected before
running the full backtest.

---

## FTMO Compatibility

| Concern                          | TSMOM behavior                                                  | Verdict          |
|----------------------------------|------------------------------------------------------------------|------------------|
| Daily 5% (or 3%) loss line       | 3–4 positions sized at 0.5% each, vol-targeted → aggregate ~2%.   | Compatible.      |
| 10% max loss                     | Position sizing capped; max drawdown in MOP is 15% pre-vol-targeting, 10% with vol targeting. | Compatible with internal kill at -7%. |
| News-blackout (Funded standard)  | TSMOM holds 1–4 weeks; entries/exits sparse enough that news    | Compatible.      |
|                                  | windows are easy to route around with the existing gate.        |                  |
| Best-Day rule (1-Step)           | Trend windows align with weekly-monthly profit pace; unlikely   | Compatible       |
|                                  | to spike a single-day profit > 50% of total profitable-day P&L. | (monitor).       |
| Weekend gap                      | Index CFDs gap on Sunday open after weekend macro events.       | Risk — must      |
|                                  |                                                                  | size for         |
|                                  |                                                                  | weekend exposure.|
| Holiday illiquidity              | US/EU/JP holidays produce thin quoting; signal computed on D1   | Compatible.      |
|                                  | close so holiday bars are simply excluded.                       |                  |

---

## Risk Controls

In addition to global FTMO gates from `risk/`:

- **Vol-target cap.** When realized vol > 2× target, position size is halved before being sent.
- **Correlation cap.** US500, NAS100, US30 are typically correlated > 0.85. If all three signals
  point the same direction, aggregate exposure is capped at 1.5× single-symbol size (treating
  them as ~1 effective independent leg).
- **Regime pause.** Cross-asset vol filter above. Pause when triggered.
- **Friday-close flat option.** For standard FTMO (non-Swing), all positions flatten on Friday
  close to avoid Sunday-gap risk. Configurable.

---

## Regime Conditions Under Which The Strategy Is Active

**Active:**
- Realized 20-day cross-asset vol below threshold.
- Each leg passes its own EMA-trend confirmation.
- News-blackout gate not triggered.
- Within FTMO daily/max headroom.

**Paused / sized down:**
- Vol spike above threshold → halve size or pause.
- Major macro events (FOMC, NFP, ECB) → news-blackout gate handles.
- FTMO headroom < 1% of either limit → no new entries.
- Friday after a defined cut-off (non-Swing accounts) → flat into weekend.

---

## Known Weaknesses

1. **Momentum crashes.** TSMOM lost 20%+ during the 2009 Q2 rally (sharp regime change from
   bear to bull). The vol-targeting overlay mitigates but doesn't eliminate this. Worst-case
   path requires the FTMO kill switch to fire before catastrophic drawdown.

2. **Whipsaw in range-bound markets.** When index ranges sideways (e.g. 2015 H1, 2023 Jan-Mar),
   the 60d momentum sign flips repeatedly, generating loss-making entries. The EMA-trend filter
   reduces but doesn't eliminate this. Acceptable if win-rate ~40% with R:R ≥ 1.6.

3. **High correlation of US indices.** US500 / NAS100 / US30 carry similar information. The
   strategy is effectively a 1–2 independent leg portfolio when including all three, not a 3-leg
   portfolio. Mitigated by the correlation cap, but the effective Sharpe is closer to a single
   leg than a 3-leg portfolio would suggest.

4. **Slippage on news.** Index CFDs widen spreads 5–20× during major events. If a stop fires
   during news, fill quality is poor. Mitigated by news-blackout gate + holding through D1 bars
   rather than intrabar.

5. **Funding / overnight financing.** Index CFDs charge daily financing (rolling at broker close).
   At a few bps per night this is non-trivial for multi-week holds. The cost model must include
   per-night financing for the long side and credit for the short side (or vice versa for
   certain brokers).

6. **Regime non-stationarity.** Post-2010 has been one extended risk-on regime. If the
   structural-flow tailwind reverses (de-globalisation, demographic-driven equity outflows from
   retirees), TSMOM Sharpe could decay further. The strategy's life expectancy is decades but
   its Sharpe is not stationary.

---

## Hypothesis Pass/Fail Criteria

Before this strategy can be considered for deployment:

1. Signal decay test: positive autocorrelation at the 20–120d lags on the chosen universe (Phase 1).
2. Full-period backtest: Sharpe ≥ 0.7, max drawdown ≤ 12%, FTMO sim PASS.
3. Walk-forward (36m IS / 12m OOS): mean OOS Sharpe ≥ 0.5, IS→OOS degradation ≤ 0.5.
4. Parameter sensitivity (formation ±20%, EMA ±20%, vol-target ±25%): Sharpe std ≤ 0.25 across cells.
5. FTMO simulation: zero daily-line breaches, zero max-line breaches, internal-kill count = 0
   or ≤ 1 per year (controlled by sizing, not by emergency).

If any of these fail, the strategy is rejected (or scope is reduced — e.g. drop to long-only,
test only on US500 alone) before further work.
