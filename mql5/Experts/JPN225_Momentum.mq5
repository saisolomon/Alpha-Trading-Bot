//+------------------------------------------------------------------+
//| JPN225_Momentum.mq5                                              |
//| Single-asset time-series momentum on Nikkei 225 (JPN225).        |
//|                                                                  |
//| Mechanism: when the trailing 12-month log return is positive,    |
//| hold a long position; when negative, hold a short. Rebalance     |
//| at month-end. Position size = inverse of 60-day realised vol so  |
//| target per-trade risk stays constant across regimes.             |
//|                                                                  |
//| Why JPN225 specifically:                                          |
//|   - Backtest 2018-2026 on the 9-index TSMOM universe (US500,     |
//|     USTEC, US30, JPN225, HK50, AUS200, FRA40, UK100, EUSTX50)    |
//|     showed JPN225 with the most robust single-asset Sharpe:      |
//|     +0.80 over 924 bars (~3.5 yrs). Only USTEC was higher        |
//|     (+1.15) but only had 562 bars -- too short to be sure it's    |
//|     not an AI-rally artifact.                                     |
//|   - JPN225 is the only Asian-session market in our portfolio,     |
//|     so this brings genuine geographic diversification.            |
//|   - BoJ's ultra-loose policy through 2024 + Japan corporate-      |
//|     reform-driven re-rating (Buffett's investments + 2023        |
//|     governance reforms) creates a fundamental backdrop where      |
//|     trend-following has structural support.                       |
//|                                                                  |
//| Academic backing:                                                 |
//|   Moskowitz, Ooi, Pedersen (2012), J.Finance, "Time Series        |
//|   Momentum." 60+ futures markets, all positive Sharpe at 12m     |
//|   lookback, average Sharpe ~0.4 per asset, ~1.0 portfolio.        |
//|                                                                  |
//| Co-existence with US500_MeanRev: orthogonal. MR fires on short-   |
//| term oversold dips; this fires on long-term trend regime. No      |
//| symbol overlap. No interference.                                  |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input string  InpSymbol              = "JPN225";
input int     InpMomentumLookback    = 252;       // 12 months D1
input int     InpVolLookback         = 60;        // 3 months for inverse-vol sizing
input double  InpTargetVolPerLeg     = 0.10;      // target 10%/yr per-leg vol
input double  InpPerTradeRiskPct     = 0.005;     // hard cap; 0.5% per trade
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 2.0;       // wider stop for trend strategies
input int     InpRebalanceBars       = 21;        // ~monthly
input bool    InpDryRun              = true;

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
long g_ftmo_handle    = 0;
datetime g_last_bar_time = 0;
int  g_bars_since_rebalance = 9999;  // force first eval
int  g_current_position = 0;         // -1 = short, 0 = flat, +1 = long
ulong g_position_ticket = 0;
double g_position_stop = 0.0;
double g_entry_price = 0.0;

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   PrintFormat("[JPN225_Momentum] Unknown account_type '%s'", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| Load N most recent CLOSED bars (chronological order)             |
//+------------------------------------------------------------------+
bool LoadCloses(const string symbol, const int n_bars, double &out[]) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(symbol, _Period, 1, n_bars, rates);
   if(got != n_bars) {
      PrintFormat("[JPN225_Momentum] CopyRates(%s) returned %d want %d",
                  symbol, got, n_bars);
      return false;
   }
   ArrayResize(out, n_bars);
   for(int i = 0; i < n_bars; i++) {
      out[n_bars - 1 - i] = rates[i].close;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Compute signal: sign of 12m log return + realised vol of 60d     |
//+------------------------------------------------------------------+
bool ComputeSignal(int &out_side, double &out_realised_vol, double &out_last_close) {
   int n = InpMomentumLookback + InpVolLookback + 5;
   double closes[];
   if(!LoadCloses(InpSymbol, n, closes)) return false;

   double last = closes[n - 1];
   double anchor = closes[n - 1 - InpMomentumLookback];
   if(last <= 0 || anchor <= 0 ||
      !MathIsValidNumber(last) || !MathIsValidNumber(anchor)) {
      Print("[JPN225_Momentum] WARN invalid close prices in window");
      return false;
   }
   double twelvem_ret = MathLog(last / anchor);
   out_side = (twelvem_ret > 0) ? +1 : (twelvem_ret < 0) ? -1 : 0;
   out_last_close = last;

   // Realised vol (annualised) over the last InpVolLookback bars
   double sum = 0.0, sum_sq = 0.0;
   int count = 0;
   for(int i = n - InpVolLookback; i < n; i++) {
      if(closes[i] <= 0 || closes[i-1] <= 0) continue;
      double r = MathLog(closes[i] / closes[i-1]);
      sum += r;
      sum_sq += r * r;
      count++;
   }
   if(count < 5) return false;
   double mean = sum / count;
   double variance = sum_sq / count - mean * mean;
   if(variance <= 0) return false;
   out_realised_vol = MathSqrt(variance) * MathSqrt(252.0);
   return true;
}

//+------------------------------------------------------------------+
//| Compute ATR for stop-loss sizing                                 |
//+------------------------------------------------------------------+
bool ComputeAtr(const string symbol, const int period, double &out_atr) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(symbol, _Period, 1, period + 5, rates);
   if(got < period + 1) return false;
   double sum = 0.0;
   for(int i = 0; i < period; i++) {
      double tr = MathMax(rates[i].high - rates[i].low,
                  MathMax(MathAbs(rates[i].high - rates[i+1].close),
                          MathAbs(rates[i].low  - rates[i+1].close)));
      sum += tr;
   }
   out_atr = sum / period;
   return out_atr > 0 && MathIsValidNumber(out_atr);
}

//+------------------------------------------------------------------+
//| Compute lot size: target_vol / realised_vol gives leg-weight,    |
//| then convert to lots via the symbol's notional contract size.    |
//+------------------------------------------------------------------+
double ComputeLots(const double equity, const double realised_vol,
                    const double atr) {
   if(realised_vol <= 0 || atr <= 0 || equity <= 0) return 0.0;
   // Inverse-vol weight: each leg targets InpTargetVolPerLeg / yr
   double leg_weight = InpTargetVolPerLeg / realised_vol;
   // Cap at the per-trade-risk-pct ATR-based cap so we never blow
   // through risk on a low-vol regime sudden-spike.
   double atr_risk_cap = (equity * InpPerTradeRiskPct) /
                          (InpAtrStopMult * atr *
                           SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE) /
                           SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE));
   double raw_lots = leg_weight * equity * 0.01;  // 1% notional per unit weight
   // Take the MIN of vol-target and ATR-risk cap so neither sizing
   // approach can exceed the other's safety bound.
   double lots = MathMin(raw_lots, atr_risk_cap);
   double step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   double min_v = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double max_v = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / step) * step;
   lots = MathMax(min_v, MathMin(max_v, lots));
   return lots;
}

