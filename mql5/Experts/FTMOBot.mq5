//+------------------------------------------------------------------+
//| FTMOBot.mq5                                                      |
//| Live trading EA: Index Mean-Reversion with HMM regime gate.      |
//|                                                                  |
//| Per ARCHITECTURE.md, this file stays THIN. All feature math goes |
//| through libquant.dll (cpp/). All risk decisions go through       |
//| libftmorisk.dll (ocaml/). MQL5 is glue, not logic.               |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.20"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

//+------------------------------------------------------------------+
//| User-configurable inputs                                         |
//+------------------------------------------------------------------+
input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input double  InpPerTradeRiskPct     = 0.005;   // 0.5% per trade
input int     InpFormationBars       = 20;
input double  InpEntryZ              = 1.0;
input double  InpExitZ               = 0.5;
input int     InpMaxHoldBars         = 10;
input double  InpAtrStopMult         = 1.5;
input double  InpAtrTpMult           = 2.0;
input int     InpAtrPeriod           = 14;
input int     InpZLookback           = 252;
// Risk
input bool    InpDryRun              = true;    // log instead of sending orders

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
long g_ftmo_handle    = 0;
datetime g_last_bar_time = 0;
ulong  g_position_ticket = 0;
double g_position_stop_price = 0.0;
double g_position_tp_price   = 0.0;
int    g_position_bars_held  = 0;
double g_initial_capital = 0.0;

