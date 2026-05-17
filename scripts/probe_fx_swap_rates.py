"""
Probe the MT5 broker for FX swap rates (the broker's carry yield per pair).

For each FX pair the broker reports SYMBOL_SWAP_LONG and SYMBOL_SWAP_SHORT
(broker-quoted swap rates -- in units that vary by SYMBOL_SWAP_MODE). We
convert to an approximate annualised yield in account currency:

    annualised_carry_pct = swap_long * 365 / contract_value_usd

For a USD-base account on USDJPY, swap_long > 0 means the broker credits
you for being LONG USDJPY (i.e. long USD, short JPY). High carry-yielders
(AUD, NZD historically) have swap_long > 0 on AUDUSD/NZDUSD.

These numbers ARE the carry-trade P&L the bot would earn live; using them
as the signal lets us hypothesis-test FX carry on the actual broker
without external interest-rate data feeds.

Usage:
    uv run python scripts/probe_fx_swap_rates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()


PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
         "USDJPY", "USDCAD", "USDCHF"]


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...")
    with MT5Client.from_config(cfg) as client:
        print(f"\n{'pair':<8} {'swap_long':>10} {'swap_short':>11} "
              f"{'mode':>5} {'point':>8} {'tick_val':>10} "
              f"{'last':>11}  notes")
        print("-" * 95)
        for sym in PAIRS:
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"{sym:<8} -- not on broker")
                continue
            tick = mt5.symbol_info_tick(sym)
            last = tick.bid if tick else 0.0
            mode = info.swap_mode  # 0=disabled, 1=points, 2=base currency, etc.
            sl = info.swap_long
            ss = info.swap_short
            # Approximate $/lot/day from swap:
            #   if mode == 1 (points): swap * point * tick_value
            #   if mode == 2 (currency): swap (already in account currency)
            #   else fallback to raw value (units may vary)
            note = ""
            if mode == 1:    # SYMBOL_SWAP_MODE_POINTS
                long_per_lot_per_day = sl * info.point * info.trade_tick_value / info.trade_tick_size
                note = f"long $/lot/day ~ {long_per_lot_per_day:+.4f}"
            elif mode == 2:  # SYMBOL_SWAP_MODE_CURRENCY_SYMBOL
                note = f"long $/lot/day = {sl:+.4f} (raw)"
            else:
                note = f"swap_mode={mode}, units unknown"
            print(f"{sym:<8} {sl:>+10.5f} {ss:>+11.5f} "
                  f"{mode:>5} {info.point:>8.5f} {info.trade_tick_value:>10.4f} "
                  f"{last:>11.5f}  {note}")
        print()
        print("Notes:")
        print("  swap_mode 1 (points): annualised carry = swap_long * 365 * point / tick_size * tick_value / lot_notional")
        print("  swap_mode 2 (currency): annualised carry = swap_long * 365 / lot_notional")
        print("  swap_long > 0  -> broker pays you to be LONG this symbol (favourable carry)")
        print("  swap_long < 0  -> broker charges you per night (unfavourable carry)")


if __name__ == "__main__":
    main()
