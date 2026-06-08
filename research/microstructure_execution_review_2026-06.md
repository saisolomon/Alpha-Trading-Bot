# Market Microstructure, Market-Making & Optimal Execution — Literature Review

> Created: 2026-06-08. User supplied a 20-PDF reading list (Downloads) spanning market-making / optimal-execution stochastic control, RL-for-HFT, FX microstructure, and FX exchange-rate economics. Intent (confirmed): **(1) post-funded crypto market-making / execution on Hyperliquid/Bybit, AND (4) FX microstructure to improve the current FX EAs' entry/exit.**
>
> **Depth disclosure (honest):** This is a triage-grade synthesis. PDFs were extracted to text with `pypdf` (the harness `pdftoppm` renderer is unavailable; firecrawl credits exhausted). I read title + abstract + conclusion + intro-head for 18 of 20; decoded the glyph-encoded header of w8116; **w1112 is image-only (0 text layer) — UNREAD, needs OCR.** Full extracted text for all 19 readable papers sits in `Downloads/_corpus_txt/` if any paper earns a page-by-page deep-read later. Equation-level derivations were NOT line-checked — where I cite a model mechanism it's from the abstract/conclusion, not a re-derivation.
>
> **Standing constraint:** Planning.md (2026-05-28) documents that scalping/HFT is NOT pursued on the MT5/OANDA retail stack — no trustworthy L2 depth, retail latency, dealer spreads eat the edge. **None of the MM/execution papers below are deployable on the current stack.** Their home is M11 post-funded, on a real order book (Hyperliquid on-chain LOB / Bybit CEX). The FX-microstructure subset has limited, careful applicability to the current EAs.

---

## The 20 papers at a glance

