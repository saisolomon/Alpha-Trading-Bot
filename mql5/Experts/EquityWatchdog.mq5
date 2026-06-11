//+------------------------------------------------------------------+
//| EquityWatchdog.mq5                                               |
//| Sub-second FTMO equity kill-switch, independent of every EA.     |
//|                                                                  |
//| CLAUDE.md sec 3 mandates equity monitoring on a high-frequency   |
//| tick or sub-second poll. Per-EA checks run inside OnTick, which  |
//| goes SPARSE in quiet markets (no tick = no check). This EA runs  |
//| on a 1-second OnTimer, independent of any chart's tick stream,   |
//| and is the last line of defense in front of the FTMO lines:      |
//|                                                                  |
//|   internal daily kill: anchor_balance - InpDailyKillPct*initial  |
//|     (anchor = balance at 00:00 Europe/Prague, FTMO's day roll)   |
//|   internal max kill:   initial * (1 - InpMaxKillPct)             |
//|                                                                  |
//| On breach: flatten EVERYTHING, set terminal global variable      |
//|   FTMO_KILL_ACTIVE = 1, alert loudly, and keep re-flattening     |
//|   every second while the breach persists (so an EA that races a  |
//|   re-entry gets closed within 1s). EAs' own libftmorisk gates    |
//|   remain layer one; this is layer two and shares no code with    |
//|   them on purpose (independent failure domains).                  |
//|                                                                  |
//| Deployment: attach MANUALLY to any single chart (like the        |
//| orchestrator). NOT in bot_manifest.txt -- the orchestrator       |
//| derives chart symbols from EA name prefixes and this EA has no   |
//| symbol. InpInitialCapital MUST be set to the account's true      |
//| initial sim capital; init fails if left 0 (no silent defaults    |
//| after the initialCapital mutability lesson).                     |
//|                                                                  |
//| Prague midnight: computed from TimeGMT() + EU DST rule (last     |
//| Sunday of March/October, 01:00 UTC). Same trap family as the     |
//| news-clock bug -- everything here runs off TimeGMT, never        |
//| TimeCurrent.                                                      |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "1.00"
#property strict

#include <QuantLib.mqh>   // SafeFillingMode

input double InpInitialCapital  = 0.0;    // REQUIRED: true initial sim capital
input double InpDailyKillPct    = 0.03;   // internal daily kill (CLAUDE.md: 3% on 2-Step)
input double InpMaxKillPct      = 0.07;   // internal max kill   (CLAUDE.md: 7%)
input int    InpTimerSeconds    = 1;

datetime g_anchor_prague_date = 0;   // Prague calendar day of current anchor
double   g_anchor_balance     = 0.0; // balance at last Prague midnight
datetime g_last_alert         = 0;

//+------------------------------------------------------------------+
//| EU DST: last Sunday of March 01:00 UTC -> last Sunday of October |
//| 01:00 UTC. Returns Prague's UTC offset in seconds.               |
//+------------------------------------------------------------------+
datetime LastSundayUtc1am(const int year, const int month) {
   MqlDateTime dt;
   dt.year = year; dt.mon = month; dt.day = 31; dt.hour = 1; dt.min = 0; dt.sec = 0;
   // walk back from the 31st to the last day that exists, then to Sunday
   datetime t = StructToTime(dt);
   while(true) {
      MqlDateTime chk; TimeToStruct(t, chk);
      if(chk.mon == month && chk.day_of_week == 0) return t;
      t -= 86400;
   }
   return 0;
}

int PragueOffsetSec(const datetime utc_now) {
   MqlDateTime dt; TimeToStruct(utc_now, dt);
   datetime dst_start = LastSundayUtc1am(dt.year, 3);
   datetime dst_end   = LastSundayUtc1am(dt.year, 10);
   if(utc_now >= dst_start && utc_now < dst_end) return 2 * 3600;  // CEST
   return 1 * 3600;                                                 // CET
}

datetime PragueDateOf(const datetime utc_now) {
   datetime prague = utc_now + PragueOffsetSec(utc_now);
   return prague - (prague % 86400);   // midnight-truncate in Prague clock
}

void FlattenAll(const string reason) {
   int n = PositionsTotal();
   for(int i = n - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      long side  = PositionGetInteger(POSITION_TYPE);
      MqlTradeRequest req; MqlTradeResult res;
      ZeroMemory(req); ZeroMemory(res);
      req.action   = TRADE_ACTION_DEAL;
      req.symbol   = sym;
      req.volume   = vol;
      req.position = ticket;
      req.type     = (side == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price    = (req.type == ORDER_TYPE_BUY)
                     ? SymbolInfoDouble(sym, SYMBOL_ASK)
                     : SymbolInfoDouble(sym, SYMBOL_BID);
      req.deviation = 100;   // kill-switch: pay up, get out
      req.type_filling = SafeFillingMode(sym);
      req.comment = StringFormat("EquityWatchdog %s", reason);
      if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE) {
         PrintFormat("[EquityWatchdog] FLATTEN FAILED %s ticket=%I64u retcode=%d -- will retry next second",
                     sym, ticket, res.retcode);
      } else {
         PrintFormat("[EquityWatchdog] FLATTENED %s ticket=%I64u (%s)", sym, ticket, reason);
      }
   }
}

int OnInit() {
   if(InpInitialCapital <= 0) {
      Print("[EquityWatchdog] FATAL: InpInitialCapital must be set to the TRUE initial sim capital (no defaults).");
      return INIT_PARAMETERS_INCORRECT;
   }
   g_anchor_prague_date = PragueDateOf(TimeGMT());
   g_anchor_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   EventSetTimer(InpTimerSeconds);
   PrintFormat("[EquityWatchdog] armed  initial=%.2f  daily_kill=%.1f%%  max_kill=%.1f%%  poll=%ds  anchor_balance=%.2f",
               InpInitialCapital, InpDailyKillPct * 100, InpMaxKillPct * 100,
               InpTimerSeconds, g_anchor_balance);
   GlobalVariableSet("FTMO_KILL_ACTIVE", 0);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   EventKillTimer();
   PrintFormat("[EquityWatchdog] disarmed reason=%d", reason);
}

void OnTimer() {
   datetime utc = TimeGMT();
   datetime today = PragueDateOf(utc);
   if(today != g_anchor_prague_date) {
      g_anchor_prague_date = today;
      g_anchor_balance = AccountInfoDouble(ACCOUNT_BALANCE);
      PrintFormat("[EquityWatchdog] Prague day roll -- new daily anchor balance %.2f", g_anchor_balance);
   }

   double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
   double daily_line = g_anchor_balance - InpDailyKillPct * InpInitialCapital;
   double max_line   = InpInitialCapital * (1.0 - InpMaxKillPct);

   string breach = "";
   if(equity <= max_line)        breach = "MAX_KILL";
   else if(equity <= daily_line) breach = "DAILY_KILL";
   if(breach == "") return;

   GlobalVariableSet("FTMO_KILL_ACTIVE", 1);
   FlattenAll(breach);
   if(TimeGMT() - g_last_alert > 300) {
      Alert(StringFormat("EquityWatchdog %s: equity %.2f <= line (daily %.2f / max %.2f) -- FLATTENED",
                         breach, equity, daily_line, max_line));
      g_last_alert = TimeGMT();
   }
}
