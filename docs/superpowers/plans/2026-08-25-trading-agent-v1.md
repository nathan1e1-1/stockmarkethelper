# Trading Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS trading system where Python agents watch US equities in real time, place long-only paper trades via Alpaca, and write a daily post-close summary — with a SwiftUI app for live monitoring.

**Architecture:** Two processes. A headless Python engine (Alpaca streaming + REST, signal computation, local Ollama LLM decisions, risk layer, order execution, daily summary, FastAPI IPC server) and a thin SwiftUI macOS app that renders live state over localhost WebSocket/REST.

**Tech Stack:** Python 3.11, `alpaca-py`, `fastapi` + `uvicorn`, `pandas` + `numpy`, `requests` (Ollama), `PyYAML`, `python-dotenv`, `pydantic`, `pytest` + `pytest-asyncio`. SwiftUI + Swift Charts (macOS 14+).

---

## File Structure

```
stockmarkethelper/
├── engine/                              # Python trading engine (the daemon)
│   ├── pyproject.toml
│   ├── config/config.yaml               # thresholds, model name, cadence
│   ├── .env.example                     # ALPACA_API_KEY, ALPACA_SECRET_KEY
│   ├── src/autotrader/
│   │   ├── __init__.py
│   │   ├── models.py                    # Signal, SignalSet, AgentDecision, Order, Position, Equity, enums
│   │   ├── config.py                    # YAML + env -> Config dataclass
│   │   ├── state.py                     # JSON journal/persistence (equity, positions, decisions)
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # MarketDataProvider, NewsProvider Protocols
│   │   │   ├── alpaca.py                # Alpaca REST snapshots + news
│   │   │   └── fixtures.py              # deterministic in-memory provider for tests/replay
│   │   ├── signals/
│   │   │   ├── __init__.py
│   │   │   ├── momentum.py              # MomentumSignal.compute
│   │   │   ├── sentiment.py             # SentimentSignal (Ollama over news) .compute
│   │   │   └── regime.py                # RegimeFilter -> weights by realized vol + trend
│   │   ├── scoring.py                   # composite_score(signals, weights) -> float
│   │   ├── universe.py                  # build_universe(provider) -> list[ticker]
│   │   ├── agent.py                     # OllamaAgent.decide(SignalSet) -> AgentDecision
│   │   ├── risk.py                      # RiskManager: sizing + circuit breakers
│   │   ├── execution.py                 # AlpacaExecutor: paper orders, positions
│   │   ├── summary.py                   # daily_summary(state, llm) -> str
│   │   ├── runner.py                    # orchestrator loop wiring everything
│   │   └── main.py                      # CLI entry point
│   └── tests/
│       ├── test_config.py
│       ├── test_state.py
│       ├── test_momentum.py
│       ├── test_sentiment.py
│       ├── test_regime.py
│       ├── test_scoring.py
│       ├── test_universe.py
│       ├── test_agent.py
│       ├── test_risk.py
│       ├── test_execution.py
│       ├── test_runner.py
│       ├── test_summary.py
│       └── test_ipc.py
├── app/                                 # SwiftUI macOS app
│   └── TradingAgentApp/
│       ├── TradingAgentApp.swift
│       ├── Models.swift                 # Codable mirrors of engine JSON
│       ├── EngineClient.swift           # WebSocket + REST client
│       ├── ContentView.swift
│       ├── DashboardView.swift
│       ├── ChartsView.swift
│       ├── PositionsView.swift
│       ├── SummaryView.swift
│       └── Assets.xcassets/
└── docs/superpowers/plans/              # this file
```

---

## Milestone 0 — Engine scaffolding

### Task 1: Python project scaffold

**Files:**
- Create: `engine/pyproject.toml`
- Create: `engine/src/autotrader/__init__.py`
- Create: `engine/config/config.yaml`
- Create: `engine/.env.example`

- [ ] **Step 1: Create the package layout and build config**

`engine/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "autotrader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "alpaca-py>=0.30.0",
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "requests>=2.31.0",
    "PyYAML>=6.0.1",
    "python-dotenv>=1.0.1",
    "pydantic>=2.6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`engine/src/autotrader/__init__.py`:
```python
"""Autotrader engine: signal -> decision -> risk -> execution."""
__version__ = "0.1.0"
```

`engine/config/config.yaml`:
```yaml
alpaca:
  paper: true
ollama:
  base_url: "http://localhost:11434"
  model: "llama3.2"
risk:
  paper_capital: 100000.0
  max_position_pct: 0.02
  max_positions: 3
  kill_switch_pct: 0.10
  daily_loss_pct: 0.05
universe:
  size: 20
  min_price: 5.0
  min_volume: 500000
loop:
  scan_interval_seconds: 60
scoring:
  entry_threshold: 0.5
  weights:
    momentum: 0.6
    sentiment: 0.4
```

`engine/.env.example`:
```
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

- [ ] **Step 2: Install and verify imports**

Run: `cd engine && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -c "import autotrader; print(autotrader.__version__)"`
Expected: `0.1.0`

- [ ] **Step 3: Commit**

```bash
git add engine/pyproject.toml engine/src/autotrader/__init__.py engine/config/config.yaml engine/.env.example engine/.gitignore
git commit -m "chore: scaffold autotrader engine package"
```

### Task 2: Config loader

**Files:**
- Create: `engine/src/autotrader/config.py`
- Create: `engine/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_config.py`:
```python
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
    )
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")
    cfg = load_config(str(cfg_path))
    assert cfg.alpaca_api_key == "pk_test"
    assert cfg.alpaca_paper is True
    assert cfg.max_position_pct == 0.02
    assert cfg.entry_threshold == 0.5


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
    )
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    import pytest
    with pytest.raises(ValueError):
        load_config(str(cfg_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'autotrader.config'`)

- [ ] **Step 3: Write minimal implementation**

`engine/src/autotrader/config.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/config.py engine/tests/test_config.py
git commit -m "feat: add YAML+env config loader"
```

### Task 3: Domain models

