"""
Unit tests for utils/config.py — no MT5 connection required.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from utils.config import (
    AppConfig,
    BacktestConfig,
    FTMOConfig,
    RiskConfig,
    _deep_merge,
    load_config,
)


# ---------------------------------------------------------------------------
# RiskConfig validators
# ---------------------------------------------------------------------------


def test_risk_config_defaults_valid() -> None:
    cfg = RiskConfig()
    assert cfg.per_trade_risk_pct_default <= cfg.per_trade_risk_pct_max
    assert cfg.internal_daily_kill_pct_2step < cfg.ftmo_daily_loss_pct_2step
    assert cfg.internal_max_kill_pct < cfg.ftmo_max_loss_pct


def test_risk_config_poll_interval_bounds() -> None:
    with pytest.raises(Exception):
        RiskConfig(equity_poll_interval_ms=10)   # too fast
    with pytest.raises(Exception):
        RiskConfig(equity_poll_interval_ms=9999) # too slow


def test_risk_config_per_trade_range_check() -> None:
    with pytest.raises(Exception):
        RiskConfig(per_trade_risk_pct_default=0.02, per_trade_risk_pct_max=0.01)


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_override() -> None:
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99}}
    result = _deep_merge(base, override)
    assert result["a"] == 1
    assert result["b"]["c"] == 99
    assert result["b"]["d"] == 3


def test_deep_merge_new_key() -> None:
    base = {"a": 1}
    override = {"b": 2}
    result = _deep_merge(base, override)
    assert result["a"] == 1
    assert result["b"] == 2


def test_deep_merge_non_dict_override() -> None:
    base = {"a": {"nested": 1}}
    override = {"a": 42}
    result = _deep_merge(base, override)
    assert result["a"] == 42


# ---------------------------------------------------------------------------
# load_config with a temp YAML
# ---------------------------------------------------------------------------


def test_load_config_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_LOGIN", "99999999")
    monkeypatch.setenv("MT5_PASSWORD", "test_pass")
    monkeypatch.setenv("MT5_SERVER", "TestBroker-Demo")
    monkeypatch.setenv("MT5_PATH", "")
    monkeypatch.setenv("FTMO_ACCOUNT_TYPE", "CHALLENGE_2STEP_PHASE1")
    monkeypatch.setenv("FTMO_INITIAL_CAPITAL", "25000.0")
    monkeypatch.setenv("ENV", "dev")

    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "default.yaml").write_text(
        yaml.dump(
            {
                "risk": {"equity_poll_interval_ms": 300},
                "backtest": {"random_seed": 7},
            }
        )
    )

    cfg = load_config(config_dir=cfg_dir, env_file=tmp_path / ".env")
    assert cfg.env == "dev"
    assert cfg.risk.equity_poll_interval_ms == 300
    assert cfg.backtest.random_seed == 7
    assert cfg.mt5.login == 99999999
    assert cfg.ftmo.account_type == "CHALLENGE_2STEP_PHASE1"
    assert cfg.ftmo.initial_capital == 25_000.0


def test_ftmo_account_type_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FTMO_ACCOUNT_TYPE", "INVALID_TYPE")
    with pytest.raises(Exception):
        FTMOConfig()
