import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from autotrader.models import AgentDecision, Decision, Equity, Position, Signal, SignalSet


@dataclass
class State:
    equity: Equity | None = None
    positions: list[Position] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)


def _decode_decision(d: dict) -> AgentDecision:
    decision = Decision(d["decision"]) if isinstance(d.get("decision"), str) else d["decision"]
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
    )


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
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(state), default=str, indent=2))