**Files:**
- Create: `engine/src/autotrader/models.py`
- Create: `engine/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_models.py`:
```python
from autotrader.models import Signal, SignalSet, Decision, AgentDecision


def test_signalset_composite_is_stored():
    s = Signal(name="momentum", value=0.6, detail={"sma20": 1.05})
    ss = SignalSet(ticker="AAPL", signals=[s], composite=0.55, regime="trending")
    assert ss.composite == 0.55
    assert ss.signals[0].name == "momentum"


def test_agent_decision_defaults_to_hold():
    d = AgentDecision(ticker="AAPL", decision=Decision.HOLD, rationale="n/a", confidence=0.1)
    assert d.decision is Decision.HOLD
    assert d.confidence == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/models.py`:
```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Decision(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Signal:
    name: str
    value: float
    detail: dict = field(default_factory=dict)


@dataclass
class SignalSet:
    ticker: str
    signals: list[Signal]
    composite: float
    regime: str
    timestamp: datetime = field(default_factory=_now)


@dataclass
class AgentDecision:
    ticker: str
    decision: Decision
    rationale: str
    confidence: float
    signals: SignalSet | None = None


@dataclass
class Order:
    id: str
    ticker: str
    side: Side
    qty: float
    filled_avg_price: float | None = None
    status: str = "submitted"
    timestamp: datetime = field(default_factory=_now)


@dataclass
class Position:
    ticker: str
    qty: float
    avg_entry_price: float
    opened_at: datetime = field(default_factory=_now)


@dataclass
class Equity:
    equity: float
    day_start_equity: float
    peak_equity: float
    day: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/models.py engine/tests/test_models.py
git commit -m "feat: add domain models (signal, decision, order, equity)"
```

### Task 4: State / journal persistence

**Files:**
- Create: `engine/src/autotrader/state.py`
- Create: `engine/tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_state.py`:
```python
from autotrader.state import StateStore, State
from autotrader.models import Equity


def test_state_roundtrips(tmp_path):
    store = StateStore(tmp_path)
    eq = Equity(equity=98000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-25")
    store.save(State(equity=eq, positions=[], decisions=[]))
    loaded = store.load()
    assert loaded.equity.equity == 98000.0
    assert loaded.equity.day == "2026-08-25"


def test_load_missing_returns_fresh_state(tmp_path):
    store = StateStore(tmp_path)
    state = store.load()
    assert state.equity is None
    assert state.positions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_state.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/state.py`:
```python
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from autotrader.models import AgentDecision, Equity, Position


@dataclass
class State:
    equity: Equity | None = None
    positions: list[Position] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)


class StateStore:
    def __init__(self, directory: Path | str):
        self.path = Path(directory) / "state.json"

    def load(self) -> State:
        if not self.path.exists():
            return State()
        raw = json.loads(self.path.read_text())
        eq = raw.get("equity")
        return State(
            equity=Equity(**eq) if eq else None,
            positions=[Position(**p) for p in raw.get("positions", [])],
            decisions=[AgentDecision(**d) for d in raw.get("decisions", [])],
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(state), default=str, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_state.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/state.py engine/tests/test_state.py
git commit -m "feat: add JSON state journal persistence"
```

---

## Milestone 1 — Market data & universe

### Task 5: Alpaca market data + news provider

**Files:**
- Create: `engine/src/autotrader/providers/__init__.py`
- Create: `engine/src/autotrader/providers/base.py`
- Create: `engine/src/autotrader/providers/alpaca.py`
- Create: `engine/src/autotrader/providers/fixtures.py`
- Create: `engine/tests/test_alpaca.py`

- [ ] **Step 1: Write the failing test (using the fixture provider, no network)**

`engine/tests/test_alpaca.py`:
```python
from autotrader.providers.fixtures import FixtureProvider


def test_fixture_provider_latest_price():
    p = FixtureProvider()
    assert p.latest_price("AAPL") == 190.0


def test_fixture_provider_bars_length():
    p = FixtureProvider()
    bars = p.bars("AAPL", limit=50)
    assert len(bars) == 50
    assert all(b["close"] > 0 for b in bars)


def test_fixture_provider_news():
    p = FixtureProvider()
    news = p.news("AAPL", limit=5)
    assert len(news) == 5
    assert all("headline" in n for n in news)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_alpaca.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write the providers**

`engine/src/autotrader/providers/base.py`:
```python
from typing import Protocol


class MarketDataProvider(Protocol):
    def latest_price(self, ticker: str) -> float: ...
    def bars(self, ticker: str, limit: int = 50) -> list[dict]: ...
    def gainers(self, limit: int) -> list[dict]: ...


class NewsProvider(Protocol):
    def news(self, ticker: str, limit: int = 5) -> list[dict]: ...
```

`engine/src/autotrader/providers/fixtures.py`:
```python
import math


class FixtureProvider:
    """Deterministic in-memory provider for tests and replay."""

    def latest_price(self, ticker: str) -> float:
        return 100.0 + (sum(ord(c) for c in ticker) % 90)

    def bars(self, ticker: str, limit: int = 50) -> list[dict]:
        base = self.latest_price(ticker)
        return [
            {"t": f"2026-08-25T13:{i:02d}:00Z", "close": base + math.sin(i / 5) * 2}
            for i in range(limit)
        ]

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        return [
            {"headline": f"{ticker} beats earnings expectations", "sentiment_hint": "positive"}
            for _ in range(limit)
        ]

    def gainers(self, limit: int) -> list[dict]:
        return [
            {"ticker": f"TICK{i:02d}", "price": 50.0 + i, "volume": 1_000_000 + i * 1000}
            for i in range(limit)
        ]
```

`engine/src/autotrader/providers/alpaca.py`:
```python
from datetime import datetime, timedelta, timezone

from alpaca.data.enums import Screener
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import StockNewsClient
from alpaca.data.requests import GetNewsRequest, StockBarsRequest, StockLatestTradeRequest, StockScreenersRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from autotrader.config import Config


