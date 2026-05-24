//+------------------------------------------------------------------+
//| XAUUSD_XAGUSD_Pairs.mq5                                                 |
//| Live trading EA for the Gold-Silver cointegration pairs strategy.|
//|                                                                  |
//| Two-leg market-neutral trade:                                    |
//|   long-spread:  long XAUUSD,  short XAGUSD  (dollar-balanced)    |
//|   short-spread: short XAUUSD, long XAGUSD                        |
//|                                                                  |
//| Entry when the rolling z-score of the cointegration residual     |
//| exceeds entry_z; exit on z-reversion, time stop, or catastrophic |
//| widening. Uses the same libquant.dll math the backtest uses --   |
//| see tests/test_cpp_parity.py for the parity guarantees.          |
//|                                                                  |
//| Attach to ANY chart for either XAUUSD or XAGUSD -- the EA loads  |
//| both symbols' bars internally.                                   |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input string  InpAccountType        = "CHALLENGE_2STEP_PHASE1";
input string  InpSymbolA            = "XAUUSD";   // long-spread = long this
input string  InpSymbolB            = "XAGUSD";   // long-spread = short this
input int     InpCointLookback      = 504;        // ~2 years D1
input int     InpZLookback          = 252;        // ~1 year D1
input double  InpEntryZ             = 2.5;
input double  InpExitZ              = 0.5;
input double  InpCatastrophicZ      = 5.0;
input int     InpMaxHoldBars        = 60;         // ~half the 123-bar half-life
input int     InpAtrPeriod          = 14;
input double  InpAtrStopMult        = 1.5;
input double  InpPerTradeRiskPct    = 0.005;      // 0.5% of equity
input bool    InpDryRun             = true;       // log instead of sending

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
long  g_ftmo_handle  = 0;
int   g_pos_direction = 0;     // 0=flat, +1=long-spread, -1=short-spread
ulong g_pos_ticket_a  = 0;     // broker ticket of the leg-A position
ulong g_pos_ticket_b  = 0;
int   g_bars_held     = 0;
double g_entry_z      = 0.0;
datetime g_last_bar_time = 0;

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
   PrintFormat("[XAUUSD_XAGUSD_Pairs] Unknown account_type '%s'", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[XAUUSD_XAGUSD_Pairs] init  pair=%s-%s  lib=%s",
               InpSymbolA, InpSymbolB, quant_version());
   // Ensure both symbols are selected in MarketWatch
   SymbolSelect(InpSymbolA, true);
   SymbolSelect(InpSymbolB, true);

   double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_ftmo_handle = ftmo_new_account(AccountTypeCode(InpAccountType), init_balance);
   if(g_ftmo_handle == 0) {
      Print("[XAUUSD_XAGUSD_Pairs] FATAL: ftmo_new_account returned 0");
      return INIT_FAILED;
   }
   PrintFormat("[XAUUSD_XAGUSD_Pairs] FTMO state init  balance=%.2f handle=%I64d  "
               "dry_run=%s  entry_z=%.2f exit_z=%.2f cat_z=%.2f risk=%.2f%%",
               init_balance, g_ftmo_handle,
               (string)(InpDryRun?"true":"false"),
               InpEntryZ, InpExitZ, InpCatastrophicZ, InpPerTradeRiskPct*100);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   PrintFormat("[XAUUSD_XAGUSD_Pairs] deinit  reason=%d", reason);
   if(g_ftmo_handle != 0) {
      ftmo_free_account(g_ftmo_handle);
      g_ftmo_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| Load N most recent CLOSED bars for a symbol; populate arrays in  |
//| chronological order (oldest at index 0, newest at index n-1).    |
//+------------------------------------------------------------------+
bool LoadCloses(const string symbol, const int n_bars, double &out[]) {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int got = CopyRates(symbol, _Period, 1, n_bars, rates);
   if(got != n_bars) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] CopyRates(%s) returned %d want %d",
                  symbol, got, n_bars);
      return false;
   }
   ArrayResize(out, n_bars);
   for(int i = 0; i < n_bars; i++) {
      out[n_bars - 1 - i] = rates[i].close;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Compute spread signal + ATR. Returns true if all data present.   |
//|                                                                  |
//| BUG-FIX 2026-05-24: Same DBL_MAX-poisoning bug class as US500_MeanRev. |
//| Old code set spread[i] = EMPTY_VALUE for warm-up indices, then    |
//| passed `spread` to quant_rolling_zscore. EMPTY_VALUE (= DBL_MAX)  |
//| is NOT NaN -- the cpp library treats it as real data, overflows   |
//| the running sum to +inf, and outputs NaN forever after.           |
//|                                                                   |
//| Fix mirrors US500_MeanRev: only pass the VALID slice (post-warm-up) to  |
//| the cpp library, and validate all final outputs with              |
//| MathIsValidNumber before returning success.                       |
//+------------------------------------------------------------------+
bool ComputeSpreadSignal(double &out_z, double &out_atr,
                          double &out_beta, double &out_close_a,
                          double &out_close_b) {
   const int n = InpCointLookback + InpZLookback + InpAtrPeriod + 10;
   double closes_a[], closes_b[];
   if(!LoadCloses(InpSymbolA, n, closes_a)) return false;
   if(!LoadCloses(InpSymbolB, n, closes_b)) return false;

   // Validate close prices upfront -- broker glitches happen
   for(int i = 0; i < n; i++) {
      if(closes_a[i] <= 0 || closes_b[i] <= 0 ||
         !MathIsValidNumber(closes_a[i]) || !MathIsValidNumber(closes_b[i])) {
         PrintFormat("[XAUUSD_XAGUSD_Pairs] invalid close at index %d: a=%.4f b=%.4f",
                     i, closes_a[i], closes_b[i]);
         return false;
      }
   }

   // Convert to log-prices for OLS
   double log_a[], log_b[];
   ArrayResize(log_a, n); ArrayResize(log_b, n);
   for(int i = 0; i < n; i++) {
      log_a[i] = MathLog(closes_a[i]);
      log_b[i] = MathLog(closes_b[i]);
   }

   // Rolling OLS  log_a = beta * log_b + alpha
   double beta[], alpha[];
   ArrayResize(beta, n); ArrayResize(alpha, n);
   int rc = quant_rolling_ols(log_b, log_a, n, InpCointLookback, beta, alpha);
   QuantLogIfError(rc, "quant_rolling_ols");
   if(rc != QUANT_OK) return false;

   // Compute spread only over the VALID range -- skip the first
   // (InpCointLookback - 1) indices where beta/alpha are NaN.
   const int valid_start = InpCointLookback - 1;
   const int valid_n = n - valid_start;
   if(valid_n < InpZLookback + InpAtrPeriod + 1) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] insufficient valid bars (%d) post-OLS warmup",
                  valid_n);
      return false;
   }
   double spread[];
   ArrayResize(spread, valid_n);
   for(int j = 0; j < valid_n; j++) {
      int i = j + valid_start;
      // Defensive: even within the valid range, OLS could emit NaN if
      // there's degenerate data. Abort rather than feed garbage on.
      if(!MathIsValidNumber(beta[i]) || !MathIsValidNumber(alpha[i])) {
         PrintFormat("[XAUUSD_XAGUSD_Pairs] OLS produced non-finite at i=%d: "
                     "beta=%.4f alpha=%.4f", i, beta[i], alpha[i]);
         return false;
      }
      spread[j] = log_a[i] - beta[i] * log_b[i] - alpha[i];
   }

   // Z-score of spread (now contains no EMPTY_VALUE contamination)
   double zscore[];
   ArrayResize(zscore, valid_n);
   rc = quant_rolling_zscore(spread, valid_n, InpZLookback, zscore);
   QuantLogIfError(rc, "quant_rolling_zscore");
   if(rc != QUANT_OK) return false;

   // ATR of spread = EMA(|spread.diff()|, InpAtrPeriod) -- all spread
   // entries are now valid, so diff is straightforward.
   double diff_abs[];
   ArrayResize(diff_abs, valid_n);
   diff_abs[0] = 0.0;
   for(int j = 1; j < valid_n; j++) {
      diff_abs[j] = MathAbs(spread[j] - spread[j-1]);
   }
   double spread_atr[];
   ArrayResize(spread_atr, valid_n);
   rc = quant_ema(diff_abs, valid_n, InpAtrPeriod, spread_atr);
   QuantLogIfError(rc, "quant_ema (spread atr)");
   if(rc != QUANT_OK) return false;

   out_z = zscore[valid_n - 1];
   out_atr = spread_atr[valid_n - 1];
   out_beta = beta[n - 1];
   out_close_a = closes_a[n - 1];
   out_close_b = closes_b[n - 1];

   // Final defensive check: never return non-finite signal values.
   if(!MathIsValidNumber(out_z) || !MathIsValidNumber(out_atr) ||
      !MathIsValidNumber(out_beta)) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] WARN non-finite output  z=%.4f atr=%.4f beta=%.4f "
                  "-- ABORTING bar", out_z, out_atr, out_beta);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Compute leg sizes for a market-neutral pair trade given spread   |
