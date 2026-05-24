"""
Probe broker swap rates for the high-carry exotic FX universe.

Used by scripts/exotic_carry_universe_sweep.py to rank pairs by current
carry and form the L/S carry portfolio (long top-N high-carry, short
bottom-N).

Usage:
    uv run python scripts/probe_exotic_swap_rates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

PAIRS = ["USDMXN", "USDZAR", "USDTRY", "USDSEK", "USDNOK",
         "USDHKD", "USDSGD"]


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...")
    with MT5Client.from_config(cfg) as client:
        print(f"\n{'pair':<8} {'swap_long':>10} {'swap_short':>11} "
              f"{'mode':>5} {'point':>10} {'tick_val':>10} "
              f"{'last':>11}  long $/lot/day   short $/lot/day")
        print("-" * 110)
        rows = []
        for sym in PAIRS:
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"{sym:<8} -- not on broker")
                continue
            tick = mt5.symbol_info_tick(sym)
            last = tick.bid if tick else 0.0
            mode = info.swap_mode
            sl = info.swap_long
            ss = info.swap_short
            sl_per_lot = ss_per_lot = 0.0
            if mode == 1:
                scale = info.point * info.trade_tick_value / info.trade_tick_size
                sl_per_lot = sl * scale
                ss_per_lot = ss * scale
            elif mode == 2:
                sl_per_lot = sl
                ss_per_lot = ss
            print(f"{sym:<8} {sl:>+10.5f} {ss:>+11.5f} "
                  f"{mode:>5} {info.point:>10.6f} {info.trade_tick_value:>10.4f} "
                  f"{last:>11.5f}    {sl_per_lot:>+10.4f}      {ss_per_lot:>+10.4f}")
            rows.append((sym, sl_per_lot, ss_per_lot))
        print()
        print("Ranked by long-side carry (most favourable to least):")
        for sym, sl, ss in sorted(rows, key=lambda r: -r[1]):
            print(f"  {sym:<8} long {sl:+7.2f} $/lot/day   short {ss:+7.2f}")


if __name__ == "__main__":
    main()
