//+------------------------------------------------------------------+
//| XAUUSD_M15_LondonFix.mq5                                         |
//| Gold London-AM-fix reversal pattern, M15.                        |
//|                                                                  |
//| Mechanism (LBMA twice-daily fixing + practitioner literature):  |
//|   - At 10:30 UTC the LBMA AM gold fix is set. Order-flow         |
//|     auctions before the fix often push gold in one direction,    |
//|     then the fix itself triggers profit-taking from large        |
//|     bullion-bank participants -> a 30-90 min REVERSAL after fix. |
//|                                                                  |
//|   - Pre-fix window: 09:30-10:30 UTC (4 M15 bars)                |
//|   - Pre-fix direction = sign of (close[10:30] - open[09:30])    |
//|   - Entry: at first M15 close AFTER 10:30 UTC                    |
//|     - If pre-fix direction was UP   -> SELL (fade the run-up)    |
//|     - If pre-fix direction was DOWN -> BUY  (fade the sell-off)  |
//|   - Stop: 1.5x M15 ATR(14)                                       |
//|   - TP:   1.5x M15 ATR(14) (1:1)                                 |
//|   - Force flat at 14:00 UTC (3.5h post-entry max hold)           |
//|                                                                  |
//| Skip rules:                                                       |
//|   - Pre-fix range must be > 0.10% of price (avoid degenerate)    |
//|   - One trade per day                                             |
//|   - Skip if FOMC / NFP / CPI scheduled (TODO: news calendar)     |
//|                                                                  |
//| Per-trade risk: 0.25%. Expected: 1 trade/day, ~5 trades/week.   |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpPreFixStartHour     = 9;
input int     InpPreFixStartMinute   = 30;
input int     InpFixHour             = 10;
input int     InpFixMinute           = 30;
input int     InpSessionCloseHour    = 14;       // force-flat 14:00 UTC
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 1.5;
input double  InpAtrTpMult           = 1.5;
input double  InpMinPreFixRangePct   = 0.001;    // 0.1% on gold
input double  InpPerTradeRiskPct     = 0.0050;   // 0.50% per Config C2 (2026-06-11 sizing calibration)
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle           = 0;
datetime g_last_bar_time         = 0;
datetime g_current_session_date  = 0;
bool     g_traded_this_session   = false;
ulong    g_open_ticket           = 0;
int      g_prefix_direction      = 0;  // computed at 10:30 each day
double   g_prefix_range_width    = 0.0;
bool     g_prefix_locked         = false;
int      g_atr_handle            = INVALID_HANDLE;

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

bool PastFix(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   return tm >= InpFixHour * 60 + InpFixMinute;
}

bool AtSessionClose(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   return tm >= InpSessionCloseHour * 60;
}

bool InTradingWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   int tm = dt.hour * 60 + dt.min;
   int start = InpFixHour * 60 + InpFixMinute;
   int end   = InpSessionCloseHour * 60;
   return tm >= start && tm < end;
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

bool ComputePreFixDirection() {
   datetime session_start;
   {
      MqlDateTime dt; TimeToStruct(g_current_session_date, dt);
      dt.hour = InpPreFixStartHour; dt.min = InpPreFixStartMinute; dt.sec = 0;
      session_start = StructToTime(dt);
   }
   datetime fix_time = session_start + ((InpFixHour - InpPreFixStartHour) * 60 +
                                         (InpFixMinute - InpPreFixStartMinute)) * 60;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(_Symbol, PERIOD_M15, 0, 12, rates);
   if(got < 4) return false;
   double open_first = 0, close_last = 0;
   double hi = -1e18, lo = 1e18;
   int matched = 0;
   datetime min_t = 0, max_t = 0;
   for(int i = 0; i < got; i++) {
      if(rates[i].time >= session_start && rates[i].time < fix_time) {
         if(matched == 0 || rates[i].time < min_t) { min_t = rates[i].time; open_first = rates[i].open; }
         if(matched == 0 || rates[i].time > max_t) { max_t = rates[i].time; close_last = rates[i].close; }
         hi = MathMax(hi, rates[i].high);
         lo = MathMin(lo, rates[i].low);
         matched++;
      }
   }
   if(matched < 2) return false;
   g_prefix_direction = (close_last > open_first) ? +1 :
                         (close_last < open_first) ? -1 : 0;
   g_prefix_range_width = hi - lo;
   g_prefix_locked = true;
   PrintFormat("[XAUUSD_M15_LondonFix:%s] pre-fix locked  bars=%d  open=%.2f close=%.2f dir=%+d width=%.2f",
               _Symbol, matched, open_first, close_last, g_prefix_direction, g_prefix_range_width);
   return true;
}

bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double tp) {
   if(InpDryRun) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] DRY-RUN: would %s %.2f  sl=%.2f tp=%.2f",
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
   req.deviation = 30;
   req.type_filling = SafeFillingMode(_Symbol);
   req.comment = "XAUUSD_M15_LondonFix";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[XAUUSD_M15_LondonFix:%s] %s filled  vol=%.2f  px=%.2f  sl=%.2f tp=%.2f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.volume, res.price, sl, tp);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(!PositionSelect(_Symbol)) { g_open_ticket = 0; return; }
   if(InpDryRun) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
      g_open_ticket = 0; return;
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
   req.deviation = 30;
   req.type_filling = SafeFillingMode(_Symbol);
   req.comment = StringFormat("XAUUSD_M15_LondonFix %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] CLOSED (%s) at %.2f", _Symbol, reason, res.price);
   }
   g_open_ticket = 0;
}

int OnInit() {
   if(_Period != PERIOD_M15) {
      PrintFormat("[XAUUSD_M15_LondonFix] FATAL: must run on M15 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[XAUUSD_M15_LondonFix:%s] init  pre-fix=%02d:%02d  fix=%02d:%02d  close=%02d:00 UTC  atr=%d  risk=%.2f%%  dry_run=%s",
               _Symbol, InpPreFixStartHour, InpPreFixStartMinute,
               InpFixHour, InpFixMinute, InpSessionCloseHour, InpAtrPeriod,
               InpPerTradeRiskPct*100, (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[XAUUSD_M15_LondonFix] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_atr_handle = iATR(_Symbol, PERIOD_M15, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE) {
      PrintFormat("[XAUUSD_M15_LondonFix] FATAL: iATR handle creation failed");
      return INIT_FAILED;
   }

   // Broker-state recovery: re-bind to an open position after MT5 restart
   // (prevents duplicate same-session entry). Broker is the source of truth.
   if(!InpDryRun && PositionSelect(_Symbol)) {
      g_open_ticket = (ulong)PositionGetInteger(POSITION_TICKET);
      g_current_session_date = SessionDateOf(TimeCurrent());
      g_traded_this_session = true;   // one-trade-per-day: the open position IS today's trade
      PrintFormat("[XAUUSD_M15_LondonFix:%s] recovered open position ticket=%I64u vol=%.2f -- session marked traded",
                  _Symbol, g_open_ticket, PositionGetDouble(POSITION_VOLUME));
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[XAUUSD_M15_LondonFix:%s] deinit reason=%d", _Symbol, reason);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] FTMO status=%d -- HALT", _Symbol, status);
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
      g_prefix_locked = false;
      g_traded_this_session = false;
      g_prefix_direction = 0;
      g_prefix_range_width = 0;
   }

   if(g_open_ticket != 0 && AtSessionClose(now)) {
      ForceFlat("session_close");
      return;
   }

   if(!g_prefix_locked && PastFix(now)) ComputePreFixDirection();

   if(!g_prefix_locked) return;
   if(g_traded_this_session) return;
   if(g_open_ticket != 0) return;
   if(!InTradingWindow(now)) return;
   if(g_prefix_direction == 0) { g_traded_this_session = true; return; }

   double last_close = iClose(_Symbol, _Period, 1);
   if(last_close <= 0 || !MathIsValidNumber(last_close)) return;
   if(g_prefix_range_width / last_close < InpMinPreFixRangePct) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] pre-fix range too narrow; skip session", _Symbol);
      g_traded_this_session = true;
      return;
   }

   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double atr = atr_buf[1];
   if(!MathIsValidNumber(atr) || atr <= 0) return;

   // Fade pre-fix direction
   int target_dir = -g_prefix_direction;
   double stop_distance = InpAtrStopMult * atr;
   double tp_distance   = InpAtrTpMult   * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) return;

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(IsNewsBlackout(TimeGMT())) {
      PrintFormat("[XAUUSD_M15_LondonFix:%s] news blackout; skip session", _Symbol);
      g_traded_this_session = true; return;
   }
   if(WouldExceedRiskCap(equity, worst_case)) { g_traded_this_session = true; return; }
   if(WouldExceedClusterCap(_Symbol, equity, worst_case)) { g_traded_this_session = true; return; }
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) { g_traded_this_session = true; return; }
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, entry_px;
   if(target_dir == +1) {
      entry_px = ask; sl = entry_px - stop_distance; tp = entry_px + tp_distance;
   } else {
      entry_px = bid; sl = entry_px + stop_distance; tp = entry_px - tp_distance;
   }

   PrintFormat("[XAUUSD_M15_LondonFix:%s] ENTRY %s  px=%.2f  prefix_dir=%+d  atr=%.2f  sl=%.2f tp=%.2f",
               _Symbol, (target_dir == +1 ? "LONG" : "SHORT"),
               entry_px, g_prefix_direction, atr, sl, tp);
   g_traded_this_session = true;
   SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl, tp);
}
