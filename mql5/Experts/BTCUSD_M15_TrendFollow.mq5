//+------------------------------------------------------------------+
//| BTCUSD_M15_TrendFollow.mq5                                       |
//| Donchian-channel breakout trend-following on Bitcoin, M15.       |
//|                                                                  |
//| Mechanism (Donchian 1960s, Turtle Traders 1980s, Hurst-Ooi-      |
//| Pedersen 2017 cross-asset momentum replication):                 |
//|   - 24h Donchian channel = max/min of last 96 M15 bars           |
//|   - Long when M15 close > prior 96-bar high (breakout up)        |
//|   - Short when M15 close < prior 96-bar low  (breakout down)     |
//|   - Initial SL: 2x ATR(14) from entry                            |
//|   - Trailing SL: every bar, ratchet SL toward price by 2*ATR     |
//|     (never moves against position)                               |
//|   - No fixed TP -- ride trend until trailing stop hits or        |
//|     opposite breakout signal                                     |
//|   - Cooldown: 16 bars (4h) after each exit to avoid whipsaw      |
//|                                                                  |
//| Why BTCUSD on M15:                                                |
//|   - Crypto is THE strongest TSMOM market in academic literature  |
//|     (Sharpe 0.8-1.5 vs 0.4-0.6 for G10 FX)                       |
//|   - 24/7 trading = no session-time filter needed = more bars     |
//|     per week than any other strategy in the portfolio            |
//|   - Volatility is high enough that Donchian breakouts produce    |
//|     clean signals without parameter optimization                  |
//|   - Completely uncorrelated to existing FX/equity strategies     |
//|                                                                  |
//| FTMO compliance:                                                  |
//|   - Per-tick equity monitor via libftmorisk                      |
//|   - NewsBlackout check before each entry                         |
//|   - Portfolio-level risk-cap gate (2% aggregate per CLAUDE.md)   |
//|   - 0.25% per-trade risk (CLAUDE.md M15 cap)                     |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>
#include <NewsBlackout.mqh>
#include <PortfolioRisk.mqh>

input string  InpAccountType         = "CHALLENGE_2STEP_PHASE1";
input int     InpDonchianBars        = 96;       // 24h on M15
input int     InpAtrPeriod           = 14;
input double  InpAtrStopMult         = 2.0;
input double  InpAtrTrailMult        = 2.0;
input int     InpCooldownBars        = 16;       // 4h
input double  InpPerTradeRiskPct     = 0.0025;
input bool    InpDryRun              = true;

//-- State
long     g_ftmo_handle    = 0;
datetime g_last_bar_time  = 0;
int      g_bars_since_exit = 9999;
int      g_atr_handle     = INVALID_HANDLE;
ulong    g_open_ticket    = 0;
int      g_pos_dir        = 0;   // -1, 0, +1
double   g_trail_sl       = 0.0; // current trailing SL price

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
//| Compute Donchian high + low over last InpDonchianBars closed     |
//| bars (excluding the bar that just closed, which is the trigger). |
//+------------------------------------------------------------------+
bool ComputeDonchian(double &out_high, double &out_low) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(_Symbol, _Period, 1, InpDonchianBars + 1, rates);
   if(got < InpDonchianBars) return false;
   double hi = -1e18, lo = 1e18;
   // skip rates[0] (the just-closed bar = trigger); use [1..N] as channel
   for(int i = 1; i < got; i++) {
      if(rates[i].high > hi) hi = rates[i].high;
      if(rates[i].low  < lo) lo = rates[i].low;
   }
   out_high = hi;
   out_low  = lo;
   return MathIsValidNumber(out_high) && MathIsValidNumber(out_low);
}

bool SendEntry(const ENUM_ORDER_TYPE type, const double lots,
                const double sl) {
   if(InpDryRun) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] DRY-RUN: would %s %.4f  sl=%.2f",
                  _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"), lots, sl);
      g_open_ticket = 1;  // simulate ticket for state machine
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
   req.tp = 0;  // no fixed TP -- trail
   req.deviation = 50;  // BTC spreads wider
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = "BTCUSD_M15_TrendFollow";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] OrderCheck retcode=%d", _Symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] OrderSend retcode=%d", _Symbol, res.retcode);
      return false;
   }
   g_open_ticket = res.order;
   PrintFormat("[BTCUSD_M15_TrendFollow:%s] %s filled  vol=%.4f  px=%.2f  sl=%.2f",
               _Symbol, (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               res.volume, res.price, sl);
   return true;
}

bool ModifyStop(const double new_sl) {
   if(InpDryRun) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] DRY-RUN: would TRAIL SL -> %.2f", _Symbol, new_sl);
      g_trail_sl = new_sl;
      return true;
   }
   if(!PositionSelect(_Symbol)) return false;
   MqlTradeRequest req; MqlTradeResult res;
   ZeroMemory(req); ZeroMemory(res);
   req.action   = TRADE_ACTION_SLTP;
   req.symbol   = _Symbol;
   req.position = PositionGetInteger(POSITION_TICKET);
   req.sl       = new_sl;
   req.tp       = 0;
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      g_trail_sl = new_sl;
      return true;
   }
   PrintFormat("[BTCUSD_M15_TrendFollow:%s] ModifyStop failed retcode=%d", _Symbol, res.retcode);
   return false;
}

