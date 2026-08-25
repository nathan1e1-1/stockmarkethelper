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
