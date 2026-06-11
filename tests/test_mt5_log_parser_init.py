"""Regression tests for init-line parsing + heartbeat eaStates plumbing (2026-06-11).

Found during VPS migration §7: heartbeat eaStates had NEVER been populated --
post_heartbeat accepts ea_states but the monitor never built it, so the go-live
hard check ("every roster EA reports dryRun:false") was reading a field that
could not populate. These tests pin the new pathway:

  MT5 Experts log init line -> SignalEvent(event_type="init", dry_run=...)
  -> update_ea_states() fold -> sidecar persistence -> heartbeat payload shape.

Runnable standalone (no pytest needed):  python tests/test_mt5_log_parser_init.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utils.mt5_log_parser import parse_line, parse_log_file_since

# scripts/ is not a package; load the monitor module by path
_spec = importlib.util.spec_from_file_location(
    "paper_trade_monitor", REPO / "scripts" / "paper_trade_monitor.py")
_mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mon)

FILE_DATE = datetime(2026, 6, 11, tzinfo=timezone.utc)

# Exact PrintFormat shapes from the EAs (mql5/Experts/*.mq5)
INIT_TRUE = ("AB\t0\t07:31:18.123\tEURUSD_M15_LondonMomo (GBPUSD.sim,M15)\t"
             "[EURUSD_M15_LondonMomo:GBPUSD.sim] init  session=07:00 UTC  "
             "range=30min  risk=0.50%  dry_run=true")
INIT_FALSE = ("AB\t0\t07:31:19.456\tXAUUSD_M15_LondonFix (XAUUSD.sim,M15)\t"
              "[XAUUSD_M15_LondonFix:XAUUSD.sim] init  pre-fix=14:30  fix=15:00  "
              "close=20:00 UTC  atr=14  risk=0.50%  dry_run=false")
ARMED = ("AB\t0\t07:31:20.789\tEquityWatchdog (EURUSD.sim,H1)\t"
         "[EquityWatchdog] armed  initial=200000.00  daily_kill=3.0%  "
         "max_kill=7.0%  poll=1s  anchor_balance=200000.00")
ENTRY = ("AB\t0\t08:02:11.000\tEURUSD_M15_LondonMomo (GBPUSD.sim,M15)\t"
         "[EURUSD_M15_LondonMomo:GBPUSD.sim] ENTRY LONG  px=1.27543 lots=0.62")
SKIP = ("AB\t0\t08:05:00.000\tEURUSD_M15_LondonMomo (GBPUSD.sim,M15)\t"
        "[EURUSD_M15_LondonMomo:GBPUSD.sim] skip: news blackout 12min to FOMC")


def test_init_line_parses_with_dry_run_flag():
    ev = parse_line(FILE_DATE, INIT_TRUE)
    assert ev is not None and ev.event_type == "init", ev
    assert ev.ea_name == "EURUSD_M15_LondonMomo"
    assert ev.symbol == "GBPUSD.sim"
    assert ev.dry_run is True
    ev2 = parse_line(FILE_DATE, INIT_FALSE)
    assert ev2.event_type == "init" and ev2.dry_run is False, ev2
    print("PASS test_init_line_parses_with_dry_run_flag")


def test_watchdog_armed_parses_as_init_never_dryrun():
    ev = parse_line(FILE_DATE, ARMED)
    assert ev is not None and ev.event_type == "init", ev
    assert ev.ea_name == "EquityWatchdog"
    assert ev.dry_run is False
    # chart symbol recovered from the MT5 "EAName (SYMBOL,TF)" prefix
    assert ev.symbol == "EURUSD.sim", ev
    print("PASS test_watchdog_armed_parses_as_init_never_dryrun")


ORCH_INIT = ("AB\t0\t05:43:39.500\tBotOrchestrator (USDNOK.sim,H1)\t"
             "[BotOrchestrator] init: manifest=bot_manifest.txt poll=60s "
             "tf=PERIOD_D1 auto_save=true")
ORCH_POLL = ("AB\t0\t06:13:40.100\tBotOrchestrator (USDNOK.sim,H1)\t"
             "[BotOrchestrator] poll #30: ok=3 fail=0 total=3  changes=0")


def test_orchestrator_init_and_poll_summary_parse():
    for line in (ORCH_INIT, ORCH_POLL):
        ev = parse_line(FILE_DATE, line)
        assert ev is not None and ev.event_type == "init", (line, ev)
        assert ev.ea_name == "BotOrchestrator"
        assert ev.symbol == "USDNOK.sim"
        assert ev.dry_run is False
    print("PASS test_orchestrator_init_and_poll_summary_parse")


def test_existing_event_types_unbroken():
    ev = parse_line(FILE_DATE, ENTRY)
    assert ev is not None and ev.event_type == "entry" and ev.side == "LONG", ev
    assert ev.dry_run is None  # only init events carry the flag
    sk = parse_line(FILE_DATE, SKIP)
    assert sk is not None and sk.event_type == "skip", sk
    print("PASS test_existing_event_types_unbroken")


def test_file_parse_utf16le_with_bom():
    tmp = Path(tempfile.mkdtemp()) / "20260611.log"
    body = "\n".join([INIT_TRUE, ARMED, ENTRY]) + "\n"
    tmp.write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
    events, offset = parse_log_file_since(tmp, FILE_DATE, 0)
    assert offset == tmp.stat().st_size
    types = [e.event_type for e in events]
    assert types == ["init", "init", "entry"], types
    print("PASS test_file_parse_utf16le_with_bom")


def test_update_ea_states_fold_and_heartbeat_shape():
    states: dict[str, dict] = {}
    init_ev = parse_line(FILE_DATE, INIT_TRUE)
    armed_ev = parse_line(FILE_DATE, ARMED)
    skip_ev = parse_line(FILE_DATE, SKIP)

    # Non-init event for an EA we haven't seen an init for yet -> no entry
    # (dryRun unknown; the schema requires a boolean, so we must not guess)
    assert _mon.update_ea_states(states, [skip_ev]) is False
    assert states == {}

    changed = _mon.update_ea_states(states, [init_ev, armed_ev, skip_ev])
    assert changed is True
    assert states["EURUSD_M15_LondonMomo"]["dryRun"] is True
    assert states["EURUSD_M15_LondonMomo"]["symbol"] == "GBPUSD.sim"
    assert "news blackout" in states["EURUSD_M15_LondonMomo"]["lastLog"]
    assert states["EquityWatchdog"]["dryRun"] is False

    # Heartbeat payload shape must match the Convex schema exactly:
    # {name, symbol, dryRun, lastLog}
    payload = [{"name": n, **st} for n, st in sorted(states.items())]
    for entry in payload:
        assert set(entry) == {"name", "symbol", "dryRun", "lastLog"}, entry
        assert isinstance(entry["dryRun"], bool)
    print("PASS test_update_ea_states_fold_and_heartbeat_shape")


def test_resolve_initial_capital_priority():
    f = _mon.resolve_initial_capital
    # CLI beats env beats balance
    assert f(150000, "200000", 199500.0) == 150000.0
    assert f(None, "200000", 199500.0) == 200000.0
    assert f(None, None, 199500.0) == 199500.0
    # Garbage / non-positive env falls through to balance
    assert f(None, "not-a-number", 199500.0) == 199500.0
    assert f(None, "0", 199500.0) == 199500.0
    print("PASS test_resolve_initial_capital_priority")


def test_sidecar_roundtrip_and_corruption_tolerance():
    tmp = Path(tempfile.mkdtemp()) / "ea_states.json"
    states = {"EURUSD_M15_LondonMomo":
              {"symbol": "GBPUSD.sim", "dryRun": True, "lastLog": "init"}}
    _mon.save_ea_states(tmp, states)
    assert _mon.load_ea_states(tmp) == states

    tmp.write_text("{not json", encoding="utf-8")
    assert _mon.load_ea_states(tmp) == {}

    # Entries with a missing/invalid dryRun must be dropped, not propagated
    tmp.write_text(json.dumps({"Bad": {"symbol": "X"},
                               "Good": {"symbol": "Y", "dryRun": False}}),
                   encoding="utf-8")
    loaded = _mon.load_ea_states(tmp)
    assert "Bad" not in loaded and loaded["Good"]["dryRun"] is False
    print("PASS test_sidecar_roundtrip_and_corruption_tolerance")


if __name__ == "__main__":
    test_init_line_parses_with_dry_run_flag()
    test_watchdog_armed_parses_as_init_never_dryrun()
    test_orchestrator_init_and_poll_summary_parse()
    test_existing_event_types_unbroken()
    test_file_parse_utf16le_with_bom()
    test_update_ea_states_fold_and_heartbeat_shape()
    test_resolve_initial_capital_priority()
    test_sidecar_roundtrip_and_corruption_tolerance()
    print("ALL INIT-PARSER / EASTATES TESTS PASS")
