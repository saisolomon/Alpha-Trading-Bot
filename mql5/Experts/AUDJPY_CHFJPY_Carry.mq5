//+------------------------------------------------------------------+
//| AUDJPY_CHFJPY_Carry.mq5                                              |
//| Regime-gated JPY-cross carry trade.                              |
//|                                                                  |
//|   long AUDJPY  + short CHFJPY                                    |
//|                                                                  |
//| Per the 2026-05-19 swap re-probe: every JPY-cross has NEGATIVE   |
//| swap_short on this broker (the swap spread is wider than the    |
//| rate differential). The original AUDJPY/NZDJPY pairing failed   |
//| the entry gate because NZDJPY swap_short = -3.83 ate the entire |
//| AUDJPY +3.52 carry.                                              |
//|                                                                  |
//| FIX: pair AUDJPY long with CHFJPY short. CHFJPY swap_short is    |
//| only -0.06 (smallest of any JPY cross), so net carry of the      |
//| pairing = +3.52 - 0.06 = +3.46 $/lot/day -- almost the full      |
//| AUDJPY carry. CHF is also the canonical risk-off currency, so    |
//| short CHFJPY provides a partial hedge against JPY-rally carry-   |
//| unwind events (when JPY rallies, CHFJPY usually drops too,       |
//| meaning our SHORT profits, partly offsetting the long-AUDJPY     |
//| loss).                                                            |
//|                                                                  |
//| Regime gate is NET CARRY based (not per-leg) -- it asks whether  |
//| the PAIRING earns positive carry, which is what matters.         |
//|                                                                  |
//| Entry: net carry > +2.00 $/lot/day, no CB meeting +/- 3 days     |
//| Exit:  TP +2%, SL -1%, time stop 60d, net-carry throttle <+1.00, |
//|        pre-flatten 24h before next BoJ/RBA/SNB meeting           |
//|                                                                  |
//| See strategies/jpy_carry/HYPOTHESIS.md for the academic basis.   |
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
input string  InpSymbolLong             = "AUDJPY";   // long leg (highest swap_long carrier)
input string  InpSymbolShort            = "CHFJPY";   // short leg (smallest swap_short cost)
input double  InpPerLegRiskPct          = 0.005;      // 0.5% per leg, 1% aggregate
input int     InpAtrPeriod              = 14;
input double  InpAtrStopMult            = 1.0;        // stop = 1x ATR for sizing
input double  InpTakeProfitEquityPct    = 0.02;       // +2% account equity
input double  InpStopLossEquityPct      = 0.01;       // -1% account equity
input int     InpMaxHoldBars            = 60;         // D1 bars (~3 months)
//-- NET-carry regime gate: sum(swap_long_of_long_leg, swap_short_of_short_leg)
//-- Entry threshold higher than exit threshold so positions get breathing room.
input double  InpEntryNetCarryMin       = 2.00;       // net $/lot/day required to enter
input double  InpExitNetCarryMin        = 1.00;       // throttle if net carry drops below
//-- News gate (hardcoded for now; future: load configs/cb_meetings.yaml)
input int     InpNewsBufferDays         = 3;          // skip +/- N days around CB meetings
input bool    InpDryRun                 = true;

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
long     g_ftmo_handle      = 0;
int      g_pos_state        = 0;     // 0=flat, 1=open
double   g_entry_equity     = 0.0;   // account equity at entry
int      g_bars_held        = 0;
datetime g_last_bar_time    = 0;
double   g_lots_long        = 0.0;
double   g_lots_short       = 0.0;

