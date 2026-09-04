import json
import os
from datetime import datetime, timezone

import pytest

from autotrader.state import StatePersistenceError, StateStore, State
from autotrader.models import Equity, Order, Reservation, RiskState, Side


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


def test_state_roundtrips_decision_timestamp(tmp_path):
    store = StateStore(tmp_path)
    timestamp = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    decision = AgentDecision(
        ticker="AAPL",
        decision=Decision.BUY,
        rationale="t",
        confidence=0.7,
        timestamp=timestamp,
    )

    store.save(State(decisions=[decision]))

    loaded = store.load()
    assert loaded.decisions[0].timestamp == timestamp


def test_load_legacy_decision_without_timestamp_preserves_missing_timestamp(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({"decisions": [{
        "ticker": "AAPL",
        "decision": "buy",
        "rationale": "legacy",
        "confidence": 0.7,
    }]}))

    loaded = store.load()
    assert loaded.decisions[0].timestamp is None


def test_state_roundtrips_closed_trades(tmp_path):
    store = StateStore(tmp_path)
    t = ClosedTrade(
        ticker="NVDA",
        qty=10.0,
        entry_price=100.0,
        exit_price=103.0,
        realized_pnl=30.0,
        exit_reason="take_profit",
        opened_at=datetime(2026, 8, 31, 14, tzinfo=timezone.utc),
        closed_at=datetime(2026, 8, 31, 15, tzinfo=timezone.utc),
    )
    store.save(State(closed_trades=[t]))
    loaded = store.load()
    assert len(loaded.closed_trades) == 1
    assert loaded.closed_trades[0].realized_pnl == 30.0
    assert loaded.closed_trades[0].exit_reason == "take_profit"
    assert loaded.closed_trades[0].closed_at == t.closed_at


def test_save_survives_disk_full(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")

    store = StateStore(tmp_path)
    eq = Equity(equity=98000.0, day_start_equity=100000.0, peak_equity=100000.0, day="2026-08-25")
    monkeypatch.setattr(os, "replace", boom)
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


def pending_order(client_order_id="entry-1"):
    return Order(
        id="broker-1",
        client_order_id=client_order_id,
        ticker="AAPL",
        side=Side.BUY,
        qty=2.0,
        status="submitted",
        timestamp=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
        observed_at=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
    )


def active_safety_payload(*, pending_orders=None, **base_fields):
    payload = {
        "risk_state": "active",
        "halt_reason": None,
        "session_id": "2026-09-01",
        "session_entry_count": 0,
        "cutoff_latched": False,
        "reservations": [],
        "pending_orders": pending_orders or [],
    }
    payload.update(base_fields)
    return payload


def pending_order_payload(**fields):
    payload = {
        "id": "broker-1",
        "client_order_id": "entry-1",
        "ticker": "AAPL",
        "side": "buy",
        "qty": 2.0,
        "status": "accepted",
        "timestamp": "2026-09-01T14:00:00+00:00",
        "filled_avg_price": 100.0,
        "filled_qty": 1.0,
        "filled_notional": 100.0,
        "processed_filled_qty": 0.0,
        "processed_filled_notional": 0.0,
        "observed_at": "2026-09-01T14:00:00+00:00",
    }
    payload.update(fields)
    return payload


def closed_trade_payload(**fields):
    payload = {
        "ticker": "AAPL",
        "qty": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "realized_pnl": 1.0,
        "exit_reason": "broker_confirmed_exit",
        "opened_at": "2026-09-01T14:00:00+00:00",
        "closed_at": "2026-09-01T14:01:00+00:00",
    }
    payload.update(fields)
    return payload


def reservation_payload(**fields):
    payload = {
        "client_order_id": "entry-1",
        "ticker": "AAPL",
        "qty": 2.0,
        "limit_price": 100.0,
        "created_at": "2026-09-01T14:00:00+00:00",
    }
    payload.update(fields)
    return payload


def test_state_roundtrips_halt_session_reservation_and_pending_order(tmp_path):
    store = StateStore(tmp_path)
    reservation = Reservation(
        client_order_id="entry-1",
        ticker="AAPL",
        qty=2.0,
        limit_price=100.0,
        created_at=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
    )
    state = State(
        risk_state=RiskState.HALTING,
        halt_reason="daily_stop",
        session_id="2026-09-01",
        session_entry_count=1,
        cutoff_latched=True,
        reservations=[reservation],
        pending_orders=[pending_order()],
    )

    store.save_or_raise(state)

    loaded = store.load()
    assert loaded.risk_state is RiskState.HALTING
    assert loaded.halt_reason == "daily_stop"
    assert loaded.session_id == "2026-09-01"
    assert loaded.session_entry_count == 1
    assert loaded.cutoff_latched is True
    assert loaded.reservations == [reservation]
    assert loaded.pending_orders == [pending_order()]


def test_pre_submit_write_failure_is_signalled_and_temporary_file_is_cleaned(tmp_path, monkeypatch):
    store = StateStore(tmp_path)

    def raise_os_error(*args, **kwargs):
        raise OSError("disk write failed")

    monkeypatch.setattr(os, "replace", raise_os_error)

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State())
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_legacy_state_is_halted_until_reconciled(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text('{"positions": []}')

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "legacy_state_requires_reconciliation"
    assert loaded.session_id == ""
    assert loaded.session_entry_count == 0
    assert loaded.cutoff_latched is False
    assert loaded.reservations == []
    assert loaded.pending_orders == []


def test_invalid_safety_serialization_fails_closed_with_safe_defaults(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({
        "risk_state": "not-a-real-state",
        "session_entry_count": "many",
        "reservations": [{"ticker": "AAPL"}],
        "pending_orders": [{"id": "broker-1"}],
    }))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"
    assert loaded.session_id == ""
    assert loaded.session_entry_count == 0
    assert loaded.cutoff_latched is False
    assert loaded.reservations == []
    assert loaded.pending_orders == []


def test_partial_active_safety_record_fails_closed_instead_of_resetting_its_budget(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({"risk_state": "active"}))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


def test_nonfinite_reservation_notional_fails_closed(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({
        "risk_state": "active",
        "halt_reason": None,
        "session_id": "2026-09-01",
        "session_entry_count": 0,
        "cutoff_latched": False,
        "pending_orders": [],
        "reservations": [{
            "client_order_id": "entry-1",
            "ticker": "AAPL",
            "qty": float("nan"),
            "limit_price": 100.0,
            "created_at": "2026-09-01T14:00:00+00:00",
        }],
    }))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


@pytest.mark.parametrize("invalid_order", [
    pending_order_payload(status="invented"),
    pending_order_payload(timestamp="2026-09-01T14:00:00"),
    pending_order_payload(observed_at=None),
    pending_order_payload(filled_qty=float("nan")),
    pending_order_payload(processed_filled_notional=-1.0),
    pending_order_payload(processed_filled_qty=1.5),
    pending_order_payload(filled_qty=2.5, filled_notional=250.0),
    pending_order_payload(filled_qty=0.0, filled_notional=1.0),
    pending_order_payload(filled_qty=1.0, filled_notional=0.0),
])
def test_invalid_pending_order_lifecycle_data_fails_closed(tmp_path, invalid_order):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(pending_orders=[invalid_order])))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