//+------------------------------------------------------------------+
//| Account type code mapping                                        |
//+------------------------------------------------------------------+
int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   PrintFormat("[FTMOBot] Unknown account type '%s' -- defaulting to 2STEP_PHASE1", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[FTMOBot] init  symbol=%s  tf=%s  lib=%s",
               _Symbol, EnumToString(_Period), quant_version());

   g_initial_capital = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(
      AccountTypeCode(InpAccountType),
      g_initial_capital
   );
   if(g_ftmo_handle == 0) {
      Print("[FTMOBot] FATAL: ftmo_new_account returned null handle");
      return INIT_FAILED;
   }
   PrintFormat("[FTMOBot] FTMO state initialised  balance=%.2f  handle=%I64d",
               g_initial_capital, g_ftmo_handle);
   PrintFormat("[FTMOBot] dry_run=%s  risk=%.3f%%  formation=%d  entry_z=%.2f",
               (string)(InpDryRun?"true":"false"), InpPerTradeRiskPct*100,
               InpFormationBars, InpEntryZ);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   PrintFormat("[FTMOBot] deinit  reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| Helpers: load N most recent CLOSED bars                          |
//+------------------------------------------------------------------+
bool LoadRecentBars(const int n_bars,
                    double &highs[], double &lows[], double &closes[]) {
   // CopyBuffer / CopyOHLC patterns; shift=1 to skip the in-progress bar.
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(_Symbol, _Period, 1, n_bars, rates);
   if(got != n_bars) {
      PrintFormat("[FTMOBot] CopyRates returned %d (asked %d)", got, n_bars);
      return false;
   }
   ArrayResize(highs,  n_bars);
   ArrayResize(lows,   n_bars);
   ArrayResize(closes, n_bars);
   // Convert from series-indexed (latest at 0) to chronological order
   for(int i = 0; i < n_bars; i++) {
      highs [n_bars - 1 - i] = rates[i].high;
      lows  [n_bars - 1 - i] = rates[i].low;
      closes[n_bars - 1 - i] = rates[i].close;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Signal pipeline: returns latest ATR + z-score (or false on error)|
//+------------------------------------------------------------------+
bool ComputeSignal(double &out_atr, double &out_zscore, double &out_close) {
   // Total bars needed = z_lookback (for z computation) + formation_bars
   // (for cumulative return window) + atr_period (for ATR warmup).
   int n_bars = InpZLookback + InpFormationBars + InpAtrPeriod + 5;
   double highs[], lows[], closes[];
   if(!LoadRecentBars(n_bars, highs, lows, closes)) return false;

   // 1. ATR
   double atr_series[];
   ArrayResize(atr_series, n_bars);
   int rc = quant_atr(highs, lows, closes, n_bars, InpAtrPeriod, atr_series);
   QuantLogIfError(rc, "quant_atr");
   if(rc != QUANT_OK) return false;
   out_atr = atr_series[n_bars - 1];
   if(out_atr <= 0) return false;

   // 2. Cumulative log returns over formation window, then rolling z-score
   double formation_returns[];
   ArrayResize(formation_returns, n_bars);
   for(int i = 0; i < n_bars; i++) {
      formation_returns[i] = EMPTY_VALUE;
   }
   // formation_return[i] = log(close[i] / close[i-formation_bars])
   for(int i = InpFormationBars; i < n_bars; i++) {
      formation_returns[i] = MathLog(closes[i] / closes[i - InpFormationBars]);
   }

   double zscore_series[];
   ArrayResize(zscore_series, n_bars);
   rc = quant_rolling_zscore(formation_returns, n_bars, InpZLookback, zscore_series);
   QuantLogIfError(rc, "quant_rolling_zscore");
   if(rc != QUANT_OK) return false;
   out_zscore = zscore_series[n_bars - 1];
   out_close  = closes[n_bars - 1];
   return true;
}

//+------------------------------------------------------------------+
//| Position size in lots given risk budget and stop distance        |
//+------------------------------------------------------------------+
double ComputeLots(const double equity, const double stop_distance_price) {
   if(stop_distance_price <= 0 || equity <= 0) return 0.0;
   double risk_amount = equity * InpPerTradeRiskPct;
   double point      = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(point <= 0 || tick_value <= 0) return 0.0;
   double pnl_per_lot_per_price_unit = tick_value / point;
   double risk_per_lot = stop_distance_price * pnl_per_lot_per_price_unit;
   if(risk_per_lot <= 0) return 0.0;
   double raw_lots = risk_amount / risk_per_lot;
   double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots = MathFloor(raw_lots / lot_step) * lot_step;
   double min_lots = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lots = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   return MathMax(min_lots, MathMin(max_lots, lots));
}

//+------------------------------------------------------------------+
//| Send long market order with stop+TP                              |
//+------------------------------------------------------------------+
bool SendLongEntry(const double lots, const double stop_price, const double tp_price) {
   if(InpDryRun) {
      PrintFormat("[FTMOBot] DRY-RUN: would BUY %.2f lots %s  stop=%.2f tp=%.2f",
                  lots, _Symbol, stop_price, tp_price);
      return true;
   }
   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.volume       = lots;
   req.type         = ORDER_TYPE_BUY;
   req.price        = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   req.sl           = stop_price;
   req.tp           = tp_price;
   req.deviation    = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = "FTMOBot meanrev";

   if(!OrderCheck(req, res) || res.retcode != 0) {
      PrintFormat("[FTMOBot] OrderCheck rejected: retcode=%d comment=%s",
                  res.retcode, res.comment);
      return false;
   }
   if(!OrderSend(req, res)) {
      PrintFormat("[FTMOBot] OrderSend FAILED: retcode=%d comment=%s",
                  res.retcode, res.comment);
      return false;
   }
   if(res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[FTMOBot] OrderSend non-DONE retcode=%d comment=%s",
                  res.retcode, res.comment);
      return false;
   }
   g_position_ticket = res.order;
   g_position_stop_price = stop_price;
   g_position_tp_price   = tp_price;
   g_position_bars_held  = 0;
   PrintFormat("[FTMOBot] BUY filled: ticket=%I64u price=%.2f volume=%.2f sl=%.2f tp=%.2f",
               res.order, res.price, res.volume, stop_price, tp_price);
   return true;
}

//+------------------------------------------------------------------+
//| Close existing long position                                      |
//+------------------------------------------------------------------+
bool CloseLongPosition(const string reason) {
   if(InpDryRun) {
      PrintFormat("[FTMOBot] DRY-RUN: would CLOSE long %s (reason=%s)",
                  _Symbol, reason);
      g_position_ticket = 0;
      return true;
   }
   if(!PositionSelect(_Symbol)) return false;
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.volume       = PositionGetDouble(POSITION_VOLUME);
   req.type         = ORDER_TYPE_SELL;
   req.position     = PositionGetInteger(POSITION_TICKET);
   req.price        = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.deviation    = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = StringFormat("FTMOBot %s", reason);
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[FTMOBot] Close failed: retcode=%d", res.retcode);
      return false;
   }
   PrintFormat("[FTMOBot] CLOSED long (%s) at %.2f", reason, res.price);
   g_position_ticket = 0;
   return true;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   // ------------------------------------------------------------------
   // Per-tick: equity watcher (sub-second monitor)
   // ------------------------------------------------------------------
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      // 2 = Internal_killed, 3 = Ftmo_failed
      PrintFormat("[FTMOBot] FTMO state status=%d at equity=%.2f -- FLATTEN & HALT",
                  status, equity);
      if(g_position_ticket != 0) CloseLongPosition("ftmo_kill");
      ExpertRemove();
      return;
   }
   if(status == 1) {
      // Imminent -- log but continue; bar-close logic will respect headroom check.
      static datetime last_imminent_log = 0;
      if(TimeCurrent() - last_imminent_log > 60) {
         PrintFormat("[FTMOBot] FTMO IMMINENT at equity=%.2f -- reducing risk", equity);
         last_imminent_log = (datetime)TimeCurrent();
      }
   }

   // ------------------------------------------------------------------
   // Bar-close detection: signal pipeline runs once per bar
   // ------------------------------------------------------------------
   const datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   // ------------------------------------------------------------------
   // If we have an open position, check time-stop / exit-z exits
   // (ATR stop/TP are handled by the broker via SL/TP fields on entry)
   // ------------------------------------------------------------------
   if(g_position_ticket != 0) {
      g_position_bars_held++;
      double atr, zs, close;
      if(ComputeSignal(atr, zs, close)) {
         bool exit_z = (zs > -InpExitZ);
         bool time_stop = (g_position_bars_held >= InpMaxHoldBars);
         if(exit_z || time_stop) {
            CloseLongPosition(time_stop ? "time_stop" : "exit_z");
         }
      }
      return;  // don't open new entries while one is open
   }

   // ------------------------------------------------------------------
   // Signal: compute z-score; entry if z < -entry_z
   // ------------------------------------------------------------------
   double atr, zscore, close;
   if(!ComputeSignal(atr, zscore, close)) return;
   if(zscore >= -InpEntryZ) return;  // not deep enough drawdown

   // ------------------------------------------------------------------
   // Sizing + risk check + send
   // ------------------------------------------------------------------
   double stop_distance = atr * InpAtrStopMult;
   double tp_distance   = atr * InpAtrTpMult;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) {
      PrintFormat("[FTMOBot] zero lots -- skipping (atr=%.4f stop_distance=%.4f)",
                  atr, stop_distance);
      return;
   }

   // Pre-trade headroom check via OCaml libftmorisk
   double worst_case_loss = lots * stop_distance *
                            (SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) /
                             SymbolInfoDouble(_Symbol, SYMBOL_POINT));
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case_loss);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[FTMOBot] DENY entry: headroom violated  worst_case_loss=%.2f",
                  worst_case_loss);
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      // Reduce size; conservative half.
      lots = NormalizeDouble(lots * 0.5,
                              (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
      PrintFormat("[FTMOBot] CAUTION imminent: halving lot size to %.2f", lots);
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double stop_price = ask - stop_distance;
   double tp_price   = ask + tp_distance;
   PrintFormat("[FTMOBot] SIGNAL: z=%.2f atr=%.4f lots=%.2f sl=%.2f tp=%.2f",
               zscore, atr, lots, stop_price, tp_price);
   SendLongEntry(lots, stop_price, tp_price);
}

//+------------------------------------------------------------------+
//| OnTradeTransaction                                                |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result) {
   // Detect when our position was closed by SL or TP (broker-side fill)
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD && g_position_ticket != 0) {
      if(!PositionSelectByTicket(g_position_ticket)) {
         PrintFormat("[FTMOBot] position %I64u closed by broker (SL/TP)",
                     g_position_ticket);
         g_position_ticket = 0;
      }
   }
}
