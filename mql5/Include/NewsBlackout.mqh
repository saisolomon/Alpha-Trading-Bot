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
const datetime kNewsCalendar2026[] = {
   // ---- US Non-Farm Payrolls (first Friday of each month, 13:30 UTC) ----
   D'2026.01.02 13:30',
   D'2026.02.06 13:30',
   D'2026.03.06 13:30',
   D'2026.04.03 13:30',
   D'2026.05.01 13:30',
   D'2026.06.05 13:30',
   D'2026.07.03 13:30',
   D'2026.08.07 13:30',
   D'2026.09.04 13:30',
   D'2026.10.02 13:30',
   D'2026.11.06 13:30',
   D'2026.12.04 13:30',
   // ---- FOMC rate decisions (~8/year, Wed 19:00 UTC) ----
   D'2026.01.28 19:00',
   D'2026.03.18 19:00',   // + SEP press conf
   D'2026.04.29 19:00',
   D'2026.06.17 19:00',   // + SEP
   D'2026.07.29 19:00',
   D'2026.09.16 19:00',   // + SEP
   D'2026.11.04 19:00',
   D'2026.12.16 19:00',   // + SEP
   // ---- US CPI release (mid-month, 13:30 UTC) ----
   D'2026.01.14 13:30',
   D'2026.02.11 13:30',
   D'2026.03.11 13:30',
   D'2026.04.15 13:30',
   D'2026.05.13 13:30',
   D'2026.06.10 13:30',
   D'2026.07.15 13:30',
   D'2026.08.12 13:30',
   D'2026.09.10 13:30',
   D'2026.10.15 13:30',
   D'2026.11.13 13:30',
   D'2026.12.10 13:30',
   // ---- ECB rate decisions (8/year, Thu 12:45 UTC announcement) ----
   D'2026.01.29 12:45',
   D'2026.03.12 12:45',
   D'2026.04.16 12:45',
   D'2026.06.04 12:45',
   D'2026.07.23 12:45',
   D'2026.09.10 12:45',
   D'2026.10.29 12:45',
   D'2026.12.17 12:45',
   // ---- BoE MPC rate decisions (8/year, Thu 12:00 UTC) ----
   D'2026.02.05 12:00',
   D'2026.03.19 12:00',
   D'2026.05.07 12:00',
   D'2026.06.18 12:00',
   D'2026.08.06 12:00',
   D'2026.09.17 12:00',
   D'2026.11.05 12:00',
   D'2026.12.17 12:00',
};

//+------------------------------------------------------------------+
//| Returns true if current UTC time is within +/- buffer of any     |
//| scheduled high-impact news event.                                |
//|                                                                  |
//| Use in entry path:                                                |
//|   if (IsNewsBlackout(TimeCurrent())) return;  // skip entry      |
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

#endif  // __NEWS_BLACKOUT_MQH__
