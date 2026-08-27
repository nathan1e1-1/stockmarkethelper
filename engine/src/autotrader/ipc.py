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
        self.equity_history: list = []


def create_app(state: SharedState, provider=None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        eq = state.equity
        body = {
            "equity": asdict(eq) if eq else None,
            "positions": [asdict(p) for p in state.positions],
            "decisions": [asdict(d) for d in state.decisions],
            "equity_history": state.equity_history,
            "kill_switch": state.risk.hard_stop_triggered(eq.equity) if (state.risk and eq) else False,
            "daily_stop": state.risk.daily_stop_triggered(eq.equity) if (state.risk and eq) else False,
        }
        return body

    @app.get("/api/summary")
    def summary() -> dict[str, str]:
        return {"summary": state.summary}

    @app.get("/api/bars")
    def bars(ticker: str = "", limit: int = 80) -> dict[str, Any]:
        if not ticker or provider is None:
            return {"bars": []}
        try:
            return {"bars": provider.bars(ticker.upper(), limit=limit)}
        except Exception:
            return {"bars": []}

    return app