//| ATR. Sizing: leg_notional = risk_amount / (atr_stop_mult * atr). |
//+------------------------------------------------------------------+
bool ComputeLots(const double equity, const double spread_atr,
                  const double price_a, const double price_b,
                  double &lots_a, double &lots_b) {
   if(spread_atr <= 0) return false;
   double stop_log = InpAtrStopMult * spread_atr;
   double risk_amount = equity * InpPerTradeRiskPct;
   double leg_notional = risk_amount / stop_log;

   double contract_a = SymbolInfoDouble(InpSymbolA, SYMBOL_TRADE_CONTRACT_SIZE);
   double contract_b = SymbolInfoDouble(InpSymbolB, SYMBOL_TRADE_CONTRACT_SIZE);
   if(contract_a <= 0 || contract_b <= 0) return false;

   double raw_lots_a = leg_notional / (contract_a * price_a);
   double raw_lots_b = leg_notional / (contract_b * price_b);

   double step_a = SymbolInfoDouble(InpSymbolA, SYMBOL_VOLUME_STEP);
   double step_b = SymbolInfoDouble(InpSymbolB, SYMBOL_VOLUME_STEP);
   lots_a = MathFloor(raw_lots_a / step_a) * step_a;
   lots_b = MathFloor(raw_lots_b / step_b) * step_b;

   double min_a = SymbolInfoDouble(InpSymbolA, SYMBOL_VOLUME_MIN);
   double min_b = SymbolInfoDouble(InpSymbolB, SYMBOL_VOLUME_MIN);
   double max_a = SymbolInfoDouble(InpSymbolA, SYMBOL_VOLUME_MAX);
   double max_b = SymbolInfoDouble(InpSymbolB, SYMBOL_VOLUME_MAX);
   lots_a = MathMax(min_a, MathMin(max_a, lots_a));
   lots_b = MathMax(min_b, MathMin(max_b, lots_b));
   return true;
}

