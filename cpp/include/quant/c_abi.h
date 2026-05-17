// C ABI for libquant.dll. This header is what MQL5 uses to import the DLL
// (translated to MQL5 import declarations in mql5/Include/QuantLib.mqh).
//
// All cross-language interop happens through this layer. Pointers + sizes,
// no std:: types, no exceptions cross the boundary. Errors return non-zero
// status codes; outputs are written via caller-allocated buffers.

#ifndef QUANT_C_ABI_H
#define QUANT_C_ABI_H

#ifdef _WIN32
  #ifdef LIBQUANT_EXPORTS
    #define QUANT_API __declspec(dllexport)
  #else
    #define QUANT_API __declspec(dllimport)
  #endif
  #define QUANT_CALL __stdcall
#else
  #define QUANT_API __attribute__((visibility("default")))
  #define QUANT_CALL
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Status codes returned by every C ABI function.
typedef enum {
    QUANT_OK = 0,
    QUANT_ERR_NULL_PTR = 1,
    QUANT_ERR_INVALID_ARG = 2,
    QUANT_ERR_BUFFER_TOO_SMALL = 3,
    QUANT_ERR_INTERNAL = 99
} QuantStatus;

// Returns the version string. Caller does not own the pointer.
QUANT_API const char* QUANT_CALL quant_version(void);

// ATR. Caller passes equal-length high/low/close arrays of length n,
// receives ATR series in out[0..n-1].
QUANT_API QuantStatus QUANT_CALL quant_atr(
    const double* high,
    const double* low,
    const double* close,
    int n,
    int period,
    double* out
);

// EMA. Caller passes series of length n, receives ema in out[0..n-1].
QUANT_API QuantStatus QUANT_CALL quant_ema(
    const double* series,
    int n,
    int span,
    double* out
);

// Rolling z-score. lookback bars warmup; warmup positions are set to NaN.
QUANT_API QuantStatus QUANT_CALL quant_rolling_zscore(
    const double* series,
    int n,
    int lookback,
    double* out
);

// Rolling OLS regression y = beta*x + alpha over a sliding window of length
// `lookback`. Outputs two parallel series; warmup positions (first lookback-1)
// are NaN.
QUANT_API QuantStatus QUANT_CALL quant_rolling_ols(
    const double* x,
    const double* y,
    int n,
    int lookback,
    double* out_beta,
    double* out_alpha
);

// Markov forward step. transition is row-major n_states x n_states.
// state and out are length n_states.
QUANT_API QuantStatus QUANT_CALL quant_markov_forward(
    const double* state,
    const double* transition,
    int n_states,
    double* out
);

// Apply n_steps successive forward steps.
QUANT_API QuantStatus QUANT_CALL quant_markov_forward_n(
    const double* state,
    const double* transition,
    int n_states,
    int n_steps,
    double* out
);

// ---------------------------------------------------------------------- //
// FTMO rule engine exports (mirrors ocaml/lib/c_stubs.ml; see              //
// cpp/src/ftmo_rules.cpp for the C++ port).                                //
// Handle-based: ftmo_new_account returns an opaque integer handle that     //
// must be released via ftmo_free_account when done.                        //
// Account-type codes (must match mql5/Include/FTMORisk.mqh):               //
//   0 = CHALLENGE_1STEP                                                    //
//   1 = CHALLENGE_2STEP_PHASE1                                             //
//   2 = CHALLENGE_2STEP_PHASE2                                             //
//   3 = FUNDED_STANDARD                                                    //
//   4 = FUNDED_SWING                                                       //
//   5 = FUNDED_REWARDS_1STEP                                               //
// Status-code returns from ftmo_apply_tick / ftmo_status:                  //
//   0 = ACTIVE, 1 = IMMINENT, 2 = INTERNAL_KILLED, 3 = FTMO_FAILED         //
// Decision-code returns from ftmo_check_pretrade:                          //
//   0 = ALLOW, 1 = DENY, 2 = IMMINENT (proceed at reduced size)            //
// ---------------------------------------------------------------------- //

QUANT_API long QUANT_CALL ftmo_new_account(int account_code, double initial_capital);
QUANT_API void QUANT_CALL ftmo_free_account(long handle);
QUANT_API int  QUANT_CALL ftmo_apply_tick(long handle, double unix_ts, double equity);
QUANT_API int  QUANT_CALL ftmo_check_pretrade(long handle, double equity, double worst_case_loss);
QUANT_API int  QUANT_CALL ftmo_daily_reset(long handle, double unix_ts, double balance);
QUANT_API int  QUANT_CALL ftmo_status(long handle);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // QUANT_C_ABI_H
