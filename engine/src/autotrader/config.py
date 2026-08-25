import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv


@dataclass
class Config:
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool
    ollama_base_url: str
    ollama_model: str
    paper_capital: float
    max_position_pct: float
    max_positions: int
    kill_switch_pct: float
    daily_loss_pct: float
    universe_size: int
    min_price: float
    min_volume: int
    scan_interval_seconds: int
    entry_threshold: float
    signal_weights: dict


def load_config(path: str = "config/config.yaml") -> Config:
    load_dotenv()
    with open(path) as f:
        raw = yaml.safe_load(f)
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
    return Config(
        alpaca_api_key=api_key,
        alpaca_secret_key=secret,
        alpaca_paper=raw["alpaca"]["paper"],
        ollama_base_url=raw["ollama"]["base_url"],
        ollama_model=raw["ollama"]["model"],
        paper_capital=raw["risk"]["paper_capital"],
        max_position_pct=raw["risk"]["max_position_pct"],
        max_positions=raw["risk"]["max_positions"],
        kill_switch_pct=raw["risk"]["kill_switch_pct"],
        daily_loss_pct=raw["risk"]["daily_loss_pct"],
        universe_size=raw["universe"]["size"],
        min_price=raw["universe"]["min_price"],
        min_volume=raw["universe"]["min_volume"],
        scan_interval_seconds=raw["loop"]["scan_interval_seconds"],
        entry_threshold=raw["scoring"]["entry_threshold"],
        signal_weights=raw["scoring"]["weights"],
    )
