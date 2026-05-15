#include "quant/markov.hpp"

#include <cmath>
#include <stdexcept>

namespace quant {

std::vector<double> markov_forward_step(
    const std::vector<double>& state,
    const std::vector<double>& transition
) {
    const std::size_t n = state.size();
    if (n == 0) return {};
    if (transition.size() != n * n) {
        throw std::invalid_argument("markov_forward_step: transition size != n*n");
    }
    std::vector<double> out(n, 0.0);
    for (std::size_t j = 0; j < n; ++j) {
        double acc = 0.0;
        for (std::size_t i = 0; i < n; ++i) {
            acc += state[i] * transition[i * n + j];
        }
        out[j] = acc;
    }
    return out;
}

std::vector<double> markov_forward_n_steps(
    const std::vector<double>& state,
    const std::vector<double>& transition,
    int n_steps
) {
    if (n_steps < 0) {
        throw std::invalid_argument("markov_forward_n_steps: n_steps must be >= 0");
    }
    std::vector<double> current = state;
    for (int i = 0; i < n_steps; ++i) {
        current = markov_forward_step(current, transition);
    }
    return current;
}

bool transition_matrix_is_valid(
    const std::vector<double>& transition,
    int n_states,
    double tol
) {
    if (n_states <= 0) return false;
    const std::size_t n = static_cast<std::size_t>(n_states);
    if (transition.size() != n * n) return false;
    for (std::size_t i = 0; i < n; ++i) {
        double row_sum = 0.0;
        for (std::size_t j = 0; j < n; ++j) {
            const double v = transition[i * n + j];
            if (v < 0.0 || std::isnan(v)) return false;
            row_sum += v;
        }
        if (std::abs(row_sum - 1.0) > tol) return false;
    }
    return true;
}

}  // namespace quant
