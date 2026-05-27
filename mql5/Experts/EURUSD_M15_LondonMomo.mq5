//+------------------------------------------------------------------+
//| EURUSD_M15_LondonMomo.mq5                                        |
//| London-open momentum continuation, M15 timeframe.                |
//|                                                                  |
//| Mechanism (Lyons 2001 FX microstructure, Menkhoff et al. 2012):  |
//|   - At London cash open (07:00 UTC), institutional flow         |
//|     overwhelms the overnight order book. The direction of the   |
//|     first hour reliably predicts the morning bias.              |
//|   - Range = first 60 min (07:00-08:00 UTC) = 4 M15 bars         |
//|   - Direction = sign of (close[08:00] - open[07:00])            |
//|   - Entry: from 08:00 onwards, on next M15 close that BREAKS    |
//|     the range in the established direction                       |
//|   - Stop: opposite side of the range                            |
//|   - TP: 1.5 * range_width (smaller than ORB because FX trends   |
//|     decay faster mid-day than equity sessions)                  |
//|   - Force flat at 16:00 UTC (London close)                      |
//|                                                                  |
//| This EA is symbol-agnostic: attach to EURUSD.sim by default but |
//| can also be attached to GBPUSD.sim, USDJPY.sim, etc. for the     |
//| same mechanism on other London-active pairs.                    |
//|                                                                  |
//| Per-trade risk: 0.25% (M15 cap per CLAUDE.md).                  |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpSessionOpenHour     = 7;        // London cash open UTC
input int     InpSessionOpenMinute   = 0;
input int     InpRangeMinutes        = 60;
input int     InpSessionCloseHour    = 16;       // London close UTC
input int     InpSessionCloseMinute  = 0;
input double  InpPerTradeRiskPct     = 0.0025;
input double  InpTakeProfitMult      = 1.5;
input double  InpMinRangePct         = 0.0005;   // 0.05% — loosened 2026-05-26 from 0.08% after both validation days skipped for "range too narrow" in low-vol regime
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle           = 0;
datetime g_last_bar_time         = 0;
datetime g_current_session_date  = 0;
double   g_range_high            = 0.0;
double   g_range_low             = 0.0;
double   g_range_open            = 0.0;   // open of first range bar
double   g_range_close           = 0.0;   // close of last range bar
bool     g_range_locked          = false;
bool     g_traded_this_session   = false;
ulong    g_open_ticket           = 0;

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

datetime SessionDateOf(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

bool InRangeWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   int om = InpSessionOpenHour * 60 + InpSessionOpenMinute;
   return tm >= om && tm < om + InpRangeMinutes;
}

bool InTradingWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   int range_end = InpSessionOpenHour * 60 + InpSessionOpenMinute + InpRangeMinutes;
   int close_m   = InpSessionCloseHour * 60 + InpSessionCloseMinute;
   return tm >= range_end && tm < close_m;
}

bool AtSessionClose(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   return tm >= InpSessionCloseHour * 60 + InpSessionCloseMinute;
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
   double lots = MathFloor(raw / step) * step;
   return MathMax(mn, MathMin(mx, lots));
}

bool BuildRange() {
   datetime session_start;
   {
      MqlDateTime dt; TimeToStruct(g_current_session_date, dt);
      dt.hour = InpSessionOpenHour; dt.min = InpSessionOpenMinute; dt.sec = 0;
      session_start = StructToTime(dt);
   }
   datetime range_end = session_start + InpRangeMinutes * 60;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(_Symbol, PERIOD_M15, 0, 12, rates);
   if(got < 4) return false;
   double hi = -1e18, lo = 1e18, op = 0, cl = 0;
   int matched = 0;
   datetime min_time = 0, max_time = 0;
   for(int i = 0; i < got; i++) {
      if(rates[i].time >= session_start && rates[i].time < range_end) {
         hi = MathMax(hi, rates[i].high);
         lo = MathMin(lo, rates[i].low);
         if(matched == 0 || rates[i].time < min_time) { min_time = rates[i].time; op = rates[i].open; }
         if(matched == 0 || rates[i].time > max_time) { max_time = rates[i].time; cl = rates[i].close; }
         matched++;
      }
   }
   if(matched < 2) return false;
   g_range_high = hi;
   g_range_low  = lo;
   g_range_open = op;
   g_range_close = cl;
   g_range_locked = true;
   int dir = (cl > op) ? +1 : (cl < op) ? -1 : 0;
   PrintFormat("[EURUSD_M15_LondonMomo:%s] range locked  bars=%d  hi=%.5f  lo=%.5f  open=%.5f  close=%.5f  dir=%+d",
               _Symbol, matched, g_range_high, g_range_low, g_range_open, g_range_close, dir);
   return true;
}

bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double tp) {
   if(InpDryRun) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] DRY-RUN: would %s %.2f  sl=%.5f tp=%.5f",
                  _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, sl, tp);
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
   req.sl = sl; req.tp = tp;
   req.deviation = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment = "EURUSD_M15_LondonMomo";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[EURUSD_M15_LondonMomo:%s] %s filled  vol=%.2f  px=%.5f  sl=%.5f  tp=%.5f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.volume, res.price, sl, tp);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(!PositionSelect(_Symbol)) { g_open_ticket = 0; return; }
   if(InpDryRun) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
      g_open_ticket = 0;
      return;
   }
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
   req.comment = StringFormat("EURUSD_M15_LondonMomo %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] CLOSED (%s) at %.5f", _Symbol, reason, res.price);
   }
   g_open_ticket = 0;
}

int OnInit() {
   if(_Period != PERIOD_M15) {
      PrintFormat("[EURUSD_M15_LondonMomo] FATAL: must run on M15 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[EURUSD_M15_LondonMomo:%s] init  session=%02d:%02d UTC  range=%dmin  risk=%.2f%%  dry_run=%s",
               _Symbol, InpSessionOpenHour, InpSessionOpenMinute, InpRangeMinutes,
               InpPerTradeRiskPct*100, (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[EURUSD_M15_LondonMomo] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[EURUSD_M15_LondonMomo:%s] deinit reason=%d", _Symbol, reason);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] FTMO status=%d -- HALT", _Symbol, status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   datetime now = TimeCurrent();
   datetime session_date = SessionDateOf(now);
   if(session_date != g_current_session_date) {
      if(g_open_ticket != 0) ForceFlat("new_session");
      g_current_session_date = session_date;
      g_range_locked = false;
      g_traded_this_session = false;
      g_range_high = g_range_low = g_range_open = g_range_close = 0;
   }

   if(g_open_ticket != 0 && AtSessionClose(now)) {
      ForceFlat("session_close");
      return;
   }

   if(!g_range_locked && !InRangeWindow(now)) {
      MqlDateTime dt; TimeToStruct(now, dt);
      int tm = dt.hour * 60 + dt.min;
      int range_end = InpSessionOpenHour * 60 + InpSessionOpenMinute + InpRangeMinutes;
      int close_m   = InpSessionCloseHour * 60 + InpSessionCloseMinute;
      if(tm >= range_end && tm < close_m) BuildRange();
   }

   if(!g_range_locked) return;
   if(g_traded_this_session) return;
   if(g_open_ticket != 0) return;
   if(!InTradingWindow(now)) return;

   int dir = (g_range_close > g_range_open) ? +1 : (g_range_close < g_range_open) ? -1 : 0;
   if(dir == 0) {
      g_traded_this_session = true;
      return;
   }

   double range_width = g_range_high - g_range_low;
   double last_close = iClose(_Symbol, _Period, 1);
   if(last_close <= 0 || !MathIsValidNumber(last_close)) return;
   if(range_width / last_close < InpMinRangePct) {
      if(!g_traded_this_session) {
         PrintFormat("[EURUSD_M15_LondonMomo:%s] range too narrow; skip session", _Symbol);
         g_traded_this_session = true;
      }
      return;
   }

   // Confirmation: M15 close beyond the range in the established direction
   bool confirmed = (dir == +1 && last_close > g_range_high) ||
                    (dir == -1 && last_close < g_range_low);
   if(!confirmed) return;

   double lots = ComputeLots(equity, range_width);
   if(lots <= 0) return;

   double worst_case = lots * range_width / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(IsNewsBlackout(TimeCurrent())) {
      PrintFormat("[EURUSD_M15_LondonMomo:%s] news blackout; skip session", _Symbol);
      g_traded_this_session = true; return;
   }
   if(WouldExceedRiskCap(equity, worst_case)) { g_traded_this_session = true; return; }
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) { g_traded_this_session = true; return; }
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, entry_px;
   if(dir == +1) {
      entry_px = ask; sl = g_range_low; tp = entry_px + InpTakeProfitMult * range_width;
   } else {
      entry_px = bid; sl = g_range_high; tp = entry_px - InpTakeProfitMult * range_width;
   }

   PrintFormat("[EURUSD_M15_LondonMomo:%s] ENTRY %s  px=%.5f  range[%.5f,%.5f]  lots=%.2f  sl=%.5f  tp=%.5f",
               _Symbol, (dir == +1 ? "LONG" : "SHORT"),
               entry_px, g_range_low, g_range_high, lots, sl, tp);
   if(SendEntry((dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl, tp)) {
      g_traded_this_session = true;
   }
}
