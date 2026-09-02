import os

import pytest
import yaml

from autotrader.config import load_config


def write_config(tmp_path, *, paper=True, risk_overrides=None):
    risk = {
        "profile": "initial",
        "paper_capital": 100000.0,
        "max_position_pct": 0.0025,
        "max_gross_exposure_pct": 0.0025,
        "max_positions": 1,
        "max_entries_per_session": 1,
        "max_snapshot_age_seconds": 120,
        "kill_switch_pct": 0.10,
        "daily_loss_pct": 0.05,
    }
    risk.update(risk_overrides or {})
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
                "exits": {"stop_loss_pct": 0.02, "take_profit_pct": 0.03, "flatten_at_close": True, "flatten_time": "15:55"},
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
