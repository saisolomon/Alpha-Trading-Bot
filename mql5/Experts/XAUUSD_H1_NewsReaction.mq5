//+------------------------------------------------------------------+
//| XAUUSD_H1_NewsReaction.mq5                                       |
//| Trade the continuation of a high-impact news bar on gold, H1.   |
//|                                                                  |
//| Mechanism (practitioner: most gold-trading desks fade or follow  |
//| NFP/FOMC/CPI within first H1 after release):                     |
//|   - When a high-impact news event (NFP / FOMC / US CPI / ECB /  |
//|     BoE) fires, the H1 bar containing the release shows the     |
//|     market's first reaction.                                     |
//|   - At the close of THAT bar, enter in the direction of the     |
//|     bar's range (close - open).                                  |
//|   - Stop: 1.5x ATR(14) from entry.                              |
//|   - TP: 2x ATR(14) (1.33:1 R:R; news momentum usually fades     |
//|     fast).                                                       |
//|   - Time stop: 4 H1 bars after entry.                           |
//|   - One trade per news event (cooldown until next news event).  |
//|                                                                  |
//| Note: This EA does NOT call IsNewsBlackout (otherwise it would   |
//| skip its own entry signal). It's the EXCEPTION to the blackout. |
//| All OTHER EAs in the portfolio still avoid the news bar -- only |
//| this one rides it.                                               |
//|                                                                  |
//| Coexistence with XAUUSD_M15_LondonFix:                          |
//|   LondonFix forces flat at 14:00 UTC every day. So if NFP (13:30|
//|   UTC) fires while LondonFix has an open position, the LondonFix|
//|   position is force-closed at 14:00 (its session-close rule)    |
//|   then NewsReaction can enter cleanly at the 14:00 H1 close.    |
//|   The portfolio risk governor also acts as a hard guard.         |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 1.5;
input double  InpAtrTpMult           = 2.0;
input int     InpMaxHoldBars         = 4;        // H1 bars
input int     InpNewsLookbackMin     = 90;       // min: must have news <90 min ago
input double  InpPerTradeRiskPct     = 0.0025;
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle           = 0;
datetime g_last_bar_time         = 0;
datetime g_last_traded_news      = 0;   // dedup: same news event = same trade
ulong    g_open_ticket           = 0;
int      g_bars_in_position      = 0;
int      g_atr_handle            = INVALID_HANDLE;
int      g_pos_dir               = 0;

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

bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl, const double tp) {
   if(InpDryRun) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] DRY-RUN: would %s %.2f  sl=%.2f tp=%.2f",
                  _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, sl, tp);
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
   req.sl = sl; req.tp = tp;
   req.deviation = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = "XAUUSD_H1_NewsReaction";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[XAUUSD_H1_NewsReaction:%s] %s filled  vol=%.2f  px=%.2f  sl=%.2f tp=%.2f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.volume, res.price, sl, tp);
   return true;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(InpDryRun) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
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
   req.deviation = 30;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = StringFormat("XAUUSD_H1_NewsReaction %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] CLOSED (%s) at %.2f", _Symbol, reason, res.price);
   }
   g_open_ticket = 0; g_pos_dir = 0; g_bars_in_position = 0;
}

int OnInit() {
   if(_Period != PERIOD_H1) {
      PrintFormat("[XAUUSD_H1_NewsReaction] FATAL: must run on H1 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[XAUUSD_H1_NewsReaction:%s] init  atr(%d) stop=%.1fx tp=%.1fx  hold=%dh  newslookback=%dmin  risk=%.2f%%  dry_run=%s",
               _Symbol, InpAtrPeriod, InpAtrStopMult, InpAtrTpMult,
               InpMaxHoldBars, InpNewsLookbackMin, InpPerTradeRiskPct*100,
               (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[XAUUSD_H1_NewsReaction] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_atr_handle = iATR(_Symbol, PERIOD_H1, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE) {
      Print("[XAUUSD_H1_NewsReaction] FATAL iATR handle = INVALID");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[XAUUSD_H1_NewsReaction:%s] deinit reason=%d", _Symbol, reason);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] FTMO status=%d -- HALT", _Symbol, status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   // Manage open position
   if(g_open_ticket != 0) {
      g_bars_in_position++;
      // Detect broker-side exit (SL/TP fill)
      if(!InpDryRun && !PositionSelect(_Symbol)) {
         PrintFormat("[XAUUSD_H1_NewsReaction:%s] position closed by broker", _Symbol);
         g_open_ticket = 0; g_pos_dir = 0; g_bars_in_position = 0;
      } else if(g_bars_in_position >= InpMaxHoldBars) {
         ForceFlat("time_stop");
      }
      return;
   }

   // Entry: did a news event happen in the last InpNewsLookbackMin minutes?
   datetime event_time;
   if(!RecentNewsEvent(TimeCurrent(), InpNewsLookbackMin, event_time)) return;
   // De-dup: don't re-trade the same event
   if(event_time == g_last_traded_news) return;

   // Read the JUST-CLOSED H1 bar (the one that contained or followed
   // the news release)
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, PERIOD_H1, 1, 2, rates) < 2) return;
   double bar_open  = rates[0].open;
   double bar_close = rates[0].close;
   double bar_range = MathAbs(bar_close - bar_open);
   if(bar_range <= 0) return;

   int target_dir = (bar_close > bar_open) ? +1 : -1;

   // ATR for sizing
   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double atr = atr_buf[1];
   if(!MathIsValidNumber(atr) || atr <= 0) return;

   // Require the news bar to be at least 0.8 ATR -- otherwise no real
   // reaction, just noise.
   if(bar_range < 0.8 * atr) {
      PrintFormat("[XAUUSD_H1_NewsReaction:%s] news bar range %.2f < 0.8*ATR %.2f; skip",
                  _Symbol, bar_range, 0.8*atr);
      g_last_traded_news = event_time;  // mark this event as handled
      return;
   }

   double stop_distance = InpAtrStopMult * atr;
   double tp_distance   = InpAtrTpMult   * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) return;

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(WouldExceedRiskCap(equity, worst_case)) {
      g_last_traded_news = event_time;
      return;
   }
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) { g_last_traded_news = event_time; return; }
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, entry_px;
   if(target_dir == +1) {
      entry_px = ask; sl = entry_px - stop_distance; tp = entry_px + tp_distance;
   } else {
      entry_px = bid; sl = entry_px + stop_distance; tp = entry_px - tp_distance;
   }

   PrintFormat("[XAUUSD_H1_NewsReaction:%s] ENTRY %s  event=%s  bar_range=%.2f atr=%.2f  px=%.2f  sl=%.2f tp=%.2f",
               _Symbol, (target_dir == +1 ? "LONG" : "SHORT"),
               TimeToString(event_time), bar_range, atr, entry_px, sl, tp);
   g_pos_dir = target_dir;
   g_bars_in_position = 0;
   g_last_traded_news = event_time;
   SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl, tp);
}