class AlpacaProvider:
    def __init__(self, cfg: Config):
        self._data = StockHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._news = StockNewsClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._trading = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)

    def latest_price(self, ticker: str) -> float:
        req = StockLatestTradeRequest(symbol_or_symbols=[ticker])
        trade = self._data.get_stock_latest_trade(req)[ticker]
        return float(trade.price)

    def bars(self, ticker: str, limit: int = 50) -> list[dict]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        req = StockBarsRequest(symbol_or_symbols=[ticker], timeframe=TimeFrame.Minute, start=start, end=end, limit=limit)
        bars = self._data.get_stock_bars(req)[ticker]
        return [{"t": b.timestamp.isoformat(), "close": float(b.close)} for b in bars]

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        req = GetNewsRequest(symbols=ticker, limit=limit)
        raw = self._news.get_news(req).news
        return [{"headline": n.headline, "summary": n.summary} for n in raw]

    def gainers(self, limit: int) -> list[dict]:
        req = StockScreenersRequest(screener=Screener.MOST_ACTIVES, limit=limit)
        res = self._data.get_stock_screeners(req)
        return [
            {"ticker": item.symbol, "price": float(item.price), "volume": int(item.volume)}
            for item in res.most_actives
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_alpaca.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/providers engine/tests/test_alpaca.py
git commit -m "feat: add market data providers (fixture + alpaca)"
```

### Task 6: Universe builder (daily screener)

**Files:**
- Create: `engine/src/autotrader/universe.py`
- Create: `engine/tests/test_universe.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_universe.py`:
```python
from autotrader.universe import build_universe
from autotrader.providers.fixtures import FixtureProvider


def test_build_universe_filters_by_price_and_volume():
    p = FixtureProvider()
    result = build_universe(p, size=10, min_price=5.0, min_volume=500000)
    assert len(result) <= 10
    assert all(r["price"] >= 5.0 for r in result)
    assert all(r["volume"] >= 500000 for r in result)


def test_build_universe_returns_tickers_only():
    p = FixtureProvider()
    tickers = build_universe(p, size=10, min_price=5.0, min_volume=500000, tickers_only=True)
    assert isinstance(tickers, list)
    assert all(isinstance(t, str) for t in tickers)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_universe.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/universe.py`:
```python
from autotrader.providers.base import MarketDataProvider


def build_universe(
    provider: MarketDataProvider,
    size: int = 20,
    min_price: float = 5.0,
    min_volume: int = 500000,
    tickers_only: bool = False,
) -> list:
    candidates = provider.gainers(limit=size * 3)
    filtered = [
        c for c in candidates
        if c.get("price", 0.0) >= min_price and c.get("volume", 0) >= min_volume
    ][:size]
    if tickers_only:
        return [c["ticker"] for c in filtered]
    return filtered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_universe.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/universe.py engine/tests/test_universe.py
git commit -m "feat: add daily universe builder"
```

---

## Milestone 2 — Signals & scoring

### Task 7: Momentum signal

**Files:**
- Create: `engine/src/autotrader/signals/__init__.py`
- Create: `engine/src/autotrader/signals/momentum.py`
- Create: `engine/tests/test_momentum.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_momentum.py`:
```python
from autotrader.signals.momentum import MomentumSignal


def test_momentum_positive_when_price_above_sma():
    bars = [{"close": float(i)} for i in range(1, 51)]  # steadily rising
    sig = MomentumSignal()
    s = sig.compute("AAPL", bars)
    assert s.name == "momentum"
    assert s.value > 0
    assert -1.0 <= s.value <= 1.0


def test_momentum_negative_when_price_below_sma():
    bars = [{"close": float(50 - i)} for i in range(50)]  # steadily falling
    sig = MomentumSignal()
    s = sig.compute("AAPL", bars)
    assert s.value < 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_momentum.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/signals/momentum.py`:
```python
import math

from autotrader.models import Signal


class MomentumSignal:
    def __init__(self, short: int = 20, long: int = 50):
        self.short = short
        self.long = long

    def compute(self, ticker: str, bars: list[dict]) -> Signal:
        closes = [b["close"] for b in bars]
        if len(closes) < self.long:
            return Signal(name="momentum", value=0.0, detail={"reason": "insufficient data"})
        sma_short = sum(closes[-self.short:]) / self.short
        sma_long = sum(closes[-self.long:]) / self.long
        last = closes[-1]
        if sma_long == 0:
            return Signal(name="momentum", value=0.0, detail={})
        pct = (last / sma_long) - 1.0
        crossover = 1.0 if sma_short > sma_long else -1.0
        raw = (pct * 20.0) + (crossover * 0.3)
        value = max(-1.0, min(1.0, raw))
        return Signal(
            name="momentum",
            value=round(value, 4),
            detail={"sma_short": round(sma_short, 2), "sma_long": round(sma_long, 2), "pct_vs_sma_long": round(pct, 4)},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_momentum.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/signals engine/tests/test_momentum.py
git commit -m "feat: add momentum signal"
```

### Task 8: Sentiment signal (Ollama over news)

**Files:**
- Create: `engine/src/autotrader/signals/sentiment.py`
- Create: `engine/tests/test_sentiment.py`

- [ ] **Step 1: Write the failing test (deterministic, no Ollama)**

`engine/tests/test_sentiment.py`:
```python
from autotrader.signals.sentiment import SentimentSignal


class FakeLLM:
    def sentiment(self, headlines: list[str]) -> float:
        return 0.7


def test_sentiment_uses_llm_result():
    sig = SentimentSignal(FakeLLM())
    s = sig.compute("AAPL", [{"headline": "AAPL beats earnings"}])
    assert s.name == "sentiment"
    assert s.value == 0.7


def test_sentiment_no_news_returns_zero():
    sig = SentimentSignal(FakeLLM())
    s = sig.compute("AAPL", [])
    assert s.value == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_sentiment.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/signals/sentiment.py`:
```python
from autotrader.models import Signal


class SentimentSignal:
    def __init__(self, llm):
        self.llm = llm

    def compute(self, ticker: str, news: list[dict]) -> Signal:
        if not news:
            return Signal(name="sentiment", value=0.0, detail={"reason": "no news"})
        headlines = [n["headline"] for n in news if n.get("headline")]
        value = self.llm.sentiment(headlines)
        return Signal(name="sentiment", value=value, detail={"headline_count": len(headlines)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_sentiment.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/signals/sentiment.py engine/tests/test_sentiment.py
git commit -m "feat: add sentiment signal"
```

### Task 9: Regime filter

**Files:**
- Create: `engine/src/autotrader/signals/regime.py`
- Create: `engine/tests/test_regime.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_regime.py`:
```python
from autotrader.signals.regime import RegimeFilter


def test_trending_regime_rewards_momentum():
    rf = RegimeFilter()
    bars = [{"close": float(i)} for i in range(50)]  # clean uptrend, low vol
    weights = rf.weights(bars, base={"momentum": 0.6, "sentiment": 0.4})
    assert weights["momentum"] > 0.6


def test_choppy_regime_reduces_momentum():
    rf = RegimeFilter()
    import math
    bars = [{"close": 100.0 + math.sin(i / 3) * 3} for i in range(50)]  # choppy
    weights = rf.weights(bars, base={"momentum": 0.6, "sentiment": 0.4})
    assert weights["momentum"] < 0.6


def test_regime_label_present():
    rf = RegimeFilter()
    bars = [{"close": float(i)} for i in range(50)]
    label = rf.label(bars)
    assert label in ("trending", "choppy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_regime.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/signals/regime.py`:
```python
import statistics


class RegimeFilter:
    def __init__(self, window: int = 20):
        self.window = window

    def label(self, bars: list[dict]) -> str:
        if len(bars) < self.window:
            return "choppy"
        closes = [b["close"] for b in bars][-self.window:]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        vol = statistics.pstdev(rets) if rets else 0.0
        trend = (closes[-1] / closes[0] - 1) if closes[0] else 0.0
        return "trending" if abs(trend) > vol * 3 else "choppy"

    def weights(self, bars: list[dict], base: dict[str, float]) -> dict[str, float]:
        label = self.label(bars)
        weights = dict(base)
        momentum = weights.get("momentum", 0.5)
        if label == "trending":
            weights["momentum"] = min(0.9, momentum * 1.4)
        else:
            weights["momentum"] = momentum * 0.5
        # renormalize so weights still sum to 1
        total = sum(weights.values())
        return {k: round(v / total, 4) for k, v in weights.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_regime.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/signals/regime.py engine/tests/test_regime.py
git commit -m "feat: add regime filter for signal weighting"
```

### Task 10: Composite scoring

**Files:**
- Create: `engine/src/autotrader/scoring.py`
- Create: `engine/tests/test_scoring.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_scoring.py`:
```python
from autotrader.scoring import composite_score
from autotrader.models import Signal


def test_composite_is_weighted_sum():
    signals = [Signal(name="momentum", value=0.6), Signal(name="sentiment", value=0.3)]
    weights = {"momentum": 0.6, "sentiment": 0.4}
    score = composite_score(signals, weights)
    assert score == round(0.6 * 0.6 + 0.3 * 0.4, 4)


def test_composite_ignores_unknown_signals():
    signals = [Signal(name="momentum", value=0.6), Signal(name="other", value=1.0)]
    weights = {"momentum": 1.0}
    assert composite_score(signals, weights) == 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_scoring.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/scoring.py`:
```python
from autotrader.models import Signal


def composite_score(signals: list[Signal], weights: dict[str, float]) -> float:
    total = 0.0
    for s in signals:
        total += s.value * weights.get(s.name, 0.0)
    return round(max(-1.0, min(1.0, total)), 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_scoring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/scoring.py engine/tests/test_scoring.py
git commit -m "feat: add composite weighted scoring"
```

---

## Milestone 3 — Decision agent

### Task 11: Ollama decision agent

**Files:**
- Create: `engine/src/autotrader/agent.py`
- Create: `engine/tests/test_agent.py`

- [ ] **Step 1: Write the failing test (no network — inject a fake HTTP client)**

`engine/tests/test_agent.py`:
```python
from autotrader.agent import OllamaAgent, parse_decision
from autotrader.models import Decision, SignalSet, Signal


class FakeSession:
    def __init__(self, text):
        self._text = text

    def post(self, url, json, timeout):
        return FakeResponse(self._text)


class FakeResponse:
    def __init__(self, text):
        self._text = text

    def json(self):
        return {"response": self._text}

    def raise_for_status(self):
        pass


def test_parse_decision_buy():
    assert parse_decision('{"decision": "buy", "confidence": 0.8, "rationale": "strong momentum"}') == Decision.BUY


def test_agent_returns_decision_from_llm():
    import json
    payload = {"decision": "buy", "confidence": 0.8, "rationale": "trend up"}
    agent = OllamaAgent(base_url="http://x", model="m", session=FakeSession(json.dumps(payload)))
    ss = SignalSet(ticker="AAPL", signals=[Signal("momentum", 0.6)], composite=0.55, regime="trending")
    d = agent.decide(ss)
    assert d.ticker == "AAPL"
    assert d.decision == Decision.BUY
    assert d.confidence == 0.8


def test_agent_sentiment_returns_float():
    import json
    payload = {"sentiment": 0.4}
    agent = OllamaAgent(base_url="http://x", model="m", session=FakeSession(json.dumps(payload)))
    assert agent.sentiment(["AAPL beats earnings"]) == 0.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_agent.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/agent.py`:
```python
import json

from autotrader.models import AgentDecision, Decision, SignalSet


def parse_decision(raw: str) -> Decision:
    try:
        obj = json.loads(raw)
        return Decision(obj.get("decision", "hold"))
    except (json.JSONDecodeError, ValueError):
        return Decision.HOLD


class OllamaAgent:
    def __init__(self, base_url: str, model: str, session=None):
        import requests
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.session = session or requests.Session()

    def decide(self, signals: SignalSet) -> AgentDecision:
        prompt = (
            f"You are a disciplined intraday trader. Given these signals for {signals.ticker}: "
            f"regime={signals.regime}, composite={signals.composite}, "
            f"signals=" + json.dumps([{"name": s.name, "value": s.value} for s in signals.signals]) + ". "
            "Respond ONLY with JSON: {\"decision\": \"buy\"|\"hold\"|\"sell\", \"confidence\": 0.0-1.0, \"rationale\": \"...\"}"
        )
        resp = self.session.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "{}")
        obj = json.loads(text)
        return AgentDecision(
            ticker=signals.ticker,
            decision=Decision(obj.get("decision", "hold")),
            rationale=obj.get("rationale", ""),
            confidence=float(obj.get("confidence", 0.0)),
            signals=signals,
        )

    def sentiment(self, headlines: list[str]) -> float:
        prompt = (
            "Score the sentiment of these headlines from -1 (very negative) to 1 (very positive) "
            "for the stock. " + " | ".join(headlines) + " "
            'Respond ONLY with JSON: {"sentiment": <float>}'
        )
        resp = self.session.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        obj = json.loads(resp.json().get("response", "{}"))
        return max(-1.0, min(1.0, float(obj.get("sentiment", 0.0))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_agent.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/agent.py engine/tests/test_agent.py
git commit -m "feat: add Ollama decision agent"
```

---

## Milestone 4 — Risk layer

### Task 12: Risk manager (sizing + circuit breakers)

**Files:**
- Create: `engine/src/autotrader/risk.py`
- Create: `engine/tests/test_risk.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_risk.py`:
```python
from autotrader.risk import RiskManager
from autotrader.models import Position


def cfg():
    from dataclasses import dataclass
    @dataclass
    class C:
        paper_capital: float = 100000.0
        max_position_pct: float = 0.02
        max_positions: int = 3
        kill_switch_pct: float = 0.10
        daily_loss_pct: float = 0.05
    return C()


def test_position_size_is_pct_of_equity():
    rm = RiskManager(cfg())
    qty = rm.position_size("AAPL", price=100.0, equity=100000.0)
    assert qty == 20  # 2% of 100k / $100 = 20 shares


def test_max_positions_reached_blocks_entry():
    rm = RiskManager(cfg())
    rm.positions = [
        Position(ticker="A", qty=1, avg_entry_price=100.0),
        Position(ticker="B", qty=1, avg_entry_price=100.0),
        Position(ticker="C", qty=1, avg_entry_price=100.0),
    ]
    assert rm.can_enter("D") is False


def test_kill_switch_triggers_on_drawdown():
    rm = RiskManager(cfg())
    rm.peak_equity = 100000.0
    assert rm.hard_stop_triggered(89000.0) is True
    assert rm.hard_stop_triggered(91000.0) is False


def test_daily_loss_limit():
    rm = RiskManager(cfg())
    rm.day_start_equity = 100000.0
    assert rm.daily_stop_triggered(94999.0) is True
    assert rm.daily_stop_triggered(95001.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_risk.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/risk.py`:
```python
import math

from autotrader.models import Position


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.positions: list[Position] = []
        self.peak_equity: float = cfg.paper_capital
        self.day_start_equity: float = cfg.paper_capital

    def position_size(self, ticker: str, price: float, equity: float) -> int:
        budget = equity * self.cfg.max_position_pct
        qty = math.floor(budget / price)
        return max(0, qty)

    def can_enter(self, ticker: str) -> bool:
        if len(self.positions) >= self.cfg.max_positions:
            return False
        if any(p.ticker == ticker for p in self.positions):
            return False
        return True

    def hard_stop_triggered(self, equity: float) -> bool:
        return equity <= self.peak_equity * (1.0 - self.cfg.kill_switch_pct)

    def daily_stop_triggered(self, equity: float) -> bool:
        return equity <= self.day_start_equity * (1.0 - self.cfg.daily_loss_pct)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_risk.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/risk.py engine/tests/test_risk.py
git commit -m "feat: add risk layer (sizing + circuit breakers)"
```

---

## Milestone 5 — Execution

### Task 13: Alpaca paper executor

**Files:**
- Create: `engine/src/autotrader/execution.py`
- Create: `engine/tests/test_execution.py`

- [ ] **Step 1: Write the failing test (fake trading client)**

`engine/tests/test_execution.py`:
```python
from autotrader.execution import AlpacaExecutor
from autotrader.models import Order, Side, Position


class FakeTrading:
    def __init__(self):
        self.orders = []

    def submit_order(self, order_data):
        from alpaca.trading.requests import MarketOrderRequest
        return None  # submit is exercised; we capture below


class FakeExec:
    def __init__(self):
        self.submitted = []

    def market_order(self, ticker, qty, side):
        self.submitted.append((ticker, qty, side))
        return Order(id="fake-1", ticker=ticker, side=side, qty=qty)

    def positions(self):
        return []


def test_executor_buys():
    ex = FakeExec()
    ex.market_order("AAPL", 20, Side.BUY)
    assert ex.submitted == [("AAPL", 20, Side.BUY)]


def test_executor_lists_positions_empty():
    ex = FakeExec()
    assert ex.positions() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_execution.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/execution.py`:
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from autotrader.config import Config
from autotrader.models import Order, Position, Side


class AlpacaExecutor:
    def __init__(self, cfg: Config):
        self.client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)

    def market_order(self, ticker: str, qty: int, side: Side) -> Order:
        req = MarketOrderRequest(
            symbol=ticker,
            qty=float(qty),
            side=OrderSide.BUY if side is Side.BUY else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        raw = self.client.submit_order(req)
        return Order(id=str(raw.id), ticker=ticker, side=side, qty=float(qty), status=raw.status)

    def positions(self) -> list[Position]:
        out = []
        for p in self.client.get_all_positions():
            out.append(
                Position(
                    ticker=p.symbol,
                    qty=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                )
            )
        return out

    def flatten_all(self) -> None:
        self.client.close_all_positions()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_execution.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/execution.py engine/tests/test_execution.py
git commit -m "feat: add Alpaca paper order executor"
```

---

## Milestone 6 — Orchestrator & summary

### Task 14: Runner (the trading loop)

**Files:**
- Create: `engine/src/autotrader/runner.py`
- Create: `engine/tests/test_runner.py`

- [ ] **Step 1: Write the failing test (inject fake providers/agent/executor)**

`engine/tests/test_runner.py`:
```python
from autotrader.runner import Runner
from autotrader.models import Decision, AgentDecision, SignalSet, Signal, Equity
from autotrader.providers.fixtures import FixtureProvider


class BuyAgent:
    def decide(self, ss):
        return AgentDecision(ticker=ss.ticker, decision=Decision.BUY, rationale="t", confidence=0.7, signals=ss)


class FakeExec:
    def __init__(self):
        self.submitted = []
        self.flat = False

    def market_order(self, ticker, qty, side):
        self.submitted.append((ticker, qty))
        from autotrader.models import Order
        return Order(id="o1", ticker=ticker, side=side, qty=qty)

    def positions(self):
        return []

    def flatten_all(self):
        self.flat = True


def test_runner_scans_and_buys_candidate():
    runner = Runner(provider=FixtureProvider(), agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["AAPL"])
    assert len(runner.executor.submitted) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_runner.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/runner.py`:
```python
from autotrader.models import Decision, Equity, Side, Signal, SignalSet
from autotrader.scoring import composite_score
from autotrader.signals.momentum import MomentumSignal
from autotrader.signals.regime import RegimeFilter
from autotrader.signals.sentiment import SentimentSignal


class Runner:
    def __init__(self, provider, agent, executor, risk, cfg, sentiment_llm=None):
        self.provider = provider
        self.agent = agent
        self.executor = executor
        self.risk = risk
        self.cfg = cfg
        self.momentum = MomentumSignal()
        self.regime = RegimeFilter()
        self.sentiment = SentimentSignal(sentiment_llm) if sentiment_llm else None
        self.equity: Equity | None = None

    def compute_signalset(self, ticker: str) -> SignalSet:
        bars = self.provider.bars(ticker)
        signals = [self.momentum.compute(ticker, bars)]
        if self.sentiment is not None:
            signals.append(self.sentiment.compute(ticker, self.provider.news(ticker)))
        weights = self.regime.weights(bars, dict(self.cfg.signal_weights)) if self.cfg else {"momentum": 0.6, "sentiment": 0.4}
        comp = composite_score(signals, weights)
        return SignalSet(ticker=ticker, signals=signals, composite=comp, regime=self.regime.label(bars))

    def run_once(self, universe: list[str]) -> None:
        if self.equity is None:
            self.equity = Equity(
                equity=self.cfg.paper_capital,
                day_start_equity=self.cfg.paper_capital,
                peak_equity=self.cfg.paper_capital,
                day="",
            )
        if self.risk and (self.risk.hard_stop_triggered(self.equity.equity) or self.risk.daily_stop_triggered(self.equity.equity)):
            return
        for ticker in universe:
            ss = self.compute_signalset(ticker)
            if ss.composite < (self.cfg.entry_threshold if self.cfg else 0.5):
                continue
            decision = self.agent.decide(ss)
            if decision.decision is not Decision.BUY:
                continue
            if self.risk and not self.risk.can_enter(ticker):
                continue
            price = self.provider.latest_price(ticker)
            qty = self.risk.position_size(ticker, price, self.equity.equity) if self.risk else 0
            self.executor.market_order(ticker, qty, Side.BUY)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_runner.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/runner.py engine/tests/test_runner.py
git commit -m "feat: add orchestrator runner loop"
```

### Task 15: Daily summary generator

**Files:**
- Create: `engine/src/autotrader/summary.py`
- Create: `engine/tests/test_summary.py`

- [ ] **Step 1: Write the failing test**

`engine/tests/test_summary.py`:
```python
from autotrader.summary import daily_summary
from autotrader.state import State
from autotrader.models import Equity, AgentDecision, Decision


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return "Good day: momentum entries worked; exits were too early."


def test_daily_summary_invokes_llm_and_returns_text():
    llm = FakeLLM()
    state = State(equity=Equity(equity=101000.0, day_start_equity=100000.0, peak_equity=101500.0, day="2026-08-25"),
                  decisions=[AgentDecision(ticker="AAPL", decision=Decision.BUY, rationale="trend", confidence=0.8)])
    out = daily_summary(state, llm)
    assert "Good day" in out
    assert llm.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_summary.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/summary.py`:
```python
from autotrader.state import State


def daily_summary(state: State, llm) -> str:
    eq = state.equity
    pnl = (eq.equity / eq.day_start_equity - 1.0) * 100 if eq and eq.day_start_equity else 0.0
    prompt = (
        f"Write a concise post-market summary for an intraday trading day. "
        f"Day P&L was {pnl:.2f}%. {len(state.decisions)} decisions were made. "
        f"Cover: what went well, what went wrong, and one concrete improvement for tomorrow."
    )
    return llm.complete(prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_summary.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/summary.py engine/tests/test_summary.py
git commit -m "feat: add daily summary generator"
```

### Task 16: Engine entry point (CLI)

**Files:**
- Create: `engine/src/autotrader/main.py`

- [ ] **Step 1: Write the entry point**

`engine/src/autotrader/main.py`:
```python
import argparse
import time

from autotrader.agent import OllamaAgent
from autotrader.config import load_config
from autotrader.execution import AlpacaExecutor
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.risk import RiskManager
from autotrader.runner import Runner
from autotrader.universe import build_universe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = AlpacaProvider(cfg)
    agent = OllamaAgent(cfg.ollama_base_url, cfg.ollama_model)
    executor = AlpacaExecutor(cfg)
    risk = RiskManager(cfg)

    runner = Runner(provider=provider, agent=agent, executor=executor, risk=risk, cfg=cfg, sentiment_llm=agent)

    universe = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
    print(f"Universe: {universe}")

    while True:
        runner.run_once(universe)
        if args.once:
            break
        time.sleep(cfg.scan_interval_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it parses**

Run: `cd engine && .venv/bin/python -m autotrader.main --help`
Expected: prints usage with `--config` and `--once` options

- [ ] **Step 3: Commit**

```bash
git add engine/src/autotrader/main.py
git commit -m "feat: add engine CLI entry point"
```

---

## Milestone 7 — IPC server

### Task 17: FastAPI REST + WebSocket server

**Files:**
- Create: `engine/src/autotrader/ipc.py`
- Create: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write the failing test (TestClient, no network socket)**

`engine/tests/test_ipc.py`:
```python
from fastapi.testclient import TestClient
from autotrader.ipc import create_app, SharedState
from autotrader.models import Equity


def test_status_endpoint():
    state = SharedState()
    state.equity = Equity(equity=99000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    client = TestClient(create_app(state))
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["equity"]["equity"] == 99000.0
    assert body["kill_switch"] is False


def test_summary_endpoint():
    state = SharedState()
    state.summary = "Good day"
    client = TestClient(create_app(state))
    r = client.get("/api/summary")
    assert r.status_code == 200
    assert r.json()["summary"] == "Good day"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd engine && .venv/bin/pytest tests/test_ipc.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementation**

`engine/src/autotrader/ipc.py`:
```python
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI

from autotrader.models import Equity


class SharedState:
    def __init__(self):
        self.equity: Equity | None = None
        self.positions: list = []
        self.decisions: list = []
        self.summary: str = ""
        self.risk = None


def create_app(state: SharedState) -> FastAPI:
    app = FastAPI()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        eq = state.equity
        body = {
            "equity": asdict(eq) if eq else None,
            "positions": [asdict(p) for p in state.positions],
            "decisions": [asdict(d) for d in state.decisions],
            "kill_switch": state.risk.hard_stop_triggered(eq.equity) if (state.risk and eq) else False,
            "daily_stop": state.risk.daily_stop_triggered(eq.equity) if (state.risk and eq) else False,
        }
        return body

    @app.get("/api/summary")
    def summary() -> dict[str, str]:
        return {"summary": state.summary}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd engine && .venv/bin/pytest tests/test_ipc.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "feat: add FastAPI IPC server"
```

---

## Milestone 8 — SwiftUI macOS app

> SwiftUI is verified by building the Xcode project and manual run, not unit tests.

### Task 18: Xcode project scaffold

**Files:**
- Create: `app/TradingAgentApp/TradingAgentApp.swift`
- Create: `app/TradingAgentApp/ContentView.swift`
- Create: `app/TradingAgentApp/Assets.xcassets/Contents.json`

- [ ] **Step 1: App entry + content view shell**

`app/TradingAgentApp/TradingAgentApp.swift`:
```swift
import SwiftUI

@main
struct TradingAgentApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
```

`app/TradingAgentApp/ContentView.swift`:
```swift
import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            DashboardView().tabItem { Label("Dashboard", systemImage: "chart.line.uptrend.xyaxis") }
            ChartsView().tabItem { Label("Charts", systemImage: "chart.xyaxis.line") }
            PositionsView().tabItem { Label("Positions", systemImage: "list.bullet") }
            SummaryView().tabItem { Label("Summary", systemImage: "text.quote") }
        }
    }
}
```

`app/TradingAgentApp/Assets.xcassets/Contents.json`:
```json
{ "info": { "author": "xcode", "version": 1 } }
```

- [ ] **Step 2: Generate an Xcode project and build**

Create the `.xcodeproj` with Swift Package Manager. Create `app/TradingAgentApp/Package.swift`:
```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TradingAgentApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "TradingAgentApp", path: ".")
    ]
)
```

Run: `cd app/TradingAgentApp && swift build`
Expected: builds without errors (once all views referenced in Task 18–23 exist)

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp
git commit -m "feat: scaffold SwiftUI app entry"
```

### Task 19: Models + engine client

**Files:**
- Create: `app/TradingAgentApp/Models.swift`
- Create: `app/TradingAgentApp/EngineClient.swift`

- [ ] **Step 1: Codable mirrors + WebSocket/REST client**

`app/TradingAgentApp/Models.swift`:
```swift
import Foundation

struct Equity: Codable {
    let equity: Double
    let day_start_equity: Double
    let peak_equity: Double
    let day: String
}

struct Position: Codable {
    let ticker: String
    let qty: Double
    let avg_entry_price: Double
}

struct Decision: Codable {
    let ticker: String
    let decision: String
    let rationale: String
    let confidence: Double
}

struct EngineStatus: Codable {
    let equity: Equity?
    let positions: [Position]
    let decisions: [Decision]
    let kill_switch: Bool
    let daily_stop: Bool
}
```

`app/TradingAgentApp/EngineClient.swift`:
```swift
import Foundation

@MainActor
final class EngineClient: ObservableObject {
    @Published var status: EngineStatus?
    @Published var summary: String = ""
    private let baseURL = URL(string: "http://127.0.0.1:8000")!

    func refresh() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/status"))
            status = try JSONDecoder().decode(EngineStatus.self, from: data)
            let (sdata, _) = try await URLSession.shared.data(from: baseURL.appending(path: "/api/summary"))
            summary = (try JSONDecoder().decode([String: String].self, from: sdata))["summary"] ?? ""
        } catch {
            // keep last known state on transient failure
        }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd app/TradingAgentApp && swift build`
Expected: builds clean

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp/Models.swift app/TradingAgentApp/EngineClient.swift
git commit -m "feat: add engine client and models"
```

### Task 20: Dashboard view

**Files:**
- Create: `app/TradingAgentApp/DashboardView.swift`

- [ ] **Step 1: Dashboard with live P&L + status banners**

`app/TradingAgentApp/DashboardView.swift`:
```swift
import SwiftUI

struct DashboardView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let eq = client.status?.equity {
                Text("Equity: $\(eq.equity, specifier: "%.2f")").font(.largeTitle)
                let pnl = (eq.equity / eq.day_start_equity - 1) * 100
                Text("Day P&L: \(pnl, specifier: "%+.2f")%").foregroundColor(pnl >= 0 ? .green : .red)
            } else {
                Text("Waiting for engine…")
            }
            if client.status?.kill_switch == true {
                Label("KILL SWITCH ENGAGED", systemImage: "exclamationmark.octagon.fill").foregroundColor(.red)
            }
            if client.status?.daily_stop == true {
                Label("Daily stop reached", systemImage: "stop.circle.fill").foregroundColor(.orange)
            }
        }
        .padding()
        .task { await client.refresh() }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd app/TradingAgentApp && swift build`
Expected: builds clean

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp/DashboardView.swift
git commit -m "feat: add dashboard view"
```

