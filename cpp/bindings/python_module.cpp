// pybind11 wrapper for the C++ core. Exposes a `quantlib` Python module
// that pytest can import. NO logic here -- this is a thin translator
// between Python lists/numpy arrays and std::vector<double>.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "quant/features.hpp"
#include "quant/markov.hpp"
#include "quant/version.hpp"

namespace py = pybind11;

PYBIND11_MODULE(quantlib, m) {
    m.doc() = "Python bindings for libquant (C++ hot-path math).";

    m.def("version", &quant::version_string,
          "Library version string.");

    // -- Features --
    m.def("compute_atr",
          &quant::compute_atr,
          py::arg("high"), py::arg("low"), py::arg("close"), py::arg("period"),
          "Average True Range, period N (Wilder/EMA smoothing).");

    m.def("compute_ema",
          &quant::compute_ema,
          py::arg("series"), py::arg("span"),
          "Exponential moving average matching pandas .ewm(span, adjust=False).mean().");

    m.def("compute_log_returns",
          &quant::compute_log_returns,
          py::arg("series"), py::arg("period"),
          "Log returns over period N: log(x_i / x_{i-N}).");

    m.def("compute_rolling_zscore",
          &quant::compute_rolling_zscore,
          py::arg("series"), py::arg("lookback"),
          "Rolling z-score with sample std (ddof=1) over a lookback window.");

    m.def("compute_rolling_ols",
          [](const std::vector<double>& x, const std::vector<double>& y,
             int lookback) {
              auto r = quant::compute_rolling_ols(x, y, lookback);
              return std::make_pair(r.beta, r.alpha);
          },
          py::arg("x"), py::arg("y"), py::arg("lookback"),
          "Rolling OLS y = beta*x + alpha over a sliding window. Returns "
          "(beta_series, alpha_series), each warmup position NaN.");

    // -- Markov --
    m.def("markov_forward_step",
          &quant::markov_forward_step,
          py::arg("state"), py::arg("transition"),
          "One Markov forward step: out[j] = sum_i state[i] * T[i*n+j].");

    m.def("markov_forward_n_steps",
          &quant::markov_forward_n_steps,
          py::arg("state"), py::arg("transition"), py::arg("n_steps"),
          "Apply n_steps successive Markov forward steps.");

    m.def("transition_matrix_is_valid",
          &quant::transition_matrix_is_valid,
          py::arg("transition"), py::arg("n_states"), py::arg("tol") = 1e-9,
          "Check that transition rows sum to 1 (within tol) and are non-negative.");
}
