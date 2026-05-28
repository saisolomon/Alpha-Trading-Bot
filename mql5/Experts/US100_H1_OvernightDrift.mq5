//+------------------------------------------------------------------+
//| US100_H1_OvernightDrift.mq5                                      |
//| Long-only overnight risk-premium capture on US100 (NASDAQ-100).  |
//|                                                                  |
//| Mechanism (Kelley & Hofstetter 2019, Lou-Polk-Skouras 2019):     |
//|   - Documented overnight risk premium on QQQ (NASDAQ-100 ETF)   |
//|     and equivalent CFDs: long from US-cash close to next US-    |
//|     cash open captures ~95% of long-term NASDAQ return.         |
//|   - Hypothesis: institutional buy-pressure absorbed during cash |
//|     hours, overnight gaps reflect overseas / passive flow with  |
//|     lower spread costs and less algo competition.                |
//|                                                                  |
//| Entry / exit:                                                     |
//|   - Entry at H1 close of 20:00 UTC (1h before NYSE 4PM close)    |
//|   - Exit  at H1 close of 13:00 UTC (1.5h before NYSE 9:30 open) |
//|   - Hold ~17 hours, always LONG                                 |
//|   - Skip Friday entries (weekend gap risk)                      |
//|   - Skip entry if any news event scheduled in the next 24h      |
//|                                                                  |
//| Stop / risk:                                                     |
//|   - 3x ATR(14) below entry as catastrophic stop (overnight     |
//|     moves > 3 ATR happen ~5% of nights -- prevents tail loss)  |
//|   - 0.25% per-trade risk (M15-cap; held overnight = more vol)  |
//|   - Portfolio risk cap check (2% aggregate)                     |
//|                                                                  |
//| Why this EA is genuinely uncorrelated to the rest:               |
//|   Every other EA in the portfolio trades during ACTIVE sessions |
//|   (London / NY / overlap). This is the ONLY EA that holds       |
//|   overnight. By design, it grinds while everything else sleeps. |
//|   Different alpha source: risk premium, not signal exploitation.|
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpEntryHourUTC        = 20;     // 20:00 UTC = 1h before NYSE close
input int     InpExitHourUTC         = 13;     // 13:00 UTC = 1.5h before NYSE open
input bool    InpSkipFriday          = true;   // skip Friday entries (weekend gap)
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 3.0;
input int     InpNewsLookaheadHours  = 24;     // skip if news within next N hours
input double  InpPerTradeRiskPct     = 0.0025;
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle      = 0;
datetime g_last_bar_time    = 0;
int      g_atr_handle       = INVALID_HANDLE;
ulong    g_open_ticket      = 0;
datetime g_entry_time       = 0;
datetime g_last_traded_date = 0;  // dedup: don't double-enter same day

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

