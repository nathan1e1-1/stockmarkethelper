import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from autotrader.models import AgentDecision, ClosedTrade, Decision, Equity, Position, Signal, SignalSet


@dataclass
class State:
    equity: Equity | None = None
    positions: list[Position] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    unrealized_pnl: float = 0.0


def _decode_decision(d: dict) -> AgentDecision:
    decision = Decision(d["decision"]) if isinstance(d.get("decision"), str) else d["decision"]
    timestamp = d.get("timestamp")
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    signals = None
    if isinstance(d.get("signals"), dict):
        ss = d["signals"]
        signals = SignalSet(
            ticker=ss["ticker"],
            signals=[Signal(**s) for s in ss.get("signals", [])],
            composite=ss["composite"],
            regime=ss["regime"],
        )
    return AgentDecision(
        ticker=d["ticker"],
        decision=decision,
        rationale=d.get("rationale", ""),
        confidence=d.get("confidence", 0.0),
        signals=signals,
        timestamp=timestamp,
    )


def _decode_closed_trade(trade: dict) -> ClosedTrade:
    decoded = dict(trade)
    for field_name in ("opened_at", "closed_at"):
        value = decoded.get(field_name)
        if isinstance(value, str):
            decoded[field_name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ClosedTrade(**decoded)


def same_day(state: State, day: str) -> bool:
    return state.equity is not None and state.equity.day == day


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
            decisions=[_decode_decision(d) for d in raw.get("decisions", [])],
            closed_trades=[_decode_closed_trade(c) for c in raw.get("closed_trades", [])],
            unrealized_pnl=raw.get("unrealized_pnl", 0.0),
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(json.dumps(asdict(state), default=str, indent=2))
        except OSError as e:
            print(f"[warn] failed to write journal {self.path}: {e}")
