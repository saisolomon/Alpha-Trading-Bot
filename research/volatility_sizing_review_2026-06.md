# Volatility Targeting, Position Sizing & Portfolio Construction — Literature Review

> Created: 2026-06-08. User hunted Google Scholar off the Phase-A search guide and pulled 28 PDFs (24 unique after dedup) plus 2 Google Books links and 2 JPM citations. Theme: **volatility targeting / vol-managed portfolios / trend-following implementation / Kelly sizing / regime detection.** This is the Phase-A highest-leverage area — *better sizing of alpha we already have*, not new alpha.
>
> **Depth disclosure (honest):** Triage-grade. Extracted to text with `pypdf`; read title+abstract+conclusion+intro-head on all 24. Equations NOT line-checked. Full text preserved in `Downloads/_vol_txt/` for page-by-page reads at implementation time. Two Google Books links (textbooks) NOT scraped — noted at bottom. One JPM paper (Xu, "Beyond Volatility Timing") is citation-only, no PDF supplied.
>
> **Why this batch matters more than the microstructure batch:** Unlike the market-making papers (which need a real order book = Phase B), **almost everything here is Phase-A deployable on FTMO/MT5** — it's daily-frequency sizing and portfolio construction needing only OHLCV. This directly addresses the trial's #1 demonstrated weakness: the Day-5 and Day-7 correlation-cluster losses.

---

## THE headline finding for our portfolio (read this first)

There is an active academic debate here, and its resolution **directly determines how we apply vol targeting to our specific EAs.** Two camps:

- **Moreira & Muir (2017, w22208):** volatility-managed portfolios (scale exposure down when vol is high) produce large alphas and big Sharpe gains across many factors INCLUDING the currency carry trade. Foundational, optimistic.
- **Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, van Hemert (2018, ssrn-3175538):** the Sharpe benefit holds **only for "risk assets" (equities, credit)** — driven by the *leverage effect* (negative correlation between returns and volatility). For **bonds, currencies, and commodities the Sharpe impact is negligible** because the leverage effect isn't present. BUT — and this is the key — vol targeting **reduces the likelihood of extreme/left-tail returns across ALL asset classes.**
- **Hood & Raughtigan (2024, ssrn-4773781, the JPM paper you named):** confirms Harvey — vol-targeting "alpha" is really just **trend-following exposure** arising from the leverage effect, ~2/3 of the apparent alpha, and ONLY in equities. Not in FX/bonds/commodities.

**What this means for our actual book:**

| EA / asset | Asset class | Vol targeting → Sharpe? | Vol targeting → tail risk? |
|---|---|---|---|
| US500_M15_ORB, US100_H1_OvernightDrift | Equity index ("risk asset") | ✅ **Yes, boosts Sharpe** (leverage effect present) | ✅ Cuts left tail |
| EURUSD/GBPUSD LondonMomo, RSIFade, AUDJPY, EURGBP | FX | ⚠️ ~No Sharpe gain | ✅ **Still cuts left tail** |
| XAUUSD LondonFix, NewsReaction | Gold/commodity | ⚠️ ~No Sharpe gain | ✅ **Still cuts left tail** |

**The takeaway:** Don't naively bolt vol targeting onto every EA expecting Sharpe gains — for the FX/gold majority of our book, the literature says it WON'T improve Sharpe. BUT vol targeting cuts tail risk on *every* asset class, and **tail-risk reduction is exactly what protects the FTMO daily-loss line.** So vol targeting is worth adopting portfolio-wide, but justified by *survival/tail-control* (FTMO-critical) for FX/gold and by *Sharpe* for the equity indices. That's a precise, defensible reason — not cargo-culting.

---

## Cluster 1 — Correlation-aware portfolio construction (THE Day-5/Day-7 fix)

This is the single most relevant cluster to the trial's demonstrated failure mode.

