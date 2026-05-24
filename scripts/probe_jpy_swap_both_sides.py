"""
Re-probe JPY-cross broker swap rates — BOTH long-side and short-side.

The first JPY swap probe (scripts/probe_fx_swap_rates.py) recorded
only swap_long. The first live log from FTMOBotJPYCarry revealed that
NZDJPY swap_short = -3.83 ($/lot/day), not the +1.20 I assumed. So
short-NZDJPY actually COSTS carry, not earns it.

This probe captures both sides so we can find the best L/S pairing
under current broker rates. Output ranked by best-side carry yield.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

PAIRS = ["GBPJPY", "EURJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY"]


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...")
    with MT5Client.from_config(cfg) as client:
        rows = []
        for sym in PAIRS:
            info = mt5.symbol_info(sym)
            if info is None:
                continue
            mode = info.swap_mode
            sl = info.swap_long
            ss = info.swap_short
            if mode == 1:
                scale = info.point * info.trade_tick_value / info.trade_tick_size
                sl_per_lot = sl * scale
                ss_per_lot = ss * scale
            elif mode == 2:
                sl_per_lot = sl
                ss_per_lot = ss
            else:
                sl_per_lot = ss_per_lot = 0.0
            rows.append((sym, sl_per_lot, ss_per_lot))

        print(f"\n{'pair':<8} {'long $/d':>10} {'short $/d':>10}   best side")
        print("-" * 60)
        for sym, sl, ss in rows:
            best = "LONG" if sl > ss else "SHORT"
            best_v = max(sl, ss)
            note = "*EARNS*" if best_v > 0 else "loses"
            print(f"{sym:<8} {sl:>+10.3f} {ss:>+10.3f}   {best:<5} ({best_v:+5.2f} {note})")

        print()
        print("Best LONG-side carrier (highest swap_long):")
        for sym, sl, ss in sorted(rows, key=lambda r: -r[1])[:3]:
            print(f"  {sym}  long {sl:+.2f} $/lot/day")
        print()
        print("Best SHORT-side carrier (highest swap_short):")
        for sym, sl, ss in sorted(rows, key=lambda r: -r[2])[:3]:
            print(f"  {sym}  short {ss:+.2f} $/lot/day")

        print()
        print("Candidate L/S pairings (long_carry + short_carry must be > 0):")
        for sym_long, sl_long, _ in rows:
            if sl_long <= 0:
                continue
            for sym_short, _, ss_short in rows:
                if sym_short == sym_long:
                    continue
                if ss_short <= 0:
                    continue
                net = sl_long + ss_short
                if net > 0:
                    print(f"  long {sym_long} + short {sym_short}: "
                          f"+{sl_long:.2f} +{ss_short:.2f} = +{net:.2f}/lot/day")


if __name__ == "__main__":
    main()