//+------------------------------------------------------------------+
//| Hardcoded CB meeting dates (placeholder -- replace with YAML).   |
//| Includes scheduled BoJ MPM, RBA Board, RBNZ MPC dates 2026.      |
//+------------------------------------------------------------------+
datetime g_cb_meetings[] = {
   D'2026.01.21 03:00',  // BoJ MPM
   D'2026.02.03 03:30',  // RBA Board
   D'2026.02.18 02:00',  // RBNZ MPC
   D'2026.03.18 03:00',  // BoJ MPM
   D'2026.03.31 03:30',  // RBA Board
   D'2026.04.08 02:00',  // RBNZ MPC
   D'2026.04.30 03:00',  // BoJ MPM
   D'2026.05.05 03:30',  // RBA Board
   D'2026.05.27 02:00',  // RBNZ MPC
   D'2026.06.17 03:00',  // BoJ MPM
   D'2026.07.07 03:30',  // RBA Board
   D'2026.07.08 02:00',  // RBNZ MPC
   D'2026.07.30 03:00',  // BoJ MPM
   D'2026.08.04 03:30',  // RBA Board
   D'2026.08.19 02:00',  // RBNZ MPC
   D'2026.09.18 03:00',  // BoJ MPM
   D'2026.09.30 03:30',  // RBA Board
   D'2026.10.07 02:00',  // RBNZ MPC
   D'2026.10.29 03:00',  // BoJ MPM
   D'2026.11.03 03:30',  // RBA Board
   D'2026.11.25 02:00',  // RBNZ MPC
   D'2026.12.17 03:00',  // BoJ MPM
   D'2026.12.08 03:30',  // RBA Board
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
   PrintFormat("[AUDJPY_CHFJPY_Carry] Unknown account_type '%s'", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| Returns true if current time is within +/- N days of any         |
//| scheduled central bank meeting.                                  |
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

//+------------------------------------------------------------------+
//| Returns true if there's a CB meeting within the next 24h.        |
//| Used to PRE-FLATTEN before announcements (one-sided check).      |
//+------------------------------------------------------------------+
bool MeetingWithin24h(const datetime now) {
   const int n = ArraySize(g_cb_meetings);
   for(int i = 0; i < n; i++) {
      long delta = (long)g_cb_meetings[i] - (long)now;
      if(delta >= 0 && delta <= 86400) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Read SYMBOL_SWAP_LONG / SYMBOL_SWAP_SHORT, convert to $/lot/day  |
//| approximation. Returns true on success.                          |
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

   // swap_mode 1 = SYMBOL_SWAP_MODE_POINTS: convert via tick_value
   // swap_mode 2 = SYMBOL_SWAP_MODE_CURRENCY_SYMBOL: already in account ccy
   if(mode == 1) {
      if(tick_size <= 0) return false;
      const double scale = point * tick_val / tick_size;
      out_long = sl * scale;
      out_short = ss * scale;
   } else if(mode == 2) {
      out_long = sl;
      out_short = ss;
   } else {
      PrintFormat("[AUDJPY_CHFJPY_Carry] %s swap_mode=%I64d (unknown units)",
                  symbol, mode);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Compute ATR(period) using the recent rates buffer.               |
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
//| Compute lot size for one leg.                                    |
//|   risk_amount = equity * per_leg_pct                             |
//|   stop_distance_quote = atr_stop_mult * ATR (price units)        |
//|   lot_size = risk_amount / (contract_size * stop_distance_quote /|
//|              price * tick_value_per_pip_per_lot) -- simplified   |
//|              via MQL5 OrderCalcProfit-style.                     |
//+------------------------------------------------------------------+
bool ComputeLot(const string symbol, const double equity,
                 const double atr, double &out_lots) {
   double risk_amount = equity * InpPerLegRiskPct;
   double stop_distance = InpAtrStopMult * atr;
   if(stop_distance <= 0) return false;

   double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_size <= 0) return false;

   // value of 1 price unit per 1 lot
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
//| Send a one-leg market order. type = ORDER_TYPE_BUY / SELL.       |
//+------------------------------------------------------------------+
bool SendLeg(const string symbol, const ENUM_ORDER_TYPE type,
              const double lots) {
   if(InpDryRun) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] DRY-RUN: would %s %.2f %s",
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
   req.deviation    = 20;
   req.type_filling = ORDER_FILLING_IOC;
   req.comment      = "AUDJPY_CHFJPY_Carry";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] OrderCheck rejected %s: retcode=%d",
                  symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] OrderSend %s FAILED: retcode=%d",
                  symbol, res.retcode);
      return false;
   }
   PrintFormat("[AUDJPY_CHFJPY_Carry] %s filled  vol=%.2f  px=%.5f",
               (type==ORDER_TYPE_BUY?"BUY":"SELL"), res.volume, res.price);
   return true;
}

