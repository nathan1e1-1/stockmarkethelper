import os
import sys

import pytest
import yaml

from autotrader.config import load_config


def write_config(tmp_path, *, paper=True, risk_overrides=None, exit_overrides=None, profile="initial"):
    risk = {
        "profile": profile,
        "paper_capital": 100000.0,
        "max_position_pct": 0.0025,
        "max_gross_exposure_pct": 0.0025,
        "max_positions": 1,
        "max_entries_per_session": 1,
        "max_snapshot_age_seconds": 120,
        "kill_switch_pct": 0.10,
        "daily_loss_pct": 0.05,
    }
    if profile == "multi-entry":
        risk.update({
            "max_position_pct": 0.05,
            "max_gross_exposure_pct": 0.05,
            "max_positions": 5,
            "max_entries_per_session": sys.maxsize,
            "max_snapshot_age_seconds": 120,
            "risk_per_position_pct": 0.01,
            "max_daily_risk_pct": 0.05,
            "kill_switch_pct": 0.25,
        })
    risk.update(risk_overrides or {})
    exits = {
        "stop_loss_pct": 0.02 if profile == "initial" else 0.05,
        "take_profit_pct": 0.03 if profile == "initial" else 0.05,
        "flatten_at_close": True,
        "flatten_time": "15:55",
    }
    exits.update(exit_overrides or {})
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "alpaca": {"paper": paper},
                "ollama": {"base_url": "http://localhost:11434", "model": "llama3.2"},
                "risk": risk,
                "universe": {"size": 20, "min_price": 5.0, "min_volume": 500000},
                "loop": {"scan_interval_seconds": 60},
                "scoring": {"entry_threshold": 0.5, "weights": {"momentum": 0.6, "sentiment": 0.4}},
                "exits": exits,
            }
        )
    )
    return path


def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
    cfg_path = write_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")
    cfg = load_config(str(cfg_path))
    assert cfg.alpaca_api_key == "pk_test"
    assert cfg.alpaca_paper is True
    assert cfg.max_position_pct == 0.0025
    assert cfg.entry_threshold == 0.5
    assert cfg.stop_loss_pct == 0.02
    assert cfg.take_profit_pct == 0.03
    assert cfg.flatten_at_close is True
    assert cfg.flatten_time == "15:55"


def test_load_config_requires_api_key(tmp_path, monkeypatch):
    cfg_path = write_config(tmp_path)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr("autotrader.config.load_dotenv", lambda: None)
    with pytest.raises(ValueError):
        load_config(str(cfg_path))


@pytest.mark.parametrize("paper", [False, "true", 1, None])
def test_load_config_rejects_every_non_paper_value(tmp_path, monkeypatch, paper):
    path = write_config(tmp_path, paper=paper)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError, match="paper trading"):
        load_config(str(path))


def test_load_config_uses_approved_initial_paper_profile(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    cfg = load_config(str(path))

    assert cfg.max_position_pct == 0.0025
    assert cfg.max_gross_exposure_pct == 0.0025
    assert cfg.max_positions == 1
    assert cfg.max_entries_per_session == 1
    assert cfg.max_snapshot_age_seconds == 120


def test_load_config_rejects_unapproved_risk_profile(tmp_path, monkeypatch):
    path = write_config(tmp_path, risk_overrides={"profile": "promoted"})
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError, match="risk.profile"):
        load_config(str(path))


@pytest.mark.parametrize(
    "risk_overrides",
    [
        {"max_position_pct": 0.5},
        {"max_gross_exposure_pct": 0.5},
        {"max_positions": 10},
        {"max_entries_per_session": 10},
        {"max_snapshot_age_seconds": 1000},
    ],
)
def test_load_config_rejects_initial_profile_overrides(tmp_path, monkeypatch, risk_overrides):
    path = write_config(tmp_path, risk_overrides=risk_overrides)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError, match="initial paper profile"):
        load_config(str(path))


@pytest.mark.parametrize(
    ("risk_overrides", "field"),
    [
        ({"max_position_pct": 0}, "max_position_pct"),
        ({"max_gross_exposure_pct": 0}, "max_gross_exposure_pct"),
        ({"max_positions": 0}, "max_positions"),
        ({"max_entries_per_session": 0}, "max_entries_per_session"),
        ({"max_snapshot_age_seconds": 0}, "max_snapshot_age_seconds"),
        ({"max_gross_exposure_pct": 0.0024}, "max_gross_exposure_pct"),
    ],
)
def test_load_config_rejects_invalid_safety_caps(tmp_path, monkeypatch, risk_overrides, field):
    path = write_config(tmp_path, risk_overrides=risk_overrides)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError, match=field):
        load_config(str(path))


def test_load_config_accepts_multi_entry_profile(tmp_path, monkeypatch):
    path = write_config(tmp_path, profile="multi-entry")
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    cfg = load_config(str(path))

    assert cfg.max_positions == 5
    assert cfg.risk_per_position_pct == 0.01
    assert cfg.max_daily_risk_pct == 0.05
    assert cfg.max_entries_per_session == sys.maxsize
    assert cfg.kill_switch_pct == 0.25
    assert cfg.stop_loss_pct == 0.05
    assert cfg.take_profit_pct == 0.05


@pytest.mark.parametrize(
    "risk_overrides",
    [
        {"max_positions": 4},
        {"max_entries_per_session": 10},
        {"max_snapshot_age_seconds": 1000},
        {"risk_per_position_pct": 0.02},
        {"risk_per_position_pct": 0.01, "max_daily_risk_pct": 0.05, "max_positions": 4},
        {"kill_switch_pct": 0.10},
    ],
)
def test_load_config_rejects_invalid_multi_entry_profile(tmp_path, monkeypatch, risk_overrides):
    path = write_config(tmp_path, profile="multi-entry", risk_overrides=risk_overrides)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError):
        load_config(str(path))


def test_load_config_multi_entry_requires_single_shared_stop_distance(tmp_path, monkeypatch):
    path = write_config(
        tmp_path,
        profile="multi-entry",
        exit_overrides={"stop_loss_pct": 0.06},
    )
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError):
        load_config(str(path))


def test_live_config_yaml_uses_an_approved_profile():
    from pathlib import Path

    repo_config = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    assert repo_config.exists(), "repo config.yaml must exist for the live engine"
    with open(repo_config) as fh:
        raw = yaml.safe_load(fh)
    assert raw["risk"]["profile"] in {"initial", "multi-entry"}
