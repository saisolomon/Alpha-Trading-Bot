// Minimal C++ smoke tests. Real parity validation happens in
// ../tests/test_cpp_parity.py against actual cached market data.

#include "quant/features.hpp"
#include "quant/markov.hpp"
#include "quant/version.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>

namespace {

constexpr double kTol = 1e-9;

void test_version() {
    const char* v = quant::version_string();
    assert(v != nullptr);
    assert(v[0] != '\0');
    std::printf("  version: %s\n", v);
}

void test_ema_basic() {
    // pandas .ewm(span=3, adjust=False).mean() of [1,2,3,4,5]:
    //   alpha=2/4=0.5
    //   y0 = 1
    //   y1 = 0.5*2 + 0.5*1 = 1.5
    //   y2 = 0.5*3 + 0.5*1.5 = 2.25
    //   y3 = 0.5*4 + 0.5*2.25 = 3.125
    //   y4 = 0.5*5 + 0.5*3.125 = 4.0625
    std::vector<double> in{1, 2, 3, 4, 5};
    std::vector<double> expected{1.0, 1.5, 2.25, 3.125, 4.0625};
    auto out = quant::compute_ema(in, 3);
    for (std::size_t i = 0; i < expected.size(); ++i) {
        assert(std::abs(out[i] - expected[i]) < kTol);
    }
    std::printf("  ema(span=3): OK\n");
}

void test_atr_smoke() {
    // Just check it runs without crashing and produces non-NaN past warmup.
    std::vector<double> high{10, 11, 12, 11, 12, 13, 14, 13, 14, 15};
    std::vector<double> low {9, 10, 11, 10, 11, 12, 13, 12, 13, 14};
    std::vector<double> close{9.5, 10.5, 11.5, 10.5, 11.5, 12.5, 13.5, 12.5, 13.5, 14.5};
    auto out = quant::compute_atr(high, low, close, 5);
    assert(out.size() == high.size());
    assert(!std::isnan(out.back()));
    assert(out.back() > 0.0);
    std::printf("  atr(period=5): last=%.4f\n", out.back());
}

void test_markov_forward() {
    // 2-state, identity-ish transition: state vector should stay close to identity.
    std::vector<double> state{1.0, 0.0};
    std::vector<double> trans{0.9, 0.1, 0.2, 0.8};  // row-major
    auto out = quant::markov_forward_step(state, trans);
    assert(std::abs(out[0] - 0.9) < kTol);
    assert(std::abs(out[1] - 0.1) < kTol);
    std::printf("  markov_forward: [0.9, 0.1] OK\n");
}

void test_transition_validity() {
    std::vector<double> good{0.7, 0.3, 0.4, 0.6};   // valid 2x2
    std::vector<double> bad {0.5, 0.6, 0.4, 0.6};   // row 0 sums to 1.1
    assert(quant::transition_matrix_is_valid(good, 2));
    assert(!quant::transition_matrix_is_valid(bad, 2));
    std::printf("  transition_matrix_is_valid: OK\n");
}

void test_zscore_basic() {
    // Rolling z-score with lookback=4 on [1,2,3,4,5,6,7]:
    //   At i=3 (value=4): window=[1,2,3,4], mean=2.5, std=sqrt(((1-2.5)^2 + ... )/3) = sqrt(5/3)
    //                     z = (4-2.5)/sqrt(5/3) = 1.5/1.291 = 1.162
    std::vector<double> in{1, 2, 3, 4, 5, 6, 7};
    auto out = quant::compute_rolling_zscore(in, 4);
    assert(out.size() == in.size());
    // First three positions are NaN (not enough lookback)
    for (int i = 0; i < 3; ++i) assert(std::isnan(out[i]));
    // Position 3 should be ~1.162
    const double expected = 1.5 / std::sqrt(5.0 / 3.0);
    assert(std::abs(out[3] - expected) < 1e-6);
    std::printf("  rolling_zscore(lookback=4): out[3]=%.4f (expected %.4f)\n",
                out[3], expected);
}

}  // namespace

int main() {
    std::printf("Running libquant C++ smoke tests...\n");
    test_version();
    test_ema_basic();
    test_atr_smoke();
    test_markov_forward();
    test_transition_validity();
    test_zscore_basic();
    std::printf("All passed.\n");
    return 0;
}
