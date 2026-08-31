from datetime import datetime, timezone

from autotrader.state import StateStore, State
from autotrader.models import Equity


def test_state_roundtrips(tmp_path):
    store = StateStore(tmp_path)
    eq = Equity(equity=98000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-25")
    store.save(State(equity=eq, positions=[], decisions=[]))
    loaded = store.load()
    assert loaded.equity.equity == 98000.0
    assert loaded.equity.day == "2026-08-25"


def test_load_missing_returns_fresh_state(tmp_path):
    store = StateStore(tmp_path)
    state = store.load()
    assert state.equity is None
    assert state.positions == []


from autotrader.models import Decision, AgentDecision, ClosedTrade

def test_state_roundtrips_decision_type(tmp_path):
    store = StateStore(tmp_path)
    store.save(State(positions=[], decisions=[AgentDecision(ticker="AAPL", decision=Decision.BUY, rationale="t", confidence=0.7)]))
    loaded = store.load()
    assert loaded.decisions[0].decision is Decision.BUY


def test_state_roundtrips_closed_trades(tmp_path):
    store = StateStore(tmp_path)
    t = ClosedTrade(
        ticker="NVDA",
        qty=10.0,
        entry_price=100.0,
        exit_price=103.0,
        realized_pnl=30.0,
        exit_reason="take_profit",
        closed_at=datetime(2026, 8, 31, 15, tzinfo=timezone.utc),
    )
    store.save(State(closed_trades=[t]))
    loaded = store.load()
    assert len(loaded.closed_trades) == 1
    assert loaded.closed_trades[0].realized_pnl == 30.0
    assert loaded.closed_trades[0].exit_reason == "take_profit"
    assert loaded.closed_trades[0].closed_at == t.closed_at


def test_save_survives_disk_full(tmp_path, monkeypatch):
    from pathlib import Path

    def boom(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    store = StateStore(tmp_path)
    eq = Equity(equity=98000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-25")
    monkeypatch.setattr(Path, "write_text", boom)
    store.save(State(equity=eq))  # must not raise


def test_same_day_true_when_equity_day_matches():
    from autotrader.state import same_day
    state = State(equity=Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-28"))
    assert same_day(state, "2026-08-28") is True


def test_same_day_false_when_different_day():
    from autotrader.state import same_day
    state = State(equity=Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-27"))
    assert same_day(state, "2026-08-28") is False


def test_same_day_false_without_equity():
    from autotrader.state import same_day
    assert same_day(State(), "2026-08-28") is False
