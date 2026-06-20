"""Query the live MT5 terminal for REAL overnight swap/financing rates (2026-06-20).

Resolves the overnight-drift viability question definitively: the account's actual server
(OANDA-Demo-1) carries the exact swap_long/short per instrument. Run on the VPS (or any box
with the terminal logged in). Annualizes the swap so it plugs straight into the
overnight_drift financing grid.

Run on the VPS:  .\.venv\Scripts\python.exe backtest\mt5_swaps.py
"""
from __future__ import annotations
import io
import sys
import MetaTrader5 as mt5

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SWAP_MODE = {0: "DISABLED", 1: "POINTS", 2: "CCY_SYMBOL", 3: "CCY_MARGIN",
             4: "CCY_DEPOSIT", 5: "INTEREST_CURRENT(%/yr)", 6: "INTEREST_OPEN(%/yr)",
             7: "REOPEN_CURRENT", 8: "REOPEN_BID_CURRENT"}
# index-CFD name fragments to look for (OANDA/.sim naming varies)
WANT = ("US500", "US100", "US30", "US2000", "SPX", "NAS", "NDX", "DOW", "USTEC",
        "GER40", "DE40", "UK100", "JP225", "SPX500", "NAS100")


def annual_pct(info) -> str:
    sl = info.swap_long
    mode = info.swap_mode
    if mode in (5, 6):                       # already %/yr
        return f"{sl:+.2f}%/yr"
    if mode == 1:                            # points: convert via price
        price = info.bid or info.ask or 0
        if price and info.point:
            # daily fraction = swap_long_points * point / price; ~360 nights/yr (×3 on rollover day nets out)
            return f"~{sl * info.point / price * 360 * 100:+.2f}%/yr (from points)"
    return "n/a (mode-specific)"


def main():
    if not mt5.initialize():
        print(f"mt5.initialize failed: {mt5.last_error()} — terminal running + logged in?")
        return
    try:
        allsyms = mt5.symbols_get() or ()
        names = [s.name for s in allsyms]
        hits = sorted({n for n in names for w in WANT if w in n.upper()})
        print(f"# MT5 swap query — {len(allsyms)} symbols, {len(hits)} index matches\n")
        if not hits:
            print("No index symbols matched. All symbols containing 'US'/'cash'/'idx':")
            print([n for n in names if any(k in n.lower() for k in ("us", "cash", "idx", "500", "100"))][:40])
            return
        print("| symbol | bid | swap_mode | swap_long | swap_short | ~annual (long) |")
        print("|---|---|---|---|---|---|")
        for n in hits:
            if not mt5.symbol_select(n, True):
                continue
            i = mt5.symbol_info(n)
            if i is None:
                continue
            print(f"| {n} | {i.bid} | {SWAP_MODE.get(i.swap_mode, i.swap_mode)} | "
                  f"{i.swap_long:+.4f} | {i.swap_short:+.4f} | {annual_pct(i)} |")
        print("\nThe '~annual (long)' column is the overnight FINANCING to plug into "
              "overnight_drift.py's grid. <3.5%/yr -> overnight drift viable on FTMO; "
              "~5-7% -> marginal/dead (matches the modeled rows).")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
