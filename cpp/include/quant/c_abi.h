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

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // QUANT_C_ABI_H
