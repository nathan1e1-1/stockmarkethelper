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
