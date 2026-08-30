from fastapi.testclient import TestClient
from autotrader.history import HistoryRange
from autotrader.ipc import create_app, SharedState
from autotrader.models import AgentDecision, Decision, Equity, Position


def test_status_endpoint():
    state = SharedState()
    state.equity = Equity(equity=99000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    client = TestClient(create_app(state))
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["equity"]["equity"] == 99000.0
    assert body["kill_switch"] is False


def test_status_includes_equity_history():
    state = SharedState()
    state.equity = Equity(equity=99000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    state.equity_history = [
        {"t": 1780000000.0, "equity": 100000.0},
        {"t": 1780000060.0, "equity": 99000.0},
    ]
    client = TestClient(create_app(state))
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["equity_history"] == state.equity_history


def test_summary_endpoint():
    state = SharedState()
    state.summary = "Good day"
    client = TestClient(create_app(state))
    r = client.get("/api/summary")
    assert r.status_code == 200
    assert r.json()["summary"] == "Good day"


def test_bars_endpoint_returns_bars():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def bars(self, ticker, history_range=HistoryRange.ONE_DAY):
            self.calls.append((ticker, history_range))
            return [
                {"t": "2026-08-26T14:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            ]

    state = SharedState()
    provider = FakeProvider()
    client = TestClient(create_app(state, provider=provider))
    r = client.get("/api/bars", params={"ticker": "AAPL"})
    assert r.status_code == 200
    bars = r.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["open"] == 100.0
    assert bars[0]["close"] == 100.5
    assert provider.calls == [("AAPL", HistoryRange.ONE_DAY)]


def test_bars_endpoint_uses_public_range_query_parameter():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def bars(self, ticker, history_range=HistoryRange.ONE_DAY):
            self.calls.append((ticker, history_range))
            return []

    provider = FakeProvider()
    client = TestClient(create_app(SharedState(), provider=provider))

    response = client.get("/api/bars", params={"ticker": "AAPL", "range": "1Y"})

    assert response.status_code == 200
    assert provider.calls == [("AAPL", HistoryRange.ONE_YEAR)]


def test_bars_endpoint_rejects_invalid_public_range_without_calling_provider():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def bars(self, ticker, history_range=HistoryRange.ONE_DAY):
            self.calls.append((ticker, history_range))
            return []

    provider = FakeProvider()
    client = TestClient(create_app(SharedState(), provider=provider))

    response = client.get("/api/bars", params={"ticker": "AAPL", "range": "all-time"})

    assert response.status_code == 422
    assert provider.calls == []


def test_bars_endpoint_empty_without_ticker():
    state = SharedState()
    client = TestClient(create_app(state))
    r = client.get("/api/bars")
    assert r.status_code == 200
    assert r.json()["bars"] == []


def test_assets_endpoint_searches_provider_and_caps_limit():
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def search_assets(self, query, limit=10):
            self.calls.append((query, limit))
            return [{"ticker": "AAPL", "name": "Apple Inc."}]

    provider = FakeProvider()
    client = TestClient(create_app(SharedState(), provider=provider))

    response = client.get("/api/assets", params={"query": "app", "limit": 9999})

    assert response.status_code == 200
    assert response.json() == {"assets": [{"ticker": "AAPL", "name": "Apple Inc."}]}
    assert provider.calls == [("app", 50)]


def test_assets_endpoint_returns_empty_without_provider():
    client = TestClient(create_app(SharedState()))

    response = client.get("/api/assets", params={"query": "app"})

    assert response.status_code == 200
    assert response.json() == {"assets": []}


def test_chat_endpoint_uses_read_only_factual_context_and_user_question():
    class FakeRisk:
        def hard_stop_triggered(self, equity):
            assert equity == 99_000.0
            return True

        def daily_stop_triggered(self, equity):
            assert equity == 99_000.0
            return False

    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt):
            self.prompts.append(prompt)
            return "A cautious, informational answer."

    state = SharedState()
    state.equity = Equity(equity=99_000.0, day_start_equity=100_000.0, peak_equity=101_000.0, day="2026-08-30")
    state.positions = [Position(ticker="AAPL", qty=3, avg_entry_price=190.0)]
    state.decisions = [AgentDecision(ticker="AAPL", decision=Decision.HOLD, rationale="mixed signals", confidence=0.4)]
    state.risk = FakeRisk()
    state.summary = "No completed trades yet."
    llm = FakeLLM()
    client = TestClient(create_app(state, llm=llm))

    response = client.post("/api/chat", json={"question": "What is the current account state?"})

    assert response.status_code == 200
    assert response.json() == {"answer": "A cautious, informational answer."}
    prompt = llm.prompts[0]
    assert "What is the current account state?" in prompt
    assert "equity=99000.0" in prompt
    assert "AAPL" in prompt
    assert "kill_switch=True" in prompt
    assert "No completed trades yet." in prompt
    assert "informational/read-only" in prompt
    assert "no orders" in prompt
    assert "no promised returns" in prompt
    assert "never disable or bypass risk" in prompt
    assert "say when data is missing" in prompt


def test_chat_endpoint_rejects_blank_question():
    client = TestClient(create_app(SharedState(), llm=object()))

    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 422


def test_chat_endpoint_rejects_question_over_2000_characters():
    client = TestClient(create_app(SharedState(), llm=object()))

    response = client.post("/api/chat", json={"question": "x" * 2001})

    assert response.status_code == 422


def test_chat_endpoint_returns_safe_retry_error_when_llm_missing():
    client = TestClient(create_app(SharedState()))

    response = client.post("/api/chat", json={"question": "How is the account?"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Assistant is temporarily unavailable. Please try again shortly."


def test_chat_endpoint_returns_safe_retry_error_when_llm_fails():
    class FailingLLM:
        def complete(self, prompt):
            raise RuntimeError("connection refused")

    client = TestClient(create_app(SharedState(), llm=FailingLLM()))

    response = client.post("/api/chat", json={"question": "How is the account?"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Assistant is temporarily unavailable. Please try again shortly."


def test_create_app_has_no_executor_dependency():
    assert "executor" not in create_app.__code__.co_varnames
