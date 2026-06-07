# Academic literature review — quant trading strategies relevant to the FTMO bot

> Created: 2026-06-03, mid-trial (Day 7 close). User requested research on MA/EMA/technical analysis/quant strategies from peer-reviewed sources (universities, economists). This is the curated synthesis — what's directly useful for our specific portfolio, separated from what's just interesting.
>
> Source: Firecrawl searches across 6 academic topics, deep-read of 4 papers (Time Series Momentum, St Louis Fed FX-TA review, ORB-on-Stocks-in-Play, arxiv trend-premia structure 2025).
>
> Standing context the research is being applied to: 10 EAs across FX (EURUSD, GBPUSD, AUDJPY, EURGBP), indices (US500, US100), gold (XAUUSD), crypto (BTCUSD, in dry-run); M15 / H1 / H4 timeframes; mechanisms include Donchian breakout, ORB, session momentum, RSI fade, gold-fix reversal, news reaction, overnight drift, cointegration mean-reversion.

---

## The 8 papers worth knowing

### 1. **Moskowitz, Ooi, Pedersen (2012)** — *Time Series Momentum*. **Journal of Financial Economics, 104(2), 228-250.**
Foundational TSMOM paper. 58 futures contracts, 25 years. Past 12-month returns predict next-month returns with positive autocorrelation across equity indices, currencies, commodities, bonds. **Key finding for us:** *"correlation among time series momentum returns is stronger than the correlation of passive long positions across the same asset classes, implying a common component to time series momentum not present in the underlying assets themselves."* Our Day 7 cluster loss (AUDJPY+XAUUSD+GBPUSD trend-followers losing simultaneously) is **literally this paper's finding playing out** — the trend premium has a common factor even when the underlyings don't.
- **Applies to:** GBPUSD_H1_SwingBreak, AUDJPY_H4_TrendFollow, BTCUSD_M15_TrendFollow.
- **URL:** https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf

### 2. **arxiv 2510.23150v2 (Oct 2025)** — *Revisiting the Structure of Trend Premia: When Diversification Hides Redundancy*
Most recent and most surprising. Tests the conventional wisdom that diversifying across short/medium/long horizons improves trend-following. Bayesian optimization across horizons. **Conclusion: the medium-term band (~125 days / ~6mo) adds little incremental value once short + long are included.** A "barbell" structure (short + long, skip medium) captures most of the Sharpe with less complexity. *"The medium-term horizon largely overlaps with its neighboring horizons"* — diversification hiding redundancy.
- **Applies to:** Our M15 / H1 / H4 structure. The H1 EAs (GBPUSD_H1_SwingBreak, XAUUSD_H1_NewsReaction, US100_H1_OvernightDrift) may be near-redundant with M15 + H4. Worth testing.
- **URL:** https://arxiv.org/html/2510.23150v2

### 3. **Hurst, Ooi, Pedersen (2017)** — *A Century of Evidence on Trend-Following Investing*. **Journal of Portfolio Management, 44(1).**
Extends MOP 2012 back to 1880 using novel commodity data. **Trend-following has worked for 137 years across 67 markets**, surviving the Great Depression, both world wars, 70s stagflation, 2008. Sharpe ~1.0 net of 2% fees for equal-weighted 1/3/12-month trend portfolio.
- **Applies to:** All trend-followers. Long-horizon validation that the strategy survives even regimes much worse than our worst trial day.
- **URL:** https://fairmodel.econ.yale.edu/ec439/hurst.pdf

### 4. **Park & Irwin (2007)** — *What Do We Know About the Profitability of Technical Analysis?* **Journal of Economic Surveys, 21(4), 786-826.**
Comprehensive review of 95 studies. **Verdict: TA works in FX and futures, doesn't work in equities** after data-snooping adjustments. FX trends persist due to central bank intervention smoothing flows.
- **Applies to:** Our FX EAs are on solid academic ground; equity-index TA (US500, US100) has weaker support — bias toward simpler entry rules, more skeptical of complex signals on indices.
- **URL:** https://ageconsearch.umn.edu/record/37487