### 1a. Baltas (2015) — "Trend-Following, Risk-Parity and the influence of Correlations" (ssrn-2673124)
**The paper that describes our Day-7 loss exactly.** Trend-following is conventionally sized by inverse-volatility weighting, which **ignores pairwise correlations**. That's fine when cross-asset correlations are low — but post-2008 the universe split into "Risk-On / Risk-Off" blocs with high within-bloc correlation, and inverse-vol weighting became **suboptimal**. Proposes extending long-only risk-parity (equal-risk-contribution) to a long-short trend strategy that accounts for the correlation structure.
**Applicability — DIRECT:** Our AUDJPY+XAUUSD+GBPUSD all broke down together on Day 7 because they share USD-counter exposure. Our 2% aggregate cap is an inverse-vol-style scheme that assumes independence. **This paper's equal-risk-contribution-with-correlations method is the fix.** Feeds M10 sizing calibration directly.

### 1b. Baltas & Kosowski (2019) — "Demystifying Time-Series Momentum" (ssrn-2140091)
Examines TSMOM implementation frictions. Two findings we can use: (1) more efficient volatility estimators (Yang-Zhang) + non-binary trading rules cut turnover by up to 36% with no significant performance loss; (2) **a dynamic-leverage mechanism using pairwise signed correlations** outperforms naive implementation, especially post-2008. Robust to transaction costs.
**Applicability — DIRECT:** The correlation-adjusted dynamic leverage is the operational recipe for 1a. The Yang-Zhang volatility estimator is a concrete, codeable upgrade to whatever vol estimate our EAs currently use (likely simple ATR or stdev).

**Cluster 1 verdict:** These two Baltas papers are the most actionable in the entire batch for *our specific problem*. They turn "the diversification thesis failed on Day 7" into "here's the correlation-aware sizing math that would have dampened it." → enhance M10 sizing-calibration task.

---

## Cluster 2 — Kelly sizing refinements (feeds M10 sizing calibration)

We already specced the M10 sizing task around f* = μ/σ² and P(ruin). These papers sharpen it.

### 2a. Bayesian Kelly with Parameter Uncertainty (ssrn-6195358, Sukhov 2026)
Classical Kelly assumes you KNOW the win probability `p`. You don't — you estimate it from finite samples, and **our sample is one 14-day trial.** Develops Bayesian Kelly with beta-distributed probability beliefs; closed-form fractional sizing that shrinks position size when confidence is low. Monte Carlo: reduces max drawdown 40-60% while keeping 85-95% of growth; biggest advantage during the **"cold-start phase"** and regime changes.
**Applicability — DIRECT & HIGH:** This is tailor-made for our situation. We're cold-starting with tiny sample → classical Kelly would massively over-size. Bayesian Kelly formalizes "size down because we're not sure yet." **Should be the actual sizing method for the next trial**, not plain fractional Kelly. Upgrades M10 #2.

### 2b. Kelly Betting Under Probabilistic Recovery Constraints (ssrn-5284131, Lee 2025)
Extends Kelly to penalize **drawdown and recovery time**: after a loss, the probability of returning to pre-loss wealth within a fixed horizon must exceed a threshold. Gives a closed-form cap on the Kelly fraction.
**Applicability — DIRECT & HIGH:** **FTMO is literally a recovery-constrained game** — daily reset at Prague midnight, static max-loss floor. A sizing rule that explicitly bounds "can I recover before I breach a limit?" maps perfectly onto FTMO mechanics. Pairs with 2a. Upgrades M10 #2.

### 2c. Leverage and Uncertainty (1612.07194, Turlakov)
Derives fractional Kelly in the presence of **fat tails** from subjective uncertainty; connects Kelly to risk-parity for multi-asset portfolios. CVA-desk practitioner.
**Applicability:** Supports fractional-Kelly-with-fat-tails (our returns are fat-tailed — Day 7 proved it). Context + theoretical backing for 2a/2b. Medium priority.

**Cluster 2 verdict:** The M10 sizing-calibration task currently uses classical Kelly. These three say: use **Bayesian Kelly (cold-start shrinkage) + a recovery constraint (FTMO-shaped)**. That's a materially better sizing method than what's specced. → upgrade M10 #2.