@pytest.mark.parametrize("base_fields", [
    {"equity": {"equity": float("nan"), "day_start_equity": 100.0, "peak_equity": 100.0, "day": "2026-09-01"}},
    {"positions": [{"ticker": "AAPL", "qty": float("nan"), "avg_entry_price": 100.0, "opened_at": "2026-09-01T14:00:00+00:00"}]},
    {"positions": [{"ticker": "AAPL", "qty": 1.0, "avg_entry_price": -1.0, "opened_at": "2026-09-01T14:00:00+00:00"}]},
    {"unrealized_pnl": float("nan")},
])
def test_invalid_broker_accounting_data_fails_closed(tmp_path, base_fields):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(**base_fields)))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


@pytest.mark.parametrize("invalid_trade", [
    closed_trade_payload(realized_pnl=float("nan")),
    closed_trade_payload(qty=0.0),
    closed_trade_payload(exit_price=float("inf")),
    closed_trade_payload(ticker=""),
    closed_trade_payload(closed_at="2026-09-01T14:01:00"),
])
def test_invalid_closed_trade_accounting_fails_closed(tmp_path, invalid_trade):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(closed_trades=[invalid_trade])))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


def test_save_or_raise_rejects_nonfinite_json_and_cleans_temporary_file(tmp_path):
    store = StateStore(tmp_path)

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State(unrealized_pnl=float("nan")))

    assert not store.path.exists()
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_save_or_raise_rejects_invalid_active_state_without_replacing_durable_state(tmp_path):
    store = StateStore(tmp_path)
    store.save_or_raise(State(unrealized_pnl=12.0))
    previous_contents = store.path.read_text()
    invalid_reservation = Reservation(
        client_order_id="entry-1",
        ticker="AAPL",
        qty=1.0,
        limit_price=100.0,
        created_at=datetime(2026, 9, 1, 14),
    )

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State(reservations=[invalid_reservation]))

    assert store.path.read_text() == previous_contents
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


@pytest.mark.parametrize("filled_order", [
    pending_order_payload(status="filled", filled_qty=1.0, filled_notional=100.0),
    pending_order_payload(status="filled", filled_avg_price=None, filled_qty=None, filled_notional=None),
])
def test_terminal_filled_order_requires_full_known_cumulative_fill(tmp_path, filled_order):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation_payload()],
        pending_orders=[filled_order],
    )))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


@pytest.mark.parametrize("reservations,pending_orders", [
    ([], [pending_order_payload()]),
    ([reservation_payload()], [pending_order_payload(ticker="MSFT")]),
    (
        [reservation_payload(), reservation_payload(client_order_id="entry-2", ticker="MSFT")],
        [pending_order_payload(), pending_order_payload(client_order_id="entry-2", id="broker-1", ticker="MSFT")],
    ),
    (
        [reservation_payload()],
        [pending_order_payload(), pending_order_payload(id="broker-2")],
    ),
    ([reservation_payload(), reservation_payload()], []),
])
def test_orphan_mismatched_or_duplicate_order_intent_fails_closed(tmp_path, reservations, pending_orders):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=reservations,
        pending_orders=pending_orders,
    )))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


