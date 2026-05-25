//+------------------------------------------------------------------+
//| EURGBP_H4_MeanReversion.mq5                                      |
//| Z-score mean-reversion on EURGBP, H4 timeframe.                  |
//|                                                                  |
//| Mechanism (Ornstein-Uhlenbeck / Avellaneda-Lee 2010):            |
//|   EURGBP is structurally cointegrated: EUR and GBP share         |
//|   regional macro drivers (ECB/BoE both inflation-targeting,      |
//|   correlated trade flows, Brexit risk-on/off), so the EUR/GBP    |
//|   ratio reverts to its multi-month mean rather than trending.    |
//|                                                                  |
//|   Compute rolling z-score of log(EURGBP) over 50 H4 bars        |
//|   (~8 trading days). On z-score extremes:                        |
//|     - z > +2  -> SHORT EURGBP (revert down)                     |
//|     - z < -2  -> LONG  EURGBP (revert up)                       |
//|                                                                  |
//|   Exit:                                                           |
//|     - z crosses back through +/- 0.5 (reversion completed)      |
//|     - SL hit (1.5x ATR(14) from entry, the catastrophic-move    |
//|       protection)                                                 |
//|     - Time stop: 24 H4 bars (4 trading days) if neither fires    |
//|     - Force flat at Friday 20:00 UTC (avoid weekend gap risk)   |
//|                                                                  |
//| Per-trade risk: 0.25%. Expect ~2-4 trades/month -- slow but     |
//| high conviction. Adds the cointegration mechanism back into the |
//| portfolio (was missing since the D1 stack was deleted).          |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpZLookback           = 50;        // 50 H4 bars = ~8 days
input double  InpEntryZ              = 2.0;
input double  InpExitZ               = 0.5;
input double  InpCatastrophicZ       = 4.0;
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 1.5;
input int     InpMaxHoldBars         = 24;        // 24 H4 = 4 days
input int     InpFridayFlatHour      = 20;        // 20:00 UTC Friday = ~3h before close
input double  InpPerTradeRiskPct     = 0.0025;
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle      = 0;
datetime g_last_bar_time    = 0;
int      g_bars_in_position = 0;
int      g_atr_handle       = INVALID_HANDLE;
ulong    g_open_ticket      = 0;
int      g_pos_dir          = 0;
double   g_entry_z          = 0.0;

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

double ComputeLots(const double equity, const double stop_distance_price) {
   if(stop_distance_price <= 0 || equity <= 0) return 0.0;
   double risk_amount = equity * InpPerTradeRiskPct;
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0 || tick_size <= 0) return 0.0;
   double loss_per_lot = stop_distance_price / tick_size * tick_value;
   if(loss_per_lot <= 0) return 0.0;
   double raw = risk_amount / loss_per_lot;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   return MathMax(mn, MathMin(mx, MathFloor(raw / step) * step));
}

//+------------------------------------------------------------------+
//| Compute current z-score of log-price using rolling mean + std    |
//| over the past InpZLookback bars (excluding the in-progress bar). |
//+------------------------------------------------------------------+
bool ComputeZScore(double &out_z, double &out_last_close) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int need = InpZLookback + 2;
   int got = CopyRates(_Symbol, _Period, 1, need, rates);
   if(got < InpZLookback + 1) return false;

   // Last closed bar's close
   out_last_close = rates[0].close;
   if(out_last_close <= 0 || !MathIsValidNumber(out_last_close)) return false;
   double log_last = MathLog(out_last_close);

   // Compute mean + std of log-price over the lookback window (excl. last bar)
   double sum = 0.0, sum_sq = 0.0;
   int count = 0;
   for(int i = 1; i <= InpZLookback; i++) {
      double c = rates[i].close;
      if(c <= 0 || !MathIsValidNumber(c)) continue;
      double lc = MathLog(c);
      sum += lc;
      sum_sq += lc * lc;
      count++;
   }
   if(count < InpZLookback / 2) return false;
   double mean = sum / count;
   double variance = sum_sq / count - mean * mean;
   if(variance <= 0) return false;
   double std = MathSqrt(variance);
   out_z = (log_last - mean) / std;
   return MathIsValidNumber(out_z);
}

bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double z) {
   if(InpDryRun) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] DRY-RUN: would %s %.2f  z=%.2f sl=%.5f",
                  _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, z, sl);
      g_open_ticket = 1;
      return true;
   }
   MqlTradeRequest req; MqlTradeResult res; MqlTradeCheckResult chk;
   ZeroMemory(req); ZeroMemory(res); ZeroMemory(chk);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = lots;
   req.type   = type;
   req.price  = (type == ORDER_TYPE_BUY)
                ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.sl = sl;
   req.tp = 0;  // z-cross exit handled in code
   req.deviation = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment = "EURGBP_H4_MeanReversion";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[EURGBP_H4_MeanReversion:%s] %s filled  vol=%.2f  px=%.5f  z=%.2f sl=%.5f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.volume, res.price, z, sl);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(InpDryRun) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
      g_open_ticket = 0; g_pos_dir = 0; g_bars_in_position = 0; return;
   }
   if(!PositionSelect(_Symbol)) { g_open_ticket = 0; g_pos_dir = 0; return; }
   double vol = PositionGetDouble(POSITION_VOLUME);
   long side  = PositionGetInteger(POSITION_TYPE);
   ENUM_ORDER_TYPE close_t = (side == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = vol;
   req.type   = close_t;
   req.position = PositionGetInteger(POSITION_TICKET);
   req.price  = (close_t == ORDER_TYPE_BUY)
                ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.deviation = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment = StringFormat("EURGBP_H4_MeanReversion %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] CLOSED (%s) at %.5f", _Symbol, reason, res.price);
   }
   g_open_ticket = 0; g_pos_dir = 0; g_bars_in_position = 0;
}