---

## Cluster 3 — Volatility targeting / vol-managed portfolios (the core theme)

### 3a. Moreira & Muir (2016, w22208) — "Volatility Managed Portfolios" (NBER)
The foundational paper. Scaling monthly returns by inverse of prior realized variance produces large alphas across market, value, momentum, profitability, investment factors AND currency carry. Utility gains ~65% for mean-variance investors. Easy to implement real-time.
**Applicability:** Foundational. But read against 3b/3c — the FX/commodity Sharpe claim is contested.

### 3b. Harvey et al (2018, ssrn-3175538) — "The Impact of Volatility Targeting"
The asset-class-dependence finding (see headline section). Sharpe benefit only for risk assets; tail-risk reduction for all. **The single most important nuance paper for our FX-heavy book.**

### 3c. Hood & Raughtigan (2024, ssrn-4773781) — "Volatility Targeting Is Trendy"
Vol-targeting alpha ≈ trend-following exposure via leverage effect; ~2/3 of apparent alpha; equities only. The JPM paper you named.

### 3d. Downside risk and vol-managed portfolios (Downside.pdf, Wang & Yan 2021, J Banking & Finance)
**Downside**-volatility-managed portfolios significantly outperform **total**-volatility-managed ones, including in out-of-sample real-time trading. Addresses the Cederburg et al critique of real-time vol management.
**Applicability:** If we adopt vol targeting, **target downside volatility, not total volatility.** Concrete refinement — only scale down on downside vol, which preserves upside participation. Codeable.

### 3e. Conditional Volatility Targeting (Conditional Volatility Targeting.pdf, Bongaerts/Kang/van Dijk 2020, FAJ)
Vol targeting only helps for a **limited range of factors/markets**, and works best when you **condition on extreme volatility states** rather than targeting continuously.
**Applicability:** Don't vol-target continuously — only intervene in extreme-vol regimes. Reduces turnover/cost. Pairs with the regime-detection cluster below.

### 3f. Cejnek & Mair (2021, ssrn-3629099) — "Understanding Volatility-Managed Portfolios"
Mechanism paper: vol management outperforms by **levering up in good times without increasing downside exposure** during severe news shocks.
**Applicability:** Explains *why* it works; useful for the hypothesis statement (CLAUDE.md §7 requires one). Context.

**Cluster 3 verdict:** Adopt vol targeting portfolio-wide, but: (a) justified by tail-control for FX/gold and Sharpe for equity indices (3b/3c), (b) target **downside** vol not total (3d), (c) consider **conditioning on extreme states** to cut turnover (3e). That's a precise spec, not "add vol targeting."

---

## Cluster 4 — Trend-following validation & implementation (validates existing EAs)

### 4a. Moskowitz, Ooi & Pedersen (2012, 1-s2.0-S0304405X11002613) — Time Series Momentum [JFE published version]
Already in `academic_review_2026-06.md` (the canonical TSMOM paper). The published JFE version of what we had. Common-factor-in-TSMOM-returns finding = the Day-7 mechanism.

### 4b. Hurst, Ooi & Pedersen — A Century of Evidence on Trend-Following (ssrn-2993026)
Already in `academic_review_2026-06.md`. 137 years, every decade positive, crisis alpha.

### 4c. Hamill, Rattray & van Hemert (2016, ssrn-2831926) — "Trend Following: Equity and Bond Crisis Alpha"
TSMOM 1960-2015. Returns **positively skewed** (like a long straddle); strongest performance in worst equity/bond environments = "crisis alpha."
**Applicability:** Reinforces that our trend EAs should be expected to have long stretches of small losses punctuated by big wins (positive skew) — exactly the GBPUSD/AUDJPY pattern in the trial. Sets correct expectations; argues against killing trend EAs after a rough patch.

