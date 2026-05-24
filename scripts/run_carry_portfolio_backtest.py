"""
Joint backtest: JPY-carry + EM-carry on 12y D1 history.

CONSERVATIVE backtest design:
  - Simulates spot return only (ignores carry income).
    Rationale: historical carry rates aren't in our cache; using
    today's broker swap as a constant would mis-state pre-2023 P&L.
    The live system earns carry ON TOP of these spot results.

  - Periodic entry: enters a new L/S position every 20 D1 bars if flat
    and regime gate is active. Holds for 60 D1 bars or until TP/SL.
    This mirrors the 60-day max-hold from the EA spec and gives ~10
    independent trades per year per strategy.

  - Regime gate (PROXY): since broker swap history isn't available,
    we use price-based proxies that approximate the rate-divergence
    regime:
      JPY-carry active: AUDJPY current price > 252d moving average
                        (JPY weakening regime = BoJ divergence)
      EM-carry active:  USDMXN current price > 252d moving average
                        (USD strengthening regime = Banxico tightening
                         relative to Fed)
    These are imperfect proxies; the LIVE system uses the actual
    broker swap rate, which is a cleaner signal.

  - Per-leg risk: 0.5% equity, sized via 1x ATR(14) stop
  - TP / SL: +2% / -1% equity (per-trade, not per-day)
  - News blackouts: NOT modeled in backtest (live system handles)

Output:
  - Per-strategy: Sharpe, max DD, win rate, profit factor, n trades
  - Joint portfolio: equity curve, Sharpe, drawdown
  - Cross-strategy correlation (the diversification thesis)
  - FTMO PASS/FAIL on the JOINT equity curve

Usage:
    uv run python scripts/run_carry_portfolio_backtest.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UTC = timezone.utc
D1 = 16408
INITIAL_CAPITAL = 100_000

# Trade schedule
ENTRY_INTERVAL_BARS = 20      # try to enter every 20 D1 bars when flat
MAX_HOLD_BARS = 60
TP_EQUITY_PCT = 0.02
SL_EQUITY_PCT = 0.01
PER_LEG_RISK_PCT = 0.005      # 0.5%
ATR_PERIOD = 14
ATR_STOP_MULT = 1.0
REGIME_MA = 252               # 252d MA proxy for regime detection

# Symbol specs (approximate broker values).
SPECS = {
    # symbol: (point, tick_value_per_lot_per_point)
    "AUDJPY": (0.001, 0.667),    # ~$0.667 per pip per lot at JPY ~150
    "NZDJPY": (0.001, 0.667),
    "USDMXN": (0.00001, 0.0575),
    "USDZAR": (0.00001, 0.0599),
}

# Carry income, USD per lot per day, broker-side. Same direction as the
# strategy (long-leg uses swap_long, short-leg uses swap_short).
# From probe_jpy_swap_rates.py + probe_exotic_swap_rates.py (2026-05-19).
# IMPORTANT: these are CURRENT rates. Historically, the AUDJPY swap was
# ~0 in 2020 (rate convergence). Using these as a constant OVERSTATES
# pre-2023 carry, but the regime gate would have kept us OUT during
# convergence periods anyway -- so the net effect partially cancels.
CARRY_USD_PER_LOT_PER_DAY = {
    ("AUDJPY", +1): +3.52,    # long AUDJPY earns
    ("NZDJPY", -1): +1.20,    # short NZDJPY earns (broker swap_short estimate)
    ("USDMXN", +1): +24.87,   # long USDMXN earns
    ("USDZAR", -1): +5.60,    # short USDZAR earns
}
INCLUDE_CARRY_INCOME = True   # set False for spot-only baseline


@dataclass
class Trade:
    symbol_long: str
    symbol_short: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    pnl_pct: float
    bars_held: int
    exit_reason: str


@dataclass
class StratResult:
    name: str
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)


def load_closes(symbols: list[str], years: int = 12) -> pd.DataFrame:
    from data.cache import ParquetCache
    cache = ParquetCache()
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    cols = {}
    for sym in symbols:
        df = cache.read(sym, D1, start, end)
        if df is None or df.empty:
            raise SystemExit(f"missing cached data for {sym}")
        cols[sym] = df[["open", "high", "low", "close"]]
    # Align on common dates
    closes = pd.concat({s: cols[s]["close"] for s in symbols}, axis=1, join="inner")
    highs = pd.concat({s: cols[s]["high"] for s in symbols}, axis=1, join="inner")
    lows = pd.concat({s: cols[s]["low"] for s in symbols}, axis=1, join="inner")
    common_idx = closes.index
    return closes.loc[common_idx], highs.loc[common_idx], lows.loc[common_idx]


def compute_atr(close: pd.Series, high: pd.Series, low: pd.Series,
                period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def per_leg_lot_size(equity: float, atr: float, point: float,
                      tick_value: float) -> float:
    """Lot size such that 1x ATR stop loses ~PER_LEG_RISK_PCT of equity."""
    if atr <= 0 or tick_value <= 0:
        return 0.0
    risk_amount = equity * PER_LEG_RISK_PCT
    loss_per_lot = (atr / point) * tick_value
    if loss_per_lot <= 0:
        return 0.0
    return risk_amount / loss_per_lot


def leg_pnl(entry_price: float, exit_price: float, direction: int,
            lots: float, point: float, tick_value: float) -> float:
    return direction * (exit_price - entry_price) / point * tick_value * lots


def simulate_strategy(name: str, sym_long: str, sym_short: str,
                       closes: pd.DataFrame, highs: pd.DataFrame,
                       lows: pd.DataFrame) -> StratResult:
    """Simulate one regime-gated carry strategy on aligned price data.
    Returns an equity curve indexed by common bar dates."""
    dates = closes.index
    n = len(dates)

    # ATR per leg
    atr_long = compute_atr(closes[sym_long], highs[sym_long], lows[sym_long],
                            ATR_PERIOD)
    atr_short = compute_atr(closes[sym_short], highs[sym_short], lows[sym_short],
                             ATR_PERIOD)
    # Regime proxy: 252d moving average of the long-leg symbol
    ma252 = closes[sym_long].rolling(REGIME_MA).mean()

    equity = INITIAL_CAPITAL
    eq_curve = pd.Series(index=dates, dtype=float)
    trades: list[Trade] = []

    in_pos = False
    pos_entry_idx = 0
    pos_entry_equity = 0.0
    pos_entry_price_long = 0.0
    pos_entry_price_short = 0.0
    pos_lots_long = 0.0
    pos_lots_short = 0.0
    last_entry_idx = -ENTRY_INTERVAL_BARS

    pl_long = SPECS[sym_long]
    pl_short = SPECS[sym_short]

    for i in range(n):
        ts = dates[i]
        # Warm-up windows
        if pd.isna(atr_long.iloc[i]) or pd.isna(atr_short.iloc[i]) or pd.isna(ma252.iloc[i]):
            eq_curve.iloc[i] = equity
            continue

        # Mark-to-market the open position
        if in_pos:
            mtm_long = leg_pnl(pos_entry_price_long, closes[sym_long].iloc[i],
                                +1, pos_lots_long, pl_long[0], pl_long[1])
            mtm_short = leg_pnl(pos_entry_price_short, closes[sym_short].iloc[i],
                                 -1, pos_lots_short, pl_short[0], pl_short[1])
            # Carry income: each day held earns swap_long * lots_long
            # for the long leg and swap_short_equivalent * lots_short for
            # the short leg (the broker pays you for being short).
            carry_income = 0.0
            if INCLUDE_CARRY_INCOME:
                bars_so_far = i - pos_entry_idx
                clong = CARRY_USD_PER_LOT_PER_DAY.get((sym_long, +1), 0.0)
                cshort = CARRY_USD_PER_LOT_PER_DAY.get((sym_short, -1), 0.0)
                carry_income = bars_so_far * (clong * pos_lots_long +
                                                cshort * pos_lots_short)
            cur_equity = pos_entry_equity + mtm_long + mtm_short + carry_income
            pnl_pct = (cur_equity - pos_entry_equity) / pos_entry_equity
            bars_held = i - pos_entry_idx
            exit_reason = None
            if pnl_pct >= TP_EQUITY_PCT:
                exit_reason = "take_profit"
            elif pnl_pct <= -SL_EQUITY_PCT:
                exit_reason = "stop_loss"
            elif bars_held >= MAX_HOLD_BARS:
                exit_reason = "time_stop"
            elif closes[sym_long].iloc[i] < ma252.iloc[i] * 0.98:
                # regime throttle: long-symbol fell well below the MA
                exit_reason = "regime_throttle"
            if exit_reason is not None:
                equity = cur_equity
                trades.append(Trade(
                    symbol_long=sym_long, symbol_short=sym_short,
                    entry_date=dates[pos_entry_idx], exit_date=ts,
                    pnl_pct=pnl_pct, bars_held=bars_held,
                    exit_reason=exit_reason,
                ))
                in_pos = False
            else:
                equity = cur_equity   # carry mtm into equity curve
        eq_curve.iloc[i] = equity

        # Entry logic (only when flat)
        if not in_pos and (i - last_entry_idx) >= ENTRY_INTERVAL_BARS:
            # Regime gate: long-symbol must be above its 252d MA
            if closes[sym_long].iloc[i] <= ma252.iloc[i]:
                continue
            lots_long = per_leg_lot_size(equity, atr_long.iloc[i],
                                          pl_long[0], pl_long[1])
            lots_short = per_leg_lot_size(equity, atr_short.iloc[i],
                                           pl_short[0], pl_short[1])
            if lots_long <= 0 or lots_short <= 0:
                continue
            pos_entry_idx = i
            pos_entry_equity = equity
            pos_entry_price_long = closes[sym_long].iloc[i]
            pos_entry_price_short = closes[sym_short].iloc[i]
            pos_lots_long = lots_long
            pos_lots_short = lots_short
            in_pos = True
            last_entry_idx = i

    # If still in position at end, mark-to-market exit
    if in_pos:
        i = n - 1
        mtm_long = leg_pnl(pos_entry_price_long, closes[sym_long].iloc[i],
                            +1, pos_lots_long, pl_long[0], pl_long[1])
        mtm_short = leg_pnl(pos_entry_price_short, closes[sym_short].iloc[i],
                             -1, pos_lots_short, pl_short[0], pl_short[1])
        carry_income = 0.0
        if INCLUDE_CARRY_INCOME:
            bars_so_far = i - pos_entry_idx
            clong = CARRY_USD_PER_LOT_PER_DAY.get((sym_long, +1), 0.0)
            cshort = CARRY_USD_PER_LOT_PER_DAY.get((sym_short, -1), 0.0)
            carry_income = bars_so_far * (clong * pos_lots_long +
                                            cshort * pos_lots_short)
        equity = pos_entry_equity + mtm_long + mtm_short + carry_income
        eq_curve.iloc[i] = equity
        trades.append(Trade(
            symbol_long=sym_long, symbol_short=sym_short,
            entry_date=dates[pos_entry_idx], exit_date=dates[i],
            pnl_pct=(equity - pos_entry_equity) / pos_entry_equity,
            bars_held=i - pos_entry_idx, exit_reason="end_of_sample",
        ))

    eq_curve = eq_curve.ffill().fillna(INITIAL_CAPITAL)
    return StratResult(name=name, equity_curve=eq_curve, trades=trades)


def metrics(eq: pd.Series, name: str) -> dict:
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return {"name": name}
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    sortino_dn = rets[rets < 0]
    sortino = float(rets.mean() / sortino_dn.std() * np.sqrt(252)) if len(sortino_dn) > 1 and sortino_dn.std() > 0 else 0.0
    rmax = eq.cummax()
    max_dd = float(((eq - rmax) / rmax).min())
    n_days = max((eq.index[-1] - eq.index[0]).days, 1)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (365.0 / n_days) - 1.0
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        "name": name,
        "total_return": eq.iloc[-1] / eq.iloc[0] - 1,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_dd": max_dd,
        "ann_vol": float(rets.std()) * np.sqrt(252),
    }


def trade_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "pf": 0.0}
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct < 0]
    win_pnl = sum(t.pnl_pct for t in wins)
    loss_pnl = abs(sum(t.pnl_pct for t in losses))
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades),
        "pf": (win_pnl / loss_pnl) if loss_pnl > 0 else 0.0,
        "exit_reasons": pd.Series([t.exit_reason for t in trades]).value_counts().to_dict(),
    }


def main() -> None:
    print("Joint carry-portfolio backtest: JPY (AUDJPY/NZDJPY) + EM (USDMXN/USDZAR)")
    print("=" * 78)
    print(f"Mode: {'INCLUDES CARRY INCOME' if INCLUDE_CARRY_INCOME else 'spot-only (no carry)'}")
    print("Regime gate: 252d MA proxy (live system uses real-time broker swap).")
    print("Sizing: 0.5%/leg risk, 60d max hold, +2%/-1% equity TP/SL.")
    print()

    symbols = ["AUDJPY", "NZDJPY", "USDMXN", "USDZAR"]
    closes, highs, lows = load_closes(symbols, years=12)
    print(f"Sample: {closes.index[0].date()} -- {closes.index[-1].date()}  "
          f"({len(closes)} bars)\n")

    jpy = simulate_strategy("JPY-carry", "AUDJPY", "NZDJPY", closes, highs, lows)
    em  = simulate_strategy("EM-carry",  "USDMXN", "USDZAR", closes, highs, lows)

    # Joint equity curve: equal-capital allocation, each starting at 50k,
    # combined into a 100k portfolio equity curve.
    half_jpy = INITIAL_CAPITAL / 2 + (jpy.equity_curve - INITIAL_CAPITAL) / 2
    half_em  = INITIAL_CAPITAL / 2 + (em.equity_curve  - INITIAL_CAPITAL) / 2
    joint = half_jpy + half_em

    # Per-strategy metrics
    for r in [jpy, em]:
        m = metrics(r.equity_curve, r.name)
        ts = trade_stats(r.trades)
        print(f"--- {r.name} ---")
        print(f"  Period:        {r.equity_curve.index[0].date()} - "
              f"{r.equity_curve.index[-1].date()}")
        print(f"  Total return:  {m['total_return']:+.2%}")
        print(f"  CAGR:          {m['cagr']:+.2%}")
        print(f"  Sharpe:        {m['sharpe']:+.2f}")
        print(f"  Sortino:       {m['sortino']:+.2f}")
        print(f"  Calmar:        {m['calmar']:+.2f}")
        print(f"  Max DD:        {m['max_dd']:.2%}")
        print(f"  Ann vol:       {m['ann_vol']:.2%}")
        print(f"  Trades:        {ts['n']}")
        print(f"  Win rate:      {ts['win_rate']:.1%}")
        print(f"  Profit factor: {ts['pf']:.2f}")
        if ts.get("exit_reasons"):
            print(f"  Exit reasons:  {ts['exit_reasons']}")
        print()

    # Joint portfolio metrics
    jm = metrics(joint, "Joint (50/50)")
    print(f"--- {jm['name']} ---")
    print(f"  Total return:  {jm['total_return']:+.2%}")
    print(f"  CAGR:          {jm['cagr']:+.2%}")
    print(f"  Sharpe:        {jm['sharpe']:+.2f}")
    print(f"  Sortino:       {jm['sortino']:+.2f}")
    print(f"  Calmar:        {jm['calmar']:+.2f}")
    print(f"  Max DD:        {jm['max_dd']:.2%}")
    print(f"  Ann vol:       {jm['ann_vol']:.2%}")
    print()

    # Cross-strategy correlation
    jpy_rets = jpy.equity_curve.pct_change().dropna()
    em_rets  = em.equity_curve.pct_change().dropna()
    common = jpy_rets.index.intersection(em_rets.index)
    rho = float(jpy_rets.loc[common].corr(em_rets.loc[common]))
    print(f"--- Cross-strategy diagnostics ---")
    print(f"  Correlation(JPY, EM):     {rho:+.3f}")
    print(f"  (deploy-both PASSES if rho < +0.30)")
    print()

    # Rolling 6m correlation
    rolling = jpy_rets.loc[common].rolling(126).corr(em_rets.loc[common]).dropna()
    if len(rolling) > 0:
        print(f"  Rolling 6m rho: mean={rolling.mean():+.3f}  "
              f"max={rolling.max():+.3f}  min={rolling.min():+.3f}")
        print(f"  (no individual 6m window > +0.50? "
              f"{'YES' if rolling.max() < 0.5 else 'NO'})")
    print()

    # FTMO simulator on the JOINT equity curve
    try:
        from backtest.ftmo_sim import FTMOSimulator
        from risk.ftmo import FTMOAccountType
        sim = FTMOSimulator(
            account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
            initial_capital=INITIAL_CAPITAL, opening_balance=INITIAL_CAPITAL,
        )
        rep = sim.run(joint)
        status = "PASS" if rep.passed else "FAIL"
        print(f"--- FTMO simulator (joint equity) ---")
        print(f"  Status: [{status}]")
        print(f"  Daily-loss breaches: {rep.ftmo_daily_line_breach_count}")
        print(f"  Max-loss breaches:   {rep.ftmo_max_line_breach_count}")
        print(f"  Min daily distance:  ${rep.min_daily_distance:,.0f}")
    except Exception as e:
        print(f"  FTMO sim error: {e}")

    # Save curves for the portfolio harness
    out_dir = Path("reports/carry_portfolio")
    out_dir.mkdir(parents=True, exist_ok=True)
    jpy.equity_curve.to_csv(out_dir / "jpy_equity.csv", header=True)
    em.equity_curve.to_csv(out_dir / "em_equity.csv", header=True)
    joint.to_csv(out_dir / "joint_equity.csv", header=True)
    print(f"\n  Equity curves saved to {out_dir}/")


if __name__ == "__main__":
    main()
