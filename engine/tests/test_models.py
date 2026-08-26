from autotrader.models import Signal, SignalSet, Decision, AgentDecision, ClosedTrade


def test_signalset_composite_is_stored():
    s = Signal(name="momentum", value=0.6, detail={"sma20": 1.05})
    ss = SignalSet(ticker="AAPL", signals=[s], composite=0.55, regime="trending")
    assert ss.composite == 0.55
    assert ss.signals[0].name == "momentum"


def test_agent_decision_defaults_to_hold():
    d = AgentDecision(ticker="AAPL", decision=Decision.HOLD, rationale="n/a", confidence=0.1)
    assert d.decision is Decision.HOLD
    assert d.confidence == 0.1


def test_closed_trade_fields():
    t = ClosedTrade(ticker="AAPL", qty=10.0, entry_price=100.0, exit_price=103.0, realized_pnl=30.0, exit_reason="take_profit")
    assert t.realized_pnl == 30.0
    assert t.exit_reason == "take_profit"
    assert t.qty == 10.0