//+------------------------------------------------------------------+
//| Send a one-leg market order. type = ORDER_TYPE_BUY / SELL.       |
//+------------------------------------------------------------------+
bool SendLeg(const string symbol, const ENUM_ORDER_TYPE type,
              const double lots, ulong &out_ticket) {
   if(InpDryRun) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] DRY-RUN: would %s %.2f %s",
                  (type==ORDER_TYPE_BUY?"BUY":"SELL"), lots, symbol);
      out_ticket = 0;
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
   req.comment      = "XAUUSD_XAGUSD_Pairs";
   if(!OrderCheck(req, chk) || chk.retcode != 0) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] OrderCheck rejected %s: retcode=%d",
                  symbol, chk.retcode);
      return false;
   }
   if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] OrderSend %s FAILED: retcode=%d",
                  symbol, res.retcode);
      return false;
   }
   out_ticket = res.order;
   PrintFormat("[XAUUSD_XAGUSD_Pairs] %s filled  ticket=%I64u  vol=%.2f  px=%.2f",
               (type==ORDER_TYPE_BUY?"BUY":"SELL"),
               res.order, res.volume, res.price);
   return true;
}

//+------------------------------------------------------------------+
//| Close both legs of the current pairs position                    |
//+------------------------------------------------------------------+
void ClosePosition(const string reason) {
   if(g_pos_direction == 0) return;
   if(InpDryRun) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] DRY-RUN: would CLOSE pair (%s)", reason);
      g_pos_direction = 0;
      g_pos_ticket_a = g_pos_ticket_b = 0;
      g_bars_held = 0;
      return;
   }
   // Long-spread = long A, short B  -> close: sell A, buy B
   // Short-spread = short A, long B -> close: buy A, sell B
   ENUM_ORDER_TYPE close_a = (g_pos_direction == +1) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   ENUM_ORDER_TYPE close_b = (g_pos_direction == +1) ? ORDER_TYPE_BUY  : ORDER_TYPE_SELL;
   // Use PositionSelect to find current volumes (in case of partial fills)
   double vol_a = 0.0, vol_b = 0.0;
   if(PositionSelect(InpSymbolA)) vol_a = PositionGetDouble(POSITION_VOLUME);
   if(PositionSelect(InpSymbolB)) vol_b = PositionGetDouble(POSITION_VOLUME);
   ulong dummy = 0;
   if(vol_a > 0) SendLeg(InpSymbolA, close_a, vol_a, dummy);
   if(vol_b > 0) SendLeg(InpSymbolB, close_b, vol_b, dummy);
   PrintFormat("[XAUUSD_XAGUSD_Pairs] CLOSED pair (%s)", reason);
   g_pos_direction = 0;
   g_pos_ticket_a = g_pos_ticket_b = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   // Per-tick: FTMO equity-line monitor
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   int status = ftmo_apply_tick(g_ftmo_handle, (double)TimeCurrent(), equity);
   if(status >= 2) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] FTMO state status=%d at equity=%.2f -- FLATTEN & HALT",
                  status, equity);
      if(g_pos_direction != 0) ClosePosition("ftmo_kill");
      ExpertRemove();
      return;
   }

   // Bar-close detection -- pairs signal evaluated once per D1 bar close
   datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;
   g_last_bar_time = current_bar;

   // ------------------------------------------------------------------
   // Time-stop must fire INDEPENDENTLY of signal-computation success.
   // If ComputeSpreadSignal ever fails (NaN data, broker glitch, etc.)
   // and we have an open position, the max-hold safety still applies.
   // ------------------------------------------------------------------
   if(g_pos_direction != 0) {
      g_bars_held++;
      if(g_bars_held >= InpMaxHoldBars) {
         PrintFormat("[XAUUSD_XAGUSD_Pairs] EXIT (time_stop)  bars_held=%d  entry_z=%+.2f",
                     g_bars_held, g_entry_z);
         ClosePosition("time_stop");
         return;
      }
   }

   double z, atr, beta, close_a, close_b;
   if(!ComputeSpreadSignal(z, atr, beta, close_a, close_b)) return;
   // ComputeSpreadSignal already MathIsValidNumber-validates z, atr,
   // beta -- but assert it here too so future restructuring doesn't
   // accidentally drop the guarantee.
   if(!MathIsValidNumber(z) || !MathIsValidNumber(atr)) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] non-finite signal post-Compute: z=%.4f atr=%.4f",
                  z, atr);
      return;
   }

   // Exit logic for an existing position (z-based exits + catastrophic)
   if(g_pos_direction != 0) {
      bool exit_z = (MathAbs(z) < InpExitZ);
      bool catastrophic =
         (g_pos_direction == +1 && z < -InpCatastrophicZ) ||
         (g_pos_direction == -1 && z >  InpCatastrophicZ);
      if(exit_z || catastrophic) {
         string reason = catastrophic ? "catastrophic" : "exit_z";
         PrintFormat("[XAUUSD_XAGUSD_Pairs] EXIT (%s)  z=%+.2f  bars_held=%d  entry_z=%+.2f",
                     reason, z, g_bars_held, g_entry_z);
         ClosePosition(reason);
      }
      return;
   }

   // Entry logic
   int target_dir = 0;
   if(z < -InpEntryZ) target_dir = +1;       // long spread
   else if(z >  InpEntryZ) target_dir = -1;  // short spread
   if(target_dir == 0) return;

   double lots_a, lots_b;
   if(!ComputeLots(equity, atr, close_a, close_b, lots_a, lots_b)) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] sizing failed; atr=%.6f", atr);
      return;
   }

   // Headroom check via libftmorisk: approximate worst-case loss as
   // 2x risk budget (the catastrophic stop is at ~2x the ATR stop).
   double worst_case_loss = 2.0 * equity * InpPerTradeRiskPct;
   int decision = ftmo_check_pretrade(g_ftmo_handle, equity, worst_case_loss);
   if(decision == FTMO_DECISION_DENY) {
      PrintFormat("[XAUUSD_XAGUSD_Pairs] DENY entry: headroom violated  worst_case=%.2f",
                  worst_case_loss);
      return;
   }
   if(decision == FTMO_DECISION_IMMINENT) {
      lots_a *= 0.5;
      lots_b *= 0.5;
      PrintFormat("[XAUUSD_XAGUSD_Pairs] CAUTION: halving lot size due to imminent");
   }

   PrintFormat("[XAUUSD_XAGUSD_Pairs] SIGNAL %s  z=%+.2f atr=%.6f beta=%.3f  lots_a=%.2f lots_b=%.2f",
               (target_dir==+1?"LONG-SPREAD":"SHORT-SPREAD"),
               z, atr, beta, lots_a, lots_b);
   ulong ta = 0, tb = 0;
   if(target_dir == +1) {
      // long A, short B
      if(SendLeg(InpSymbolA, ORDER_TYPE_BUY,  lots_a, ta) &&
         SendLeg(InpSymbolB, ORDER_TYPE_SELL, lots_b, tb)) {
         g_pos_direction = +1;
         g_pos_ticket_a = ta; g_pos_ticket_b = tb;
         g_bars_held = 0; g_entry_z = z;
      }
   } else {
      // short A, long B
      if(SendLeg(InpSymbolA, ORDER_TYPE_SELL, lots_a, ta) &&
         SendLeg(InpSymbolB, ORDER_TYPE_BUY,  lots_b, tb)) {
         g_pos_direction = -1;
         g_pos_ticket_a = ta; g_pos_ticket_b = tb;
         g_bars_held = 0; g_entry_z = z;
      }
   }
}
