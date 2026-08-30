from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from autotrader.history import HistoryRange
from autotrader.models import Equity


class SharedState:
    def __init__(self):
        self.equity: Equity | None = None
        self.positions: list = []
        self.decisions: list = []
        self.summary: str = ""
        self.risk = None
        self.equity_history: list = []


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


def _chat_context(state: SharedState) -> str:
    equity = state.equity
    if equity is None:
        equity_text = "equity data missing"
        kill_switch = "unknown"
        daily_stop = "unknown"
    else:
        equity_text = (
            f"equity={equity.equity}; day_start_equity={equity.day_start_equity}; "
            f"peak_equity={equity.peak_equity}; day={equity.day}"
        )
        kill_switch = state.risk.hard_stop_triggered(equity.equity) if state.risk else "unknown"
        daily_stop = state.risk.daily_stop_triggered(equity.equity) if state.risk else "unknown"

    positions = ", ".join(
        f"{position.ticker} qty={position.qty} avg_entry_price={position.avg_entry_price}"
        for position in state.positions
    ) or "none"
    decisions = ", ".join(
        f"{decision.ticker} decision={decision.decision} confidence={decision.confidence} rationale={decision.rationale}"
        for decision in state.decisions
    ) or "none"

    return (
        f"Account: {equity_text}\n"
        f"Positions: {positions}\n"
        f"Recent decisions: {decisions}\n"
        f"Risk: kill_switch={kill_switch}; daily_stop={daily_stop}\n"
        f"Summary: {state.summary or 'missing'}"
    )


def create_app(state: SharedState, provider=None, llm=None) -> FastAPI:
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

    @app.get("/api/assets")
    def assets(query: str = "", limit: int = Query(10, ge=1)) -> dict[str, list]:
        if provider is None:
            return {"assets": []}
        try:
            return {"assets": provider.search_assets(query, limit=min(limit, 50))}
        except Exception:
            return {"assets": []}

    @app.get("/api/bars")
    def bars(
        ticker: str = "",
        history_range: HistoryRange = Query(HistoryRange.ONE_DAY, alias="range"),
    ) -> dict[str, Any]:
        if not ticker or provider is None:
            return {"bars": []}
        try:
            return {"bars": provider.bars(ticker.upper(), history_range=history_range)}
        except Exception:
            return {"bars": []}

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, str]:
        if llm is None:
            raise HTTPException(
                status_code=503,
                detail="Assistant is temporarily unavailable. Please try again shortly.",
            )

        prompt = (
            "Answer the user's question using the factual context below. This is an "
            "informational/read-only assistant: no orders, no promised returns, never "
            "disable or bypass risk controls, and say when data is missing.\n\n"
            f"Factual context:\n{_chat_context(state)}\n\n"
            f"User question: {request.question}"
        )
        try:
            return {"answer": str(llm.complete(prompt))}
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Assistant is temporarily unavailable. Please try again shortly.",
            ) from error

    return app
