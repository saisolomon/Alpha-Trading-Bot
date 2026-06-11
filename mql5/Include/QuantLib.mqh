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

   // Rolling OLS y = beta*x + alpha over a sliding window. Outputs
   // out_beta + out_alpha each of length n; warmup positions are NaN.
   int     quant_rolling_ols(const double &x[], const double &y[],
                              int n, int lookback,
                              double &out_beta[], double &out_alpha[]);

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

//+------------------------------------------------------------------+
//| SafeFillingMode: query the broker's supported filling modes at   |
//| runtime instead of hardcoding one.                                |
//|                                                                  |
//| Origin: trial #1 near-miss (2026-05-27). All EAs hardcoded       |
//| ORDER_FILLING_IOC; OANDA only supports FOK -> every entry was    |
//| rejected with retcode 10030 for 24h. The sed fix hardcoded FOK,  |
//| which works on OANDA but would break on an IOC-only or           |
//| RETURN-only broker. This helper makes the filling mode broker-   |
//| derived so the class of bug is dead permanently.                 |
//|                                                                  |
//| Preference order: FOK > IOC > RETURN (RETURN is always legal as  |
//| the fallback for instruments quoted in exchange-execution mode). |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING SafeFillingMode(const string symbol) {
   long flags = 0;
   if(!SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE, flags))
      return ORDER_FILLING_RETURN;
   if((flags & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((flags & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}
