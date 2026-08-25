from autotrader.agent import OllamaAgent, parse_decision
from autotrader.models import Decision, SignalSet, Signal


class FakeSession:
    def __init__(self, text):
        self._text = text

    def post(self, url, json, timeout):
        return FakeResponse(self._text)


class FakeResponse:
    def __init__(self, text):
        self._text = text

    def json(self):
        return {"response": self._text}

    def raise_for_status(self):
        pass


def test_parse_decision_buy():
    assert parse_decision('{"decision": "buy", "confidence": 0.8, "rationale": "strong momentum"}') == Decision.BUY


def test_agent_returns_decision_from_llm():
    import json
    payload = {"decision": "buy", "confidence": 0.8, "rationale": "trend up"}
    agent = OllamaAgent(base_url="http://x", model="m", session=FakeSession(json.dumps(payload)))
    ss = SignalSet(ticker="AAPL", signals=[Signal("momentum", 0.6)], composite=0.55, regime="trending")
    d = agent.decide(ss)
    assert d.ticker == "AAPL"
    assert d.decision == Decision.BUY
    assert d.confidence == 0.8


def test_agent_sentiment_returns_float():
    import json
    payload = {"sentiment": 0.4}
    agent = OllamaAgent(base_url="http://x", model="m", session=FakeSession(json.dumps(payload)))
    assert agent.sentiment(["AAPL beats earnings"]) == 0.4
