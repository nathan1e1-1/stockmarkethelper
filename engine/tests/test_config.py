import os
from autotrader.config import load_config, Config


def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "alpaca:\n  paper: true\n"
        "ollama:\n  base_url: http://localhost:11434\n  model: llama3.2\n"
        "risk:\n  paper_capital: 100000.0\n  max_position_pct: 0.02\n"
        "  max_positions: 3\n  kill_switch_pct: 0.10\n  daily_loss_pct: 0.05\n"
        "universe:\n  size: 20\n  min_price: 5.0\n  min_volume: 500000\n"
        "loop:\n  scan_interval_seconds: 60\n"
        "scoring:\n  entry_threshold: 0.5\n  weights:\n    momentum: 0.6\n    sentiment: 0.4\n"
        "exits:\n  stop_loss_pct: 0.02\n  take_profit_pct: 0.03\n  flatten_at_close: true\n  flatten_time: \"15:55\"\n"
    )
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")
    cfg = load_config(str(cfg_path))
    assert cfg.alpaca_api_key == "pk_test"
    assert cfg.alpaca_paper is True
    assert cfg.max_position_pct == 0.02
    assert cfg.entry_threshold == 0.5
    assert cfg.stop_loss_pct == 0.02
    assert cfg.take_profit_pct == 0.03
    assert cfg.flatten_at_close is True
    assert cfg.flatten_time == "15:55"


def test_load_config_requires_api_key(tmp_path, monkeypatch):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        "alpaca:\n  paper: true\n"
        "ollama:\n  base_url: http://localhost:11434\n  model: llama3.2\n"
        "risk:\n  paper_capital: 100000.0\n  max_position_pct: 0.02\n  max_positions: 3\n"
        "  kill_switch_pct: 0.10\n  daily_loss_pct: 0.05\n"
        "universe:\n  size: 20\n  min_price: 5.0\n  min_volume: 500000\n"
        "loop:\n  scan_interval_seconds: 60\n"
        "scoring:\n  entry_threshold: 0.5\n  weights:\n    momentum: 0.6\n    sentiment: 0.4\n"
        "exits:\n  stop_loss_pct: 0.02\n  take_profit_pct: 0.03\n  flatten_at_close: true\n  flatten_time: \"15:55\"\n"
    )
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr("autotrader.config.load_dotenv", lambda: None)
    import pytest
    with pytest.raises(ValueError):
        load_config(str(cfg_path))
