#pragma once

// Feature math used by both research backtests (Python via pybind11) and the
// live MQL5 EA (via DLL import). Single source of truth -- reimplementing
// these in MQL5 would re-introduce research-vs-live drift.
//
// All functions are pure: no internal state, no global mutation. They take
// std::vector<double> inputs (all of equal length, indexed by bar) and
// return a std::vector<double> output of the same length, with NaN in the
// warmup positions.
//
// Conventions:
//   - Inputs are bar-aligned price series (open/high/low/close/etc).
//   - Output[i] is computable from inputs[0..i] only -- NO LOOK-AHEAD.
//   - Warmup positions (where the rolling window has insufficient bars)
//     contain std::nan("") so callers cannot accidentally use them.

#include <vector>

namespace quant {

// Average True Range, period N, computed via exponential moving average of
// the true-range series (Wilder smoothing). Matches pandas .ewm(span=period,
// adjust=False).mean() applied to TR.
//
// TR_i = max(high_i - low_i, |high_i - prev_close|, |low_i - prev_close|)
// ATR_i = EMA(TR_i, span=period)
std::vector<double> compute_atr(
    const std::vector<double>& high,
    const std::vector<double>& low,
    const std::vector<double>& close,
    int period
);

// Exponential moving average. Matches pandas .ewm(span=N, adjust=False).mean()
// (NOT the variant with adjust=True which is also common).
//
// Recurrence: alpha = 2 / (span + 1)
//             y_0 = x_0
//             y_i = alpha * x_i + (1 - alpha) * y_{i-1}
std::vector<double> compute_ema(
    const std::vector<double>& series,
    int span
);

// Simple log returns: log(x_i / x_{i-N}). First N elements are NaN.
std::vector<double> compute_log_returns(
    const std::vector<double>& series,
    int period
);

// Rolling z-score over a lookback window: (x_i - mean(window)) / std(window).
// Uses ddof=1 (sample standard deviation) to match pandas .rolling().std().
std::vector<double> compute_rolling_zscore(
    const std::vector<double>& series,
    int lookback
);

// Rolling OLS regression y = beta * x + alpha over a sliding window.
// At each bar i, fits the regression to the last `lookback` aligned values
// of x and y (positions [i-lookback+1, i]). Outputs two parallel series:
//   beta[i]  = cov(x,y) / var(x)  over the window ending at i
//   alpha[i] = mean(y) - beta[i] * mean(x)
// Warmup positions [0, lookback-2] are NaN. Inputs of unequal length throw.
//
// Used by the gold-silver pairs strategy to fit the cointegrating
// relationship log(P_a) = beta * log(P_b) + alpha on rolling 504-bar
// windows.
struct RollingOlsResult {
    std::vector<double> beta;
    std::vector<double> alpha;
};

RollingOlsResult compute_rolling_ols(
    const std::vector<double>& x,
    const std::vector<double>& y,
    int lookback
);

}  // namespace quant
