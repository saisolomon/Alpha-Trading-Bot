"""
Probe broker swap rates on Central European EM-FX (USDPLN, USDHUF,
USDCZK) plus a few other carry candidates. Used to design the CE-EM
carry EA the same way we did JPY and EM-FX.

Same pattern as probe_jpy_swap_both_sides.py: capture BOTH swap_long
and swap_short so we can identify the net-carry-positive pairing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

PAIRS = ["USDPLN", "USDHUF", "USDCZK", "EURSEK", "EURTRY", "USDNOK", "USDSEK"]


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
        print("Candidate L/S pairings ranked by NET carry (sum of long+short):")
        candidates = []
        for sym_long, sl_long, _ in rows:
            for sym_short, _, ss_short in rows:
                if sym_short == sym_long:
                    continue
                net = sl_long + ss_short
                candidates.append((sym_long, sym_short, sl_long, ss_short, net))
        candidates.sort(key=lambda c: -c[4])
        for sym_long, sym_short, sl, ss, net in candidates[:8]:
            marker = "*" if net > 0 else " "
            print(f"  {marker} long {sym_long} + short {sym_short}: "
                  f"+{sl:.2f} + {ss:.2f} = {net:+.2f}/lot/day")


if __name__ == "__main__":
    main()