### 5. **Neely, Weller (2011)** — *Technical Analysis in the Foreign Exchange Market*. **St Louis Fed Working Paper 2011-001.**
FX-focused review. *"Academic research on the profitability of technical analysis tends to confirm the idea that foreign exchange markets trend particularly well."* Three methodological traps explicitly enumerated: **data snooping** (testing many rules, reporting the winner), **data mining** (selecting from pre-tested set), **publication bias** (journals favor positive results). Fix: bootstrap-based reality checks, automated rule selection.
- **Applies to:** the ai-quant-researcher integration. Their three-trap framework should be the mandatory test before any new EA ships post-trial.
- **URL:** https://files.stlouisfed.org/files/htdocs/wp/2011/2011-001.pdf

### 6. **Zarattini, Barbon, Aziz (2024)** — *A Profitable Day Trading Strategy For The U.S. Equity Market*. **Swiss Finance Institute Research Paper 24-98.**
**CRITICAL for our US500_M15_ORB EA.** 7,000 US stocks 2016-2023, 5-minute ORB. Headline: portfolio of top-20 *Stocks in Play* (abnormally high volume on news) returned 1,600% total, Sharpe 2.81, alpha 36% annualized. **BUT — ORB on random stocks or indices = noise.** The "Stocks in Play" filter (high-volume, news-driven) is the entire edge.
- **Applies to:** US500_M15_ORB applies ORB to a passive index, NOT to news-driven stocks. The Day 5 -$882 loss is consistent with this paper's verdict. ORB without context = weak.
- **URL:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284

### 7. **Gatev, Goetzmann, Rouwenhorst (2006)** — *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*. **Review of Financial Studies, 19(3), 797-827.**
Original pairs-trading paper. Distance-based selection of cointegrated equity pairs; open on 2σ divergence, close on convergence. Average 11% annualized 1962-2002 before costs, ~5% after. **But Yale 2024 (Zhu) + Springer 2025 (Krauss-Stübinger) show sharp post-2002 decay** — ETF era + HFT compress the spreads before pairs traders can act. Cointegration *stability* matters more than historical cointegration.
- **Applies to:** EURGBP_H4_MeanReversion. Mechanism sound but half-life and base-rate have shrunk; need rolling cointegration-stability test.
- **URL:** http://stat.wharton.upenn.edu/~steele/Courses/434/434Context/PairsTrading/PairsTradingGGR.pdf

### 8. **Sullivan, Timmermann, White (1999)** — *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap*. **Journal of Finance, 54(5), 1647-1691.**
**The methodological gold standard.** Tests 7,846 trading rules on the Dow 1897-1986 using White's Reality Check bootstrap. **Naive testing shows many "winning" rules; bootstrap-corrected, most apparent edges vanish.** A handful survive — but the chosen rule's edge is much smaller than its naive backtest suggests.
- **Applies to:** Every EA we keep post-trial. The ai-quant-researcher must apply Reality Check / Hansen's SPA before greenlighting size-up. Naive Sharpe + naive walk-forward is insufficient.
- **URL:** https://www.jstor.org/stable/222500

---

## The 5 actionable insights (mapped to Tasks.md M10 items)

### Insight 1: Recognize the TSMOM common-factor problem explicitly
**Source:** MOP 2012, paper #1.
**The mechanism behind Day 5 + Day 7 cluster losses.** The trend premium itself has a common factor across assets — even when the underlyings appear uncorrelated, the *trend-following returns* are correlated. Our 2% aggregate-risk cap assumed independence; the data says otherwise.
**Maps to:** Enhances existing M10 #1 (post-mortem factor decomposition) and M10 #2 (Kelly sizing with correlation-aware variance). No new task needed; the framework was already added with Article 2 enhancements.

### Insight 2: Test "barbell" timeframe structure (drop H1 EAs?)
**Source:** arxiv 2510.23150v2, paper #2.
The 2025 paper argues mid-horizon trend signals are largely redundant with short + long. We have 3 H1 EAs (GBPUSD_H1_SwingBreak, XAUUSD_H1_NewsReaction, US100_H1_OvernightDrift) that may be adding complexity without independent edge.
**Maps to:** **NEW M10 Tier 2 task** — barbell test.