def test_save_or_raise_rejects_orphan_pending_buy_before_replacing_durable_state(tmp_path):
    store = StateStore(tmp_path)
    store.save_or_raise(State(unrealized_pnl=12.0))
    previous_contents = store.path.read_text()

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State(pending_orders=[pending_order()]))

    assert store.path.read_text() == previous_contents


def test_pending_buy_quantity_must_match_its_reservation_and_preflight_rejects_it(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation_payload(qty=2.0)],
        pending_orders=[pending_order_payload(qty=1.0, filled_qty=0.0, filled_notional=0.0)],
    )))

    assert store.load().risk_state is RiskState.HALTED

    store.save_or_raise(State(unrealized_pnl=12.0))
    previous_contents = store.path.read_text()
    reservation = Reservation(
        client_order_id="entry-1",
        ticker="AAPL",
        qty=2.0,
        limit_price=100.0,
        created_at=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
    )
    mismatched_order = pending_order()
    mismatched_order.qty = 1.0

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State(reservations=[reservation], pending_orders=[mismatched_order]))

    assert store.path.read_text() == previous_contents


def test_reservation_client_id_cannot_be_reused_by_a_pending_sell(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation_payload()],
        pending_orders=[pending_order_payload(side="sell")],
    )))

    loaded = store.load()

    assert loaded.risk_state is RiskState.HALTED
    assert loaded.halt_reason == "invalid_persisted_safety_state"


def test_pending_buy_fill_price_cannot_exceed_its_reservation_limit(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation_payload(limit_price=100.0)],
        pending_orders=[pending_order_payload(filled_avg_price=101.0, filled_qty=1.0, filled_notional=101.0)],
    )))

    assert store.load().risk_state is RiskState.HALTED


def test_partial_buy_reservation_tracks_remaining_quantity_in_decode_and_save_preflight(tmp_path):
    reservation = reservation_payload(qty=1.0)
    partial_order = pending_order_payload(
        status="partially_filled",
        qty=2.0,
        filled_qty=1.0,
        filled_notional=100.0,
        processed_filled_qty=1.0,
        processed_filled_notional=100.0,
    )
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation],
        pending_orders=[partial_order],
    )))

    assert store.load().risk_state is RiskState.ACTIVE

    persisted_reservation = Reservation(
        client_order_id="entry-1",
        ticker="AAPL",
        qty=1.0,
        limit_price=100.0,
        created_at=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
    )
    persisted_order = pending_order()
    persisted_order.status = "partially_filled"
    persisted_order.filled_avg_price = 100.0
    persisted_order.filled_qty = 1.0
    persisted_order.filled_notional = 100.0
    persisted_order.processed_filled_qty = 1.0
    persisted_order.processed_filled_notional = 100.0

    store.save_or_raise(State(reservations=[persisted_reservation], pending_orders=[persisted_order]))
    assert store.load().risk_state is RiskState.ACTIVE


def test_partial_fill_slices_cannot_exceed_the_reservation_limit_in_decode_or_preflight(tmp_path):
    invalid_reservation = reservation_payload(qty=7.0, limit_price=100.0)
    invalid_order = pending_order_payload(
        status="partially_filled",
        qty=10.0,
        filled_avg_price=100.0,
        filled_qty=5.0,
        filled_notional=500.0,
        processed_filled_qty=3.0,
        processed_filled_notional=1.0,
    )
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[invalid_reservation],
        pending_orders=[invalid_order],
    )))

    assert store.load().risk_state is RiskState.HALTED

    store.save_or_raise(State(unrealized_pnl=12.0))
    previous_contents = store.path.read_text()
    persisted_reservation = Reservation(
        client_order_id="entry-1",
        ticker="AAPL",
        qty=7.0,
        limit_price=100.0,
        created_at=datetime(2026, 9, 1, 14, tzinfo=timezone.utc),
    )
    persisted_order = pending_order()
    persisted_order.status = "partially_filled"
    persisted_order.qty = 10.0
    persisted_order.filled_avg_price = 100.0
    persisted_order.filled_qty = 5.0
    persisted_order.filled_notional = 500.0
    persisted_order.processed_filled_qty = 3.0
    persisted_order.processed_filled_notional = 1.0

    with pytest.raises(StatePersistenceError, match="failed to persist"):
        store.save_or_raise(State(reservations=[persisted_reservation], pending_orders=[persisted_order]))

    assert store.path.read_text() == previous_contents


def test_partial_fill_price_improvement_with_coherent_slices_remains_active(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps(active_safety_payload(
        reservations=[reservation_payload(qty=7.0, limit_price=100.0)],
        pending_orders=[pending_order_payload(
            status="partially_filled",
            qty=10.0,
            filled_avg_price=98.0,
            filled_qty=5.0,
            filled_notional=490.0,
            processed_filled_qty=3.0,
            processed_filled_notional=291.0,
        )],
    )))

    assert store.load().risk_state is RiskState.ACTIVE
