//+------------------------------------------------------------------+
//| FTMORisk.mqh                                                     |
//| DLL imports for libftmorisk.dll (built from ../ocaml/)           |
//|                                                                  |
//| ALL pre-trade risk decisions go through these imports. Do NOT    |
//| reimplement the FTMO rules in MQL5 -- the OCaml state machine   |
//| is the single source of truth, with property-test guarantees.   |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"

// Decision return codes (match the OCaml pretrade_decision variant).
#define FTMO_DECISION_ALLOW     0
#define FTMO_DECISION_DENY      1
#define FTMO_DECISION_IMMINENT  2

// Account type codes (match the OCaml account_type variant).
#define FTMO_ACCT_CHALLENGE_1STEP        0
#define FTMO_ACCT_CHALLENGE_2STEP_PHASE1 1
#define FTMO_ACCT_CHALLENGE_2STEP_PHASE2 2
#define FTMO_ACCT_FUNDED_STANDARD        3
#define FTMO_ACCT_FUNDED_SWING           4
#define FTMO_ACCT_FUNDED_REWARDS_1STEP   5

// PLACEHOLDER: these are the function signatures Phase 5 will implement.
// The actual symbol names will be exported by the OCaml `Ctypes.foreign`
// stubs in ../ocaml/lib/c_stubs.ml.

#import "libftmorisk.dll"
   // Initialise an account snapshot. Returns an opaque handle (long).
   long    ftmo_new_account(int account_type, double initial_capital);

   // Free a handle previously returned by ftmo_new_account.
   void    ftmo_free_account(long handle);

   // Apply one equity tick. Returns the new account status code:
   //   0 = Active
   //   1 = Internal_killed
   //   2 = Ftmo_failed
   int     ftmo_apply_tick(long handle, double unix_ts, double equity);

   // Pre-trade decision. Returns FTMO_DECISION_*.
   int     ftmo_check_pretrade(long handle, double current_equity,
                                double worst_case_drawdown);

   // Roll over to the next Prague day -- update midnight_balance to current
   // equity. Caller is responsible for invoking this at 00:00 Europe/Prague.
   void    ftmo_daily_reset(long handle);
#import

//+------------------------------------------------------------------+
//| Convenience: human-readable decision label for logging          |
//+------------------------------------------------------------------+
string FTMODecisionString(const int decision) {
   switch(decision) {
      case FTMO_DECISION_ALLOW:    return "ALLOW";
      case FTMO_DECISION_DENY:     return "DENY";
      case FTMO_DECISION_IMMINENT: return "IMMINENT";
      default:                      return StringFormat("UNKNOWN(%d)", decision);
   }
}
