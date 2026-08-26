from autotrader.summary import daily_summary
from autotrader.state import State
from autotrader.models import Equity, AgentDecision, Decision, SignalSet, Signal


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Good day: momentum entries worked; exits were too early."


def test_daily_summary_returns_text():
    llm = FakeLLM()
    state = State(equity=Equity(equity=101000.0, day_start_equity=100000.0, peak_equity=101500.0, day="2026-08-25"),
                  decisions=[AgentDecision(ticker="AAPL", decision=Decision.BUY, rationale="trend", confidence=0.8)])
    out = daily_summary(state, llm)
    assert "Good day" in out
    assert len(llm.prompts) == 1


def test_daily_summary_includes_real_decisions():
    llm = FakeLLM()
    state = State(
        equity=Equity(equity=101000.0, day_start_equity=100000.0, peak_equity=101500.0, day="2026-08-25"),
        decisions=[AgentDecision(
            ticker="AAPL",
            decision=Decision.BUY,
            rationale="trend",
            confidence=0.8,
            signals=SignalSet(ticker="AAPL", signals=[Signal("momentum", 0.6)], composite=0.6, regime="trending"),
        )],
    )
    daily_summary(state, llm)
    prompt = llm.prompts[0]
    assert "AAPL" in prompt
    assert "buy" in prompt
    assert "trend" in prompt
    assert "momentum" in prompt


def test_daily_summary_no_trades_is_explicit():
    llm = FakeLLM()
    state = State(equity=Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-25"),
                  decisions=[])
    daily_summary(state, llm)
    assert "No trades were placed today" in llm.prompts[0]