### 4d. Babu, Hoffman, Levine, Ooi et al (AQR, ssrn-3487134) — "You Can't Always Trend When You Want"
Decomposes trend underperformance into (i) size of market moves, (ii) strategy's ability to capture them, (iii) diversification. Finds recent underperformance is almost entirely (i) — muted market moves — NOT strategy decay or lost diversification.
**Applicability:** Diagnostic framework. If our trend EAs underperform, this says check whether market moves were just small before concluding the strategy is broken. Prevents premature kills.

### 4e. Co (2023, ssrn-4545551) — "A New Approach to Trend-Following"
Argues reported trend profitability is overstated; proposes hierarchical-clustering + downside-risk weighting (accounting for distances between assets) instead of inverse-vol or equal-risk-contribution.
**Applicability:** Another correlation-aware construction method (cf. Cluster 1). The hierarchical clustering idea is interesting for grouping our EAs by hidden factor (e.g., the USD cluster). Medium.

### 4f. Shi & Lian (2025, ssrn-5140633) — "Trend Following Strategies: A Practical Guide"
Comprehensive survey. Key claim: **choice of time scale matters more than choice of trend measure** — "methodology matters less than selecting an appropriate time horizon." China futures 1999-2019, multi-scale combined strategy Sharpe 0.88.
**Applicability:** Reinforces the M10 barbell-timeframe-test task — time scale (M15/H1/H4) is the lever, not the indicator. Supports testing horizon selection over swapping Donchian for something fancier.

### 4g. Huuhka (2026 thesis, Hanken) — "Evolution of Trend-Following Profitability Across Macro Regimes"
Master's thesis. Trend profitability varies over time; macro factors don't systematically explain it (some pre-2012 effect). **Position sizing relative to realized volatility improves performance vs equal weighting.**
**Applicability:** Independent confirmation that vol-scaled sizing > equal weighting for trend. Student work (lower weight) but directionally consistent with the AQR/Baltas literature.

---

## Cluster 5 — Regime detection (deferred M11 task; some Phase-A-usable ideas)

