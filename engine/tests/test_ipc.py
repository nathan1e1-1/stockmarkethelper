from fastapi.testclient import TestClient
from autotrader.ipc import create_app, SharedState
from autotrader.models import Equity


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
        def bars(self, ticker, limit=80):
            return [
                {"t": "2026-08-26T14:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            ]

    state = SharedState()
    client = TestClient(create_app(state, provider=FakeProvider()))
    r = client.get("/api/bars", params={"ticker": "AAPL"})
    assert r.status_code == 200
    bars = r.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["open"] == 100.0
    assert bars[0]["close"] == 100.5


def test_bars_endpoint_empty_without_ticker():
    state = SharedState()
    client = TestClient(create_app(state))
    r = client.get("/api/bars")
    assert r.status_code == 200
    assert r.json()["bars"] == []
