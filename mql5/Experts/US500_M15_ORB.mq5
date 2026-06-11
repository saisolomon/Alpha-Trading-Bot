//+------------------------------------------------------------------+
//| US500_M15_ORB.mq5                                                |
//| Opening Range Breakout on US500.sim (NY cash equity open)        |
//|                                                                  |
//| Mechanism (Crabel 1990, Christophe/Ferri/Angel 1997):            |
//|   - Range = first 60 min after NY cash open (14:30 - 15:30 UTC)  |
//|     = 4 M15 bars at 14:30, 14:45, 15:00, 15:15                   |
//|   - Range high = max(high) over those 4 bars                     |
//|   - Range low  = min(low)  over those 4 bars                     |
//|   - From 15:30 UTC onwards: if M15 close > range high -> long    |
//|                            if M15 close < range low  -> short    |
//|   - Stop-loss: opposite side of range                            |
//|   - Take-profit: entry + 2 * range_width (long), mirror for short|
//|   - One trade per day max                                        |
//|   - Force flat by 20:30 UTC (90 min before NY close)             |
//|                                                                  |
//| Per-trade risk: 0.25% (tight because M15 = more trades = more    |
//| spread cost exposure than D1)                                    |
//|                                                                  |
//| Skip rules:                                                       |
//|   - Range width must be > min_range_pct * current_price          |
//|     (avoid degenerate trades on ultra-narrow ranges)             |
//|                                                                  |
//| FTMO compliance: hardcoded equity-line monitor via libftmorisk.  |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
//-- Session hours in UTC. NYSE cash open = 14:30 UTC year-round
//-- (broker normally handles DST so 14:30 is constant).
input int     InpSessionOpenHour     = 14;
input int     InpSessionOpenMinute   = 30;
input int     InpRangeMinutes        = 60;       // first 60 min = 4 M15 bars
input int     InpSessionCloseHour    = 20;       // 20:30 UTC = ~90 min before NY close
input int     InpSessionCloseMinute  = 30;
//-- Risk + sizing
input double  InpPerTradeRiskPct     = 0.0025;   // 0.25% per trade (M15)
input double  InpTakeProfitMult      = 2.0;      // TP = 2 * range_width from entry
input double  InpMinRangePct         = 0.0015;   // skip if range < 0.15% of price
input bool    InpDryRun              = true;

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
long     g_ftmo_handle      = 0;
datetime g_last_bar_time    = 0;
//-- Session tracking
datetime g_current_session_date = 0;  // UTC midnight of the session's open
double   g_range_high       = 0.0;
double   g_range_low        = 0.0;
bool     g_range_locked     = false;
bool     g_traded_this_session = false;
ulong    g_open_ticket      = 0;

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   PrintFormat("[US500_M15_ORB] unknown account_type '%s'", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| Return UTC midnight of the bar's session date                    |
//+------------------------------------------------------------------+
datetime SessionDateOf(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

//+------------------------------------------------------------------+
//| Is the given UTC time inside the range-building window?          |
//+------------------------------------------------------------------+
bool InRangeWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int t_minutes = dt.hour * 60 + dt.min;
   int open_min  = InpSessionOpenHour * 60 + InpSessionOpenMinute;
   int range_end = open_min + InpRangeMinutes;
   return t_minutes >= open_min && t_minutes < range_end;
}

//+------------------------------------------------------------------+
//| Is the given UTC time inside the post-range trading window?      |
//+------------------------------------------------------------------+
bool InTradingWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int t_minutes = dt.hour * 60 + dt.min;
   int range_end  = InpSessionOpenHour * 60 + InpSessionOpenMinute + InpRangeMinutes;
   int close_min  = InpSessionCloseHour * 60 + InpSessionCloseMinute;
   return t_minutes >= range_end && t_minutes < close_min;
}

//+------------------------------------------------------------------+
//| Is current time the session-close (force-flat) point?            |
//+------------------------------------------------------------------+
bool AtSessionClose(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int t_minutes = dt.hour * 60 + dt.min;
   int close_min = InpSessionCloseHour * 60 + InpSessionCloseMinute;
   return t_minutes >= close_min;
}

