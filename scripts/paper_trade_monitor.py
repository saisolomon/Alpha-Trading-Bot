"""
Paper-trade monitor: connects to MT5, snapshots account state to JSONL.

Designed to run in the background for the duration of the 4-week paper-trade
window. Every poll_interval seconds, captures:
  - account equity / balance / margin
  - open positions (per-symbol P&L)
  - closed deals since last snapshot
  - the OCaml FTMO state machine's status code (via the same ftmo_apply_tick
    the live EA uses -- single source of truth)

Output: data/paper_trade/<YYYY-MM-DD>.jsonl (one JSON object per snapshot).
These files are the input to scripts/paper_trade_daily_report.py.

Usage:
    uv run python scripts/paper_trade_monitor.py --poll-seconds 60
    uv run python scripts/paper_trade_monitor.py --account-type CHALLENGE_2STEP_PHASE1

This script does NOT trade; it only observes. The actual EA (FTMOBot.mq5)
runs inside the MT5 terminal -- this script runs alongside as a watcher.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load MT5_LOGIN / MT5_PASSWORD / MT5_SERVER from .env at the repo root.
# Without this, MT5Config() fails validation when run as a standalone script.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper-trade monitor for the MT5 demo / FTMO account")
    p.add_argument("--poll-seconds", type=int, default=60,
                   help="Seconds between snapshots (default 60)")
    p.add_argument("--account-type", default="CHALLENGE_2STEP_PHASE1",
                   help="FTMO account type for the parallel risk machine")
    p.add_argument("--output-dir", default="data/paper_trade",
                   help="Where to write JSONL snapshots")
    p.add_argument("--initial-capital", type=float, default=None,
                   help="Override initial capital (default = account balance at startup)")
    p.add_argument("--max-snapshots", type=int, default=0,
                   help="Stop after N snapshots (0 = run forever)")
    return p.parse_args()


def setup_signal_handlers(stop_flag: list[bool]) -> None:
    def handler(signum, frame):
        print(f"\n[monitor] caught signal {signum}, shutting down cleanly...", flush=True)
        stop_flag[0] = True
    signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handler)


def open_today_log(output_dir: Path) -> tuple[Path, "object"]:
    """Open the JSONL log file for today's UTC date. Returns (path, file_handle)."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = output_dir / f"{today}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path, out_path.open("a", encoding="utf-8")


def snapshot_account(client) -> dict:
    """Build one snapshot dict from current MT5 state."""
    info = client.account_info()
    positions = []
    try:
        import MetaTrader5 as mt5
        pos_tuple = mt5.positions_get() or ()
        for p in pos_tuple:
            positions.append({
                "ticket": int(p.ticket),
                "symbol": p.symbol,
                "type": int(p.type),     # 0=buy, 1=sell
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "price_current": float(p.price_current),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "swap": float(p.swap),
                "time_open": int(p.time),
            })
    except Exception as exc:
        positions = [{"error": str(exc)}]

    return {
        "ts_utc": datetime.now(UTC).isoformat(),
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "margin_free": float(info.margin_free),
        "margin_level": float(info.margin_level) if info.margin > 0 else None,
        "profit": float(info.profit),
        "open_positions": positions,
    }


