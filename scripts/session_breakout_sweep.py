"""
Multi-market, multi-session breakout signal sweep.

For each (symbol, session, range_minutes) configuration, run the same
bucket test as scripts/orb_bucket_test.py but generalised: the "session"
is any defined trading-session open (Tokyo 00:00 UTC, London 08:00 UTC,
NY 13:30 UTC, etc.). The "range" is the first N minutes after that
session start. Breakouts are detected during the rest of the session.

The goal: find which (symbol, session) pairs have POSITIVE breakout
expectancy after costs. The literature says JPY crosses at London open
and energy markets at WTI inventory release are the canonical winners.
This sweep tests that empirically on our 3y M30 cache.

Output: a sorted leaderboard. Symbols with t-stat > 1.5 and mean
magnitude > 0.1% are real candidates for a breakout strategy.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
M30 = 30

# Configurations: (symbol, session_label, session_start_utc, session_end_utc, range_minutes)
# Sessions chosen per market's actual liquid hours.
CONFIGS = [
    # ---- JPY crosses: London Breakout (most-documented setup) ----
    ("GBPJPY", "London",  time(8, 0),  time(16, 0), 60),
    ("GBPJPY", "Tokyo",   time(0, 0),  time(8, 0),  60),
    ("GBPJPY", "NY",      time(13, 0), time(21, 0), 60),
    ("EURJPY", "London",  time(8, 0),  time(16, 0), 60),
    ("EURJPY", "Tokyo",   time(0, 0),  time(8, 0),  60),
    ("AUDJPY", "London",  time(8, 0),  time(16, 0), 60),
    ("AUDJPY", "Tokyo",   time(0, 0),  time(8, 0),  60),
    ("NZDJPY", "London",  time(8, 0),  time(16, 0), 60),
    ("CADJPY", "London",  time(8, 0),  time(16, 0), 60),
    ("CHFJPY", "London",  time(8, 0),  time(16, 0), 60),
    # ---- Energy ----
    ("WTI",    "NY",      time(13, 30), time(20, 0), 60),
    ("WTI",    "London",  time(8, 0),   time(16, 0), 60),
    ("BRT",    "London",  time(8, 0),   time(16, 0), 60),
    ("NG",     "NY",      time(13, 30), time(20, 0), 60),
    # ---- Asian / European indices ----
    ("JPN225", "Tokyo",   time(0, 0),  time(6, 0),  60),
    ("HK50",   "Asia",    time(1, 30), time(8, 0),  60),
    ("AUS200", "Asia",    time(0, 0),  time(6, 0),  60),
    ("FRA40",  "European",time(7, 0),  time(15, 30),60),
    ("EUSTX50","European",time(7, 0),  time(15, 30),60),
]


@dataclass
class Result:
    symbol: str
    session: str
    n_long: int
    n_short: int
    mean_long_pct: float
    mean_short_pct: float
    mean_signed_pct: float
    t_stat: float


def load_m30(symbol: str, years: int = 3) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    return cache.read(symbol, M30, start, end)


def test_config(symbol: str, session_label: str, session_open: time,
                session_close: time, range_min: int,
                min_range_pct: float = 0.0015) -> Result | None:
    df = load_m30(symbol)
    if df is None or df.empty:
        return None
    # Mask bars to within the session window (handle cross-midnight cases)
    if session_open < session_close:
        sess = df[(df.index.time >= session_open) & (df.index.time < session_close)].copy()
    else:
        # cross-midnight
        sess = df[(df.index.time >= session_open) | (df.index.time < session_close)].copy()
    # group by session "date" -- if session crosses midnight, we group by
    # the date OF THE session_open in UTC. Easiest hack: shift the index
    # by -session_open hours before extracting the date.
    sess["session_date"] = (sess.index - pd.Timedelta(hours=session_open.hour,
                                                       minutes=session_open.minute)).date

    range_end = (datetime.combine(datetime.today(), session_open)
                  + timedelta(minutes=range_min)).time()

    longs, shorts = [], []
    for sdate, day_df in sess.groupby("session_date"):
        # Range = bars within [session_open, session_open + range_min)
        if session_open < session_close:
            rw_mask = (day_df.index.time >= session_open) & (day_df.index.time < range_end)
            pr_mask = (day_df.index.time >= range_end) & (day_df.index.time < session_close)
        else:
            # cross-midnight: assume range_min < (24h - session_open) so range_end same-day
            rw_mask = (day_df.index.time >= session_open) & (day_df.index.time < range_end)
            pr_mask = ((day_df.index.time >= range_end) & (day_df.index.time < time(23, 59))) | \
                      (day_df.index.time < session_close)
        rw = day_df[rw_mask]
        pr = day_df[pr_mask]
        if len(rw) < 2 or len(pr) < 1:
            continue
        rh = float(rw["high"].max())
        rl = float(rw["low"].min())
        ref = float(pr.iloc[0]["open"])
        if ref <= 0 or (rh - rl) / ref < min_range_pct:
            continue
        breakout_dir = 0
        entry_price = 0.0
        for ts, bar in pr.iterrows():
            if bar["close"] > rh:
                breakout_dir = +1
                entry_price = float(bar["close"])
                break
            elif bar["close"] < rl:
                breakout_dir = -1
                entry_price = float(bar["close"])
                break
        if breakout_dir == 0:
            continue
        end_px = float(pr.iloc[-1]["close"])
        fwd = (end_px - entry_price) / entry_price
        if breakout_dir == +1:
            longs.append(fwd)
        else:
            shorts.append(fwd)

    n_long, n_short = len(longs), len(shorts)
    long_mean = float(np.mean(longs)) if n_long else 0.0
    short_mean = float(np.mean(shorts)) if n_short else 0.0
    all_signed = np.concatenate([longs, [-x for x in shorts]]) if n_long + n_short else np.array([])
    if len(all_signed) > 1:
        mean_signed = float(all_signed.mean())
        se = float(all_signed.std(ddof=1) / np.sqrt(len(all_signed)))
        t = mean_signed / se if se > 0 else 0.0
    else:
        mean_signed, t = 0.0, 0.0
    return Result(symbol, session_label, n_long, n_short, long_mean,
                  short_mean, mean_signed, t)


def main() -> None:
    results: list[Result] = []
    for sym, sess_lbl, so, sc, rm in CONFIGS:
        r = test_config(sym, sess_lbl, so, sc, rm)
        if r is None:
            continue
        results.append(r)

    # Sort by t-stat descending (best breakout edges first)
    results.sort(key=lambda r: -r.t_stat)

    print("Session-Breakout Sweep Results (sorted by t-stat)")
    print("=" * 95)
    print(f"  {'symbol':<8} {'session':<10} {'n_long':>7} {'n_short':>7} "
          f"{'long%':>7} {'short%':>7} {'signed%':>9} {'t-stat':>7}  verdict")
    print("  " + "-" * 93)
    for r in results:
        verdict = (
            "STRONG"   if r.t_stat >= 2.5 and r.mean_signed_pct >= 0.001 else
            "WEAK"     if r.t_stat >= 1.5 and r.mean_signed_pct >= 0.0005 else
            "MARGINAL" if r.t_stat >= 1.0 else
            "fail"
        )
        print(f"  {r.symbol:<8} {r.session:<10} {r.n_long:>7} {r.n_short:>7} "
              f"{100*r.mean_long_pct:>+6.3f}% {100*r.mean_short_pct:>+6.3f}% "
              f"{100*r.mean_signed_pct:>+8.3f}% {r.t_stat:>+7.2f}  {verdict}")

    print()
    print("=" * 95)
    print("SUMMARY")
    print("=" * 95)
    strong = [r for r in results if r.t_stat >= 2.5 and r.mean_signed_pct >= 0.001]
    weak = [r for r in results if 1.5 <= r.t_stat < 2.5 and r.mean_signed_pct >= 0.0005]
    print(f"  Strong candidates (t>=2.5, signed%>=0.10%): {len(strong)}")
    for r in strong:
        print(f"    {r.symbol} @ {r.session}: t={r.t_stat:+.2f}, mean={100*r.mean_signed_pct:+.3f}%")
    print(f"  Weak candidates (t>=1.5):                   {len(weak)}")
    for r in weak:
        print(f"    {r.symbol} @ {r.session}: t={r.t_stat:+.2f}, mean={100*r.mean_signed_pct:+.3f}%")
    if not strong and not weak:
        print("  ZERO viable breakout candidates -- abandon breakout family entirely.")


if __name__ == "__main__":
    main()
