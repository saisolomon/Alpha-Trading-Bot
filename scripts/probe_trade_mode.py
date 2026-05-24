"""
Diagnose retcode=10017 (TRADE_DISABLED) by checking each EA-symbol's
broker-level trade mode and per-chart permission state.

Usage: uv run python scripts/probe_trade_mode.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

# All symbols across the 4 live EAs
SYMBOLS = ["US500", "USTEC", "US30",
           "XAUUSD", "XAGUSD",
           "AUDJPY", "CHFJPY",
           "USDMXN", "USDZAR"]

TRADE_MODE_NAMES = {
    0: "DISABLED",        # SYMBOL_TRADE_MODE_DISABLED
    1: "LONGONLY",        # SYMBOL_TRADE_MODE_LONGONLY
    2: "SHORTONLY",       # SYMBOL_TRADE_MODE_SHORTONLY
    3: "CLOSEONLY",       # SYMBOL_TRADE_MODE_CLOSEONLY
    4: "FULL",            # SYMBOL_TRADE_MODE_FULL  <- normal/expected
}


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...")
    with MT5Client.from_config(cfg) as client:
        # Account-level info first
        acc = mt5.account_info()
        if acc is None:
            print("ERROR: cannot read account info")
            return
        print(f"\nAccount: {acc.login}  type: {('REAL' if acc.trade_mode == 0 else 'CONTEST' if acc.trade_mode == 1 else 'DEMO')}")
        print(f"  trade_allowed: {acc.trade_allowed}      <-- must be True")
        print(f"  trade_expert:  {acc.trade_expert}       <-- must be True for EAs")
        print(f"  limit_orders:  {acc.limit_orders}")
        print(f"  margin_mode:   {acc.margin_mode}")
        print()

        # Per-symbol trade mode
        print(f"{'symbol':<10} {'trade_mode':<12} {'spread':>8} {'last':>12}  notes")
        print("-" * 70)
        any_bad = False
        for sym in SYMBOLS:
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"{sym:<10} NOT-ON-BROKER")
                any_bad = True
                continue
            mode_name = TRADE_MODE_NAMES.get(info.trade_mode, f"?{info.trade_mode}")
            tick = mt5.symbol_info_tick(sym)
            last = tick.bid if tick else 0.0
            note = ""
            if info.trade_mode != 4:
                note = "*** TRADE NOT FULL ***"
                any_bad = True
            elif not info.visible:
                note = "not in MarketWatch (will fail SymbolSelect)"
            elif info.spread == 0:
                note = "spread=0 (illiquid / stale)"
            print(f"{sym:<10} {mode_name:<12} {info.spread:>8d} {last:>12.5f}  {note}")

        print()
        if any_bad:
            print("FIX: any symbol marked '*** TRADE NOT FULL ***' is the cause of retcode=10017.")
            print("     For MetaQuotes-Demo specifically: try a different demo broker (FTMO,")
            print("     IC Markets, Pepperstone) -- MetaQuotes-Demo restricts many symbols.")
        else:
            print("All symbols full-trade. retcode=10017 must be coming from somewhere else --")
            print("check the chart-level 'Allow Algo Trading' checkbox per chart.")


if __name__ == "__main__":
    main()
