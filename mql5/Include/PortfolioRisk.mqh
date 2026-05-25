//+------------------------------------------------------------------+
//| PortfolioRisk.mqh                                                |
//| Aggregate-open-risk governor across ALL EAs on the account.     |
//|                                                                  |
//| The CLAUDE.md hard cap is 2% aggregate open risk. With multiple |
//| M15 EAs running at 0.25% per trade each, the cap can be          |
//| accidentally breached when several EAs fire simultaneously       |
//| (e.g. LondonMomo + RSIFade + ORB all entering long-dollar on the |
//| same news). This module gives every EA a one-function gate:      |
//|                                                                  |
//|   if (WouldExceedRiskCap(equity, proposed_worst_case_loss)) return; |
//|                                                                  |
//| Mechanism: iterate every open position on the account, sum the   |
//| dollar worst-case loss (price-to-SL distance * lots * tick value)|
//| then check if adding the proposed trade pushes total > 2%.       |
//|                                                                  |
//| Caveats:                                                          |
//|   - Positions without a SL set are skipped (cannot compute risk) |
//|     and logged as a warning -- those positions are unbounded     |
//|     risk and should not exist in our system                      |
//|   - Manually-placed trades (no comment) are also counted, since  |
//|     they consume the same capital                                |
//|   - Computation is per-tick-cheap (one PositionsTotal + N        |
//|     PositionSelectByTicket + 4-5 SymbolInfoDouble per position). |
//|     For 10 open positions: ~50-100us. Negligible.                |
//+------------------------------------------------------------------+
#ifndef __PORTFOLIO_RISK_MQH__
#define __PORTFOLIO_RISK_MQH__

//-- Default cap matches CLAUDE.md sec 3 internal limit
#define PORTFOLIO_RISK_CAP_FRACTION  0.02   // 2% of equity

//+------------------------------------------------------------------+
//| Compute the sum of worst-case losses (in account currency)       |
//| across all open positions on this account. Positions with no SL  |
//| set are skipped (and we log a warning per unique symbol).        |
//+------------------------------------------------------------------+
double ComputeAggregateOpenRiskUSD() {
   double total = 0.0;
   int n = PositionsTotal();
   for(int i = 0; i < n; i++) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      double volume = PositionGetDouble(POSITION_VOLUME);
      double entry  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl     = PositionGetDouble(POSITION_SL);
      string sym    = PositionGetString(POSITION_SYMBOL);
      if(sl <= 0) {
         // Position has no stop-loss -- can't quantify risk.
         // We do NOT include in total (otherwise we'd have to assume
         // worst-case = full notional which is too punitive for the
         // common case of small unstopped positions in dry-run).
         // But we do log so future-me can hunt down the source EA.
         static datetime last_warn = 0;
         if(TimeCurrent() - last_warn > 300) {  // 5 min throttle
            PrintFormat("[PortfolioRisk] WARN: open position %s ticket=%I64u has no SL set",
                        sym, ticket);
            last_warn = TimeCurrent();
         }
         continue;
      }
      double risk_distance = MathAbs(entry - sl);
      double tick_size = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
      double tick_val  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      if(tick_size <= 0 || tick_val <= 0) continue;
      double risk_dollars = (risk_distance / tick_size) * tick_val * volume;
      total += risk_dollars;
   }
   return total;
}

//+------------------------------------------------------------------+
//| Returns current aggregate open risk as a fraction of equity.    |
//+------------------------------------------------------------------+
double ComputeAggregateRiskFraction(const double account_equity) {
   if(account_equity <= 0) return 0.0;
   return ComputeAggregateOpenRiskUSD() / account_equity;
}

//+------------------------------------------------------------------+
//| Pre-trade check: would adding the proposed loss put us over the |
//| portfolio-level cap?                                              |
//|                                                                  |
//| Returns true if the trade should be SKIPPED.                     |
//| Returns false if it's safe to proceed.                           |
//|                                                                  |
//| Logs once-per-5-min when blocking, so the cause is visible       |
//| without filling the Experts tab.                                 |
//+------------------------------------------------------------------+
bool WouldExceedRiskCap(const double account_equity,
                        const double proposed_worst_case_loss_usd,
                        const double cap_fraction = PORTFOLIO_RISK_CAP_FRACTION) {
   if(account_equity <= 0) return true;  // refuse on bad equity
   double current = ComputeAggregateOpenRiskUSD();
   double new_total = current + proposed_worst_case_loss_usd;
   double new_fraction = new_total / account_equity;
   if(new_fraction > cap_fraction) {
      static datetime last_log = 0;
      if(TimeCurrent() - last_log > 300) {
         PrintFormat("[PortfolioRisk] BLOCK entry: current=%.3f%% + proposed=%.3f%% = %.3f%% > cap %.2f%%",
                     100*current/account_equity,
                     100*proposed_worst_case_loss_usd/account_equity,
                     100*new_fraction, 100*cap_fraction);
         last_log = TimeCurrent();
      }
      return true;
   }
   return false;
}

#endif  // __PORTFOLIO_RISK_MQH__
