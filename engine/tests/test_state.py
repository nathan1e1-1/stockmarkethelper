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
    t = ClosedTrade(ticker="NVDA", qty=10.0, entry_price=100.0, exit_price=103.0, realized_pnl=30.0, exit_reason="take_profit")
    store.save(State(closed_trades=[t]))
    loaded = store.load()
    assert len(loaded.closed_trades) == 1
    assert loaded.closed_trades[0].realized_pnl == 30.0
    assert loaded.closed_trades[0].exit_reason == "take_profit"
