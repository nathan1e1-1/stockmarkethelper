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
    timestamp: datetime = field(default_factory=_now)


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
class ClosedTrade:
    ticker: str
    qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    exit_reason: str
    opened_at: datetime = field(default_factory=_now)
    closed_at: datetime = field(default_factory=_now)


@dataclass
class Equity:
    equity: float
    day_start_equity: float
    peak_equity: float
    day: str