//+------------------------------------------------------------------+
//| Lot sizing: 0.25% equity risk for the given SL distance          |
//+------------------------------------------------------------------+
double ComputeLots(const double equity, const double stop_distance_price) {
   if(stop_distance_price <= 0 || equity <= 0) return 0.0;
   double risk_amount = equity * InpPerTradeRiskPct;
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0 || tick_size <= 0) return 0.0;
   double loss_per_lot = stop_distance_price / tick_size * tick_value;
   if(loss_per_lot <= 0) return 0.0;
   double raw_lots = risk_amount / loss_per_lot;
   double step  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double min_v = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_v = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lots = MathFloor(raw_lots / step) * step;
   return MathMax(min_v, MathMin(max_v, lots));
}

//+------------------------------------------------------------------+
//| Build the range from M15 bars in the range window                |
//+------------------------------------------------------------------+
bool BuildRange(const datetime bar_time) {
   // Load M15 bars covering the range window for today's session
   datetime session_start;
   {
      MqlDateTime dt; TimeToStruct(g_current_session_date, dt);
      dt.hour = InpSessionOpenHour; dt.min = InpSessionOpenMinute; dt.sec = 0;
      session_start = StructToTime(dt);
   }
   datetime range_end = session_start + InpRangeMinutes * 60;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   // Pull the last ~10 M15 bars (covers the 4-bar range with margin)
   int got = CopyRates(_Symbol, PERIOD_M15, 0, 10, rates);
   if(got < 4) return false;
   double hi = -1e18, lo = 1e18;
   int matched = 0;
   for(int i = 0; i < got; i++) {
      if(rates[i].time >= session_start && rates[i].time < range_end) {
         hi = MathMax(hi, rates[i].high);
         lo = MathMin(lo, rates[i].low);
         matched++;
      }
   }
   if(matched < 2) return false;
   g_range_high = hi;
   g_range_low  = lo;
   g_range_locked = true;
   PrintFormat("[US500_M15_ORB] range locked  matched_bars=%d  hi=%.2f  lo=%.2f  width=%.2f",
               matched, g_range_high, g_range_low, g_range_high - g_range_low);
   return true;
}

//+------------------------------------------------------------------+
//| Send order with stop + TP                                         |
//+------------------------------------------------------------------+
bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double tp) {
   if(InpDryRun) {
      PrintFormat("[US500_M15_ORB] DRY-RUN: would %s %.2f %s  sl=%.2f tp=%.2f",
                  (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, _Symbol, sl, tp);
      return true;
   }
   MqlTradeRequest req; MqlTradeResult res; MqlTradeCheckResult chk;
   ZeroMemory(req); ZeroMemory(res); ZeroMemory(chk);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.volume       = lots;
   req.type         = type;
   req.price        = (type == ORDER_TYPE_BUY)
                      ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                      : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.sl           = sl;
   req.tp           = tp;
   req.deviation    = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment      = "US500_M15_ORB";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[US500_M15_ORB] OrderCheck rejected retcode=%d comment=%s",
                  chk.retcode, chk.comment);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[US500_M15_ORB] OrderSend FAILED retcode=%d", res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[US500_M15_ORB] %s filled ticket=%I64u px=%.2f vol=%.2f sl=%.2f tp=%.2f",
               (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.order, res.price, res.volume, sl, tp);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(!PositionSelect(_Symbol)) { g_open_ticket = 0; return; }
   if(InpDryRun) {
      PrintFormat("[US500_M15_ORB] DRY-RUN: would CLOSE (%s)", reason);
      g_open_ticket = 0;
      return;
   }
   double vol = PositionGetDouble(POSITION_VOLUME);
   long  side = PositionGetInteger(POSITION_TYPE);  // 0=BUY, 1=SELL
   ENUM_ORDER_TYPE close_t = (side == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action       = TRADE_ACTION_DEAL;
   req.symbol       = _Symbol;
   req.volume       = vol;
   req.type         = close_t;
   req.position     = PositionGetInteger(POSITION_TICKET);
   req.price        = (close_t == ORDER_TYPE_BUY)
                      ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                      : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.deviation    = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment      = StringFormat("US500_M15_ORB %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[US500_M15_ORB] CLOSED (%s) at %.2f", reason, res.price);
   }
   g_open_ticket = 0;
}

