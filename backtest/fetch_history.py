"""Historical-data puller for the walk-forward harness (3 sources, UTC-normalized).

Prerequisite for backtest/walk_forward.py. Runs on the DEV box (off the live VPS).
User-ratified 2026-06-16; built 2026-06-20.

Sources, by ROLE:
  - OANDA-via-MT5  = PARITY SPINE. The same feed the EAs trade -> source of truth for
                     signal backtests. M15/H1/H4 bars via mt5.copy_rates_range().
                     Requires a running MT5 terminal logged into OANDA (data-only).
  - Dukascopy      = COST-MODEL CALIBRATION. Free historical TICKS (.bi5, LZMA) ->
                     reconstruct real spread/slippage; retail MT5 tick history too shallow.
  - HistData       = LOOKBACK EXTENSION + independent cross-check (free M1 bars).

CRITICAL — timezone normalization (the 2026-06-11 clock-bug lesson, applied to ingest):
  MT5/OANDA stamps = broker time (UTC+2/+3, DST-shifting); Dukascopy = UTC; HistData = US
  Eastern WITHOUT DST. EVERY series is normalized to true UTC here and written tz-naive-UTC.

Output: data/history/<source>/<SYMBOL>_<TF>.parquet  (columns: time[UTC], open, high, low,
        close, volume[, spread]).  Symbols are stored suffix-free (GBPUSD, not GBPUSD.sim).

CLI:
  python backtest/fetch_history.py dukascopy --symbol EURUSD --tf M15 --start 2026-06-15 --end 2026-06-18
  python backtest/fetch_history.py mt5       --symbol GBPUSD --tf M15 --start 2024-01-01 --end 2026-06-20
  python backtest/fetch_history.py selftest   # offline decode unit-check, no network/MT5
"""
from __future__ import annotations

import argparse
import datetime as dt
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "data" / "history"

# Roster + benched symbols. dukascopy instrument name + price decimals (point factor).
# decimals verified against the MT5 spine via the divergence report — if a scale is wrong
# it shows up as an order-of-magnitude delta there.
SYMBOLS = {
    "EURUSD": {"duka": "EURUSD", "decimals": 5},
    "GBPUSD": {"duka": "GBPUSD", "decimals": 5},
    "AUDJPY": {"duka": "AUDJPY", "decimals": 3},
    "XAUUSD": {"duka": "XAUUSD", "decimals": 3},
    "EURGBP": {"duka": "EURGBP", "decimals": 5},
}

TF_PANDAS = {"M15": "15min", "H1": "1h", "H4": "4h", "M1": "1min"}


# --------------------------------------------------------------------------- #
# Dukascopy (ticks .bi5 -> bars)
# --------------------------------------------------------------------------- #
DUKA_URL = ("https://datafeed.dukascopy.com/datafeed/{inst}/"
            "{y:04d}/{m0:02d}/{d:02d}/{h:02d}h_ticks.bi5")
_TICK = struct.Struct(">IIIff")   # ms-since-hour, ask_pts, bid_pts, ask_vol, bid_vol


def _duka_hour(inst: str, day: dt.date, hour: int, retries: int = 3) -> bytes:
    """Fetch one hourly .bi5. Returns raw compressed bytes (b'' if no data / 404)."""
    url = DUKA_URL.format(inst=inst, y=day.year, m0=day.month - 1, d=day.day, h=hour)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""          # no ticks this hour (weekend/holiday/closed)
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return b""


def decode_bi5(raw: bytes, day: dt.date, hour: int, point: float) -> list[tuple]:
    """Decode one hour's LZMA .bi5 into [(utc_datetime, bid, ask), ...]. Pure/offline-testable."""
    if not raw:
        return []
    try:
        data = lzma.decompress(raw)              # bi5 is LZMA-alone; FORMAT_AUTO handles it
    except lzma.LZMAError:
        data = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(raw)
    base = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.timezone.utc)
    ticks = []
    for off in range(0, len(data) - len(data) % _TICK.size, _TICK.size):
        ms, ask_pts, bid_pts, _av, _bv = _TICK.unpack_from(data, off)
        t = base + dt.timedelta(milliseconds=ms)
        ticks.append((t, bid_pts / point, ask_pts / point))
    return ticks