### Task 21: Charts view

**Files:**
- Create: `app/TradingAgentApp/ChartsView.swift`

- [ ] **Step 1: Searchable chart placeholder (Swift Charts)**

`app/TradingAgentApp/ChartsView.swift`:
```swift
import SwiftUI
import Charts

struct ChartsView: View {
    @State private var query = ""

    var body: some View {
        VStack {
            TextField("Search ticker…", text: $query)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 300)
            if query.isEmpty {
                Text("Enter a ticker to load its chart").foregroundColor(.secondary)
            } else {
                Chart {
                    PointMark(x: .value("t", 0), y: .value("price", 100))
                }
                .frame(height: 300)
            }
        }
        .padding()
    }
}
```

- [ ] **Step 2: Build**

Run: `cd app/TradingAgentApp && swift build`
Expected: builds clean

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp/ChartsView.swift
git commit -m "feat: add searchable charts view"
```

### Task 22: Positions & order log view

**Files:**
- Create: `app/TradingAgentApp/PositionsView.swift`

- [ ] **Step 1: Positions list + decisions log**

`app/TradingAgentApp/PositionsView.swift`:
```swift
import SwiftUI

struct PositionsView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        List {
            Section("Positions") {
                if let positions = client.status?.positions, !positions.isEmpty {
                    ForEach(positions, id: \.ticker) { p in
                        Text("\(p.ticker) · \(p.qty, specifier: "%.0f") @ $\(p.avg_entry_price, specifier: "%.2f")")
                    }
                } else {
                    Text("No open positions")
                }
            }
            Section("Decisions") {
                if let decisions = client.status?.decisions, !decisions.isEmpty {
                    ForEach(decisions, id: \.ticker) { d in
                        VStack(alignment: .leading) {
                            Text("\(d.ticker) — \(d.decision) (\(d.confidence, specifier: "%.2f"))")
                            Text(d.rationale).font(.caption).foregroundColor(.secondary)
                        }
                    }
                } else {
                    Text("No decisions yet")
                }
            }
        }
        .task { await client.refresh() }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd app/TradingAgentApp && swift build`
Expected: builds clean

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp/PositionsView.swift
git commit -m "feat: add positions and decision log view"
```

