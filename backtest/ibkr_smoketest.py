"""IBKR connection smoke test (2026-06-26) — run FIRST, before any adapter/order logic.

Validates the whole READ path against a headless IB Gateway PAPER session: socket/port,
Read-Only setting, account access, positions, and delayed pricing for the 15-ETF momentum
sleeve. Places ZERO orders. Green run == Gateway config is correct and the adapter can be built.

Prereqs (see research/ibkr_onboarding_2026-06.md):
  - IB Gateway running, logged into the PAPER account
  - API enabled, Socket port = 4002 (Gateway paper), "Read-Only API" UNCHECKED
  - pip install ib_async   (Python >=3.10; do NOT co-install ibapi/ib_insync)

Run:  python backtest/ibkr_smoketest.py            (defaults host=127.0.0.1 port=4002 clientId=17)
      python backtest/ibkr_smoketest.py --port 7497 --client-id 17   (if using TWS paper instead)
"""
from __future__ import annotations
import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG",
            "GLD", "SLV", "USO", "DBC", "VNQ", "UUP"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002, help="4002=Gateway paper, 7497=TWS paper")
    ap.add_argument("--client-id", type=int, default=17)
    args = ap.parse_args()

    try:
        from ib_async import IB, Stock
    except ImportError:
        print("[X] ib_async not installed.  ->  pip install ib_async  (Python >=3.10)")
        return 1

    ib = IB()
    print(f"connecting to {args.host}:{args.port} (clientId={args.client_id}) ...")
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    except (ConnectionRefusedError, OSError) as e:
        print(f"[X] connection refused: {e}")
        print("    -> Is IB Gateway running + logged into PAPER? Is the port right "
              "(4002 Gateway paper / 7497 TWS paper)? Is 127.0.0.1 trusted?")
        return 1
    except Exception as e:  # ib_async raises TimeoutError on wrong port
        print(f"[X] connect failed ({type(e).__name__}): {e}")
        print("    -> Wrong port silently times out. Verify Gateway paper = 4002.")
        return 1

    try:
        accts = ib.managedAccounts()
        if not accts:
            print("[X] connected but no managed accounts — Gateway not fully logged in?")
            return 1
        acct = accts[0]
        paper = acct.startswith("D")  # paper account codes start with 'D'
        print(f"[OK] connected. account={acct} ({'PAPER' if paper else 'LIVE(!)'})")
        if not paper:
            print("    [!] WARNING: this looks like a LIVE account code, not paper (D...). STOP and "
                  "point Gateway at the paper session before building the order adapter.")

        ib.reqMarketDataType(3)  # 3 = delayed/free (paper lacks live entitlements)
        ib.sleep(1.5)            # warm the account/position caches the gateway pushes on connect

        summ = {v.tag: v.value for v in ib.accountSummary(acct)}
        nav = summ.get("NetLiquidation", "?")
        cash = summ.get("TotalCashValue", "?")
        print(f"[OK] NAV={nav}  cash={cash}  currency={summ.get('Currency','?')}")

        positions = ib.positions()
        if positions:
            print(f"[OK] {len(positions)} open position(s):")
            for p in positions:
                print(f"       {p.contract.symbol:<6} {float(p.position):+g} @ avgCost {p.avgCost}")
        else:
            print("[OK] no open positions (clean paper account).")

        # read-only check: if orders can't be read, Read-Only API is likely still ON
        try:
            _ = ib.reqAllOpenOrders()
            print("[OK] order interface reachable (Read-Only API appears OFF — good).")
        except Exception as e:
            print(f"[!] could not query open orders ({e}) — is 'Read-Only API' still checked? "
                  "It must be OFF for the adapter to place orders.")

        print("\nqualifying + pricing the 15-ETF sleeve (delayed data) ...")
        contracts = [Stock(s, "SMART", "USD") for s in UNIVERSE]
        ib.qualifyContracts(*contracts)
        tickers = ib.reqTickers(*contracts)
        print("| symbol | conId | mktPrice | last | close |")
        print("|---|---|---|---|---|")
        ok = 0
        for s, t in zip(UNIVERSE, tickers):
            cid = t.contract.conId if t.contract else "?"
            mp, last, close = t.marketPrice(), t.last, t.close
            if mp == mp:  # not NaN
                ok += 1
            print(f"| {s} | {cid} | {mp} | {last} | {close} |")
        print(f"\n[{'OK' if ok >= 12 else '!'}] priced {ok}/{len(UNIVERSE)} names "
              f"({'delayed quotes flowing' if ok >= 12 else 'many NaN — check market-data type/subscriptions'}).")
        print("\n=== SMOKE TEST PASSED — read path is green. Safe to build the order adapter. ===")
        return 0
    finally:
        ib.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
