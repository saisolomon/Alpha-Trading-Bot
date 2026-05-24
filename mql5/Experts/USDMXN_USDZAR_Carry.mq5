//+------------------------------------------------------------------+
//| USDMXN_USDZAR_Carry.mq5                                               |
//| Regime-gated emerging-markets FX carry trade.                    |
//|                                                                  |
//|   long USDMXN + short USDZAR                                     |
//|                                                                  |
//| Both legs are independent (not a cointegration spread). Earns    |
//| the Banxico-vs-Fed rate differential on the long-USDMXN leg      |
//| (+$24.87/lot/day broker carry) and the SARB-vs-Fed differential  |
//| on the short-USDZAR leg (+$5.60/lot/day broker carry).           |
//|                                                                  |
//| This EA is the SECOND carry strategy in the portfolio. It is     |
//| regime-anti-correlated with AUDJPY_CHFJPY_Carry by construction:     |
//| see strategies/em_carry/HYPOTHESIS.md for the joint deployment   |
//| rationale and the 2014-2018 vs 2023-2026 sub-period story.       |
//|                                                                  |
//| Regime gate (entry):                                             |
//|   - USDMXN swap_long  > +20.0 USD/lot/day                        |
//|   - USDZAR swap_short > +4.0  USD/lot/day                        |
//|   - No FOMC/Banxico/SARB meeting within +/- 3 days               |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input string  InpAccountType            = "CHALLENGE_2STEP_PHASE1";
input string  InpSymbolLong             = "USDMXN";   // long leg
input string  InpSymbolShort            = "USDZAR";   // short leg
input double  InpPerLegRiskPct          = 0.005;      // 0.5%/leg, 1% aggregate
input int     InpAtrPeriod              = 14;
input double  InpAtrStopMult            = 1.0;
input double  InpTakeProfitEquityPct    = 0.02;       // +2% account
input double  InpStopLossEquityPct      = 0.01;       // -1% account
input int     InpMaxHoldBars            = 60;         // D1 bars
//-- Regime gate thresholds (calibrated to MXN/ZAR swap magnitudes,
//-- which are ~10x JPY-cross magnitudes).
//-- NET-carry gate: sum of swap_long_of_long_leg + swap_short_of_short_leg.
//-- Switched from per-leg to net-carry on 2026-05-19 after the JPY sibling
//-- EA revealed broker swap spreads can make per-leg checks reject pairings
//-- that ARE net profitable (or accept pairings that ARE NOT). Net carry is
//-- what the position actually earns each day, so gate on that.
input double  InpEntryNetCarryMin       = 20.0;       // $/lot/day required to enter
input double  InpExitNetCarryMin        = 12.0;       // throttle if net drops below
input int     InpNewsBufferDays         = 3;
input bool    InpDryRun                 = true;

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
long     g_ftmo_handle      = 0;
int      g_pos_state        = 0;
double   g_entry_equity     = 0.0;
int      g_bars_held        = 0;
datetime g_last_bar_time    = 0;
double   g_lots_long        = 0.0;
double   g_lots_short       = 0.0;

//+------------------------------------------------------------------+
//| Hardcoded 2026 CB meeting dates: FOMC, Banxico, SARB.            |
//| Placeholder -- replace with configs/cb_meetings.yaml loader.     |
//+------------------------------------------------------------------+
datetime g_cb_meetings[] = {
   // ----- FOMC 2026 (~8/year, Tue/Wed) -----
   D'2026.01.28 19:00',  // FOMC
   D'2026.03.18 19:00',  // FOMC + SEP
   D'2026.04.29 19:00',  // FOMC
   D'2026.06.17 19:00',  // FOMC + SEP
   D'2026.07.29 19:00',  // FOMC
   D'2026.09.16 19:00',  // FOMC + SEP
   D'2026.11.04 19:00',  // FOMC
   D'2026.12.16 19:00',  // FOMC + SEP
   // ----- Banxico 2026 (8/year, Thu) -----
   D'2026.02.12 19:00',  // Banxico
   D'2026.03.26 19:00',
   D'2026.05.14 19:00',
   D'2026.06.25 19:00',
   D'2026.08.06 19:00',
   D'2026.09.24 19:00',
   D'2026.11.05 19:00',
   D'2026.12.17 19:00',
   // ----- SARB 2026 (~6/year, Thu) -----
   D'2026.01.29 13:00',  // SARB
   D'2026.03.19 13:00',
   D'2026.05.21 13:00',
   D'2026.07.30 13:00',
   D'2026.09.17 13:00',
   D'2026.11.19 13:00',
};

