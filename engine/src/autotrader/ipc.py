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