| # | File | Paper (author, year) | Cluster | Stack relevance |
|---|---|---|---|---|
| 1 | HighFrequency...Orderbook | **Avellaneda & Stoikov (2008)** — HF trading in a LOB | MM canonical | M11 crypto MM |
| 2 | 1106.5040 | **Guilbaud & Pham (2011)** — Optimal HFT w/ limit & market orders | MM control | M11 crypto MM |
| 3 | 1310.1756 | **Fodra & Pham (2015)** — HFT, Markov renewal, small risk-aversion | MM control | M11 crypto MM |
| 4 | sigest | **Cartea, Jaimungal & Ricci** — Algo trading, stochastic control, mutually-exciting (Hawkes) | MM control | M11 crypto MM |
| 5 | ssrn-1964781 | **Cartea, Jaimungal & Ricci** — "Buy Low Sell High: a HFT Perspective" (SIAM J Fin Math version of #4) | MM control | M11 crypto MM |
| 6 | Modelling_Asset_Prices... | **Cartea & Jaimungal (2013)** — Modelling asset prices for algo/HF trading (HMM) | MM/regime | M11 + regime ideas |
| 7 | ssrn-2578733 | **Huang, Jaimungal & Nourian** — Mean-Field Game strategies for optimal execution | Execution | M11 execution |
| 8 | 3580305.3599813 | **Han et al. (KDD 2023)** — Efficient continuous-space policy optimization (DRL) for HFT | RL-HFT | M11 (skeptical) |
| 9 | Deep_RL_for...Order | **Dong, Zhang & Xin (2024)** — DRL for order-book-imbalance HFT | RL-HFT | M11 (skeptical) |
| 10 | 2205.10743 | **Atha & Bolla (2022)** — Do DL & news beat conventional on Forex? (NEGATIVE) | ML-FX | already in academic_review |
| 11 | S89 | **Sarno & Taylor (2001)** — Microstructure of the FX market: a survey | FX micro | **current FX EAs** |
| 12 | w8116 | **Evans (2001)** — FX trading and exchange rate dynamics (NBER) | FX micro (order flow) | **current FX EAs** |
| 13 | ssrn-1935858 | **King, Osler & Rime (2011)** — FX market structure, players, evolution | FX micro | **current FX EAs** |
| 14 | ssrn-2268871 | **King, Osler & Rime (2013)** — Microstructure approach to FX: back & forward | FX micro | **current FX EAs** |
| 15 | ssrn-4063213 | **Chaboud, Rime & Sushko (2023)** — The Foreign Exchange Market | FX micro | **current FX EAs** |
| 16 | taylor-exr-jel-1995 | **Taylor (1995, JEL)** — The Economics of Exchange Rates | FX macro | context only |
| 17 | c6829 | **Mussa (1984, NBER)** — Theory of Exchange Rate Determination | FX macro | context only |
| 18 | S42 | **Isard (1978, Princeton)** — Exchange-Rate Determination survey | FX macro | context only (dated) |
| 19 | 2009_Pbl_Westerhoff | **Westerhoff (2009)** — Exchange rate dynamics: a nonlinear survey | FX behavioral | **current FX EAs** |
| 20 | w1112 | **Levich (1983)** — Empirical Studies of Exchange Rates: Price Behavior, Rate Determination & Market Efficiency (NBER) | FX macro/efficiency | context only (dated) |

---

## Cluster A — Market-making & optimal execution (the "HFT math" core)

**The seven papers (1-7) that form a coherent body of stochastic-control market-making theory.** This is the real intellectual backbone of algorithmic market-making, and it's directly usable on a real order book — i.e. **M11 crypto, not the current MT5 stack.**

### A1. Avellaneda & Stoikov (2008) — the foundational paper
**The single most important paper in the stack.** Establishes the canonical market-making framework:
- A dealer posts bid/ask quotes around a **reservation price** `r(s,t) = s − q·γ·σ²·(T−t)`, where `s` = mid, `q` = current inventory, `γ` = risk aversion, `σ²` = variance. The reservation price skews quotes against your inventory — if you're long, you quote lower to encourage selling.
- The **optimal bid-ask spread** is `δ = γσ²(T−t) + (2/γ)·ln(1 + γ/k)` where `k` relates to order-book liquidity/arrival intensity.
- Inventory risk vs. spread capture is the central tradeoff.
**Applicability:** This is the literal blueprint for a crypto market-making strategy on Hyperliquid/Bybit. Every later paper here extends it. If we build ONE MM strategy post-funded, it starts here.

### A2. Guilbaud & Pham (2011) — limit + market order mixing
Extends A-S: the MM continuously posts limit orders at best bid/ask (or one tick inside for queue priority), AND can cross the spread with market orders to manage inventory. Spread modeled as a Markov chain (discrete tick multiples); executions as Cox processes whose intensity depends on the spread and the trader's quoted price. Solved via stochastic control.
**Applicability:** The "limit-or-market" decision is exactly the choice a crypto MM faces. The queue-priority modeling matters on Hyperliquid's on-chain LOB where priority is explicit.

### A3. Fodra & Pham (2015) — adverse selection, tractable
Market-making in a Markov Renewal Process price model. Key contribution: models **two forms of adverse selection** — (a) big market orders that move the price against you, (b) small orders that reduce your fill probability. Perturbation method gives near-closed-form optimal controls for small risk aversion, cutting compute cost.
**Applicability:** Adverse selection is THE killer risk for a small MM. This paper names and models it. Critical reading before deploying any MM strategy with real money.

### A4/A5. Cartea, Jaimungal & Ricci — Hawkes / short-term-alpha (sigest + ssrn-1964781 are the same work)
**The most directly actionable MM paper for a signal-driven trader.** Uses **mutually-exciting (Hawkes) processes** to model market-order clustering and the shape of the LOB. Distinguishes **influential vs non-influential market orders** — influential MOs move the midprice and trigger more activity; non-influential ones just walk the book. Models **short-term-alpha** (the short-lived predictable drift in midprice after an influential MO/news) as a zero-mean-reverting process that jumps on influential MO arrivals.
**The killer finding:** *"HF traders who do NOT include predictors of short-term-alpha in their strategies are driven out of the market because they are adversely selected by better-informed traders."* In plain terms: **a naive market-maker that ignores order-flow toxicity gets picked off and dies.** You must predict short-term-alpha to survive.
**Applicability:** This is the bridge between our existing signal-generation skill and market-making. We already build directional signals; this says a viable crypto MM must fold a directional short-term-alpha predictor into its quoting. Highest-value MM paper for our specific skillset.

### A6. Cartea & Jaimungal (2013) — HMM intraday regimes
Uses a **hidden Markov model** to classify intraday market states by trade duration (waiting time between trades). Empirical finding (2001 vs 2008 NYSE data): by 2008, the vast majority of trades occurred in the **shortest-duration states**, and those states had the **smallest price impact** (lowest volatility of price innovations) — fast trading → low volatility regime. Confirms Diamond-Verrecchia / Admati-Pfleiderer theory.
**Applicability — DUAL:** (a) MM quoting should condition on the intraday regime. (b) **The HMM regime-detection method is directly relevant to the deferred M11 regime-detection task** and even to our current EAs' "is this a trending or ranging session?" question. This is the one paper that touches both the MM cluster AND our existing strategy improvement.

### A7. Huang, Jaimungal & Nourian — Mean-Field Game execution
Optimal **execution** (not market-making) when many agents trade simultaneously: a major agent liquidating a big position, many minor HFT agents detecting and trading against it, plus noise traders. Solves the otherwise-intractable N-agent stochastic game via mean-field approximation. Accounts for permanent price impact from all trader types.
**Applicability:** This is about executing LARGE orders without getting front-run. Lower priority for us — our position sizes (even post-funded) won't be large enough to need mean-field execution against predatory HFTs for a while. File for when AUM is large enough that our own order flow moves the book.

---

## Cluster B — RL / ML for HFT (treat with skepticism)

### B1. Han et al. (KDD 2023) — DRPO continuous-space policy optimization
Deep RL for HFT portfolio optimization. Models portfolio management as an MDP, infers equity weights directly in continuous action space, uses probabilistic dynamic programming to avoid trajectory-sampling cost. Claims significant improvement over baselines on 3 benchmark datasets; says it was deployed in real HFT systems.
**Verdict:** Real venue (KDD), real method. But RL-for-trading has a notorious reproducibility / overfitting problem — backtests look great, live rarely matches. The deflated-Sharpe / bootstrap discipline (academic_review_2026-06.md, Sullivan-Timmermann-White) applies double here. **Interesting, not a priority.**

### B2. Dong, Zhang & Xin (2024) — DQN on order-book imbalance
DQN using order-book imbalance (OBI) as the predictive signal for short-term price moves on AAPL. **Claims:** 15.2% cumulative return, Sharpe 1.8, max DD 5.3%, Calmar 2.9 — beating MA-crossover (8.5%), market-making (10.3%), random (-2.1%).
**Verdict — RED FLAGS:** Single asset (AAPL), single 12-month period, no transaction-cost detail in the conclusion, weak venue (a low-profile open-access journal), no walk-forward/OOS robustness shown. This is the exact "backtest looks great" profile CLAUDE.md §9 warns about. **The OBI signal itself is real and worth knowing** (order-book imbalance does predict short-term direction — it's the same short-term-alpha Cartea-Jaimungal-Ricci model rigorously), but **trust the Cartea Hawkes paper for the mechanism, not this DQN for the returns.**

### B3. Atha & Bolla (2022) — DL & news on Forex (NEGATIVE)
Already cataloged in `academic_review_2026-06.md`. Simple regression beats LSTM/RNN; news sentiment doesn't help. Reinforces "don't chase deep learning for FX."

**Cluster B takeaway:** Order-book imbalance / short-term-alpha is a real, exploitable microstructure signal for crypto MM. But get the mechanism from the rigorous stochastic-control papers (A4/A5), not the RL papers. RL-for-HFT is a research curiosity for us, gated behind the same bootstrap discipline as everything else, and low priority.

---

## Cluster C — FX microstructure (DIRECTLY relevant to current FX EAs)

**This is the bucket with near-term applicability** — these inform how our existing EURUSD/GBPUSD/AUDJPY EAs could time entries/exits better, without changing the stack.

### C1. Sarno & Taylor (2001) — Microstructure of the FX market: a survey
**The canonical FX-microstructure survey.** Core thesis: short-run exchange-rate dynamics are driven by **order flow, heterogeneity among agents, and private information** — NOT by macro fundamentals (which famously fail to explain short-run FX, the "exchange-rate disconnect puzzle"). Order flow is the proximate cause of price moves.
**Applicability:** Validates that our FX EAs operate in a regime where **flow and technicals dominate fundamentals at short horizons** — which is exactly why technical strategies (London momentum, RSI fade) work on FX intraday. Confirms the thesis; doesn't directly give a new signal.

### C2. Evans (2001) — FX Trading and Exchange Rate Dynamics (NBER)
The Evans-Lyons order-flow research line. Order flow (signed transaction volume) carries private information and predicts exchange-rate moves at horizons where macro can't.
**Applicability:** Order flow is the FX equivalent of order-book imbalance. We don't have true interdealer order-flow data on OANDA retail, BUT tick volume + aggressor-side proxies are a weak stand-in. Possible (speculative) enhancement: add a tick-volume-imbalance filter to the London momentum EA. Low confidence — retail tick volume is a poor proxy for true order flow. Flag, don't build.

### C3 / C4. King, Osler & Rime (2011, 2013) — FX market structure & microstructure
Two complementary works. 2011: maps the players (dealers, retail, HFT) and how electronic trading transformed FX — transparency up, costs down, volume tripled. 2013: "looking back and looking forward" — order flow, agent heterogeneity, private information as the determinants of short-run FX; flags open questions on private information, liquidity, price discovery as markets get faster.
**Applicability:** Context for WHO is on the other side of our FX trades and HOW the market has evolved. The practical nugget: **retail FX traders are at an information disadvantage to dealers** — our edge has to come from systematic discipline and risk management, not information. Reinforces the existing strategy (defensible technical edges + tight risk), doesn't add a signal.

### C5. Chaboud, Rime & Sushko (2023) — The Foreign Exchange Market
Most recent FX-structure survey. Modern FX: bank liquidity provision challenged by HFT firms, fragmented electronic market, high-frequency cross-asset correlations (especially with futures) now more important, plus the FX-fixing scandal and flash events.
**Applicability — TWO concrete nuggets:**
- **"high-frequency cross-asset correlations, especially with the futures market, have become more important"** — directly relevant to the Day-7 cluster-loss problem. Our AUDJPY/XAUUSD/GBPUSD all moved together on USD strength. This paper says cross-asset correlation is a structural feature of modern FX, not noise. **Supports the M10 factor-decomposition task's premise.**
- **Flash events** — the XAUUSD/gold-fix EA trades around a fixing window; this paper's discussion of the FX-fixing scandal is a cautionary note on trading into fixes (the very thing XAUUSD_M15_LondonFix does). Worth re-reading that EA's assumptions against this paper before scaling it.

---

## Cluster D — FX exchange-rate economics (context only, mostly dated)

### D1. Taylor (1995, JEL) — The Economics of Exchange Rates
Canonical survey of exchange-rate economics: flexible-price monetary model, PPP, the fundamentals-disconnect puzzle. Establishes that **macro fundamentals fail to explain short-run FX** (the Meese-Rogoff result) — which is precisely why microstructure/technical approaches exist.
**Applicability:** Foundational context. Explains WHY our technical FX EAs can work at all (fundamentals don't bind short-run). No direct signal.

### D2. Mussa (1984, NBER) — Theory of Exchange Rate Determination
Asset-price view of exchange rates; overshooting in response to monetary shocks. Classic theory.
**Applicability:** Context only. Dated (1984). No actionable signal.

### D3. Isard (1978, Princeton) — Exchange-Rate Determination survey
Bretton-Woods-era survey of FX views. **Heavily dated (1978, pre-floating-era maturity).** Historical interest only.
**Applicability:** None actionable. Skip.

### D5. Levich (1983, NBER w1112) — Empirical Studies of Exchange Rates [OCR-recovered 2026-06-08]
Originally unreadable (image-only PDF); recovered via PyMuPDF render → vision read. Levich survey of (a) exchange-rate price behavior, (b) rate determination under the asset-market approach, (c) **market efficiency**. Abstract's central tension: *"Several recent studies claim that speculative profit opportunities are present, but it is unclear whether these are related to risk premiums or actual market inefficiencies."* — the classic 1980s unresolved efficiency/risk-premium debate.
**Applicability:** Context only, and **dated (1983, pre-microstructure-revolution).** Its market-efficiency conclusions are superseded by Park-Irwin (2007, in academic_review) and Sarno-Taylor (2001, C1). The "is it a risk premium or an inefficiency?" question it raises is, notably, the same question our whole project answers operationally: we don't care which it is as long as the edge is real, persistent, and survives costs. Historical interest; no new signal.

### D4. Westerhoff (2009) — Exchange rate dynamics: a nonlinear survey
**More interesting than the other macro papers.** Surveys **chartist-fundamentalist agent-based models**: FX moves are driven by interaction of boundedly-rational speculators using BOTH technical and fundamental rules. Key mechanism: when price is near fundamental value, traders switch to technical analysis (driving price away); when misalignment is large, they switch to fundamentals (pulling it back) → endogenous complex cycles.
**Applicability:** This is a *theoretical foundation for why technical trading rules persist and are self-sustaining* — the chartist share of the market is endogenous and never goes to zero. Mild support for our technical EAs' durability. Also a conceptual model for regime-switching (technical-dominated vs fundamental-dominated regimes) that connects to the HMM regime work in A6.

---

## Phase A vs Phase B applicability (the deployment-reality split)

**"Actively funded" is two phases with totally different constraints. Most of this library is Phase B, not Phase A. Do not let the volume of market-making papers create pressure to deploy them on MT5 — that's the scalping/HFT trap documented as off-limits in Planning.md (2026-05-28).**

### Phase A — FTMO funded, still on MT5 / OANDA (immediately post-trial)
Retail rails: no trustworthy L2 depth, dealer spreads, retail latency. **The MM/HFT papers are NOT deployable here at all.** Only the FX-microstructure cluster applies, and it *informs the existing EAs* rather than creating new strategies.

| Paper | Phase A use |
|---|---|
| #15 Chaboud-Rime-Sushko (2023) | ✅ **Strongest.** Cross-asset correlation is structural in modern FX → backs M10 factor-decomposition + USD-cluster sizing. Day-7 cluster loss IS this thesis. Flags FX-fixing pathology for XAUUSD_M15_LondonFix. |
| #10 Atha-Bolla (2022) | ✅ Defensive. What NOT to build (no deep learning, no news sentiment). |
| #11 Sarno-Taylor / #13-#14 King-Osler-Rime | 🟡 Context. Validate that short-run FX is flow/technical-driven. No new signal. |
| #12 Evans (order flow) | 🟡 Speculative. Tick-volume-imbalance filter idea; retail tick vol is a poor proxy. Flag, don't build. |
| #19 Westerhoff | 🟡 Context. Why technical rules persist. |
| All of Cluster A (#1-7), Cluster B (#8-9) | ❌ **Not deployable.** Require a real order book. Wait for Phase B. |
| Cluster D macro (#16-18, #20) | ❌ Context only, no code in them, ever. |

**Phase A reality: 1 genuinely actionable paper (#15), 1 defensive (#10), rest context. ZERO new strategies from this library.** The MM papers are dead weight on MT5.

### Phase B — self-funded crypto, post-FTMO, Nautilus + Hyperliquid/Bybit (real LOB)
This is the actual home of what was downloaded. Cluster A unlocks fully. See the M11 ranking below.

---

## What's genuinely actionable — ranked

### For the current FX EAs (near-term, M10-adjacent — but NOT during the trial)
1. **Cross-asset correlation is structural (Chaboud 2023, C5).** Reinforces the M10 factor-decomposition task — the Day-7 USD cluster loss is a known feature of modern FX, not bad luck. *Already captured in M10 #1; this is academic backing, not new work.*
2. **Re-examine XAUUSD_M15_LondonFix against the FX-fixing-scandal literature (Chaboud 2023, C5).** Trading into a fix has known pathologies. Worth a sanity re-read of that EA's thesis post-trial. → small new consideration for the EA's post-mortem.
3. **Order-flow / tick-volume imbalance as a weak entry filter (Evans 2001 C2, Cartea-Jaimungal-Ricci A4).** Speculative — retail tick volume is a poor order-flow proxy. Flag as a research idea, low confidence, do NOT build without validation.

### For M11 post-funded crypto market-making (the real prize)
1. **Avellaneda-Stoikov (A1)** — the foundational quoting framework. Start here.
2. **Cartea-Jaimungal-Ricci Hawkes / short-term-alpha (A4/A5)** — the "you must predict short-term-alpha or get adversely selected" result. The bridge from our signal skill to MM.
3. **Fodra-Pham adverse selection (A3)** — name and model the killer risk before risking capital.
4. **Guilbaud-Pham limit-vs-market (A2)** — the execution decision on a real LOB.
5. **Cartea-Jaimungal HMM regimes (A6)** — quoting conditioned on intraday regime; also feeds general regime-detection.

### Skeptical / low priority
- RL-for-HFT (B1, B2) — real methods, but reproducibility/overfit risk; gated behind bootstrap discipline. Get the OBI mechanism from A4, not the DQN returns from B2.
- FX macro (D1-D3) — context only, no signals.

---

## How this maps to existing plans (no new milestones — extends what exists)

- **M11 crypto market-making — TASKS ADDED to Tasks.md 2026-06-08.** Two tasks now in M11 off-MT5 section: (1) first crypto market-maker (Avellaneda-Stoikov baseline, full §4 pipeline), (2) short-term-alpha / adverse-selection guard (the Cartea-Jaimungal-Ricci survival requirement). MM is a NEW strategy type for us; strictly Phase B (real LOB, post-Nautilus).
- **M11 regime detection — TASK ADDED to Tasks.md 2026-06-08.** Regime-detection module (HMM per Cartea-Jaimungal A6 + Hurst + hysteresis), dual-use for crypto-MM quoting and Alpha-Factory candidate evaluation.
- **M10 factor decomposition:** Chaboud 2023 (C5) is academic backing for the cross-asset-correlation premise. Already in M10 #1.
- **M10 cost-model — EURGBP cointegration-stability sub-bullet ADDED 2026-06-08** (cross-referenced from academic_review #7).
- **academic_review_2026-06.md:** the Atha-Bolla negative DL finding is already there; this doc covers the other 19.

## Open items / honesty flags
- **w1112.pdf RESOLVED 2026-06-08.** Was image-only/unreadable; recovered via PyMuPDF page-render → vision read of pages 1-2. Confirmed: Levich (1983) FX-efficiency survey, Cluster D context-only. No longer an open item.
- **w8116 (Evans)** identified via decoded header; abstract/conclusion not cleanly extracted (glyph-encoded body). Identity is certain; detailed findings are from my read of the Evans-Lyons literature line, flagged as such. Could be fully recovered via the same PyMuPDF-render → vision method if it becomes load-bearing.
- **No equations were re-derived or line-checked.** Model mechanisms cited are from abstracts/conclusions. Before implementing any MM strategy, the actual paper math must be read in full from `Downloads/_corpus_txt/` (extracted, available) or the original PDFs.
- This synthesis is **triage depth, not implementation depth.** Sufficient to decide what's worth building and when; NOT sufficient to code from. Each MM paper needs a full read at build time.

## How to use this document
1. **During the trial:** reference only. No action.
2. **Post-funded, when M11 crypto MM is on the table:** this is the reading-list-with-verdicts. Read A1 → A4 → A3 → A2 → A6 in that order, in full, from the extracted text.
3. **Post-trial FX EA post-mortem:** Chaboud 2023 (C5) backs the cross-asset-correlation finding; re-read the gold-fix EA against the FX-fixing discussion.
4. If w1112 turns out to matter, OCR it first.
