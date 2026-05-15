//+------------------------------------------------------------------+
//| FTMOBot.mq5                                                      |
//| The live trading EA. Orchestrates: tick -> features -> regime -> |
//| signal -> risk gate -> order send.                                |
//|                                                                  |
//| Per ../ARCHITECTURE.md this file should stay short. All math    |
//| flows through libquant.dll. All risk decisions flow through     |
//| libftmorisk.dll. The MQL5 layer is glue, not logic.              |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property link      "https://github.com/your-org/ftmo-bot"
#property version   "0.10"
#property strict

#include <QuantLib.mqh>
#include <FTMORisk.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input string  InpStrategy        = "index_meanrev";  // strategy id
input int     InpFormationBars   = 20;
input double  InpEntryZ          = 1.0;
input double  InpExitZ           = 0.5;
input int     InpMaxHoldBars     = 10;
input double  InpAtrStopMult     = 1.5;
input double  InpAtrTpMult       = 2.0;
input double  InpRiskPct         = 0.005;            // 0.5% per trade
input string  InpAccountType     = "CHALLENGE_2STEP_PHASE1";

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
long g_account_handle = 0;
int  g_bar_count      = 0;
datetime g_last_bar_time = 0;

//+------------------------------------------------------------------+
//| Map account-type string to FTMO_ACCT_* code                     |
//+------------------------------------------------------------------+
int AccountTypeCode(const string s) {
   if(s == "CHALLENGE_1STEP")        return FTMO_ACCT_CHALLENGE_1STEP;
   if(s == "CHALLENGE_2STEP_PHASE1") return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
   if(s == "CHALLENGE_2STEP_PHASE2") return FTMO_ACCT_CHALLENGE_2STEP_PHASE2;
   if(s == "FUNDED_STANDARD")        return FTMO_ACCT_FUNDED_STANDARD;
   if(s == "FUNDED_SWING")           return FTMO_ACCT_FUNDED_SWING;
   if(s == "FUNDED_REWARDS_1STEP")   return FTMO_ACCT_FUNDED_REWARDS_1STEP;
   PrintFormat("[FTMOBot] Unknown account type '%s'; defaulting to 2STEP_PHASE1", s);
   return FTMO_ACCT_CHALLENGE_2STEP_PHASE1;
}

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[FTMOBot] init: strategy=%s, lib=%s",
               InpStrategy, quant_version());

   // Allocate FTMO risk state machine for THIS account.
   const double init_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   g_account_handle = ftmo_new_account(
      AccountTypeCode(InpAccountType),
      init_balance
   );
   if(g_account_handle == 0) {
      Print("[FTMOBot] FATAL: ftmo_new_account returned null handle");
      return INIT_FAILED;
   }
   PrintFormat("[FTMOBot] FTMO state initialised: balance=%.2f, handle=%I64d",
               init_balance, g_account_handle);

   // Validate symbol matches the strategy's expected universe.
   PrintFormat("[FTMOBot] Bound to symbol: %s, timeframe: %s",
               _Symbol, EnumToString(_Period));

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   PrintFormat("[FTMOBot] deinit: reason=%d", reason);
   if(g_account_handle != 0) {
      ftmo_free_account(g_account_handle);
      g_account_handle = 0;
   }
}

//+------------------------------------------------------------------+
//| OnTick                                                           |
//| Drives the per-tick equity update and (on bar close) the signal |
//| pipeline.                                                        |
//+------------------------------------------------------------------+
void OnTick() {
   // 1. Update FTMO state from current account equity (sub-second polling).
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const int status = ftmo_apply_tick(g_account_handle,
                                      (double)TimeCurrent(), equity);
   if(status != 0) {
      // Internal kill or FTMO failure. Flatten and stop trading.
      // PHASE 6: implement actual flatten-all-positions here.
      PrintFormat("[FTMOBot] FTMO state non-Active: status=%d -- halting trading",
                  status);
      ExpertRemove();
      return;
   }

   // 2. New-bar detection (signal pipeline only fires on bar close).
   const datetime current_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   if(current_bar == g_last_bar_time) return;  // mid-bar -- nothing more to do
   g_last_bar_time = current_bar;

   // 3. PHASE 1-3 of the build plan slots in here:
   //      - load recent bars
   //      - call quant_atr / quant_rolling_zscore via libquant
   //      - call quant_markov_forward (Phase 1)
   //      - call ONNX inference (Phase 3)
   //      - check ftmo_check_pretrade
   //      - OrderSend if everything passes
   //
   // Currently a placeholder log so the EA compiles and shows up in the
   // Experts log when attached to a chart.
   if(g_bar_count % 50 == 0) {
      PrintFormat("[FTMOBot] bar %d: equity=%.2f -- signal pipeline NOT YET IMPLEMENTED",
                  g_bar_count, equity);
   }
   g_bar_count++;
}

//+------------------------------------------------------------------+
//| OnTradeTransaction                                               |
//| Called when a trade event (open/modify/close) occurs.            |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result) {
   // PHASE 6: reconcile our internal state with broker fills.
}
