// Faithful C++ port of ocaml/lib/ftmo_rules.ml.
//
// Every public function here mirrors a function in the OCaml module.
// Tests/test_ocaml_cpp_parity.py runs identical tick sequences through
// both implementations and asserts the status codes match -- the
// mechanical guarantee that the two stay in sync.

#include "quant/ftmo_rules.hpp"

#include <algorithm>

namespace quant {

// -- Rules table (must match ocaml/lib/ftmo_rules.ml::rules_for) --
FtmoRules rules_for(FtmoAccountType account) noexcept {
    switch (account) {
        case FTMO_ACCT_CHALLENGE_1STEP:
            return { .ftmo_daily_loss_pct = 0.03,
                     .ftmo_max_loss_pct = 0.10,
                     .internal_daily_kill_pct = 0.02,
                     .internal_max_kill_pct = 0.07,
                     .profit_target_pct = 0.10,
                     .headroom_buffer_pct = 0.01,
                     .imminent_buffer_pct = 0.005,
                     .best_day_throttle_ratio = 0.40 };
        case FTMO_ACCT_CHALLENGE_2STEP_PHASE1:
            return { .ftmo_daily_loss_pct = 0.05,
                     .ftmo_max_loss_pct = 0.10,
                     .internal_daily_kill_pct = 0.03,
                     .internal_max_kill_pct = 0.07,
                     .profit_target_pct = 0.10,
                     .headroom_buffer_pct = 0.01,
                     .imminent_buffer_pct = 0.005,
                     .best_day_throttle_ratio = 0.40 };
        case FTMO_ACCT_CHALLENGE_2STEP_PHASE2:
            return { .ftmo_daily_loss_pct = 0.05,
                     .ftmo_max_loss_pct = 0.10,
                     .internal_daily_kill_pct = 0.03,
                     .internal_max_kill_pct = 0.07,
                     .profit_target_pct = 0.05,
                     .headroom_buffer_pct = 0.01,
                     .imminent_buffer_pct = 0.005,
                     .best_day_throttle_ratio = 0.40 };
        case FTMO_ACCT_FUNDED_STANDARD:
        case FTMO_ACCT_FUNDED_SWING:
            return { .ftmo_daily_loss_pct = 0.05,
                     .ftmo_max_loss_pct = 0.10,
                     .internal_daily_kill_pct = 0.03,
                     .internal_max_kill_pct = 0.07,
                     .profit_target_pct = 0.0,
                     .headroom_buffer_pct = 0.01,
                     .imminent_buffer_pct = 0.005,
                     .best_day_throttle_ratio = 0.40 };
        case FTMO_ACCT_FUNDED_REWARDS_1STEP:
            return { .ftmo_daily_loss_pct = 0.03,
                     .ftmo_max_loss_pct = 0.10,
                     .internal_daily_kill_pct = 0.02,
                     .internal_max_kill_pct = 0.07,
                     .profit_target_pct = 0.0,
                     .headroom_buffer_pct = 0.01,
                     .imminent_buffer_pct = 0.005,
                     .best_day_throttle_ratio = 0.40 };
    }
    // Unreachable; default to 2-step phase 1 as a safe fallback.
    return rules_for(FTMO_ACCT_CHALLENGE_2STEP_PHASE1);
}

bool best_day_rule_applies(FtmoAccountType account) noexcept {
    return account == FTMO_ACCT_CHALLENGE_1STEP
        || account == FTMO_ACCT_FUNDED_REWARDS_1STEP;
}

bool max_loss_is_trailing(FtmoAccountType account) noexcept {
    return account == FTMO_ACCT_FUNDED_REWARDS_1STEP;
}

FtmoState new_state(FtmoAccountType account, double initial_capital) noexcept {
    return FtmoState {
        .account = account,
        .initial_capital = initial_capital,
        .daily_anchor_balance = initial_capital,
        .highest_eod_balance = initial_capital,
        .today_closed_pnl = 0.0,
        .sum_profitable_pnl = 0.0,
        .status = FTMO_STATUS_ACTIVE,
    };
}

double ftmo_daily_limit(const FtmoState& s) noexcept {
    auto r = rules_for(s.account);
    return s.daily_anchor_balance - r.ftmo_daily_loss_pct * s.initial_capital;
}

double ftmo_max_loss_limit(const FtmoState& s) noexcept {
    auto r = rules_for(s.account);
    double floor_base;
    if (max_loss_is_trailing(s.account)) {
        floor_base = std::max(s.highest_eod_balance, s.initial_capital);
    } else {
        floor_base = s.initial_capital;
    }
    return floor_base - r.ftmo_max_loss_pct * s.initial_capital;
}

double internal_daily_kill_line(const FtmoState& s) noexcept {
    auto r = rules_for(s.account);
    return s.daily_anchor_balance - r.internal_daily_kill_pct * s.initial_capital;
}

double internal_max_kill_line(const FtmoState& s) noexcept {
    auto r = rules_for(s.account);
    return s.initial_capital - r.internal_max_kill_pct * s.initial_capital;
}

double best_day_ratio(const FtmoState& s, double projected_pnl) noexcept {
    if (!best_day_rule_applies(s.account)) return 0.0;
    double today = s.today_closed_pnl + projected_pnl;
    double denom = s.sum_profitable_pnl;
    if (today > 0.0) denom += today;
    if (denom <= 0.0) return 0.0;
    return today / denom;
}

void apply_tick(FtmoState& s, double /*unix_ts*/, double equity) noexcept {
    // Terminal status: never transition out.
    if (s.status == FTMO_STATUS_INTERNAL_KILLED ||
        s.status == FTMO_STATUS_FTMO_FAILED) {
        return;
    }
    auto r = rules_for(s.account);
    double imminent_buf = r.imminent_buffer_pct * s.initial_capital;
    double ftmo_daily = ftmo_daily_limit(s);
    double ftmo_max   = ftmo_max_loss_limit(s);
    double int_daily  = internal_daily_kill_line(s);
    double int_max    = internal_max_kill_line(s);

    // Priority: FTMO max > FTMO daily > internal max > internal daily
    //         > imminent max > imminent daily > active.
    if (equity <= ftmo_max) {
        s.status = FTMO_STATUS_FTMO_FAILED;
    } else if (equity <= ftmo_daily) {
        s.status = FTMO_STATUS_FTMO_FAILED;
    } else if (equity <= int_max) {
        s.status = FTMO_STATUS_INTERNAL_KILLED;
    } else if (equity <= int_daily) {
        s.status = FTMO_STATUS_INTERNAL_KILLED;
    } else if (equity < ftmo_max + imminent_buf) {
        s.status = FTMO_STATUS_IMMINENT;
    } else if (equity < ftmo_daily + imminent_buf) {
        s.status = FTMO_STATUS_IMMINENT;
    } else {
        s.status = FTMO_STATUS_ACTIVE;
    }
}

FtmoDecision check_pretrade(
    const FtmoState& s,
    double current_equity,
    double worst_case_loss
) noexcept {
    auto r = rules_for(s.account);
    double worst_case = current_equity - worst_case_loss;
    double buffer = r.headroom_buffer_pct * s.initial_capital;

    double ftmo_daily = ftmo_daily_limit(s);
    double ftmo_max   = ftmo_max_loss_limit(s);
    double int_daily  = internal_daily_kill_line(s);
    double int_max    = internal_max_kill_line(s);

    if (worst_case < ftmo_daily + buffer) return FTMO_DECISION_DENY;
    if (worst_case < ftmo_max + buffer)   return FTMO_DECISION_DENY;
    if (worst_case < int_daily)           return FTMO_DECISION_DENY;
    if (worst_case < int_max)             return FTMO_DECISION_DENY;
    // Best Day governor (1-Step only)
    if (best_day_rule_applies(s.account)) {
        // For pre-trade check, project an OPTIMISTIC PnL = worst_case_loss
        // (i.e., assume win). If even that pushes ratio over throttle, deny.
        double ratio = best_day_ratio(s, worst_case_loss);
        if (ratio > r.best_day_throttle_ratio) return FTMO_DECISION_DENY;
    }
    return FTMO_DECISION_ALLOW;
}

FtmoState daily_reset(const FtmoState& s, double balance) noexcept {
    FtmoState out = s;
    // Roll today's closed P&L into best-day running sum if positive
    if (s.today_closed_pnl > 0.0) {
        out.sum_profitable_pnl = s.sum_profitable_pnl + s.today_closed_pnl;
    }
    out.daily_anchor_balance = balance;
    out.highest_eod_balance = std::max(s.highest_eod_balance, balance);
    out.today_closed_pnl = 0.0;
    out.status = FTMO_STATUS_ACTIVE;  // daily reset clears any imminent flags
    return out;
}

}  // namespace quant
