"""
Verify the OANDA-Demo-1 migration: connect with new creds, confirm
account info, and check that every symbol our 7 EAs depend on is
tradeable on this broker.

Symbols by EA:
  US500_MeanRev          -> US500
  XAUUSD_XAGUSD_Pairs    -> XAUUSD + XAGUSD
  AUDJPY_CHFJPY_Carry    -> AUDJPY + CHFJPY
  USDMXN_USDZAR_Carry    -> USDMXN + USDZAR
  WTI_BRT_Pairs          -> WTI + BRT
  MSFT_AAPL_Pairs        -> MSFT + AAPL
  JPN225_Momentum        -> JPN225

12 unique symbols total. If any are missing or TRADE_DISABLED on
OANDA, we need to either find an alias (e.g. SPX500 instead of US500)
or remove that EA from the migration.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

# Symbols by EA. The aliases column lists alternative names the broker
# may use for the same instrument; we try each in order until one works.
EA_SYMBOLS = [
    ("US500_MeanRev",        ["US500", "SPX500", "US500.cash", "SPX500USD"]),
    ("XAUUSD_XAGUSD_Pairs",  ["XAUUSD", "XAU/USD", "XAUUSD.s"]),
    ("XAUUSD_XAGUSD_Pairs",  ["XAGUSD", "XAG/USD"]),
    ("AUDJPY_CHFJPY_Carry",  ["AUDJPY", "AUD/JPY"]),
    ("AUDJPY_CHFJPY_Carry",  ["CHFJPY", "CHF/JPY"]),
    ("USDMXN_USDZAR_Carry",  ["USDMXN", "USD/MXN"]),
    ("USDMXN_USDZAR_Carry",  ["USDZAR", "USD/ZAR"]),
    ("WTI_BRT_Pairs",        ["WTI", "USOIL", "WTICOUSD", "USOILCash", "WTI.cash"]),
    ("WTI_BRT_Pairs",        ["BRT", "UKOIL", "BCOUSD", "BRENT", "UKOILCash"]),
    ("MSFT_AAPL_Pairs",      ["MSFT", "#MSFT", "MSFT.US"]),
    ("MSFT_AAPL_Pairs",      ["AAPL", "#AAPL", "AAPL.US"]),
    ("JPN225_Momentum",      ["JPN225", "JP225", "NIK225", "JP225USD"]),
]

TRADE_MODE_NAMES = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}


def main():
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server}) as login {cfg.login}...")
    with MT5Client.from_config(cfg) as client:
        acc = mt5.account_info()
        if acc is None:
            print("ERROR: account_info() returned None")
            return
        print()
        print("=" * 70)
        print(f"  Account #{acc.login}  ({cfg.server})")
        print("=" * 70)
        print(f"  Name:         {getattr(acc, 'name', '?')}")
        print(f"  Type:         {('REAL' if acc.trade_mode == 0 else 'CONTEST' if acc.trade_mode == 1 else 'DEMO')}")
        print(f"  Currency:     {acc.currency}")
        print(f"  Balance:      ${acc.balance:>12,.2f}")
        print(f"  Equity:       ${acc.equity:>12,.2f}")
        print(f"  Leverage:     {acc.leverage}x")
        print(f"  trade_allowed: {acc.trade_allowed}  (must be True for live trading)")
        print(f"  trade_expert:  {acc.trade_expert}   (must be True for EAs)")
        print()
        print("=" * 70)
        print("  Symbol availability for the 7 deployed EAs")
        print("=" * 70)
        print(f"  {'EA':<24} {'requested':<10} {'found':<14} {'mode':<10} {'spread':>7}")
        print("  " + "-" * 80)
        results = []
        for ea, candidates in EA_SYMBOLS:
            found = None
            for sym in candidates:
                info = mt5.symbol_info(sym)
                if info is not None:
                    found = sym
                    break
            if found is None:
                print(f"  {ea:<24} {candidates[0]:<10} {'NOT FOUND':<14}")
                results.append((ea, candidates[0], None, None, None))
                continue
            info = mt5.symbol_info(found)
            mode = TRADE_MODE_NAMES.get(info.trade_mode, str(info.trade_mode))
            tag = "[FULL]" if info.trade_mode == 4 else f"[{mode}]"
            print(f"  {ea:<24} {candidates[0]:<10} {found:<14} {mode:<10} {info.spread:>7}")
            results.append((ea, candidates[0], found, mode, info.spread))

        print()
        print("=" * 70)
        print("  MIGRATION VERDICT")
        print("=" * 70)
        missing = [r for r in results if r[2] is None]
        disabled = [r for r in results if r[2] is not None and r[3] != "FULL"]
        ok = [r for r in results if r[2] is not None and r[3] == "FULL"]
        print(f"  Tradeable:      {len(ok)}/{len(results)}")
        print(f"  Not on broker:  {len(missing)}")
        print(f"  Restricted:     {len(disabled)}")

        if missing:
            print()
            print("  Symbols MISSING on OANDA-Demo-1:")
            for r in missing:
                print(f"    {r[0]} needed {r[1]}")
            print("  -> If broker uses an alias, add it to EA_SYMBOLS in this script")
            print("  -> Otherwise EA must be excluded from the migration or pointed at a substitute")
        if disabled:
            print()
            print("  Symbols RESTRICTED on OANDA-Demo-1:")
            for r in disabled:
                print(f"    {r[0]} symbol {r[2]} has mode {r[3]}")

        # Symbol-name remap that the .env / EAs will need
        print()
        if any(r[1] != r[2] for r in results if r[2]):
            print("  ALIAS REMAP needed in EA inputs:")
            for ea, want, got, _, _ in results:
                if got and got != want:
                    print(f"    {ea}:  {want}  ->  {got}")


if __name__ == "__main__":
    main()
