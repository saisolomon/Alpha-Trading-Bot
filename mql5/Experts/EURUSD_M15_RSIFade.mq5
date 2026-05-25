//+------------------------------------------------------------------+
//| EURUSD_M15_RSIFade.mq5                                           |
//| Short-term mean-reversion fade on RSI extremes, M15.             |
//|                                                                  |
//| Mechanism (Bollinger 1992, Avellaneda-Lee 2010 mean-reversion):  |
//|   - On every M15 close, compute RSI(14) on closed bars.         |
//|   - If RSI just crossed ABOVE 80 (overbought) -> SHORT (fade).  |
//|   - If RSI just crossed BELOW 20 (oversold)   -> LONG (fade).   |
//|   - Stop:  1x ATR(14) from entry.                                |
//|   - Take:  1x ATR(14) from entry (1:1 R:R, lots of small wins). |
//|   - Cooldown: skip 8 bars (2h) after each trade to avoid         |
//|     stacking on the same extreme.                                |
//|   - Time filter: only trade during London + NY overlap (07:00-  |
//|     21:00 UTC) to avoid thin-liquidity reversals.                |
//|                                                                  |
//| Symbol-agnostic: attach to EURUSD.sim (default), or any major   |
//| FX pair / index where you want the same mechanism. Same .ex5,   |
//| multiple chart attachments.                                      |
//|                                                                  |
//| Per-trade risk: 0.25%. Expect ~5-10 trades/day across all       |
//| attached symbols.                                                 |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpRsiPeriod           = 14;
input double  InpRsiOverbought       = 80.0;
input double  InpRsiOversold         = 20.0;
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 1.0;       // SL = 1x ATR
input double  InpAtrTpMult           = 1.0;       // TP = 1x ATR (1:1 R:R)
input int     InpCooldownBars        = 8;         // 2h cooldown between trades
input int     InpTradingStartHour    = 7;         // 07:00 UTC = London open
input int     InpTradingEndHour      = 21;        // 21:00 UTC = NY close
input double  InpPerTradeRiskPct     = 0.0025;
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle    = 0;
datetime g_last_bar_time  = 0;
int      g_bars_since_trade = 9999;
ulong    g_open_ticket    = 0;
//-- MQL5 indicator handles (must create once in OnInit, release in OnDeinit)
int      g_rsi_handle = INVALID_HANDLE;
int      g_atr_handle = INVALID_HANDLE;

int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

bool InTradingWindow(const datetime t) {
   MqlDateTime dt; TimeToStruct(t, dt);
   return dt.hour >= InpTradingStartHour && dt.hour < InpTradingEndHour;
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
                const double sl, const double tp, const double rsi_val) {
   if(InpDryRun) {
      PrintFormat("[EURUSD_M15_RSIFade:%s] DRY-RUN: would %s %.2f  rsi=%.1f  sl=%.5f tp=%.5f",
                  _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, rsi_val, sl, tp);
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
   req.comment = "EURUSD_M15_RSIFade";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[EURUSD_M15_RSIFade:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[EURUSD_M15_RSIFade:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[EURUSD_M15_RSIFade:%s] %s filled  rsi=%.1f  vol=%.2f  px=%.5f  sl=%.5f  tp=%.5f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               rsi_val, res.volume, res.price, sl, tp);
   return true;
}

int OnInit() {
   if(_Period != PERIOD_M15) {
      PrintFormat("[EURUSD_M15_RSIFade] FATAL: must run on M15 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[EURUSD_M15_RSIFade:%s] init  rsi(%d) ob=%.0f os=%.0f  atr(%d) stop=%.1fx tp=%.1fx  cooldown=%d  window=%02d-%02d UTC  risk=%.2f%%  dry_run=%s",
               _Symbol, InpRsiPeriod, InpRsiOverbought, InpRsiOversold,
               InpAtrPeriod, InpAtrStopMult, InpAtrTpMult, InpCooldownBars,
               InpTradingStartHour, InpTradingEndHour, InpPerTradeRiskPct*100,
               (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[EURUSD_M15_RSIFade] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_rsi_handle = iRSI(_Symbol, PERIOD_M15, InpRsiPeriod, PRICE_CLOSE);
   g_atr_handle = iATR(_Symbol, PERIOD_M15, InpAtrPeriod);
   if(g_rsi_handle == INVALID_HANDLE || g_atr_handle == INVALID_HANDLE) {
      PrintFormat("[EURUSD_M15_RSIFade] FATAL: indicator handle creation failed rsi=%d atr=%d",
                  g_rsi_handle, g_atr_handle);
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[EURUSD_M15_RSIFade:%s] deinit reason=%d", _Symbol, reason);
   if(g_rsi_handle != INVALID_HANDLE) IndicatorRelease(g_rsi_handle);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[EURUSD_M15_RSIFade:%s] FTMO status=%d -- HALT", _Symbol, status);
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;
   g_bars_since_trade++;

   // If we have an open position, the broker manages SL/TP. Nothing to do.
   if(g_open_ticket != 0) {
      // Detect that the broker closed the position (SL/TP hit) so we can re-arm
      if(!PositionSelect(_Symbol)) g_open_ticket = 0;
      return;
   }

   datetime now = TimeCurrent();
   if(!InTradingWindow(now)) return;
   if(g_bars_since_trade < InpCooldownBars) return;

   // RSI on last 2 closed bars + ATR for stop sizing (handle-based MQL5)
   double rsi_buf[], atr_buf[];
   ArraySetAsSeries(rsi_buf, true);
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_rsi_handle, 0, 0, 3, rsi_buf) < 3) return;
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double rsi_now  = rsi_buf[1];  // last closed bar
   double rsi_prev = rsi_buf[2];  // bar before
   double atr      = atr_buf[1];

   if(!MathIsValidNumber(rsi_now) || !MathIsValidNumber(rsi_prev) ||
      !MathIsValidNumber(atr) || atr <= 0) return;

   int target_dir = 0;
   if(rsi_now >= InpRsiOverbought && rsi_prev < InpRsiOverbought)      target_dir = -1;  // just crossed OB -> short fade
   else if(rsi_now <= InpRsiOversold   && rsi_prev > InpRsiOversold)   target_dir = +1;  // just crossed OS -> long fade
   if(target_dir == 0) return;

   double stop_distance = InpAtrStopMult * atr;
   double tp_distance   = InpAtrTpMult   * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) return;

   double worst_case = lots * stop_distance / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) return;
   if(decision == FTMO_DECISION_IMMINENT) lots *= 0.5;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, entry_px;
   if(target_dir == +1) {
      entry_px = ask;
      sl = entry_px - stop_distance;
      tp = entry_px + tp_distance;
   } else {
      entry_px = bid;
      sl = entry_px + stop_distance;
      tp = entry_px - tp_distance;
   }

   if(SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                 lots, sl, tp, rsi_now)) {
      g_bars_since_trade = 0;
   }
}