datetime DateOf(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
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
//| Check if any news event lies in the next N hours.                |
//| Used to skip overnight holds that would span a major release.    |
//+------------------------------------------------------------------+
bool NewsInNextHours(const datetime now, const int hours) {
   int mins_to_next = MinutesToNextNews(now);
   if(mins_to_next < 0) return false;  // no news on the horizon
   return mins_to_next < hours * 60;
}

bool SendEntry(const double lots, const double sl) {
   if(InpDryRun) {
      PrintFormat("[US100_H1_OvernightDrift:%s] DRY-RUN: would BUY %.2f  sl=%.2f", _Symbol, lots, sl);
      g_open_ticket = 1;
      return true;
   }
   MqlTradeRequest req; MqlTradeResult res; MqlTradeCheckResult chk;
   ZeroMemory(req); ZeroMemory(res); ZeroMemory(chk);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = lots;
   req.type   = ORDER_TYPE_BUY;
   req.price  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   req.sl = sl;
   req.tp = 0;  // time-based exit
   req.deviation = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = "US100_H1_OvernightDrift";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[US100_H1_OvernightDrift:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[US100_H1_OvernightDrift:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[US100_H1_OvernightDrift:%s] BUY filled  vol=%.2f  px=%.2f  sl=%.2f",
               _Symbol, res.volume, res.price, sl);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(InpDryRun) {
      PrintFormat("[US100_H1_OvernightDrift:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
      g_open_ticket = 0; g_entry_time = 0; return;
   }
   if(!PositionSelect(_Symbol)) { g_open_ticket = 0; return; }
   double vol = PositionGetDouble(POSITION_VOLUME);
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = _Symbol;
   req.volume = vol;
   req.type   = ORDER_TYPE_SELL;
   req.position = PositionGetInteger(POSITION_TICKET);
   req.price  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   req.deviation = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = StringFormat("US100_H1_OvernightDrift %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[US100_H1_OvernightDrift:%s] CLOSED (%s) at %.2f  hold_hours=%.1f",
                  _Symbol, reason, res.price,
                  (double)(TimeCurrent() - g_entry_time) / 3600.0);
   }
   g_open_ticket = 0; g_entry_time = 0;
}

int OnInit() {
   if(_Period != PERIOD_H1) {
      PrintFormat("[US100_H1_OvernightDrift] FATAL: must run on H1 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[US100_H1_OvernightDrift:%s] init  entry=%02d:00 UTC  exit=%02d:00 UTC  skip_fri=%s  atr(%d) stop=%.1fx  news_lookahead=%dh  risk=%.2f%%  dry_run=%s",
               _Symbol, InpEntryHourUTC, InpExitHourUTC,
               (string)(InpSkipFriday?"true":"false"),
               InpAtrPeriod, InpAtrStopMult, InpNewsLookaheadHours,
               InpPerTradeRiskPct*100, (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[US100_H1_OvernightDrift] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_atr_handle = iATR(_Symbol, PERIOD_H1, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE) {
      Print("[US100_H1_OvernightDrift] FATAL iATR handle = INVALID");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[US100_H1_OvernightDrift:%s] deinit reason=%d", _Symbol, reason);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[US100_H1_OvernightDrift:%s] FTMO status=%d -- HALT", _Symbol, status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   datetime now = TimeCurrent();
   MqlDateTime dt; TimeToStruct(now, dt);

   // ---- EXIT LOGIC (only if in position) ----
   if(g_open_ticket != 0) {
      // Detect broker-side close (SL hit overnight)
      if(!InpDryRun && !PositionSelect(_Symbol)) {
         PrintFormat("[US100_H1_OvernightDrift:%s] position closed by broker (SL hit)", _Symbol);
         g_open_ticket = 0; g_entry_time = 0;
         return;
      }
      // Time-based exit at InpExitHourUTC
      if(dt.hour >= InpExitHourUTC) {
         ForceFlat("time_exit");
         return;
      }
      return;  // still holding, wait
   }

   // ---- ENTRY LOGIC (only if flat) ----
   // Only enter at the precise entry hour (H1 bar closes ON that hour)
   if(dt.hour != InpEntryHourUTC) return;
   // De-dup: one entry per UTC date
   datetime today = DateOf(now);
   if(g_last_traded_date == today) return;
   // Skip Friday
   if(InpSkipFriday && dt.day_of_week == 5) {
      g_last_traded_date = today;
      PrintFormat("[US100_H1_OvernightDrift:%s] Friday skip (weekend gap risk)", _Symbol);
      return;
   }
   // Skip weekend days entirely
   if(dt.day_of_week == 0 || dt.day_of_week == 6) {
      return;
   }
   // News blackout: skip if release scheduled in the next 24h
   if(NewsInNextHours(now, InpNewsLookaheadHours)) {
      g_last_traded_date = today;
      PrintFormat("[US100_H1_OvernightDrift:%s] news in next %dh; skip entry",
                  _Symbol, InpNewsLookaheadHours);
      return;
   }

   // ATR for stop sizing
   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double atr = atr_buf[1];
   if(!MathIsValidNumber(atr) || atr <= 0) return;

   double stop_distance = InpAtrStopMult * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) {
      PrintFormat("[US100_H1_OvernightDrift:%s] sizing returned 0 lots; skip", _Symbol);
      g_last_traded_date = today;
      return;
   }

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(WouldExceedRiskCap(equity, worst_case)) {
      g_last_traded_date = today;
      return;
   }
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) { g_last_traded_date = today; return; }
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl  = ask - stop_distance;

   PrintFormat("[US100_H1_OvernightDrift:%s] ENTRY LONG  px=%.2f  atr=%.2f  lots=%.2f  sl=%.2f  hold_until=%02d:00 UTC",
               _Symbol, ask, atr, lots, sl, InpExitHourUTC);
   g_entry_time = now;
   g_last_traded_date = today;
   SendEntry(lots, sl);
}
