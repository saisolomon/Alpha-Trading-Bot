#pragma once

// C++ port of ocaml/lib/ftmo_rules.ml -- the FTMO rule state machine.
//
// The OCaml version remains the FORMAL SPEC, with qcheck property tests
// proving its correctness (failure-is-terminal, internal-lines-above-FTMO,
// monotonicity, etc.). This C++ port is what actually runs in MQL5 because
// the Windows OCaml-shared-lib + flexdll path has known DLL-init issues
// that aren't trivially fixable.
//
// A cross-language parity test (tests/test_ocaml_cpp_parity.py) runs the
// SAME tick sequences through both implementations and asserts identical
// status codes, mechanically guaranteeing the two stay in sync.

#include <string>

namespace quant {

// -- Account types (must match OCaml `account_type` constructor order) --
enum FtmoAccountType : int {
    FTMO_ACCT_CHALLENGE_1STEP        = 0,
    FTMO_ACCT_CHALLENGE_2STEP_PHASE1 = 1,
    FTMO_ACCT_CHALLENGE_2STEP_PHASE2 = 2,
    FTMO_ACCT_FUNDED_STANDARD        = 3,
    FTMO_ACCT_FUNDED_SWING           = 4,
    FTMO_ACCT_FUNDED_REWARDS_1STEP   = 5,
};

// -- Status codes (must match OCaml `account_status` severity ordering) --
enum FtmoStatus : int {
    FTMO_STATUS_ACTIVE          = 0,
    FTMO_STATUS_IMMINENT        = 1,
    FTMO_STATUS_INTERNAL_KILLED = 2,
    FTMO_STATUS_FTMO_FAILED     = 3,
};

// -- Pre-trade decision codes --
enum FtmoDecision : int {
    FTMO_DECISION_ALLOW    = 0,
    FTMO_DECISION_DENY     = 1,
    FTMO_DECISION_IMMINENT = 2,
};

// Rule parameters per account type. Mirrors OCaml `rules` record.
struct FtmoRules {
    double ftmo_daily_loss_pct;
    double ftmo_max_loss_pct;
    double internal_daily_kill_pct;
    double internal_max_kill_pct;
    double profit_target_pct;
    double headroom_buffer_pct;
    double imminent_buffer_pct;
    double best_day_throttle_ratio;
};

FtmoRules rules_for(FtmoAccountType account) noexcept;

bool best_day_rule_applies(FtmoAccountType account) noexcept;
bool max_loss_is_trailing(FtmoAccountType account) noexcept;

// Live state. Field meanings mirror OCaml `state`.
struct FtmoState {
    FtmoAccountType account;
    double initial_capital;
    double daily_anchor_balance;
    double highest_eod_balance;
    double today_closed_pnl;
    double sum_profitable_pnl;
    FtmoStatus status;
};

// Constructors / accessors
FtmoState new_state(FtmoAccountType account, double initial_capital) noexcept;

// Derived limits
double ftmo_daily_limit(const FtmoState& s) noexcept;
double ftmo_max_loss_limit(const FtmoState& s) noexcept;
double internal_daily_kill_line(const FtmoState& s) noexcept;
double internal_max_kill_line(const FtmoState& s) noexcept;

// Apply one equity tick. Mutates `s.status` if a threshold is crossed.
// Once status is INTERNAL_KILLED or FTMO_FAILED, further ticks do not
// change it (terminal). Priority order:
//   FTMO_FAILED > INTERNAL_KILLED > IMMINENT > ACTIVE
void apply_tick(FtmoState& s, double unix_ts, double equity) noexcept;

// Pre-trade headroom gate. Returns Allow / Deny / Imminent.
FtmoDecision check_pretrade(
    const FtmoState& s,
    double current_equity,
    double worst_case_loss
) noexcept;

// Prague-midnight rollover. Returns a NEW state with rolled anchors.
FtmoState daily_reset(const FtmoState& s, double balance) noexcept;

// Best Day ratio (1-Step only; returns 0 for other account types or if
// no profitable days yet).
double best_day_ratio(const FtmoState& s, double projected_pnl = 0.0) noexcept;

}  // namespace quant