### 5a. RADIANT (ssrn-6427863, Saraf 2026) — regime-adaptive allocation network
Hybrid LSTM + Bayesian HMM filter + hysteresis gating for regime detection on 1-min OHLC. Features: realized vol, **Hurst exponent, Shannon entropy**. "Sticky" transition matrix to avoid whipsaw.
**Verdict:** 1-minute frequency + deep learning = leans Phase B / skeptical. BUT the **feature set (Hurst, entropy, realized vol) for regime classification is usable at M15+** and the hysteresis idea (don't flip regimes too fast) is sound. Mine the features, skip the DL architecture.

### 5b. Fractal Market Dynamics / Hurst on NQ (ssrn-6744643, Ntingana 2026)
Rolling **Hurst exponent** via variance-ratio classifies 5-min bars into persistent (H>0.55) / neutral / anti-persistent (H<0.45). Trades in persistent regimes: 52.5% win, +$153 avg; anti-persistent: 44.8% win, +$47 — 3.25× trade-quality difference. Adds a realized-vol-z-score tail filter for position scaling.
**Applicability:** The **Hurst-exponent regime filter is genuinely interesting and Phase-A-portable** — "only take trend trades when H>0.55 (persistent regime)" could gate our Donchian EAs to avoid chop. The multi-timeframe-confirmation point (fractal self-similarity) supports our existing M15/H1/H4 structure. Worth a real test post-trial. Independent researcher (lower weight) but the method is classical and codeable.

### 5c. Cartea & Jaimungal HMM (from microstructure batch, #6 there)
Cross-referenced — HMM intraday regime detection. Same regime-detection theme.

**Cluster 5 verdict:** Regime detection is a deferred M11 task, but two Phase-A-portable ideas surface: **Hurst-exponent regime gating** (5b) and **hysteresis to avoid whipsaw** (5a). Both could reduce the chop-driven losses (e.g., GBPUSD's 2-2 trial record). Candidate research, not yet a build.

---

## Cluster 6 — Methodology template + FX-specific + skeptical

### 6a. Singha, Aguilera-Toste & Lahiri (2025, 2511.08571) — "Forecast-to-Fill: ...Gold Futures"
**A complete methodology template we should copy.** Gold, rolling 10yr→6mo walk-forward 2015-2025. Trend-momentum regime signal → **volatility-targeted, friction-aware positions via fractional, impact-adjusted Kelly sizing + ATR-based exits.** OOS Sharpe 2.88, max DD 0.52%, net of 0.7bps cost + square-root impact. **Bootstrap CI + SPA test p=0.000** (the Sullivan-Timmermann-White discipline we already mandated). Defines a friction-adjusted growth frontier capping AUM.
**Applicability — DIRECT & HIGH:** This is essentially a worked example of our entire M10 methodology — walk-forward + fractional Kelly + ATR exits + cost model + SPA test — applied to gold (we trade XAUUSD). **Use it as the reference implementation template for the post-trial backtest harness and the XAUUSD EAs specifically.** NASA/MIT/Sorbonne authors, recent, rigorous. Among the most useful papers in the batch.

### 6b. Menkhoff, Sarno, Schmeling & Schrimpf (2011, ssrn-1342968) — "Carry Trades and Global FX Volatility"
High-interest currencies load negatively on global FX-volatility innovations (crash risk); a global FX-vol risk factor explains >90% of carry portfolio cross-sectional returns. Liquidity risk matters too, less so.
**Applicability:** FX-specific. If we ever revive a carry EA (we killed the earlier ones), global-FX-vol is the risk factor to monitor/hedge. Also: a global-FX-vol spike is a regime signal that our FX EAs are entering a dangerous state — could feed a portfolio-level risk gate. Medium.

### 6c. Lim, Zohren & Roberts (2019, 1904.04912) — "Deep Momentum Networks"
LSTM that jointly learns trend estimation + position sizing, trained on Sharpe. Claims 2× improvement, holds to 2-3bps costs.
**Verdict — SKEPTICAL:** DL for TSMOM. Same reproducibility/overfit concerns as the Atha-Bolla finding (academic_review) and the RL-HFT papers. The *idea* of jointly learning trend+sizing is elegant, but DL-in-finance rarely survives live. Low priority; if anything, a Phase-B curiosity.

### 6d. Bloch (2025, ssrn-5278107) — "A Course on Systematic Trading with RMA" (153 pages)
A full course/book. Introduces Relative Moving Average (RMA) — a moving average with a dynamic price distribution around it for regime/disequilibrium detection without stationarity assumptions. Covers momentum + mean-reversion robustness to structural breaks, fakeouts, reversal traps.
**Applicability:** It's a textbook-length reference, not a single result. The RMA indicator is interesting (adaptive MA that knows its own uncertainty) and Phase-A-codeable. Too long to deep-read now; flagged as a reference to mine if we want a more adaptive trend indicator than Donchian. Medium, large time cost.

---

## What's genuinely actionable — ranked for Phase A (FTMO funded)

**Tier 1 — directly upgrades the M10 sizing calibration (the trial's #1 weakness):**
1. **Baltas (2673124) + Baltas-Kosowski (2140091)** — correlation-aware risk-parity sizing. THE Day-7 fix. Replace inverse-vol/independent-assumption aggregate cap with equal-risk-contribution accounting for the correlation matrix.
2. **Bayesian Kelly (6195358) + Recovery-Constrained Kelly (5284131)** — the actual sizing method for the next trial: cold-start shrinkage + FTMO-shaped recovery constraint. Better than the plain fractional Kelly currently specced in M10 #2.
3. **Forecast-to-Fill Gold (2511.08571)** — worked methodology template (walk-forward + fractional Kelly + ATR exits + cost model + SPA test). Reference implementation for the M10 backtest harness, esp. for XAUUSD.

**Tier 2 — vol targeting, applied correctly:**
4. **Harvey et al (3175538) + Hood-Raughtigan (4773781)** — the asset-class-dependence rule: vol targeting helps Sharpe only on equity indices (US500/US100), but cuts tail risk on all → adopt portfolio-wide justified by FTMO tail-control.
5. **Downside (Wang-Yan)** — target downside vol, not total vol.
6. **Conditional Vol Targeting (Bongaerts)** — condition on extreme-vol states to cut turnover.

**Tier 3 — regime gating (candidate research, post-trial test):**
7. **Hurst-exponent regime filter (6744643) + hysteresis (6427863)** — gate trend EAs to persistent regimes (H>0.55) to cut chop losses. Test before building.

**Tier 4 — validation/expectations (no build, just calibrate expectations):**
8. Hamill-Rattray-van Hemert (2831926), Babu et al (3487134), Shi-Lian (5140633) — trend is positively skewed, underperformance usually = small moves not decay, time scale > indicator choice. Prevents premature EA kills.

**Skeptical / Phase-B / low priority:**
- Deep Momentum Networks (1904.04912), RADIANT DL architecture (6427863) — DL-in-finance, reproducibility risk.
- Bloch RMA course (5278107) — reference textbook, mine later.
- Menkhoff et al (1342968) — only if we revive carry.

---

## How this maps to existing plans

- **M10 #2 (sizing calibration) — UPGRADE.** Currently specced with classical fractional Kelly. The batch says: (a) correlation-aware risk-parity (Baltas) instead of independent-asset inverse-vol, (b) Bayesian Kelly cold-start shrinkage (Sukhov), (c) recovery-constrained Kelly (Lee, FTMO-shaped). These are concrete method upgrades, not new tasks.
- **M10 #1 (post-mortem factor decomposition) — REINFORCED.** Baltas correlation work + Harvey asset-class dependence back the cross-asset-correlation premise.
- **M10 backtest harness — TEMPLATE FOUND.** Forecast-to-Fill Gold (2511.08571) is a worked example of walk-forward + Kelly + ATR + cost + SPA. Copy its structure.
- **M10 barbell-timeframe test — REINFORced.** Shi-Lian: time scale matters more than indicator.
- **NEW candidate (not yet a task): vol-targeting overlay** — adopt portfolio-wide, downside-vol, conditional on extreme states, justified by FTMO tail-control. Worth a dedicated M10 Tier 2 task post-trial.
- **NEW candidate (not yet a task): Hurst-regime gate** for trend EAs. Test post-trial.
- **M11 regime detection — candidate methods identified** (Hurst, HMM, hysteresis).

---

## Open items / honesty flags
- **Triage depth only.** Equations not line-checked. Full text in `Downloads/_vol_txt/` for implementation-time reads.
- **2 Google Books links NOT scraped** (textbooks — likely Chan "Quantitative Trading" / Carver "Systematic Trading" or similar by the id pattern, but I will NOT guess titles). If they matter, supply the PDFs or confirm titles.
- **Xu, "Beyond Volatility Timing" (JPM 2026)** — citation only, no PDF supplied. Theme (target timing vs vol timing) is adjacent to Cluster 3; get the PDF if we pursue vol targeting seriously.
- **Several papers are working papers / theses / independent researchers** (Huuhka, RADIANT, Fractal-NQ, Bayesian Kelly, Recovery Kelly) — lower citation weight than the AQR/NBER/JFE papers. Their *methods* are sound and codeable; their *claimed returns* get the full bootstrap-skepticism treatment (Sullivan-Timmermann-White) before we trust any of them.
- **No equation re-derivation.** Before implementing any sizing method, read the actual math in full from the extracted text.

## How to use this document
1. **During the trial:** reference only.
2. **Post-trial, opening M10 #2 (sizing):** this is the method upgrade source. Read Baltas (2673124, 2140091), Bayesian Kelly (6195358), Recovery Kelly (5284131) in FULL before coding the sizing module.
3. **Building the M10 backtest harness:** use Forecast-to-Fill Gold (2511.08571) as the structural template.
4. **If adopting vol targeting:** Harvey (3175538) for the asset-class rule, Wang-Yan downside, Bongaerts conditional. Justify per-EA by Sharpe (equity indices) vs tail-control (FX/gold).
5. **Regime gating experiments:** Hurst (6744643) + hysteresis (6427863).
