//+------------------------------------------------------------------+
//| NewsBlackout.mqh                                                 |
//| High-impact news-window detection for all FTMO EAs.              |
//|                                                                  |
//| FTMO's standard funded-account rules forbid opening or closing  |
//| positions within 2 minutes of high-impact news (NFP, FOMC, CPI). |
//| Hitting that rule fails the account. This module gives every EA |
//| a one-function check: IsNewsBlackout(now) -> true/false.         |
//|                                                                  |
//| Also valuable on Challenge accounts (where the rule doesn't apply|
//| strictly) because the price-action around these releases is      |
//| extreme tail risk -- a single ORB whipsaw on NFP can blow the    |
//| daily-loss line.                                                  |
//|                                                                  |
//| Calendar source: hardcoded for 2026 from public BLS / Federal   |
//| Reserve / BLS-CPI / ECB / BoE schedules. Times are in UTC.       |
//| Buffer default: 5 min before / 5 min after = 10 min total window.|
//|                                                                  |
//| TODO: replace hardcoded array with configs/news_calendar.yaml    |
//| loader once we have a calendar-update routine. For now, append   |
//| new dates here at start of each year.                            |
//+------------------------------------------------------------------+
#ifndef __NEWS_BLACKOUT_MQH__
#define __NEWS_BLACKOUT_MQH__

//-- Default buffers (minutes before / after each event)
#define NEWS_BUFFER_BEFORE_MIN  5
#define NEWS_BUFFER_AFTER_MIN   5

//-- Hardcoded high-impact 2026 news calendar (UTC datetimes)
//-- NFP, FOMC, US CPI, ECB rate decision, BoE rate decision
//--
//-- DST-CORRECTED 2026-06-11 (silent-EA replay finding #2): releases are
//-- pinned to LOCAL clocks (08:30 ET, 14:00 ET, 14:45 CET presser, 12:00 UK),
//-- so their UTC time SHIFTS with DST. The original table used winter
//-- offsets year-round (+1h wrong all summer).
//--   US DST 2026:    Mar 8  - Nov 1   (ET = UTC-4, else UTC-5)
//--   EU/UK DST 2026: Mar 29 - Oct 25  (CET->CEST, GMT->BST)
const datetime kNewsCalendar2026[] = {
   // ---- US Non-Farm Payrolls (first Friday, 08:30 ET) ----
   D'2026.01.02 13:30',   // EST
   D'2026.02.06 13:30',   // EST
   D'2026.03.06 13:30',   // EST (US DST starts Mar 8)
   D'2026.04.03 12:30',   // EDT
   D'2026.05.01 12:30',   // EDT
   D'2026.06.05 12:30',   // EDT
   D'2026.07.03 12:30',   // EDT
   D'2026.08.07 12:30',   // EDT
   D'2026.09.04 12:30',   // EDT
   D'2026.10.02 12:30',   // EDT
   D'2026.11.06 13:30',   // EST (US DST ended Nov 1)
   D'2026.12.04 13:30',   // EST
   // ---- FOMC rate decisions (14:00 ET statement) ----
   D'2026.01.28 19:00',   // EST
   D'2026.03.18 18:00',   // EDT  + SEP press conf
   D'2026.04.29 18:00',   // EDT
   D'2026.06.17 18:00',   // EDT  + SEP
   D'2026.07.29 18:00',   // EDT
   D'2026.09.16 18:00',   // EDT  + SEP
   D'2026.11.04 19:00',   // EST
   D'2026.12.16 19:00',   // EST  + SEP
   // ---- US CPI release (mid-month, 08:30 ET) ----
   D'2026.01.14 13:30',   // EST
   D'2026.02.11 13:30',   // EST
   D'2026.03.11 12:30',   // EDT (after Mar 8)
   D'2026.04.15 12:30',   // EDT
   D'2026.05.13 12:30',   // EDT
   D'2026.06.10 12:30',   // EDT
   D'2026.07.15 12:30',   // EDT
   D'2026.08.12 12:30',   // EDT
   D'2026.09.10 12:30',   // EDT
   D'2026.10.15 12:30',   // EDT
   D'2026.11.13 13:30',   // EST
   D'2026.12.10 13:30',   // EST
   // ---- ECB rate decisions (Thu; 14:45 CET/CEST press conference) ----
   D'2026.01.29 13:45',   // CET
   D'2026.03.12 13:45',   // CET (EU DST starts Mar 29)
   D'2026.04.16 12:45',   // CEST
   D'2026.06.04 12:45',   // CEST
   D'2026.07.23 12:45',   // CEST
   D'2026.09.10 12:45',   // CEST
   D'2026.10.29 13:45',   // CET (EU DST ended Oct 25)
   D'2026.12.17 13:45',   // CET
   // ---- BoE MPC rate decisions (Thu, 12:00 UK) ----
   D'2026.02.05 12:00',   // GMT
   D'2026.03.19 12:00',   // GMT (UK DST starts Mar 29)
   D'2026.05.07 11:00',   // BST
   D'2026.06.18 11:00',   // BST
   D'2026.08.06 11:00',   // BST
   D'2026.09.17 11:00',   // BST
   D'2026.11.05 12:00',   // GMT
   D'2026.12.17 12:00',   // GMT
};