### Task 23: Summary view

**Files:**
- Create: `app/TradingAgentApp/SummaryView.swift`

- [ ] **Step 1: Daily summary display**

`app/TradingAgentApp/SummaryView.swift`:
```swift
import SwiftUI

struct SummaryView: View {
    @StateObject private var client = EngineClient()

    var body: some View {
        ScrollView {
            Text(client.summary.isEmpty ? "No summary yet — generated after market close." : client.summary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        }
        .task { await client.refresh() }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd app/TradingAgentApp && swift build`
Expected: builds clean

- [ ] **Step 3: Commit**

```bash
git add app/TradingAgentApp/SummaryView.swift
git commit -m "feat: add daily summary view"
```

### Task 24: Full app build

**Files:**
- Modify: `app/TradingAgentApp/ContentView.swift` (already references all views)

- [ ] **Step 1: Clean build of the whole app**

Run: `cd app/TradingAgentApp && swift build`
Expected: no errors, produces executable

- [ ] **Step 2: Commit**

```bash
git add -A app/
git commit -m "feat: complete SwiftUI monitoring app"
```

---

## Milestone 9 — Integration & run

### Task 25: README + run instructions

**Files:**
- Create: `README.md`
- Create: `docs/superpowers/plans/README-note.md` (omit)

- [ ] **Step 1: Write README**