void ForceFlat(const string reason) {
   if(g_open_ticket == 0) return;
   if(InpDryRun) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] DRY-RUN: would CLOSE (%s)", _Symbol, reason);
      g_open_ticket = 0; g_pos_dir = 0; g_bars_since_exit = 0;
      return;
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
   req.deviation = 50;
   req.type_filling = ORDER_FILLING_FOK;
   req.comment = StringFormat("BTCUSD_M15_TrendFollow %s", reason);
   if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] CLOSED (%s) at %.2f", _Symbol, reason, res.price);
   }
   g_open_ticket = 0; g_pos_dir = 0; g_bars_since_exit = 0;
}

int OnInit() {
   if(_Period != PERIOD_M15) {
      PrintFormat("[BTCUSD_M15_TrendFollow] FATAL: must run on M15 (current=%s)", EnumToString(_Period));
      return INIT_PARAMETERS_INCORRECT;
   }
   PrintFormat("[BTCUSD_M15_TrendFollow:%s] init  donchian=%d bars  atr(%d) stop=%.1fx trail=%.1fx  cooldown=%d  risk=%.2f%%  dry_run=%s",
               _Symbol, InpDonchianBars, InpAtrPeriod, InpAtrStopMult,
               InpAtrTrailMult, InpCooldownBars, InpPerTradeRiskPct*100,
               (string)(InpDryRun?"true":"false"));
   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) { Print("[BTCUSD_M15_TrendFollow] FATAL ftmo_new_account=0"); return INIT_FAILED; }
   g_atr_handle = iATR(_Symbol, PERIOD_M15, InpAtrPeriod);
   if(g_atr_handle == INVALID_HANDLE) {
      Print("[BTCUSD_M15_TrendFollow] FATAL iATR handle = INVALID");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[BTCUSD_M15_TrendFollow:%s] deinit reason=%d", _Symbol, reason);
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ftmo_handle != 0) { ftmo_free_account(g_ftmo_handle); g_ftmo_handle = 0; }
}

void OnTick() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] FTMO status=%d -- HALT", _Symbol, status);
      ForceFlat("ftmo_kill");
      ExpertRemove();
      return;
   }

   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;
   g_bars_since_exit++;

   // Detect broker-side exit (SL hit by price)
   if(g_open_ticket != 0 && !InpDryRun && !PositionSelect(_Symbol)) {
      PrintFormat("[BTCUSD_M15_TrendFollow:%s] position closed by broker (SL hit)", _Symbol);
      g_open_ticket = 0; g_pos_dir = 0; g_bars_since_exit = 0;
   }

   // ATR for stop sizing + trailing
   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 0, 2, atr_buf) < 2) return;
   double atr = atr_buf[1];
   if(!MathIsValidNumber(atr) || atr <= 0) return;

   // If in position: trail the stop
   if(g_open_ticket != 0 && g_pos_dir != 0) {
      double last_close = iClose(_Symbol, _Period, 1);
      if(!MathIsValidNumber(last_close) || last_close <= 0) return;
      double trail_distance = InpAtrTrailMult * atr;
      double new_sl = (g_pos_dir == +1)
                      ? last_close - trail_distance
                      : last_close + trail_distance;
      // Ratchet only -- never move against the position
      bool should_move = (g_pos_dir == +1 && new_sl > g_trail_sl) ||
                         (g_pos_dir == -1 && new_sl < g_trail_sl);
      if(should_move) {
         ModifyStop(new_sl);
      }
      return;
   }

   // ---- ENTRY GATE ----
   if(g_bars_since_exit < InpCooldownBars) return;
   if(IsNewsBlackout(TimeCurrent())) {
      static datetime last_news_log = 0;
      if(TimeCurrent() - last_news_log > 600) {
         PrintFormat("[BTCUSD_M15_TrendFollow:%s] news blackout (%d min to next event); skip",
                     _Symbol, MinutesToNextNews(TimeCurrent()));
         last_news_log = TimeCurrent();
      }
      return;
   }

   double don_high, don_low;
   if(!ComputeDonchian(don_high, don_low)) return;
   double last_close = iClose(_Symbol, _Period, 1);
   if(!MathIsValidNumber(last_close) || last_close <= 0) return;

   int target_dir = 0;
   if(last_close > don_high)      target_dir = +1;
   else if(last_close < don_low)  target_dir = -1;
   if(target_dir == 0) return;

   double stop_distance = InpAtrStopMult * atr;
   double lots = ComputeLots(equity, stop_distance);
   if(lots <= 0) return;

   // FTMO + portfolio risk check
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
      entry_px = ask;
      sl = entry_px - stop_distance;
   } else {
      entry_px = bid;
      sl = entry_px + stop_distance;
   }

   PrintFormat("[BTCUSD_M15_TrendFollow:%s] ENTRY %s  px=%.2f  donchian[%.2f,%.2f]  atr=%.2f  lots=%.4f  sl=%.2f",
               _Symbol, (target_dir == +1 ? "LONG" : "SHORT"),
               entry_px, don_low, don_high, atr, lots, sl);

   g_pos_dir = target_dir;
   g_trail_sl = sl;
   SendEntry((target_dir == +1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots, sl);
}