//+------------------------------------------------------------------+
//| Send / close orders                                              |
//+------------------------------------------------------------------+
bool SendOrder(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double tp) {
   if(InpDryRun) {
      PrintFormat("[JPN225_Momentum] DRY-RUN: would %s %.2f %s  sl=%.2f tp=%.2f",
                  (type==ORDER_TYPE_BUY?"BUY":"SELL"), lots, InpSymbol, sl, tp);
      return true;
   }
   MqlTradeRequest req; MqlTradeResult res; MqlTradeCheckResult chk;
   ZeroMemory(req); ZeroMemory(res); ZeroMemory(chk);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = InpSymbol;
   req.volume       = lots;
   req.type         = type;
   req.price        = (type==ORDER_TYPE_BUY)
                      ? SymbolInfoDouble(InpSymbol, SYMBOL_ASK)
                      : SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   req.sl           = sl;
   req.tp           = tp;
   req.deviation    = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = "JPN225_Momentum";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[JPN225_Momentum] OrderCheck rejected retcode=%d comment=%s",
                  chk.retcode, chk.comment);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[JPN225_Momentum] OrderSend FAILED retcode=%d", res.retcode);
      return false;
   }
   g_position_ticket = res.order;
   g_entry_price = res.price;
   g_position_stop = sl;
   PrintFormat("[JPN225_Momentum] %s filled  ticket=%I64u px=%.2f vol=%.2f sl=%.2f tp=%.2f",
               (type==ORDER_TYPE_BUY?"BUY":"SELL"), res.order, res.price, res.volume, sl, tp);
   return true;
}