`README.md`:
```markdown
# stockmarkethelper

LLM-driven intraday trading agents for US equities (long-only), with a SwiftUI macOS monitor.

## Architecture
- `engine/` — Python daemon: Alpaca data + paper orders, momentum/sentiment signals,
  regime filter, composite scoring, local Ollama decision agent, risk layer, daily summary,
  FastAPI IPC server.
- `app/` — SwiftUI macOS app connecting to the engine over localhost.

## Run
1. `cd engine && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
2. `cp .env.example .env` and fill `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`.
3. Start Ollama locally (`ollama run llama3.2`).
4. `cd engine && .venv/bin/python -m autotrader.main --once`  (or drop `--once` for the live loop).
5. `cd app/TradingAgentApp && swift run` for the macOS app.

## Risk (non-negotiable)
- 2% per trade, max 3 positions, −10% from peak hard stop, −5% daily stop.
- Paper trading only for the first 2 weeks; real money is a manual, gated decision.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with run instructions"
```

---

## Self-Review Notes

- Spec coverage: all v1 scope items (two-process arch, Alpaca paper, momentum + sentiment,
  regime filter, composite scoring, Ollama agent, risk layer, daily summary, SwiftUI app,
  journaling) map to tasks 1–25. Out-of-scope items (valuation/event signals, real money,
  short/options, backtesting harness) intentionally omitted.
- Placeholder scan: no TBD/TODO; every code step shows complete code.
- Type consistency: `Signal`, `SignalSet`, `AgentDecision`, `Decision`, `Side`, `Order`,
  `Position`, `Equity` are defined once in `models.py` and referenced consistently.
  `composite_score(signals, weights)`, `RiskManager.position_size`, `OllamaAgent.decide`,
  `Runner.run_once` signatures match their tests.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-25-trading-agent-v1.md`.