def main() -> None:
    # Stand-down kill-switch: the scheduled task fires every 5 min and cannot
    # be disabled without elevation, and mt5.initialize() would RELAUNCH the
    # terminal we deliberately stopped. If the sentinel exists, exit before
    # touching MT5. Re-enable monitoring by deleting logs/MONITOR_DISABLED.
    sentinel = Path(__file__).resolve().parents[1] / "logs" / "MONITOR_DISABLED"
    if sentinel.exists():
        print(f"monitor disabled by sentinel {sentinel} -- exiting (delete the file to re-enable)")
        return

    args = parse_args()

    # Lazy imports so the script can be syntax-checked without MT5 installed
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    from risk.ftmo import (
        FTMOAccountType, new_state, equity_tick,
        FTMOInternalBreach, FTMOImminent, daily_reset,
    )
    from utils.convex_client import ConvexClient
    convex = ConvexClient.from_env()  # None if env vars missing; safe
    # Track the highest deal ticket we've sent to Convex so we only
    # fetch+post NEW fills each poll cycle. Seeded from Convex itself
    # at startup so a monitor restart doesn't re-send the whole history.
    deal_high_water = 0
    # MT5 Experts-tab log tailer state. Each poll reads NEW lines from
    # today's log file and POSTs parsed signal events to Convex.
    from utils.mt5_log_parser import parse_log_file_since, todays_log_path
    MT5_LOGS_DIR = Path(
        r"C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal"
        r"\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs"
    )
    log_tail_state = {"path": None, "offset": 0, "date": None}
    from utils.timeutils import prague_midnight_of

    cfg = MT5Config()
    print(f"[monitor] connecting to {cfg.server} (login {cfg.login})...", flush=True)
    client = MT5Client.from_config(cfg)
    client.connect()
    try:
        info = client.account_info()
        initial = args.initial_capital if args.initial_capital else float(info.balance)
        acct_type = FTMOAccountType(args.account_type)
        ftmo_state = new_state(acct_type, initial)
        print(f"[monitor] account={acct_type.value}  balance={info.balance:.2f}  "
              f"equity={info.equity:.2f}  init={initial:.2f}", flush=True)
        print(f"[monitor] FTMO limits  daily={ftmo_state.ftmo_daily_limit:.2f}  "
              f"max={ftmo_state.ftmo_max_loss_limit:.2f}  "
              f"internal_daily={ftmo_state.internal_daily_kill_limit:.2f}  "
              f"internal_max={ftmo_state.internal_max_kill_limit:.2f}", flush=True)

        stop_flag = [False]
        setup_signal_handlers(stop_flag)
        out_dir = Path(args.output_dir)
        out_path, fh = open_today_log(out_dir)
        current_log_date = out_path.stem
        last_prague_midnight = prague_midnight_of(datetime.now(UTC))
        snapshots = 0

        # Seed deal_high_water from Convex so we don't replay history
        if convex is not None:
            deal_high_water = convex.get_latest_deal_ticket(int(cfg.login))
            print(f"[monitor] Convex deal-sync seeded at ticket={deal_high_water}", flush=True)

        while not stop_flag[0]:
            # Roll log file at UTC midnight (cheap proxy for "new day")
            today_str = datetime.now(UTC).strftime("%Y-%m-%d")
            if today_str != current_log_date:
                fh.close()
                out_path, fh = open_today_log(out_dir)
                current_log_date = out_path.stem
                print(f"[monitor] rolled log to {out_path}", flush=True)

            # FTMO daily reset at Prague midnight
            now = datetime.now(UTC)
            new_prague_midnight = prague_midnight_of(now)
            if new_prague_midnight > last_prague_midnight:
                ftmo_state = daily_reset(ftmo_state, now, float(client.account_info().balance))
                last_prague_midnight = new_prague_midnight
                print(f"[monitor] FTMO daily reset @ {now.isoformat()}  "
                      f"new daily limit={ftmo_state.ftmo_daily_limit:.2f}", flush=True)

            try:
                snap = snapshot_account(client)
            except Exception as exc:
                print(f"[monitor] snapshot failed: {exc}", flush=True)
                time.sleep(args.poll_seconds)
                continue

            # Apply equity_tick to the parallel FTMO state machine
            risk_status = "active"
            risk_distance = {
                "to_ftmo_daily": ftmo_state.distance_to_ftmo_daily(snap["equity"]),
                "to_ftmo_max":   ftmo_state.distance_to_ftmo_max(snap["equity"]),
                "to_internal_daily": ftmo_state.distance_to_internal_daily(snap["equity"]),
                "to_internal_max":   ftmo_state.distance_to_internal_max(snap["equity"]),
            }
            try:
                equity_tick(snap["equity"], ftmo_state, now)
            except FTMOImminent as imm:
                risk_status = f"imminent_{imm.line_type}"
            except FTMOInternalBreach as br:
                risk_status = f"internal_killed_{br.breach_type}"

            snap["risk_status"] = risk_status
            snap["risk_distance"] = risk_distance
            snap["ftmo_daily_limit"] = ftmo_state.ftmo_daily_limit
            snap["ftmo_max_limit"] = ftmo_state.ftmo_max_loss_limit

            fh.write(json.dumps(snap) + "\n")
            fh.flush()
            snapshots += 1

            # Parallel POST to Convex (fire-and-forget; failures logged
            # but don't crash the monitor — JSONL on disk is the canonical
            # record). Heartbeat goes every poll; snapshot too. The
            # heartbeat exists separately so the staleness detector can
            # alarm even if snapshot inserts fail.
            if convex is not None:
                ftmo_status_code = 0
                if risk_status.startswith("imminent_"):
                    ftmo_status_code = 1
                elif risk_status.startswith("internal_killed"):
                    ftmo_status_code = 2

                # Normalize positions to the Convex schema's shape
                cnv_positions = []
                for p in snap["open_positions"]:
                    if "error" in p:
                        continue
                    cnv_positions.append({
                        "ticket": p["ticket"],
                        "symbol": p["symbol"],
                        "side": "BUY" if p["type"] == 0 else "SELL",
                        "volume": p["volume"],
                        "priceOpen": p["price_open"],
                        "priceCurrent": p["price_current"],
                        "profit": p["profit"],
                        "swap": p["swap"],
                    })

                convex.post_heartbeat(
                    broker_login=int(cfg.login),
                    broker_server=cfg.server,
                    account_type=acct_type.value,
                    initial_capital=initial,
                    currency="USD",
                    monitor_version="paper_trade_monitor-0.2-convex",
                    mt_connected=True,
                )
                convex.post_snapshot(
                    broker_login=int(cfg.login),
                    broker_server=cfg.server,
                    account_type=acct_type.value,
                    initial_capital=initial,
                    currency="USD",
                    balance=snap["balance"],
                    equity=snap["equity"],
                    profit=snap["profit"],
                    margin_used=snap["margin"],
                    margin_free=snap["margin_free"],
                    daily_limit_distance=risk_distance["to_ftmo_daily"],
                    max_limit_distance=risk_distance["to_ftmo_max"],
                    ftmo_status=ftmo_status_code,
                    carry_today=sum(p.get("swap", 0) for p in snap["open_positions"]
                                     if isinstance(p.get("swap"), (int, float))),
                    positions=cnv_positions,
                )

                # ---- Sync NEW deals (closed fills) to Convex ----
                # MT5 history_deals_get returns ALL deals since the date
                # we pass. We re-fetch from the last 24h every poll and
                # let the backend dedupe by ticket (cheap, idempotent).
                try:
                    import MetaTrader5 as mt5
                    from datetime import timedelta as _td
                    since = datetime.now(UTC) - _td(days=2)
                    raw_deals = mt5.history_deals_get(since, datetime.now(UTC)) or ()
                    new_deals = []
                    for d in raw_deals:
                        if int(d.ticket) <= deal_high_water:
                            continue
                        # entry: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY
                        entry_map = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
                        new_deals.append({
                            "ticket": int(d.ticket),
                            "positionId": int(d.position_id) if d.position_id else None,
                            "symbol": d.symbol,
                            "side": "BUY" if d.type == 0 else "SELL",
                            "entry": entry_map.get(int(d.entry), "IN"),
                            "volume": float(d.volume),
                            "price": float(d.price),
                            "profit": float(d.profit),
                            "swap": float(d.swap),
                            "commission": float(d.commission),
                            "dealTimeMs": int(d.time) * 1000,
                            "eaName": d.comment or None,
                        })
                    if new_deals:
                        r = convex.post_deals(
                            broker_login=int(cfg.login),
                            deals=new_deals,
                        )
                        max_new_ticket = max(int(x["ticket"]) for x in new_deals)
                        if max_new_ticket > deal_high_water:
                            deal_high_water = max_new_ticket
                        print(f"[monitor] posted {len(new_deals)} deals to Convex "
                              f"(inserted={r.get('inserted') if r else '?'}, "
                              f"high_water={deal_high_water})", flush=True)
                except Exception as exc:
                    print(f"[monitor] deal sync failed: {exc}", flush=True)

                # ---- Tail MT5 Experts-tab log + POST new signal events ----
                # Each poll reads only NEW bytes from today's log file
                # using a per-file high-water-mark offset. Cheap.
                try:
                    cur_log_path, cur_log_date = todays_log_path(MT5_LOGS_DIR)
                    # Reset offset if we rolled over to a new day's log file
                    if log_tail_state["path"] != cur_log_path or log_tail_state["date"] != cur_log_date:
                        log_tail_state["path"] = cur_log_path
                        log_tail_state["date"] = cur_log_date
                        log_tail_state["offset"] = 0
                    events, new_offset = parse_log_file_since(
                        cur_log_path,
                        cur_log_date,
                        log_tail_state["offset"],
                    )
                    log_tail_state["offset"] = new_offset
                    if events:
                        event_dicts = [{
                            "eaName": e.ea_name,
                            "symbol": e.symbol,
                            "eventType": e.event_type,
                            "side": e.side,
                            "price": e.price,
                            "volume": e.volume,
                            "eventTimeMs": e.event_time_ms,
                            "rawLine": e.raw_line,
                        } for e in events]
                        r = convex.post_signals(
                            broker_login=int(cfg.login),
                            events=event_dicts,
                        )
                        if r and r.get("inserted", 0) > 0:
                            print(f"[monitor] posted {r['inserted']} new EA signals "
                                  f"({r.get('skipped', 0)} dedupe-skipped)", flush=True)
                except Exception as exc:
                    print(f"[monitor] signal-log tail failed: {exc}", flush=True)

            if snapshots % 30 == 0:
                print(f"[monitor] {snapshots} snapshots  "
                      f"equity={snap['equity']:.2f}  status={risk_status}"
                      f"  convex={'on' if convex else 'off'}", flush=True)

            if args.max_snapshots and snapshots >= args.max_snapshots:
                print(f"[monitor] reached max_snapshots={args.max_snapshots}", flush=True)
                break

            time.sleep(args.poll_seconds)

    finally:
        try:
            fh.close()
        except Exception:
            pass
        client.disconnect()
        print(f"[monitor] disconnected", flush=True)


if __name__ == "__main__":
    main()
