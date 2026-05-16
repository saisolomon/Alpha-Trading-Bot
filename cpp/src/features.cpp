#include "quant/features.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace quant {

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

void require_equal_length(const std::vector<double>& a,
                          const std::vector<double>& b,
                          const char* what) {
    if (a.size() != b.size()) {
        throw std::invalid_argument(std::string(what) +
            ": series have different lengths");
    }
}

}  // namespace

std::vector<double> compute_atr(
    const std::vector<double>& high,
    const std::vector<double>& low,
    const std::vector<double>& close,
    int period
) {
    require_equal_length(high, low, "compute_atr");
    require_equal_length(high, close, "compute_atr");
    if (period <= 0) {
        throw std::invalid_argument("compute_atr: period must be positive");
    }

    const std::size_t n = high.size();
    std::vector<double> tr(n, kNaN);

    if (n == 0) return {};

    // True range: bar 0 has no previous close; pandas defines it as
    // (high - low) only -- this matches the existing Python implementation.
    tr[0] = high[0] - low[0];
    for (std::size_t i = 1; i < n; ++i) {
        const double hl = high[i] - low[i];
        const double hpc = std::abs(high[i] - close[i - 1]);
        const double lpc = std::abs(low[i] - close[i - 1]);
        tr[i] = std::max({hl, hpc, lpc});
    }

    return compute_ema(tr, period);
}

std::vector<double> compute_ema(
    const std::vector<double>& series,
    int span
) {
    if (span <= 0) {
        throw std::invalid_argument("compute_ema: span must be positive");
    }

    const std::size_t n = series.size();
    std::vector<double> out(n, kNaN);
    if (n == 0) return out;

    // pandas .ewm(span=span, adjust=False).mean():
    //   alpha = 2 / (span + 1)
    //   y_0 = x_0  (seeded from first value)
    //   y_i = alpha * x_i + (1 - alpha) * y_{i-1}
    const double alpha = 2.0 / (static_cast<double>(span) + 1.0);
    out[0] = series[0];
    for (std::size_t i = 1; i < n; ++i) {
        out[i] = alpha * series[i] + (1.0 - alpha) * out[i - 1];
    }
    return out;
}

std::vector<double> compute_log_returns(
    const std::vector<double>& series,
    int period
) {
    if (period <= 0) {
        throw std::invalid_argument("compute_log_returns: period must be positive");
    }
    const std::size_t n = series.size();
    std::vector<double> out(n, kNaN);
    for (std::size_t i = static_cast<std::size_t>(period); i < n; ++i) {
        const double prev = series[i - static_cast<std::size_t>(period)];
        if (prev > 0.0 && series[i] > 0.0) {
            out[i] = std::log(series[i] / prev);
        }
    }
    return out;
}

std::vector<double> compute_rolling_zscore(
    const std::vector<double>& series,
    int lookback
) {
    if (lookback <= 1) {
        throw std::invalid_argument("compute_rolling_zscore: lookback must be > 1");
    }
    const std::size_t n = series.size();
    const std::size_t L = static_cast<std::size_t>(lookback);
    std::vector<double> out(n, kNaN);
    if (n < L) return out;

    // O(n) with running sums (Welford-ish). Two-pass per index would be O(n*L).
    double sum = 0.0, sum_sq = 0.0;
    std::size_t valid = 0;
    for (std::size_t i = 0; i < L; ++i) {
        if (!std::isnan(series[i])) {
            sum += series[i];
            sum_sq += series[i] * series[i];
            ++valid;
        }
    }

    auto emit = [&](std::size_t i) {
        // Match pandas .rolling(N) default min_periods=N: require the
        // window to be FULL of valid values. Otherwise output NaN.
        // Anything else risks trading on partial-window indicators
        // (research-vs-live drift waiting to happen).
        if (valid < L) {
            out[i] = kNaN;
            return;
        }
        const double mean = sum / static_cast<double>(valid);
        // Sample (ddof=1) variance, matching pandas .rolling().std().
        const double var = (sum_sq - static_cast<double>(valid) * mean * mean) /
                            static_cast<double>(valid - 1);
        if (var <= 0.0) {
            out[i] = kNaN;
            return;
        }
        const double sd = std::sqrt(var);
        const double x = series[i];
        if (std::isnan(x)) {
            out[i] = kNaN;
        } else {
            out[i] = (x - mean) / sd;
        }
    };

    emit(L - 1);

    for (std::size_t i = L; i < n; ++i) {
        const double leaving = series[i - L];
        const double entering = series[i];
        if (!std::isnan(leaving)) {
            sum -= leaving;
            sum_sq -= leaving * leaving;
            --valid;
        }
        if (!std::isnan(entering)) {
            sum += entering;
            sum_sq += entering * entering;
            ++valid;
        }
        emit(i);
    }

    return out;
}

}  // namespace quant
