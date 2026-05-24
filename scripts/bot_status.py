"""
Live status dashboard for the deployed bot portfolio.

Reports account state, open positions, and recent trade history
from MT5. Run this any time you want a "how's it doing" snapshot.

Usage: uv run python scripts/bot_status.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

UTC = timezone.utc


def main() -> None:
    from utils.config import MT5Config
    from data.mt5_client import MT5Client
    import MetaTrader5 as mt5

    cfg = MT5Config()
    print(f"Connecting to MT5 ({cfg.server})...\n")
    with MT5Client.from_config(cfg) as client:
        # -----------------------------------------------------
        # Account state
        # -----------------------------------------------------
        acc = mt5.account_info()
        print("=" * 70)
        print(f"  ACCOUNT  #{acc.login}  ({cfg.server})")
        print("=" * 70)
        print(f"  Balance:        ${acc.balance:>12,.2f}")
        print(f"  Equity:         ${acc.equity:>12,.2f}")
        print(f"  Floating P&L:   ${acc.profit:>+12,.2f}")
        print(f"  Free margin:    ${acc.margin_free:>12,.2f}")
        print(f"  Margin used:    ${acc.margin:>12,.2f}")
        print(f"  Leverage:        {acc.leverage}x")
        pct_change = (acc.equity / acc.balance - 1) * 100 if acc.balance > 0 else 0.0
        print(f"  Equity/Balance:  {pct_change:+.3f}%")
        print()

        # -----------------------------------------------------
        # Open positions
        # -----------------------------------------------------
        positions = mt5.positions_get()
        if not positions:
            print("--- OPEN POSITIONS ---")
            print("  (none)")
        else:
            print(f"--- OPEN POSITIONS ({len(positions)}) ---")
            print(f"  {'symbol':<10} {'side':<5} {'volume':>8} {'entry':>10} "
                  f"{'current':>10} {'pnl':>10} {'swap':>8}  EA")
            print("  " + "-" * 86)
            total_pnl = 0.0
            total_swap = 0.0
            for p in positions:
                side = "BUY" if p.type == 0 else "SELL"
                ea = p.comment or "(manual)"
                total_pnl += p.profit
                total_swap += p.swap
                print(f"  {p.symbol:<10} {side:<5} {p.volume:>8.2f} "
                      f"{p.price_open:>10.4f} {p.price_current:>10.4f} "
                      f"{p.profit:>+10.2f} {p.swap:>+8.2f}  {ea}")
            print("  " + "-" * 86)
            print(f"  {'TOTAL':<46} {total_pnl:>+10.2f} {total_swap:>+8.2f}")
        print()

        # -----------------------------------------------------
        # Recent closed trades (last 7 days)
        # -----------------------------------------------------
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
        deals = mt5.history_deals_get(start, end)
        if not deals:
            print("--- RECENT TRADES (last 7d) ---")
            print("  (no closed deals in the last week)")
        else:
            # Group by ticket -> show entry+exit pairs
            entries = {d.position_id: d for d in deals if d.entry == 0}
            exits = [d for d in deals if d.entry == 1]
            print(f"--- RECENT TRADES (last 7d, {len(exits)} closed) ---")
            print(f"  {'closed':<17} {'symbol':<10} {'side':<5} "
                  f"{'volume':>7} {'pnl':>10}  EA")
            print("  " + "-" * 70)
            total = 0.0
            for d in exits[-20:]:  # last 20
                ts = datetime.fromtimestamp(d.time, tz=UTC).strftime("%Y-%m-%d %H:%M")
                e = entries.get(d.position_id)
                side = "BUY" if (e and e.type == 0) else "SELL"
                ea = d.comment or "(manual)"
                pnl = d.profit + d.swap + d.commission
                total += pnl
                print(f"  {ts:<17} {d.symbol:<10} {side:<5} "
                      f"{d.volume:>7.2f} {pnl:>+10.2f}  {ea}")
            print(f"  Total 7d realized: ${total:+,.2f}")
        print()

        # -----------------------------------------------------
        # Carry accrual estimate for open carry positions
        # -----------------------------------------------------
        if positions:
            carry_positions = [p for p in positions
                                if "Carry" in (p.comment or "")]
            if carry_positions:
                print("--- CARRY ACCRUAL (open positions only) ---")
                for p in carry_positions:
                    info = mt5.symbol_info(p.symbol)
                    sl = info.swap_long if p.type == 0 else info.swap_short
                    if info.swap_mode == 1:
                        scale = info.point * info.trade_tick_value / info.trade_tick_size
                        per_lot_per_day = sl * scale
                    elif info.swap_mode == 2:
                        per_lot_per_day = sl
                    else:
                        per_lot_per_day = 0.0
                    daily = per_lot_per_day * p.volume
                    print(f"  {p.symbol:<10} {p.volume:>5.2f} lots  "
                          f"${daily:>+7.2f}/day  (${daily*30:>+7.2f}/month)")


if __name__ == "__main__":
    main()
