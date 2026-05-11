"""
Config layer — type-safe, pydantic-validated, env-var-aware.

Loading order:
  1. configs/default.yaml  (checked in, safe defaults)
  2. Any environment-specific YAML (optional, overlaid)
  3. Environment variables (highest priority, override YAML)

Usage:
    from utils.config import load_config
    cfg = load_config()
    print(cfg.risk.internal_daily_kill_pct)
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class MT5Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MT5_", extra="ignore")

    login: int = Field(..., description="MT5 account number")
    password: str = Field(..., description="MT5 account password")
    server: str = Field(..., description="MT5 broker server name")
    path: str = Field(
        default="",
        description="Full path to terminal64.exe. Empty = auto-detect.",
    )


class FTMOConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FTMO_", extra="ignore")

    account_type: Literal[
        "CHALLENGE_1STEP",
        "CHALLENGE_2STEP_PHASE1",
        "CHALLENGE_2STEP_PHASE2",
        "FUNDED_STANDARD",
        "FUNDED_SWING",
        "FUNDED_REWARDS_1STEP",
    ] = Field(default="CHALLENGE_2STEP_PHASE1")

    initial_capital: float = Field(
        default=25_000.0,
        gt=0,
        description="Starting balance when the Challenge/account was opened.",
    )


class RiskConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # ---- FTMO outer limits (from CLAUDE.md §3) ----
    ftmo_daily_loss_pct_2step: float = Field(default=0.05)   # 5% of initial capital
    ftmo_daily_loss_pct_1step: float = Field(default=0.03)   # 3% of initial capital
    ftmo_max_loss_pct: float = Field(default=0.10)           # 10% of initial capital

    # ---- Internal limits (bot's own operating box) ----
    internal_daily_kill_pct_2step: float = Field(default=0.03)  # 3% → 60% of FTMO 5%
    internal_daily_kill_pct_1step: float = Field(default=0.02)  # 2% → 66% of FTMO 3%
    internal_max_kill_pct: float = Field(default=0.07)           # 7% → 70% of FTMO 10%

    # ---- Per-trade limits ----
    per_trade_risk_pct_min: float = Field(default=0.005)   # 0.5%
    per_trade_risk_pct_max: float = Field(default=0.010)   # 1.0% hard cap
    per_trade_risk_pct_default: float = Field(default=0.005)

    # ---- Portfolio-level limits ----
    aggregate_open_risk_pct: float = Field(default=0.02)    # 2% across all open stops
    correlated_cluster_cap_pct: float = Field(default=0.03) # 3% on any correlated cluster
    correlation_window_days: int = Field(default=60)
    correlation_threshold: float = Field(default=0.60)

    # ---- Best Day governor (1-Step only) ----
    best_day_throttle_ratio: float = Field(default=0.40)    # throttle at 40% (FTMO limit 50%)

    # ---- Equity watcher ----
    equity_poll_interval_ms: int = Field(default=250)       # sub-second polling
    ftmo_imminent_buffer_pct: float = Field(default=0.005)  # 0.5% warning zone

    # ---- Headroom check safety buffer ----
    headroom_safety_buffer_pct: float = Field(default=0.01) # reject if within 1% of FTMO line

    # ---- Weekend / news ----
    flatten_before_weekend: bool = Field(default=True)
    friday_flatten_hour_prague: int = Field(default=21)     # 21:00 Europe/Prague
    news_blackout_minutes: int = Field(default=2)           # ±2 min around events

    @model_validator(mode="after")
    def per_trade_range_valid(self) -> "RiskConfig":
        if self.per_trade_risk_pct_default > self.per_trade_risk_pct_max:
            raise ValueError("per_trade_risk_pct_default must not exceed per_trade_risk_pct_max")
        return self

    @field_validator("equity_poll_interval_ms")
    @classmethod
    def poll_interval_reasonable(cls, v: int) -> int:
        if v < 50 or v > 5000:
            raise ValueError("equity_poll_interval_ms must be 50–5000 ms")
        return v


class BacktestConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Walk-forward defaults
    walk_forward_is_months: int = Field(default=12, description="In-sample window (months)")
    walk_forward_oos_months: int = Field(default=3, description="Out-of-sample window (months)")
    walk_forward_step_months: int = Field(default=1, description="Roll step (months)")

    # Cost model defaults
    slippage_multiplier: float = Field(
        default=0.5,
        description="Slippage as a fraction of the average spread.",
    )
    commission_per_lot: float = Field(
        default=7.0,
        description="Commission in account currency per round-trip lot.",
    )

    # Reporting
    output_dir: str = Field(default="backtest/output")
    random_seed: int = Field(default=42)


class AppConfig(BaseSettings):
    """Top-level configuration container."""

    model_config = SettingsConfigDict(extra="ignore")

    env: Literal["dev", "paper", "live"] = Field(default="dev")

    mt5: MT5Config = Field(default_factory=MT5Config)  # type: ignore[call-arg]
    ftmo: FTMOConfig = Field(default_factory=FTMOConfig)  # type: ignore[call-arg]
    risk: RiskConfig = Field(default_factory=RiskConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)


# ---------------------------------------------------------------------------
# YAML loader with ${ENV_VAR} substitution
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(text: str) -> str:
    """Replace ${VAR} placeholders in YAML text with os.environ values."""

    def replacer(match: re.Match[str]) -> str:
        var = match.group(1)
        val = os.environ.get(var, "")
        return val

    return _ENV_VAR_RE.sub(replacer, text)


def _load_yaml(path: Path) -> dict:  # type: ignore[type-arg]
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(_substitute_env_vars(text)) or {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(
    config_dir: Path | None = None,
    env_file: Path | None = None,
) -> AppConfig:
    """Load and return the fully-validated AppConfig.

    1. Loads configs/default.yaml.
    2. Optionally overlays configs/<env>.yaml based on the ENV env var.
    3. Environment variables override everything (pydantic-settings behaviour).
    """
    config_dir = config_dir or (_PROJECT_ROOT / "configs")
    env_file = env_file or (_PROJECT_ROOT / ".env")

    # Load .env so env vars are available for ${} substitution and pydantic-settings
    if env_file.exists():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)  # don't clobber already-set vars

    defaults = _load_yaml(config_dir / "default.yaml")

    env_name = os.environ.get("ENV", "dev")
    env_overrides = _load_yaml(config_dir / f"{env_name}.yaml")

    # Deep merge (env_overrides wins)
    merged = _deep_merge(defaults, env_overrides)

    # Build sub-models from merged YAML, then let pydantic-settings pick up
    # env vars on top (env vars win over everything).
    return AppConfig(
        env=env_name,  # type: ignore[arg-type]
        mt5=MT5Config(**merged.get("mt5", {})),
        ftmo=FTMOConfig(**merged.get("ftmo", {})),
        risk=RiskConfig(**merged.get("risk", {})),
        backtest=BacktestConfig(**merged.get("backtest", {})),
    )


def _deep_merge(base: dict, override: dict) -> dict:  # type: ignore[type-arg]
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