### Insight 3: Add a Stocks-in-Play / volume filter to US500_M15_ORB (or retire it)
**Source:** Zarattini-Barbon-Aziz 2024, paper #6.
ORB-without-context is weak. Day 5 -$882 loss consistent with this. Two paths: (a) retrofit a volume-spike filter, (b) port to a stock-picking version (post-funded, after Nautilus migration so we can trade individual stocks), (c) retire the EA.
**Maps to:** **NEW M10 Tier 1 task** — US500 ORB decision (parallel structure to BTC EA decision).

### Insight 4: Add bootstrap reality check to ai-quant-researcher
**Source:** Sullivan-Timmermann-White 1999 (paper #8), Park-Irwin 2007 (#4), Neely 2011 (#5).
Naive Sharpe + naive walk-forward is academically insufficient. White's Reality Check, Hansen's SPA, or Stepwise White must be applied to control for data snooping when comparing multiple rules. Otherwise false-positive into adding strategies that don't survive OOS.
**Maps to:** Enhance existing M10 Tier 2 #5 (ai-quant-researcher integration) — add explicit bootstrap reality check requirement to acceptance criteria.

### Insight 5: Add cointegration-stability test to EURGBP_H4_MeanReversion
**Source:** Gatev-Goetzmann-Rouwenhorst 2006 (paper #7) + Yale 2024 + Springer 2025 updates.
Pairs trading post-2002 requires the pair to *stay* cointegrated, not just to have been cointegrated historically. Rolling Engle-Granger or Johansen test with a freshness window. If stability drops below threshold → pause the EA, not just adjust size.
**Maps to:** Defer to M10 Tier 2 #9 (per-EA cost-model refinement) as a sub-bullet. Lower priority than insights 2-4 because EURGBP_H4_MeanReversion never fired during the trial (no qualifying 3σ deviation observed) — there's no realized data to calibrate against yet. Address only if we choose to keep the EA after Insight 4's bootstrap check.

---

## What's NOT worth adopting (and why)

- **Beneish / Altman / Piotroski forensic accounting scores** (from 2026-06-02 article) — single-stock fundamental signals. We trade FX/indices/crypto. Zero overlap with our universe unless we expand to single-stock strategies post-funded.
- **Black-Scholes Greeks framework** — no options strategies. Could matter post-funded if we add vol strategies, but premature.
- **Famous-investor agent prompts (Buffett/Burry/Druckenmiller)** — personality-prompts don't add edge.
- **High-frequency microstructure papers** — wrong stack. Our timeframes are M15+; retail execution rails.
- **Equity-only TA papers** (mostly the Brock-Lakonishok-LeBaron era) — superseded by Park-Irwin's review showing equity TA fails data-snooping correction.

---

## Decision matrix: how the 5 insights land in Tasks.md

| Insight | Action | Where |
|---|---|---|
| #1 TSMOM common factor | Already captured | M10 #1 + #2 (Article-2 enhancements done 2026-06-03) |
| #2 Barbell timeframe test | **NEW TASK** | M10 Tier 2 |
| #3 US500 ORB decision | **NEW TASK** | M10 Tier 1 (parallel to BTC EA decision) |
| #4 Bootstrap reality check | Enhance existing | M10 Tier 2 #5 (ai-quant-researcher) acceptance criteria |
| #5 EURGBP cointegration stability | Defer | M10 Tier 2 (sub-bullet of cost-model refinement) only if EA kept |

Three new/enhanced tasks total. The other two insights are absorbed into existing task scope.

---

## How to use this document going forward

1. **At trial close (2026-06-10):** read this before starting M10 Tier 1 post-mortem. The TSMOM common-factor framing in Insight #1 is the single most important lens for interpreting the trial's cluster-loss days.
2. **When opening M10 #1 (post-mortem):** Insight #1 → factor decomposition must include "trend-following factor" as one of the regressors, not just market beta.
3. **When opening M10 #5 (ai-quant-researcher):** Insight #4 → Reality Check / Hansen's SPA is a hard requirement.
4. **When opening the barbell test task (M10 Tier 2):** Insight #2 → method is direct comparison of M15+H4-only vs M15+H1+H4 cumulative metrics from trial deals.
5. **When opening the US500 ORB decision (M10 Tier 1):** Insight #3 → reference Zarattini 2024 directly when picking between filter / port / retire.

The papers themselves are linked at the URLs above; download them and put PDFs in `research/papers/` if we want offline copies. None are paywalled.
