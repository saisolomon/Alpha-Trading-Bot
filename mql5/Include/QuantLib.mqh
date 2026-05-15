//+------------------------------------------------------------------+
//| QuantLib.mqh                                                     |
//| DLL imports for libquant.dll (built from ../cpp/)                |
//|                                                                  |
//| ALL feature math goes through these imports. Do NOT reimplement  |
//| ATR / EMA / z-score in MQL5 -- if you do, you reintroduce the    |
//| research-vs-live drift the architecture exists to prevent.       |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property link      "https://github.com/your-org/ftmo-bot"

// QuantStatus return codes mirror cpp/include/quant/c_abi.h
#define QUANT_OK                  0
#define QUANT_ERR_NULL_PTR        1
#define QUANT_ERR_INVALID_ARG     2
#define QUANT_ERR_BUFFER_TOO_SMALL 3
#define QUANT_ERR_INTERNAL        99

#import "libquant.dll"
   // Returns the version string. Owned by the DLL; do not free.
   string  quant_version(void);

   // ATR. high/low/close arrays must be length n; out must also be length n.
   int     quant_atr(const double &high[], const double &low[],
                     const double &close[], int n, int period,
                     double &out[]);

   // EMA over span N.
   int     quant_ema(const double &series[], int n, int span,
                     double &out[]);

   // Rolling z-score over a lookback window.
   int     quant_rolling_zscore(const double &series[], int n, int lookback,
                                 double &out[]);

   // Markov chain forward step. transition is row-major n_states x n_states.
   int     quant_markov_forward(const double &state[], const double &transition[],
                                 int n_states, double &out[]);

   // Apply n_steps successive forward steps.
   int     quant_markov_forward_n(const double &state[], const double &transition[],
                                   int n_states, int n_steps, double &out[]);
#import

//+------------------------------------------------------------------+
//| Convenience: log a quant_* return code with a label              |
//+------------------------------------------------------------------+
void QuantLogIfError(const int rc, const string label) {
   if(rc == QUANT_OK) return;
   string msg;
   switch(rc) {
      case QUANT_ERR_NULL_PTR:        msg = "NULL_PTR"; break;
      case QUANT_ERR_INVALID_ARG:     msg = "INVALID_ARG"; break;
      case QUANT_ERR_BUFFER_TOO_SMALL: msg = "BUFFER_TOO_SMALL"; break;
      case QUANT_ERR_INTERNAL:        msg = "INTERNAL"; break;
      default:                         msg = "UNKNOWN"; break;
   }
   PrintFormat("[QuantLib] %s failed: %s (rc=%d)", label, msg, rc);
}
