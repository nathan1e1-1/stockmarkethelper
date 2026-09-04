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


class RiskState(str, Enum):
    ACTIVE = "active"
    HALTING = "halting"
    HALTED = "halted"


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
    timestamp: datetime | None = field(default_factory=_now)


@dataclass
class Order:
    id: str
    ticker: str
    side: Side
    qty: float
    filled_avg_price: float | None = None
    status: str = "submitted"
    timestamp: datetime = field(default_factory=_now)
    client_order_id: str | None = None
    filled_qty: float | None = None
    filled_notional: float | None = None
    processed_filled_qty: float = 0.0
    processed_filled_notional: float = 0.0
    observed_at: datetime | None = None


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    source_timestamp: datetime
    observed_at: datetime


@dataclass
class Reservation:
    client_order_id: str
    ticker: str
    qty: float
    limit_price: float
    created_at: datetime


@dataclass
class Position:
    ticker: str
    qty: float
    avg_entry_price: float
    opened_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float | None
    observed_at: datetime


@dataclass(frozen=True)
class PositionsSnapshot:
    positions: list[Position] | None
    observed_at: datetime


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