bool IsFridayLate(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   return dt.day_of_week == 5 && dt.hour >= InpFridayFlatHour;
}

int OnInit() {
   if(_Period != PERIOD_H4) {
      PrintFormat("[EURGBP_H4_MeanReversion] FATAL: must run on H4 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[EURGBP_H4_MeanReversion:%s] init  z_lookback=%d entry_z=%.1f exit_z=%.1f cat_z=%.1f  atr(%d) stop=%.1fx  hold=%db  risk=%.2f%%  dry_run=%s",
               _Symbol, InpZLookback, InpEntryZ, InpExitZ, InpCatastrophicZ,
               InpAtrPeriod, InpAtrStopMult, InpMaxHoldBars, InpPerTradeRiskPct*100,
               (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[EURGBP_H4_MeanReversion] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_atr_handle = iATR(_Symbol, PERIOD_H4, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE) {
      Print("[EURGBP_H4_MeanReversion] FATAL iATR handle = INVALID");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[EURGBP_H4_MeanReversion:%s] deinit reason=%d", _Symbol, reason);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[EURGBP_H4_MeanReversion:%s] FTMO status=%d -- HALT", _Symbol, status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   double z, last_close;
   if(!ComputeZScore(z, last_close)) return;

   // Friday-late force flat (weekend gap protection)
   if(g_open_ticket != 0 && IsFridayLate(TimeCurrent())) {
      ForceFlat("friday_flat");
      return;
   }

   // Manage open position
   if(g_open_ticket != 0) {
      g_bars_in_position++;
      // Detect broker exit (SL hit)
      if(!InpDryRun && !PositionSelect(_Symbol)) {
         PrintFormat("[EURGBP_H4_MeanReversion:%s] position closed by broker (SL hit)", _Symbol);
         g_open_ticket = 0; g_pos_dir = 0; g_bars_in_position = 0;
         return;
      }
      // Time stop
      if(g_bars_in_position >= InpMaxHoldBars) {
         ForceFlat("time_stop");
         return;
      }
      // Catastrophic widening: z went further from mean (e.g. entered at z=-2.5
      // hoping to revert, but z now < -4)
      bool catastrophic = (g_pos_dir == +1 && z < -InpCatastrophicZ) ||
                          (g_pos_dir == -1 && z >  InpCatastrophicZ);
      if(catastrophic) {
         PrintFormat("[EURGBP_H4_MeanReversion:%s] catastrophic z=%.2f  bars_held=%d  entry_z=%.2f",
                     _Symbol, z, g_bars_in_position, g_entry_z);
         ForceFlat("catastrophic");
         return;
      }
      // Z-reversion exit
      bool exit_z = (MathAbs(z) < InpExitZ);
      if(exit_z) {
         PrintFormat("[EURGBP_H4_MeanReversion:%s] exit_z reached z=%.2f  bars_held=%d  entry_z=%.2f",
                     _Symbol, z, g_bars_in_position, g_entry_z);
         ForceFlat("exit_z");
      }
      return;
   }

   // Entry logic (only when flat)
   if(IsNewsBlackout(TimeCurrent())) return;
   if(IsFridayLate(TimeCurrent())) return;  // don't open new positions Friday late

   int target_dir = 0;
   if(z < -InpEntryZ)      target_dir = +1;  // long (mean-revert up)
   else if(z >  InpEntryZ) target_dir = -1;  // short (mean-revert down)
   if(target_dir == 0) return;

   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double atr = atr_buf[1];
   if(!MathIsValidNumber(atr) || atr <= 0) return;

   double stop_distance = InpAtrStopMult * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) return;

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(WouldExceedRiskCap(equity, worst_case)) return;
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) return;
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, entry_px;
   if(target_dir == +1) {
      entry_px = ask; sl = entry_px - stop_distance;
   } else {
      entry_px = bid; sl = entry_px + stop_distance;
   }

   PrintFormat("[EURGBP_H4_MeanReversion:%s] ENTRY %s  z=%.2f  px=%.5f  atr=%.5f  sl=%.5f",
               _Symbol, (target_dir == +1 ? "LONG" : "SHORT"), z, entry_px, atr, sl);
   if(SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl, z)) {
      g_pos_dir = target_dir;
      g_bars_in_position = 0;
      g_entry_z = z;
   }
}