def fetch_dukascopy(symbol: str, tf: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    meta = SYMBOLS[symbol]
    inst, point = meta["duka"], 10 ** meta["decimals"]
    rule = TF_PANDAS[tf]
    rows, day, n_hours, n_empty = [], start, 0, 0
    while day < end:
        if day.weekday() < 5 or True:    # FX trades Sun-eve..Fri; pull all, empties are skipped
            for hour in range(24):
                raw = _duka_hour(inst, day, hour)
                n_hours += 1
                ticks = decode_bi5(raw, day, hour, point)
                if not ticks:
                    n_empty += 1
                    continue
                rows.extend(ticks)
        day += dt.timedelta(days=1)
    if not rows:
        print(f"[dukascopy] {symbol}: 0 ticks over {n_hours} hours "
              f"({n_empty} empty) — check range/instrument.", file=sys.stderr)
        return pd.DataFrame()
    ticks = pd.DataFrame(rows, columns=["time", "bid", "ask"]).set_index("time")
    mid = (ticks["bid"] + ticks["ask"]) / 2
    spr = (ticks["ask"] - ticks["bid"])
    bars = mid.resample(rule, label="left", closed="left").ohlc()
    bars["volume"] = mid.resample(rule, label="left", closed="left").count()
    bars["spread"] = spr.resample(rule, label="left", closed="left").mean()
    bars = bars.dropna(subset=["open"])
    print(f"[dukascopy] {symbol} {tf}: {len(ticks):,} ticks -> {len(bars):,} bars "
          f"({n_hours} hours pulled, {n_empty} empty)")
    return bars.reset_index()


# --------------------------------------------------------------------------- #
# OANDA-via-MT5 (the parity spine) — runs only with a live terminal
# --------------------------------------------------------------------------- #
MT5_MAX_BARS = 500_000   # copy_rates_from_pos cap; MT5 returns min(available, MaxBars)


def fetch_mt5(symbol: str, tf: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Pull the parity-spine bars from a running OANDA terminal.

    TIME SEMANTICS (decided 2026-06-20 after the live pull): bars are stored in RAW
    BROKER time (OANDA-Demo, ~UTC+2/+3), NOT converted to UTC. Reasons:
      1. The EAs run on broker TimeCurrent() (the session-clock finding), so a
         broker-time backtest is MORE faithful to live than a UTC-converted one —
         converting then re-applying broker assumptions would double-convert.
      2. Naive offset auto-detect via the last tick is unreliable (stale on weekends;
         it returned "UTC+-21" on the first run). Guessing an offset silently corrupts
         every timestamp — the exact clock-bug class this project keeps hitting.
    True-UTC alignment is done EMPIRICALLY later in the feed-divergence step, by
    cross-correlating against Dukascopy (native UTC) to recover the real per-period
    offset incl. DST shifts. Output column 'time' here = broker time; tagged in a
    sidecar .meta.json so downstream never assumes UTC.
    """
    import json as _json
    import MetaTrader5 as mt5
    tfmap = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
             "H4": mt5.TIMEFRAME_H4, "M1": mt5.TIMEFRAME_M1}
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()} — "
                           "is the terminal running + logged into OANDA?")
    try:
        sym = symbol + ".sim"
        if not mt5.symbol_select(sym, True):
            sym = symbol
            mt5.symbol_select(sym, True)
        # copy_rates_from_pos is robust where copy_rates_range returns -2 'Invalid
        # params' on large M15 ranges (and it forces the on-demand download).
        rates = mt5.copy_rates_from_pos(sym, tfmap[tf], 0, MT5_MAX_BARS)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"no rates for {sym} {tf}: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")     # RAW broker time
        df = df.rename(columns={"tick_volume": "volume"})
        a = pd.Timestamp(start)
        b = pd.Timestamp(end)
        df = df[(df["time"] >= a) & (df["time"] < b)]
        cols = ["time", "open", "high", "low", "close", "volume"]
        if "spread" in df:
            cols.append("spread")
        out = df[cols].reset_index(drop=True)
        span = f"{out['time'].iloc[0]:%Y-%m-%d}..{out['time'].iloc[-1]:%Y-%m-%d}" if len(out) else "empty"
        print(f"[mt5] {symbol} {tf}: {len(out):,} bars [BROKER time, {span}]")
        # sidecar so downstream never mistakes broker time for UTC
        meta = OUT_ROOT / "mt5" / f"{symbol}_{tf}.meta.json"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(_json.dumps({"symbol": symbol, "tf": tf, "rows": len(out),
                                     "time_basis": "broker_OANDA_demo_UTC+2or3",
                                     "utc_aligned": False,
                                     "note": "empirical UTC offset recovered in the divergence step"}))
        return out
    finally:
        mt5.shutdown()


# --------------------------------------------------------------------------- #
# HistData (free M1) — best-effort; documented manual fallback
# --------------------------------------------------------------------------- #
def fetch_histdata(symbol: str, tf: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    raise NotImplementedError(
        "HistData automated pull is intentionally deferred: histdata.com gates downloads "
        "behind a per-file form token + referer that breaks headless scraping. MANUAL "
        "FALLBACK: download the ASCII M1 monthly ZIPs for the symbol from "
        "https://www.histdata.com/download-free-forex-data/ , unzip into "
        "data/history/histdata_raw/<SYMBOL>/, then run `fetch_history.py histdata-ingest`. "
        "HistData M1 stamps are US Eastern WITHOUT DST (EST = UTC-5 year-round) — the ingest "
        "step shifts +5h to UTC. (Implement the ingest reader when this source is needed; "
        "Dukascopy + MT5 cover the harness's first pass.)")


# --------------------------------------------------------------------------- #
def write_parquet(df: pd.DataFrame, source: str, symbol: str, tf: str) -> Path:
    out = OUT_ROOT / source / f"{symbol}_{tf}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out


def selftest() -> None:
    """Offline decode unit-check: a synthetic 2-tick .bi5 must decode to exact prices."""
    point = 10 ** 5  # EURUSD
    payload = (_TICK.pack(0, 133900, 133897, 1.0, 1.0)
               + _TICK.pack(900_000, 133950, 133948, 2.0, 2.0))  # +15 min
    raw = lzma.compress(payload, format=lzma.FORMAT_ALONE)
    ticks = decode_bi5(raw, dt.date(2026, 6, 17), 8, point)
    assert len(ticks) == 2, ticks
    t0, bid0, ask0 = ticks[0]
    assert abs(bid0 - 1.33897) < 1e-9 and abs(ask0 - 1.33900) < 1e-9, ticks[0]
    assert t0 == dt.datetime(2026, 6, 17, 8, 0, tzinfo=dt.timezone.utc), t0
    t1 = ticks[1][0]
    assert t1 == dt.datetime(2026, 6, 17, 8, 15, tzinfo=dt.timezone.utc), t1
    # aggregation sanity
    mid = pd.Series([(b + a) / 2 for _, b, a in ticks],
                    index=[t for t, _, _ in ticks])
    bars = mid.resample("15min").ohlc().dropna()
    assert len(bars) == 2, bars
    print("PASS selftest: bi5 decode + scaling + UTC + resample all correct")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", choices=["dukascopy", "mt5", "histdata", "selftest"])
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--tf", default="M15", choices=list(TF_PANDAS))
    p.add_argument("--start")
    p.add_argument("--end")
    a = p.parse_args()

    if a.source == "selftest":
        selftest()
        return

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    fn = {"dukascopy": fetch_dukascopy, "mt5": fetch_mt5, "histdata": fetch_histdata}[a.source]
    df = fn(a.symbol, a.tf, start, end)
    if df is not None and len(df):
        out = write_parquet(df, a.source, a.symbol, a.tf)
        print(f"wrote {len(df):,} rows -> {out}")
        print(df.head(3).to_string(index=False))
        print(df.tail(2).to_string(index=False))


if __name__ == "__main__":
    main()