//+------------------------------------------------------------------+
//| Map account-type input string to libftmorisk code                |
//+------------------------------------------------------------------+
int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   PrintFormat("[USDMXN_USDZAR_Carry] Unknown account_type '%s'", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| News-window helpers                                              |
//+------------------------------------------------------------------+
bool InNewsBlackout(const datetime now, const int buffer_days) {
   const long buffer_sec = (long)buffer_days * 86400;
   const int n = ArraySize(g_cb_meetings);
   for(int i = 0; i < n; i++) {
      long delta = (long)now - (long)g_cb_meetings[i];
      if(delta < 0) delta = -delta;
      if(delta <= buffer_sec) return true;
   }
   return false;
}

bool MeetingWithin24h(const datetime now) {
   const int n = ArraySize(g_cb_meetings);
   for(int i = 0; i < n; i++) {
      long delta = (long)g_cb_meetings[i] - (long)now;
      if(delta >= 0 && delta <= 86400) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Swap-rate probe (USD/lot/day approximation)                      |
//+------------------------------------------------------------------+
bool GetSwapPerLotPerDay(const string symbol, double &out_long,
                          double &out_short) {
   if(!SymbolSelect(symbol, true)) return false;
   double sl = SymbolInfoDouble(symbol, SYMBOL_SWAP_LONG);
   double ss = SymbolInfoDouble(symbol, SYMBOL_SWAP_SHORT);
   long mode = SymbolInfoInteger(symbol, SYMBOL_SWAP_MODE);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(mode == 1) {
      if(tick_size <= 0) return false;
      const double scale = point * tick_val / tick_size;
      out_long = sl * scale;
      out_short = ss * scale;
   } else if(mode == 2) {
      out_long = sl;
      out_short = ss;
   } else {
      PrintFormat("[USDMXN_USDZAR_Carry] %s swap_mode=%I64d (unknown units)",
                  symbol, mode);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| ATR(D1, period) of the symbol                                     |
//+------------------------------------------------------------------+
bool ComputeAtrD1(const string symbol, const int period, double &out_atr) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(symbol, PERIOD_D1, 1, period + 5, rates);
   if(got < period + 1) return false;
   double sum_tr = 0.0;
   for(int i = 0; i < period; i++) {
      double tr = MathMax(rates[i].high - rates[i].low,
                  MathMax(MathAbs(rates[i].high - rates[i+1].close),
                          MathAbs(rates[i].low  - rates[i+1].close)));
      sum_tr += tr;
   }
   out_atr = sum_tr / period;
   return out_atr > 0;
}

//+------------------------------------------------------------------+
//| Per-leg lot sizing using ATR stop                                |
//+------------------------------------------------------------------+
bool ComputeLot(const string symbol, const double equity,
                 const double atr, double &out_lots) {
   double risk_amount = equity * InpPerLegRiskPct;
   double stop_distance = InpAtrStopMult * atr;
   if(stop_distance <= 0) return false;
   double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_size <= 0) return false;
   double per_unit_per_lot = tick_val / tick_size;
   double loss_per_lot = stop_distance * per_unit_per_lot;
   if(loss_per_lot <= 0) return false;
   double raw_lots = risk_amount / loss_per_lot;
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_v = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_v = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   out_lots = MathFloor(raw_lots / step) * step;
   out_lots = MathMax(min_v, MathMin(max_v, out_lots));
   return out_lots > 0;
}

//+------------------------------------------------------------------+
//| SendLeg / ClosePosition (mirror AUDJPY_CHFJPY_Carry)                 |
//+------------------------------------------------------------------+
bool SendLeg(const string symbol, const ENUM_ORDER_TYPE type,
              const double lots) {
   if(InpDryRun) {
      PrintFormat("[USDMXN_USDZAR_Carry] DRY-RUN: would %s %.2f %s",
                  (type==ORDER_TYPE_BUY?"BUY":"SELL"), lots, symbol);
      return true;
   }
   MqlTradeRequest      req;
   MqlTradeResult       res;
   MqlTradeCheckResult  chk;
   ZeroMemory(req); ZeroMemory(res); ZeroMemory(chk);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = symbol;
   req.volume       = lots;
   req.type         = type;
   req.price        = (type==ORDER_TYPE_BUY) ?
                       SymbolInfoDouble(symbol, SYMBOL_ASK) :
                       SymbolInfoDouble(symbol, SYMBOL_BID);
   req.deviation    = 50;   // EM pairs wider spreads
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = "USDMXN_USDZAR_Carry";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[USDMXN_USDZAR_Carry] OrderCheck rejected %s: retcode=%d",
                  symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[USDMXN_USDZAR_Carry] OrderSend %s FAILED: retcode=%d",
                  symbol, res.retcode);
      return false;
   }
   PrintFormat("[USDMXN_USDZAR_Carry] %s filled  vol=%.2f  px=%.5f",
               (type==ORDER_TYPE_BUY?"BUY":"SELL"), res.volume, res.price);
   return true;
}

void ClosePosition(const string reason) {
   if(g_pos_state == 0) return;
   if(InpDryRun) {
      PrintFormat("[USDMXN_USDZAR_Carry] DRY-RUN: would CLOSE both legs (%s)",
                  reason);
      g_pos_state = 0;
      g_bars_held = 0;
      g_lots_long = g_lots_short = 0.0;
      return;
   }
   double vol_l = 0.0, vol_s = 0.0;
   if(PositionSelect(InpSymbolLong))  vol_l = PositionGetDouble(POSITION_VOLUME);
   if(PositionSelect(InpSymbolShort)) vol_s = PositionGetDouble(POSITION_VOLUME);
   if(vol_l > 0) SendLeg(InpSymbolLong,  ORDER_TYPE_SELL, vol_l);
   if(vol_s > 0) SendLeg(InpSymbolShort, ORDER_TYPE_BUY,  vol_s);
   PrintFormat("[USDMXN_USDZAR_Carry] CLOSED carry pair (%s)", reason);
   g_pos_state = 0;
   g_bars_held = 0;
   g_lots_long = g_lots_short = 0.0;
}

//+------------------------------------------------------------------+
//| OnInit / OnDeinit                                                 |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[USDMXN_USDZAR_Carry] init  long=%s short=%s  lib=%s",
               InpSymbolLong, InpSymbolShort, quant_version());
   SymbolSelect(InpSymbolLong,  true);
   SymbolSelect(InpSymbolShort, true);
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) {
      Print("[USDMXN_USDZAR_Carry] FATAL: ftmo_new_account returned 0");
      return INIT_FAILED;
   }
   PrintFormat("[USDMXN_USDZAR_Carry] FTMO state  bal=%.2f handle=%I64d  dry_run=%s",
               init_balance, g_ftmo_handle,
               (string)(InpDryRun?"true":"false"));
   PrintFormat("[USDMXN_USDZAR_Carry] gates: entry net_carry>=%.2f $/lot/day  "
               "exit net_carry<%.2f  news_buffer=%dd  "
               "tp=+%.1f%% sl=-%.1f%% max_hold=%db",
               InpEntryNetCarryMin, InpExitNetCarryMin,
               InpNewsBufferDays,
               InpTakeProfitEquityPct*100, InpStopLossEquityPct*100,
               InpMaxHoldBars);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[USDMXN_USDZAR_Carry] deinit  reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[USDMXN_USDZAR_Carry] FTMO status=%d equity=%.2f -- FLATTEN & HALT",
                  status, equity);
      if(g_pos_state != 0) ClosePosition("ftmo_kill");
      ExpertRemove();
      return;
   }

   if(g_pos_state == 1) {
      // Defensive: NaN pnl_pct would silently bypass TP/SL via false
      // comparisons. Force-close instead. (Same fix as JPYCarry.)
      if(g_entry_equity <= 0 || !MathIsValidNumber(g_entry_equity)) {
         PrintFormat("[USDMXN_USDZAR_Carry] WARN g_entry_equity=%.4f invalid; "
                     "force-closing", g_entry_equity);
         ClosePosition("entry_equity_corrupt");
         return;
      }
      double pnl_pct = (equity - g_entry_equity) / g_entry_equity;
      if(!MathIsValidNumber(pnl_pct)) {
         PrintFormat("[USDMXN_USDZAR_Carry] WARN pnl_pct=NaN; force-closing");
         ClosePosition("pnl_nan");
         return;
      }
      if(pnl_pct >= InpTakeProfitEquityPct) { ClosePosition("take_profit"); return; }
      if(pnl_pct <= -InpStopLossEquityPct)  { ClosePosition("stop_loss");   return; }
      if(MeetingWithin24h(TimeCurrent()))   { ClosePosition("pre_news_flatten"); return; }
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, PERIOD_D1, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   double long_sl, long_ss, short_sl, short_ss;
   if(!GetSwapPerLotPerDay(InpSymbolLong,  long_sl, long_ss)) return;
   if(!GetSwapPerLotPerDay(InpSymbolShort, short_sl, short_ss)) return;

   // NET carry of the pairing
   double net_carry = long_sl + short_ss;
   if(!MathIsValidNumber(net_carry)) {
      PrintFormat("[USDMXN_USDZAR_Carry] WARN net_carry=NaN (long_sl=%.2f short_ss=%.2f) "
                  "-- skipping bar", long_sl, short_ss);
      return;
   }

   if(g_pos_state == 1) {
      g_bars_held++;
      if(g_bars_held >= InpMaxHoldBars) { ClosePosition("time_stop"); return; }
      if(net_carry < InpExitNetCarryMin) {
         PrintFormat("[USDMXN_USDZAR_Carry] regime throttle  net_carry=%.2f  "
                     "(long %s swap_long=%.2f + short %s swap_short=%.2f)",
                     net_carry, InpSymbolLong, long_sl,
                     InpSymbolShort, short_ss);
         ClosePosition("regime_throttle");
         return;
      }
      return;
   }

   if(InNewsBlackout(TimeCurrent(), InpNewsBufferDays)) return;

   if(net_carry < InpEntryNetCarryMin) {
      PrintFormat("[USDMXN_USDZAR_Carry] gate FAIL  net_carry=%.2f need>=%.2f  "
                  "(long %s swap_long=%.2f + short %s swap_short=%.2f)",
                  net_carry, InpEntryNetCarryMin,
                  InpSymbolLong, long_sl,
                  InpSymbolShort, short_ss);
      return;
   }

   double atr_long, atr_short;
   if(!ComputeAtrD1(InpSymbolLong,  InpAtrPeriod, atr_long))  return;
   if(!ComputeAtrD1(InpSymbolShort, InpAtrPeriod, atr_short)) return;
   double lots_long, lots_short;
   if(!ComputeLot(InpSymbolLong,  equity, atr_long,  lots_long))  return;
   if(!ComputeLot(InpSymbolShort, equity, atr_short, lots_short)) return;

   double worst_case = 2.0 * equity * InpPerLegRiskPct;
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[USDMXN_USDZAR_Carry] DENY: headroom violated  worst_case=%.2f",
                  worst_case);
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      lots_long  *= 0.5;
      lots_short *= 0.5;
      PrintFormat("[USDMXN_USDZAR_Carry] CAUTION: halving lot size (imminent)");
   }

   PrintFormat("[USDMXN_USDZAR_Carry] ENTRY  %s long %.2f lots (swap_long=%.2f) "
               "+ %s short %.2f lots (swap_short=%.2f)  net_carry=%.2f $/lot/day",
               InpSymbolLong, lots_long, long_sl,
               InpSymbolShort, lots_short, short_ss, net_carry);

   if(InpDryRun) {
      SendLeg(InpSymbolLong,  ORDER_TYPE_BUY,  lots_long);
      SendLeg(InpSymbolShort, ORDER_TYPE_SELL, lots_short);
      g_pos_state = 1;
      g_entry_equity = equity;
      g_bars_held = 0;
      g_lots_long = lots_long;
      g_lots_short = lots_short;
      return;
   }

   if(!SendLeg(InpSymbolLong, ORDER_TYPE_BUY, lots_long)) {
      Print("[USDMXN_USDZAR_Carry] long leg failed; aborting entry");
      return;
   }
   if(!SendLeg(InpSymbolShort, ORDER_TYPE_SELL, lots_short)) {
      Print("[USDMXN_USDZAR_Carry] short leg failed; unwinding long leg");
      double vol_l = PositionSelect(InpSymbolLong) ?
                      PositionGetDouble(POSITION_VOLUME) : lots_long;
      SendLeg(InpSymbolLong, ORDER_TYPE_SELL, vol_l);
      return;
   }
   g_pos_state = 1;
   g_entry_equity = equity;
   g_bars_held = 0;
   g_lots_long = lots_long;
   g_lots_short = lots_short;
}