void CloseCurrentPosition(const string reason) {
   if(g_current_position == 0) return;
   if(InpDryRun) {
      PrintFormat("[JPN225_Momentum] DRY-RUN: would CLOSE (%s)", reason);
      g_current_position = 0;
      g_position_ticket = 0;
      return;
   }
   if(!PositionSelect(InpSymbol)) {
      g_current_position = 0;
      g_position_ticket = 0;
      return;
   }
   double vol = PositionGetDouble(POSITION_VOLUME);
   ENUM_ORDER_TYPE close_t = (g_current_position == +1) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = InpSymbol;
   req.volume       = vol;
   req.type         = close_t;
   req.position     = PositionGetInteger(POSITION_TICKET);
   req.price        = (close_t==ORDER_TYPE_BUY)
                      ? SymbolInfoDouble(InpSymbol, SYMBOL_ASK)
                      : SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   req.deviation    = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = StringFormat("JPN225_Momentum %s", reason);
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[JPN225_Momentum] Close failed: retcode=%d", res.retcode);
      return;
   }
   PrintFormat("[JPN225_Momentum] CLOSED (%s) at %.2f", reason, res.price);
   g_current_position = 0;
   g_position_ticket = 0;
}

//+------------------------------------------------------------------+
//| OnInit / OnDeinit                                                 |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[JPN225_Momentum] init  symbol=%s lookback=%dd rebal=%dd target_vol=%.1f%%  dry_run=%s",
               InpSymbol, InpMomentumLookback, InpRebalanceBars,
               InpTargetVolPerLeg*100, (string)(InpDryRun?"true":"false"));
   SymbolSelect(InpSymbol, true);
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) {
      Print("[JPN225_Momentum] FATAL: ftmo_new_account returned 0");
      return INIT_FAILED;
   }
   PrintFormat("[JPN225_Momentum] FTMO state init bal=%.2f handle=%I64d",
               init_balance, g_ftmo_handle);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[JPN225_Momentum] deinit reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[JPN225_Momentum] FTMO status=%d eq=%.2f -- FLATTEN & HALT",
                  status, equity);
      if(g_current_position != 0) CloseCurrentPosition("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;
   g_bars_since_rebalance++;

   // Only rebalance every InpRebalanceBars bars
   if(g_bars_since_rebalance < InpRebalanceBars && g_current_position != 0) {
      return;
   }

   int target_side; double realised_vol, last_close;
   if(!ComputeSignal(target_side, realised_vol, last_close)) return;

   PrintFormat("[JPN225_Momentum] signal: 12m sign=%+d  realised_vol=%.1f%%  last=%.2f",
               target_side, realised_vol*100, last_close);

   // If position matches target, hold (re-evaluate next rebal window)
   if(target_side == g_current_position) {
      g_bars_since_rebalance = 0;
      return;
   }

   // Otherwise: close old, open new
   if(g_current_position != 0) {
      CloseCurrentPosition("regime_flip");
   }
   if(target_side == 0) {
      g_bars_since_rebalance = 0;
      return;  // 12m return exactly zero; stay flat
   }

   double atr;
   if(!ComputeAtr(InpSymbol, InpAtrPeriod, atr)) return;
   double lots = ComputeLots(equity, realised_vol, atr);
   if(lots <= 0) {
      PrintFormat("[JPN225_Momentum] sizing returned 0 lots; skipping");
      return;
   }

   // Headroom check
   double worst_case = lots * (InpAtrStopMult * atr) *
                        (SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE) /
                         SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE));
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[JPN225_Momentum] DENY entry (worst_case=%.2f)", worst_case);
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      lots *= 0.5;
      PrintFormat("[JPN225_Momentum] CAUTION halving size (imminent)");
   }

   double price = (target_side == +1)
                  ? SymbolInfoDouble(InpSymbol, SYMBOL_ASK)
                  : SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double sl = (target_side == +1) ? price - InpAtrStopMult * atr : price + InpAtrStopMult * atr;
   double tp = 0;  // no fixed TP -- exit on next rebalance if regime flips

   PrintFormat("[JPN225_Momentum] ENTRY %s lots=%.2f atr=%.2f sl=%.2f",
               (target_side == +1 ? "LONG" : "SHORT"), lots, atr, sl);

   if(SendOrder((target_side == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                 lots, sl, tp)) {
      g_current_position = target_side;
      g_bars_since_rebalance = 0;
   }
}