//+------------------------------------------------------------------+
//| Close both legs of the carry position.                           |
//+------------------------------------------------------------------+
void ClosePosition(const string reason) {
   if(g_pos_state == 0) return;
   if(InpDryRun) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] DRY-RUN: would CLOSE both legs (%s)",
                  reason);
      g_pos_state = 0;
      g_bars_held = 0;
      g_lots_long = g_lots_short = 0.0;
      return;
   }
   double vol_l = 0.0, vol_s = 0.0;
   if(PositionSelect(InpSymbolLong))  vol_l = PositionGetDouble(POSITION_VOLUME);
   if(PositionSelect(InpSymbolShort)) vol_s = PositionGetDouble(POSITION_VOLUME);
   if(vol_l > 0) SendLeg(InpSymbolLong,  ORDER_TYPE_SELL, vol_l);  // close long
   if(vol_s > 0) SendLeg(InpSymbolShort, ORDER_TYPE_BUY,  vol_s);  // close short
   PrintFormat("[AUDJPY_CHFJPY_Carry] CLOSED carry pair (%s)", reason);
   g_pos_state = 0;
   g_bars_held = 0;
   g_lots_long = g_lots_short = 0.0;
}

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[AUDJPY_CHFJPY_Carry] init  long=%s short=%s  lib=%s",
               InpSymbolLong, InpSymbolShort, quant_version());
   SymbolSelect(InpSymbolLong,  true);
   SymbolSelect(InpSymbolShort, true);

   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) {
      Print("[AUDJPY_CHFJPY_Carry] FATAL: ftmo_new_account returned 0");
      return INIT_FAILED;
   }
   PrintFormat("[AUDJPY_CHFJPY_Carry] FTMO state  bal=%.2f handle=%I64d  dry_run=%s",
               init_balance, g_ftmo_handle,
               (string)(InpDryRun?"true":"false"));
   PrintFormat("[AUDJPY_CHFJPY_Carry] gates: entry net_carry>=%.2f $/lot/day  "
               "exit net_carry<%.2f  news_buffer=%dd  "
               "tp=+%.1f%% sl=-%.1f%% max_hold=%db",
               InpEntryNetCarryMin, InpExitNetCarryMin,
               InpNewsBufferDays,
               InpTakeProfitEquityPct*100, InpStopLossEquityPct*100,
               InpMaxHoldBars);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   PrintFormat("[AUDJPY_CHFJPY_Carry] deinit  reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   // Per-tick FTMO equity-line monitor (per CLAUDE.md sec 3)
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] FTMO status=%d equity=%.2f -- FLATTEN & HALT",
                  status, equity);
      if(g_pos_state != 0) ClosePosition("ftmo_kill");
      ExpertRemove();
      return;
   }

   // Per-tick: TP/SL on equity (carry strategy uses equity-PnL exits)
   if(g_pos_state == 1) {
      // Defensive: if g_entry_equity got corrupted to 0 (state bug,
      // hot-reload mid-position), the division would NaN and ALL
      // comparisons would silently return false -- the position
      // would never exit via TP/SL. Fail safe to time-stop instead.
      if(g_entry_equity <= 0 || !MathIsValidNumber(g_entry_equity)) {
         PrintFormat("[AUDJPY_CHFJPY_Carry] WARN g_entry_equity=%.4f invalid; "
                     "force-closing position", g_entry_equity);
         ClosePosition("entry_equity_corrupt");
         return;
      }
      double pnl_pct = (equity - g_entry_equity) / g_entry_equity;
      if(!MathIsValidNumber(pnl_pct)) {
         PrintFormat("[AUDJPY_CHFJPY_Carry] WARN pnl_pct=NaN; force-closing");
         ClosePosition("pnl_nan");
         return;
      }
      if(pnl_pct >= InpTakeProfitEquityPct) {
         ClosePosition("take_profit");
         return;
      }
      if(pnl_pct <= -InpStopLossEquityPct) {
         ClosePosition("stop_loss");
         return;
      }
      // Pre-flatten 24h before next CB meeting
      if(MeetingWithin24h(TimeCurrent())) {
         ClosePosition("pre_news_flatten");
         return;
      }
   }

   // Once-per-D1-bar evaluation
   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, PERIOD_D1, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   // Read swap rates for both legs (every D1 bar; broker may re-set)
   double long_sl, long_ss, short_sl, short_ss;
   if(!GetSwapPerLotPerDay(InpSymbolLong,  long_sl, long_ss)) return;
   if(!GetSwapPerLotPerDay(InpSymbolShort, short_sl, short_ss)) return;

   // NET carry of the pairing: what we EARN per lot per day if both
   // positions are opened simultaneously.
   //   long leg earns swap_long_of_long_leg
   //   short leg earns swap_short_of_short_leg
   double net_carry = long_sl + short_ss;
   if(!MathIsValidNumber(net_carry)) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] WARN net_carry=NaN (long_sl=%.2f short_ss=%.2f) "
                  "-- skipping bar", long_sl, short_ss);
      return;
   }

   if(g_pos_state == 1) {
      g_bars_held++;
      // Time stop
      if(g_bars_held >= InpMaxHoldBars) {
         ClosePosition("time_stop");
         return;
      }
      // Regime throttle: net carry collapsed below exit threshold
      if(net_carry < InpExitNetCarryMin) {
         PrintFormat("[AUDJPY_CHFJPY_Carry] regime throttle  net_carry=%.2f  "
                     "(long %s swap_long=%.2f + short %s swap_short=%.2f)",
                     net_carry, InpSymbolLong, long_sl,
                     InpSymbolShort, short_ss);
         ClosePosition("regime_throttle");
         return;
      }
      return;
   }

   // Entry logic (only when flat)
   if(InNewsBlackout(TimeCurrent(), InpNewsBufferDays)) {
      // Quiet during news window
      return;
   }
   if(net_carry < InpEntryNetCarryMin) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] gate FAIL  net_carry=%.2f need>=%.2f  "
                  "(long %s swap_long=%.2f + short %s swap_short=%.2f)",
                  net_carry, InpEntryNetCarryMin,
                  InpSymbolLong, long_sl,
                  InpSymbolShort, short_ss);
      return;
   }

   // Sizing
   double atr_long, atr_short;
   if(!ComputeAtrD1(InpSymbolLong,  InpAtrPeriod, atr_long))  return;
   if(!ComputeAtrD1(InpSymbolShort, InpAtrPeriod, atr_short)) return;
   double lots_long, lots_short;
   if(!ComputeLot(InpSymbolLong,  equity, atr_long,  lots_long))  return;
   if(!ComputeLot(InpSymbolShort, equity, atr_short, lots_short)) return;

   // Headroom check: aggregate worst-case = 2 * per-leg risk (SL trigger
   // pads to ~2x ATR via the equity-stop logic).
   double worst_case = 2.0 * equity * InpPerLegRiskPct;  // ~1% of equity
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[AUDJPY_CHFJPY_Carry] DENY: headroom violated  worst_case=%.2f",
                  worst_case);
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      lots_long  *= 0.5;
      lots_short *= 0.5;
      PrintFormat("[AUDJPY_CHFJPY_Carry] CAUTION: halving lot size (imminent)");
   }

   // Both legs must succeed or we don't open either (atomic entry)
   PrintFormat("[AUDJPY_CHFJPY_Carry] ENTRY  %s long %.2f lots (swap_long=%.2f) "
               "+ %s short %.2f lots (swap_short=%.2f)  net_carry=%.2f $/lot/day",
               InpSymbolLong, lots_long, long_sl,
               InpSymbolShort, lots_short, short_ss, net_carry);

   if(InpDryRun) {
      // dry run: log both and set state
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
      Print("[AUDJPY_CHFJPY_Carry] long leg failed; aborting entry");
      return;
   }
   if(!SendLeg(InpSymbolShort, ORDER_TYPE_SELL, lots_short)) {
      // Long leg already filled; close it to keep atomic
      Print("[AUDJPY_CHFJPY_Carry] short leg failed; unwinding long leg");
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
