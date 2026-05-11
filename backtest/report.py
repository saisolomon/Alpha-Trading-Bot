"""
Backtest report generator.

Produces:
  - equity_curve.png  — equity curve with FTMO daily/max lines overlaid
  - drawdown.png      — underwater equity curve
  - monthly_returns.png — heatmap of monthly returns
  - rolling_sharpe.png  — 12-month rolling Sharpe
  - trades.csv        — trade-by-trade log
  - metrics.json      — full metric set

Usage:
    report = BacktestReport(result, ftmo_report, metrics, output_dir)
    report.generate()
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestResult, Trade
from backtest.ftmo_sim import FTMOSimReport
from backtest.metrics import PerformanceMetrics

log = logging.getLogger(__name__)


class BacktestReport:
    """Generates all report artifacts for one completed backtest run.

    Parameters
    ----------
    result:
        BacktestResult from engine.run().
    ftmo_report:
        FTMOSimReport from FTMOSimulator.run(). May be None if FTMO sim was skipped.
    metrics:
        PerformanceMetrics from compute().
    output_dir:
        Directory where all artifacts are written.
    """

    def __init__(
        self,
        result: BacktestResult,
        ftmo_report: FTMOSimReport | None,
        metrics: PerformanceMetrics,
        output_dir: Path,
    ) -> None:
        self._result = result
        self._ftmo = ftmo_report
        self._metrics = metrics
        self._out = output_dir
        self._out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def generate(self, plots: bool = True) -> dict[str, Path]:
        """Write all artifacts. Returns mapping of artifact name → path.

        Set plots=False to skip matplotlib (useful in CI / headless envs).
        """
        artifacts: dict[str, Path] = {}

        artifacts["trades_csv"] = self._write_trades_csv()
        artifacts["metrics_json"] = self._write_metrics_json()

        if plots:
            try:
                artifacts.update(self._write_plots())
            except Exception as exc:
                log.warning("report.plot_failed", extra={"error": str(exc)})

        log.info(
            "report.generated",
            extra={
                "strategy": self._result.strategy_name,
                "output_dir": str(self._out),
                "artifacts": list(artifacts.keys()),
            },
        )
        return artifacts

    # ------------------------------------------------------------------ #
    # CSV / JSON                                                           #
    # ------------------------------------------------------------------ #

    def _write_trades_csv(self) -> Path:
        path = self._out / "trades.csv"
        trades = self._result.trades
        fieldnames = [
            "entry_time", "exit_time", "symbol", "direction", "size",
            "entry_price", "exit_price", "gross_pnl", "commission", "net_pnl",
            "exit_reason", "entry_bar", "exit_bar", "signal_comment",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for t in trades:
                writer.writerow({
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "symbol": t.symbol,
                    "direction": t.direction.name,
                    "size": t.size,
                    "entry_price": round(t.entry_price, 6),
                    "exit_price": round(t.exit_price, 6),
                    "gross_pnl": round(t.gross_pnl, 4),
                    "commission": round(t.commission, 4),
                    "net_pnl": round(t.net_pnl, 4),
                    "exit_reason": t.exit_reason,
                    "entry_bar": t.entry_bar,
                    "exit_bar": t.exit_bar,
                    "signal_comment": t.signal_comment,
                })
        return path

    def _write_metrics_json(self) -> Path:
        path = self._out / "metrics.json"
        m = self._metrics
        ftmo = self._ftmo

        data: dict = {
            "strategy": self._result.strategy_name,
            "symbol": self._result.symbol,
            "initial_capital": self._result.initial_capital,
            "returns": {
                "cagr": round(m.cagr, 6),
                "total_return": round(m.total_return, 6),
            },
            "risk": {
                "annualized_volatility": round(m.annualized_volatility, 6),
                "max_drawdown": round(m.max_drawdown, 6),
                "max_drawdown_duration_bars": m.max_drawdown_duration_bars,
                "var_95": round(m.var_95, 6),
                "cvar_95": round(m.cvar_95, 6),
            },
            "risk_adjusted": {
                "sharpe": round(m.sharpe, 4),
                "sortino": round(m.sortino, 4),
                "calmar": round(m.calmar, 4),
                "information_ratio": round(m.information_ratio, 4),
            },
            "trading": {
                "total_trades": m.total_trades,
                "win_rate": round(m.win_rate, 4),
                "profit_factor": round(m.profit_factor, 4) if m.profit_factor != float("inf") else None,
                "avg_win": round(m.avg_win, 4),
                "avg_loss": round(m.avg_loss, 4),
                "avg_win_loss_ratio": round(m.avg_win_loss_ratio, 4) if m.avg_win_loss_ratio != float("inf") else None,
                "avg_holding_bars": round(m.avg_holding_bars, 2),
            },
            "stability": {
                "return_autocorrelation": round(m.return_autocorrelation, 4),
            },
        }

        if ftmo is not None:
            data["ftmo"] = {
                "passed": ftmo.passed,
                "ftmo_daily_breach_count": ftmo.ftmo_daily_line_breach_count,
                "ftmo_max_breach_count": ftmo.ftmo_max_line_breach_count,
                "internal_daily_kill_count": ftmo.internal_daily_kill_count,
                "internal_max_kill_count": ftmo.internal_max_kill_count,
                "min_daily_distance": round(ftmo.min_daily_distance, 4),
                "min_max_distance": round(ftmo.min_max_distance, 4),
                "peak_best_day_ratio": round(ftmo.peak_best_day_ratio, 4),
            }

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------ #
    # Plots                                                                #
    # ------------------------------------------------------------------ #

    def _write_plots(self) -> dict[str, Path]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick

        artifacts: dict[str, Path] = {}
        eq = self._result.equity_curve
        initial = self._result.initial_capital

        # ---- Equity curve ----
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(eq.index, eq.values, linewidth=1.2, color="#2196F3", label="Equity")

        if self._ftmo is not None:
            state = self._ftmo.final_state
            daily_lim = state.ftmo_daily_limit
            max_lim = state.ftmo_max_loss_limit
            ax.axhline(daily_lim, color="#FF5252", linestyle="--", linewidth=0.8,
                       label=f"FTMO Daily Limit ({daily_lim:,.0f})")
            ax.axhline(max_lim, color="#B71C1C", linestyle="--", linewidth=0.8,
                       label=f"FTMO Max Loss ({max_lim:,.0f})")

        ax.set_title(f"{self._result.strategy_name} — {self._result.symbol} Equity Curve")
        ax.set_ylabel("Equity")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        p = self._out / "equity_curve.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        artifacts["equity_curve_png"] = p

        # ---- Drawdown ----
        peak = eq.expanding().max()
        dd = (eq - peak) / peak * 100
        fig, ax = plt.subplots(figsize=(12, 3))
        ax.fill_between(dd.index, dd.values, 0, color="#EF9A9A", alpha=0.8)
        ax.set_title("Drawdown (%)")
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=1))
        ax.grid(alpha=0.3)
        fig.tight_layout()
        p = self._out / "drawdown.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        artifacts["drawdown_png"] = p

        # ---- Monthly returns heatmap ----
        monthly = self._metrics.monthly_returns
        if len(monthly) >= 2:
            try:
                monthly_df = monthly.to_frame("return")
                monthly_df.index = pd.PeriodIndex(monthly_df.index, freq="M")
                monthly_df["year"] = monthly_df.index.year
                monthly_df["month"] = monthly_df.index.month
                pivot = monthly_df.pivot(index="year", columns="month", values="return") * 100

                fig, ax = plt.subplots(figsize=(12, max(3, len(pivot))))
                im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=-5, vmax=5)
                ax.set_xticks(range(12))
                ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], fontsize=8)
                ax.set_yticks(range(len(pivot)))
                ax.set_yticklabels(pivot.index.tolist(), fontsize=8)
                ax.set_title("Monthly Returns (%)")
                plt.colorbar(im, ax=ax, label="%")
                fig.tight_layout()
                p = self._out / "monthly_returns.png"
                fig.savefig(p, dpi=150)
                plt.close(fig)
                artifacts["monthly_returns_png"] = p
            except Exception:
                pass  # skip if monthly data is malformed

        # ---- Rolling Sharpe ----
        rs = self._metrics.rolling_sharpe_12m
        if len(rs) >= 2:
            fig, ax = plt.subplots(figsize=(12, 3))
            ax.plot(rs.index, rs.values, linewidth=1.0, color="#4CAF50")
            ax.axhline(0, color="black", linewidth=0.5)
            ax.axhline(1, color="#2196F3", linestyle="--", linewidth=0.8, label="Sharpe=1")
            ax.set_title("Rolling Sharpe")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            fig.tight_layout()
            p = self._out / "rolling_sharpe.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            artifacts["rolling_sharpe_png"] = p

        return artifacts
