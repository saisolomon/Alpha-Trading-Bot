// C ABI implementation -- thin wrappers over the C++ core.
// Compiled into libquant.dll. MQL5 imports this DLL via stdcall.

#define LIBQUANT_EXPORTS
#include "quant/c_abi.h"

#include "quant/features.hpp"
#include "quant/ftmo_rules.hpp"
#include "quant/markov.hpp"
#include "quant/version.hpp"

#include <cstring>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace {

// Convert a C array + length to a std::vector<double>. Returns true on success.
bool to_vec(const double* p, int n, std::vector<double>* out) {
    if (n < 0) return false;
    if (n > 0 && p == nullptr) return false;
    out->assign(p, p + n);
    return true;
}

// Copy a std::vector<double> into a caller-allocated buffer.
// Returns QUANT_OK if buffer is exactly the expected size.
QuantStatus from_vec(const std::vector<double>& src, double* dst, int dst_n) {
    if (dst == nullptr) return QUANT_ERR_NULL_PTR;
    if (static_cast<int>(src.size()) != dst_n) return QUANT_ERR_BUFFER_TOO_SMALL;
    std::memcpy(dst, src.data(), src.size() * sizeof(double));
    return QUANT_OK;
}

}  // namespace

extern "C" {

const char* QUANT_CALL quant_version(void) {
    return quant::version_string();
}

QuantStatus QUANT_CALL quant_atr(
    const double* high, const double* low, const double* close,
    int n, int period, double* out
) {
    if (high == nullptr || low == nullptr || close == nullptr || out == nullptr)
        return QUANT_ERR_NULL_PTR;
    if (n < 0 || period <= 0) return QUANT_ERR_INVALID_ARG;
    std::vector<double> h, l, c;
    if (!to_vec(high, n, &h) || !to_vec(low, n, &l) || !to_vec(close, n, &c))
        return QUANT_ERR_INVALID_ARG;
    try {
        auto r = quant::compute_atr(h, l, c, period);
        return from_vec(r, out, n);
    } catch (...) {
        return QUANT_ERR_INTERNAL;
    }
}

QuantStatus QUANT_CALL quant_ema(
    const double* series, int n, int span, double* out
) {
    if (series == nullptr || out == nullptr) return QUANT_ERR_NULL_PTR;
    if (n < 0 || span <= 0) return QUANT_ERR_INVALID_ARG;
    std::vector<double> s;
    if (!to_vec(series, n, &s)) return QUANT_ERR_INVALID_ARG;
    try {
        auto r = quant::compute_ema(s, span);
        return from_vec(r, out, n);
    } catch (...) {
        return QUANT_ERR_INTERNAL;
    }
}

QuantStatus QUANT_CALL quant_rolling_zscore(
    const double* series, int n, int lookback, double* out
) {
    if (series == nullptr || out == nullptr) return QUANT_ERR_NULL_PTR;
    if (n < 0 || lookback <= 1) return QUANT_ERR_INVALID_ARG;
    std::vector<double> s;
    if (!to_vec(series, n, &s)) return QUANT_ERR_INVALID_ARG;
    try {
        auto r = quant::compute_rolling_zscore(s, lookback);
        return from_vec(r, out, n);
    } catch (...) {
        return QUANT_ERR_INTERNAL;
    }
}

QuantStatus QUANT_CALL quant_markov_forward(
    const double* state, const double* transition, int n_states, double* out
) {
    if (state == nullptr || transition == nullptr || out == nullptr)
        return QUANT_ERR_NULL_PTR;
    if (n_states <= 0) return QUANT_ERR_INVALID_ARG;
    std::vector<double> s, t;
    if (!to_vec(state, n_states, &s) ||
        !to_vec(transition, n_states * n_states, &t))
        return QUANT_ERR_INVALID_ARG;
    try {
        auto r = quant::markov_forward_step(s, t);
        return from_vec(r, out, n_states);
    } catch (...) {
        return QUANT_ERR_INTERNAL;
    }
}

QuantStatus QUANT_CALL quant_markov_forward_n(
    const double* state, const double* transition,
    int n_states, int n_steps, double* out
) {
    if (state == nullptr || transition == nullptr || out == nullptr)
        return QUANT_ERR_NULL_PTR;
    if (n_states <= 0 || n_steps < 0) return QUANT_ERR_INVALID_ARG;
    std::vector<double> s, t;
    if (!to_vec(state, n_states, &s) ||
        !to_vec(transition, n_states * n_states, &t))
        return QUANT_ERR_INVALID_ARG;
    try {
        auto r = quant::markov_forward_n_steps(s, t, n_steps);
        return from_vec(r, out, n_states);
    } catch (...) {
        return QUANT_ERR_INTERNAL;
    }
}

// ---------------------------------------------------------------------- //
// FTMO rule engine -- handle-based C ABI                                  //
// ---------------------------------------------------------------------- //
//
// State table keyed by integer handle. Wrapped in a mutex because MQL5
// may call from multiple threads (rare but possible).

namespace {

std::mutex g_ftmo_mutex;
long g_next_handle = 1;
std::unordered_map<long, quant::FtmoState> g_ftmo_states;

quant::FtmoState* lookup(long handle) {
    auto it = g_ftmo_states.find(handle);
    return it == g_ftmo_states.end() ? nullptr : &it->second;
}

}  // namespace

long QUANT_CALL ftmo_new_account(int account_code, double initial_capital) {
    if (account_code < 0 || account_code > 5) return 0;
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    long h = g_next_handle++;
    g_ftmo_states.emplace(
        h, quant::new_state(static_cast<quant::FtmoAccountType>(account_code),
                             initial_capital)
    );
    return h;
}

void QUANT_CALL ftmo_free_account(long handle) {
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    g_ftmo_states.erase(handle);
}

int QUANT_CALL ftmo_apply_tick(long handle, double unix_ts, double equity) {
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    auto* s = lookup(handle);
    if (s == nullptr) return -1;
    quant::apply_tick(*s, unix_ts, equity);
    return static_cast<int>(s->status);
}

int QUANT_CALL ftmo_check_pretrade(long handle, double equity, double worst_case_loss) {
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    auto* s = lookup(handle);
    if (s == nullptr) return -1;
    return static_cast<int>(quant::check_pretrade(*s, equity, worst_case_loss));
}

int QUANT_CALL ftmo_daily_reset(long handle, double /*unix_ts*/, double balance) {
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    auto* s = lookup(handle);
    if (s == nullptr) return -1;
    *s = quant::daily_reset(*s, balance);
    return 0;
}

int QUANT_CALL ftmo_status(long handle) {
    std::lock_guard<std::mutex> lk(g_ftmo_mutex);
    auto* s = lookup(handle);
    if (s == nullptr) return -1;
    return static_cast<int>(s->status);
}

}  // extern "C"
