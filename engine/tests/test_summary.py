from autotrader.summary import daily_summary
from autotrader.state import State
from autotrader.models import Equity, AgentDecision, Decision, SignalSet, Signal, Position


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Good day: momentum entries worked; exits were too early."


def _eq():
    return Equity(equity=101000.0, day_start_equity=100000.0, peak_equity=101500.0, day="2026-08-25")


def test_daily_summary_returns_text():
    llm = FakeLLM()
    state = State(equity=_eq(), decisions=[AgentDecision(ticker="AAPL", decision=Decision.BUY, rationale="trend", confidence=0.8)])
    out = daily_summary(state, llm)
    assert "Good day" in out
    assert len(llm.prompts) == 1


def test_daily_summary_includes_real_decisions():
    llm = FakeLLM()
    state = State(
        equity=_eq(),
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
    state = State(equity=_eq(), decisions=[])
    daily_summary(state, llm)
    assert "No trades were placed today" in llm.prompts[0]


def test_daily_summary_includes_positions():
    llm = FakeLLM()
    state = State(equity=_eq(), decisions=[], positions=[Position(ticker="AAPL", qty=20.0, avg_entry_price=150.0)])
    daily_summary(state, llm)
    prompt = llm.prompts[0]
    assert "AAPL" in prompt
    assert "150.00" in prompt


def test_daily_summary_forbids_outcome_claims():
    llm = FakeLLM()
    state = State(equity=_eq(), decisions=[])
    daily_summary(state, llm)
    assert "per-trade results are not available" in llm.prompts[0]