//+------------------------------------------------------------------+
//| OnInit / OnDeinit                                                 |
//+------------------------------------------------------------------+
int OnInit() {
   if(_Period != PERIOD_M15) {
      PrintFormat("[US500_M15_ORB] FATAL: must be attached to an M15 chart (current=%s)",
                  EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[US500_M15_ORB] init  symbol=%s  session=%02d:%02d UTC  range=%dmin  flat=%02d:%02d UTC  risk=%.2f%%  dry_run=%s  lib=%s",
               _Symbol, InpSessionOpenHour, InpSessionOpenMinute, InpRangeMinutes,
               InpSessionCloseHour, InpSessionCloseMinute, InpPerTradeRiskPct*100,
               (string)(InpDryRun?"true":"false"), quant_version());
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) {
      Print("[US500_M15_ORB] FATAL: ftmo_new_account returned 0");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[US500_M15_ORB] deinit reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[US500_M15_ORB] FTMO status=%d -- FLATTEN & HALT", status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   datetime now = TimeCurrent();
   datetime session_date = SessionDateOf(now);

   // New session -> reset state
   if(session_date != g_current_session_date) {
      // If a position is still open from yesterday, force-flat
      if(g_open_ticket != 0) ForceFlat("new_session");
      g_current_session_date = session_date;
      g_range_locked = false;
      g_traded_this_session = false;
      g_range_high = 0; g_range_low = 0;
      PrintFormat("[US500_M15_ORB] new session %s", TimeToString(session_date, TIME_DATE));
   }

   // Force-flat at session close regardless of state
   if(g_open_ticket != 0 && AtSessionClose(now)) {
      ForceFlat("session_close");
      return;
   }

   // Lock the range as soon as we're past the range window
   if(!g_range_locked && !InRangeWindow(now)) {
      MqlDateTime dt; TimeToStruct(now, dt);
      int t_min = dt.hour * 60 + dt.min;
      int range_end = InpSessionOpenHour * 60 + InpSessionOpenMinute + InpRangeMinutes;
      if(t_min >= range_end && t_min < (InpSessionCloseHour * 60 + InpSessionCloseMinute)) {
         BuildRange(now);
      }
   }

   // Entry logic: only if range locked, in trading window, no trade yet today, flat
   if(!g_range_locked) return;
   if(g_traded_this_session) return;
   if(g_open_ticket != 0) return;
   if(!InTradingWindow(now)) return;

   double range_width = g_range_high - g_range_low;
   double last_close = iClose(_Symbol, _Period, 1);  // last fully-closed bar
   if(last_close <= 0 || !MathIsValidNumber(last_close)) return;
   if(range_width / last_close < InpMinRangePct) {
      // Range too narrow -- treat as no-signal-today
      if(!g_traded_this_session) {
         PrintFormat("[US500_M15_ORB] range too narrow %.4f%% < min %.4f%%; skip session",
                     100*range_width/last_close, 100*InpMinRangePct);
         g_traded_this_session = true;  // suppress repeat-skip logging
      }
      return;
   }

   int target_dir = 0;
   if(last_close > g_range_high) target_dir = +1;
   else if(last_close < g_range_low) target_dir = -1;
   if(target_dir == 0) return;

   double stop_distance = range_width;  // SL at opposite range bound
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) {
      PrintFormat("[US500_M15_ORB] sizing returned 0 lots; skip");
      return;
   }

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   // News blackout (NFP/FOMC/CPI/ECB/BoE +/- 5min)
   if(IsNewsBlackout(TimeGMT())) {
      PrintFormat("[US500_M15_ORB] news blackout; skip session");
      g_traded_this_session = true;
      return;
   }
   // Portfolio-level aggregate-risk cap (2% per CLAUDE.md sec 3)
   if(WouldExceedRiskCap(equity, worst_case)) {
      g_traded_this_session = true;
      return;
   }
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[US500_M15_ORB] DENY (worst_case=%.2f)", worst_case);
      g_traded_this_session = true;
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      lots *= 0.5;
      PrintFormat("[US500_M15_ORB] CAUTION halving size (imminent)");
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, entry_px;
   if(target_dir == +1) {
      entry_px = ask;
      sl = g_range_low;
      tp = entry_px + InpTakeProfitMult * range_width;
   } else {
      entry_px = bid;
      sl = g_range_high;
      tp = entry_px - InpTakeProfitMult * range_width;
   }

   PrintFormat("[US500_M15_ORB] ENTRY %s  px=%.2f  range[%.2f,%.2f]  lots=%.2f  sl=%.2f  tp=%.2f",
               (target_dir == +1 ? "LONG" : "SHORT"),
               entry_px, g_range_low, g_range_high, lots, sl, tp);

   g_traded_this_session = true;
   SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl, tp);
}
