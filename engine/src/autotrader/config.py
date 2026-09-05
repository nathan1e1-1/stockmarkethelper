import os
from dataclasses import dataclass
from math import isfinite

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
    risk_profile: str
    max_position_pct: float
    max_gross_exposure_pct: float
    max_positions: int
    max_entries_per_session: int
    max_snapshot_age_seconds: int
    kill_switch_pct: float
    daily_loss_pct: float
    universe_size: int
    min_price: float
    min_volume: int
    scan_interval_seconds: int
    entry_threshold: float
    signal_weights: dict
    stop_loss_pct: float
    take_profit_pct: float
    flatten_at_close: bool
    flatten_time: str


def _positive_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


def _positive_integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_paper_profile(raw: dict) -> None:
    alpaca = raw.get("alpaca", {})
    if alpaca.get("paper") is not True:
        raise ValueError("paper trading must be enabled; live trading is not supported")

    risk = raw.get("risk", {})
    if risk.get("profile") != "initial":
        raise ValueError("risk.profile must be the approved 'initial' paper profile")

    position_cap = _positive_number(risk.get("max_position_pct"), "max_position_pct")
    gross_cap = _positive_number(risk.get("max_gross_exposure_pct"), "max_gross_exposure_pct")
    max_positions = _positive_integer(risk.get("max_positions"), "max_positions")
    max_entries = _positive_integer(risk.get("max_entries_per_session"), "max_entries_per_session")
    max_snapshot_age = _positive_integer(risk.get("max_snapshot_age_seconds"), "max_snapshot_age_seconds")
    if (position_cap, gross_cap, max_positions, max_entries, max_snapshot_age) != (0.0025, 0.0025, 1, 1, 120):
        raise ValueError(
            "the initial paper profile requires max_position_pct=0.0025, "
            "max_gross_exposure_pct=0.0025, max_positions=1, "
            "max_entries_per_session=1, and max_snapshot_age_seconds=120"
        )
    if gross_cap < position_cap:
        raise ValueError("max_gross_exposure_pct must be at least max_position_pct")


def load_config(path: str = "config/config.yaml") -> Config:
    load_dotenv()
    with open(path) as f:
        raw = yaml.safe_load(f)
    _validate_paper_profile(raw)
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
        risk_profile=raw["risk"]["profile"],
        max_position_pct=raw["risk"]["max_position_pct"],
        max_gross_exposure_pct=raw["risk"]["max_gross_exposure_pct"],
        max_positions=raw["risk"]["max_positions"],
        max_entries_per_session=raw["risk"]["max_entries_per_session"],
        max_snapshot_age_seconds=raw["risk"]["max_snapshot_age_seconds"],
        kill_switch_pct=raw["risk"]["kill_switch_pct"],
        daily_loss_pct=raw["risk"]["daily_loss_pct"],
        universe_size=raw["universe"]["size"],
        min_price=raw["universe"]["min_price"],
        min_volume=raw["universe"]["min_volume"],
        scan_interval_seconds=raw["loop"]["scan_interval_seconds"],
        entry_threshold=raw["scoring"]["entry_threshold"],
        signal_weights=raw["scoring"]["weights"],
        stop_loss_pct=raw["exits"]["stop_loss_pct"],
        take_profit_pct=raw["exits"]["take_profit_pct"],
        flatten_at_close=raw["exits"]["flatten_at_close"],
        flatten_time=raw["exits"]["flatten_time"],
    )