//+------------------------------------------------------------------+
//| Returns true if the given UTC time is within +/- buffer of any   |
//| scheduled high-impact news event.                                |
//|                                                                  |
//| CLOCK CONTRACT (root cause of the trial-#1 news misalignment):   |
//| the calendar is UTC, so callers MUST pass TimeGMT().             |
//| NEVER pass TimeCurrent() -- that is BROKER time (UTC+3 on OANDA),|
//| which shifted every window ~3h early for the whole trial and     |
//| made XAUUSD_H1_NewsReaction evaluate pre-release bars (zero      |
//| entries in 14 days despite ECB 6/04 + NFP 6/05 + CPI 6/10 all    |
//| matching its lookback).                                           |
//|                                                                  |
//| Use in entry path:                                                |
//|   if (IsNewsBlackout(TimeGMT())) return;  // skip entry          |
//+------------------------------------------------------------------+
bool IsNewsBlackout(const datetime now,
                    const int buffer_before_min = NEWS_BUFFER_BEFORE_MIN,
                    const int buffer_after_min  = NEWS_BUFFER_AFTER_MIN) {
   const long before_sec = (long)buffer_before_min * 60;
   const long after_sec  = (long)buffer_after_min  * 60;
   const int n = ArraySize(kNewsCalendar2026);
   for(int i = 0; i < n; i++) {
      long delta = (long)now - (long)kNewsCalendar2026[i];
      // Inside window: now is in [event - before, event + after]
      if(delta >= -before_sec && delta <= after_sec) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Returns minutes until the next news event (or -1 if none in      |
//| next 24h). Useful for pre-emptive flatten logic.                 |
//+------------------------------------------------------------------+
int MinutesToNextNews(const datetime now) {
   const int n = ArraySize(kNewsCalendar2026);
   long min_delta = 24 * 60 * 60;  // 24h horizon
   bool found = false;
   for(int i = 0; i < n; i++) {
      long delta = (long)kNewsCalendar2026[i] - (long)now;
      if(delta > 0 && delta < min_delta) {
         min_delta = delta;
         found = true;
      }
   }
   if(!found) return -1;
   return (int)(min_delta / 60);
}

//+------------------------------------------------------------------+
//| Detect a news event that fired in the LAST `look_back_min`       |
//| minutes. Used by news-reaction strategies that want to enter on  |
//| the first bar AFTER a news release (continuation trade).         |
//|                                                                  |
//| Returns true and populates out_event_time if any high-impact     |
//| event released within the look-back window. Returns false        |
//| otherwise.                                                        |
//+------------------------------------------------------------------+
bool RecentNewsEvent(const datetime now, const int look_back_min,
                     datetime &out_event_time) {
   out_event_time = 0;
   const long look_sec = (long)look_back_min * 60;
   const int n = ArraySize(kNewsCalendar2026);
   long best_delta = look_sec + 1;  // sentinel: greater than any valid
   for(int i = 0; i < n; i++) {
      long delta = (long)now - (long)kNewsCalendar2026[i];
      // delta > 0 -> event is in the past
      // delta <= look_sec -> within our look-back window
      if(delta > 0 && delta <= look_sec && delta < best_delta) {
         best_delta = delta;
         out_event_time = kNewsCalendar2026[i];
      }
   }
   return out_event_time != 0;
}

#endif  // __NEWS_BLACKOUT_MQH__
