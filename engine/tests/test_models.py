from datetime import datetime, timezone

import autotrader.models as models
from autotrader.models import (
    AgentDecision,
    ClosedTrade,
    Decision,
    Order,
    Side,
    Signal,
    SignalSet,
)


def test_signalset_composite_is_stored():
    s = Signal(name="momentum", value=0.6, detail={"sma20": 1.05})
    ss = SignalSet(ticker="AAPL", signals=[s], composite=0.55, regime="trending")
    assert ss.composite == 0.55
    assert ss.signals[0].name == "momentum"


def test_agent_decision_defaults_to_hold():
    d = AgentDecision(ticker="AAPL", decision=Decision.HOLD, rationale="n/a", confidence=0.1)
    assert d.decision is Decision.HOLD
    assert d.confidence == 0.1


def test_agent_decision_timestamp_defaults_to_timezone_aware_now():
    decision = AgentDecision(ticker="AAPL", decision=Decision.HOLD, rationale="n/a", confidence=0.1)

    assert decision.timestamp.tzinfo is not None
    assert decision.timestamp.utcoffset() is not None


def test_agent_decision_allows_missing_legacy_timestamp():
    decision = AgentDecision(
        ticker="AAPL",
        decision=Decision.HOLD,
        rationale="legacy",
        confidence=0.1,
        timestamp=None,
    )

    assert decision.timestamp is None


def test_closed_trade_fields():
    t = ClosedTrade(ticker="AAPL", qty=10.0, entry_price=100.0, exit_price=103.0, realized_pnl=30.0, exit_reason="take_profit")
    assert t.realized_pnl == 30.0
    assert t.exit_reason == "take_profit"
    assert t.qty == 10.0


def test_safety_records_normalize_timestamps_and_order_fill_fields():
    timestamp = datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)
    quote = models.Quote("AAPL", 100.0, timestamp, timestamp)
    reservation = models.Reservation("entry-20260901-AAPL", "AAPL", 2.0, 100.0, timestamp)
    order = Order(
        id="broker-1",
        ticker="AAPL",
        side=Side.BUY,
        qty=2.0,
        client_order_id="entry-20260901-AAPL",
        filled_qty=1.0,
        filled_notional=100.0,
        processed_filled_qty=1.0,
        processed_filled_notional=100.0,
        observed_at=timestamp,
    )

    assert models.RiskState.ACTIVE.value == "active"
    assert quote.source_timestamp is timestamp
    assert quote.observed_at is timestamp
    assert reservation.created_at is timestamp
    assert order.client_order_id == reservation.client_order_id
    assert order.filled_qty == order.processed_filled_qty == 1.0
    assert order.filled_notional == order.processed_filled_notional == 100.0
    assert order.observed_at is timestamp


def test_order_safety_fields_have_legacy_safe_defaults():
    order = Order(id="legacy", ticker="AAPL", side=Side.BUY, qty=1.0)

    assert order.client_order_id is None
    assert order.filled_qty is None
    assert order.filled_notional is None
    assert order.processed_filled_qty == 0.0
    assert order.processed_filled_notional == 0.0
    assert order.observed_at is None
