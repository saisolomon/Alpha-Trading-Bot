#pragma once

// Markov chain forward step. Both the observable Markov regime model and the
// HMM use the same forward propagation: probability vector × transition
// matrix.
//
// The transition matrix is stored row-major: row i = transitions out of
// state i, sums to 1. Vector size = matrix.size() == n_states.

#include <cstddef>
#include <vector>

namespace quant {

// Multiply state probability vector by transition matrix once.
// out[j] = sum_i (state[i] * T[i][j])
//
// Inputs:
//   state[n_states]                 -- current probability over states
//   transition[n_states * n_states] -- row-major, row i = T[i][:]
//
// Returns out[n_states].
std::vector<double> markov_forward_step(
    const std::vector<double>& state,
    const std::vector<double>& transition
);

// Apply n_steps successive forward steps.
std::vector<double> markov_forward_n_steps(
    const std::vector<double>& state,
    const std::vector<double>& transition,
    int n_steps
);

// Validate that a transition matrix has rows summing to 1 (within tol) and
// no negative entries. Returns true if valid, false otherwise.
bool transition_matrix_is_valid(
    const std::vector<double>& transition,
    int n_states,
    double tol = 1e-9
);

}  // namespace quant
