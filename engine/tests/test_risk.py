from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import inf, nan
from threading import Event, Lock, Thread

import pytest

from autotrader.models import Order, Position, Reservation, RiskState, Side
from autotrader.risk import RiskManager


@dataclass
class InitialPaperCfg:
    paper_capital: float = 100_000.0
    max_position_pct: float = 0.0025
    max_gross_exposure_pct: float = 0.0025
    max_positions: int = 1
    max_entries_per_session: int = 1
    max_snapshot_age_seconds: int = 120
    kill_switch_pct: float = 0.10
    daily_loss_pct: float = 0.05


class NoHash(str):
    __hash__ = None


class ExplodingStrip(str):
    def strip(self):
        raise RuntimeError("hostile ticker")


class ExplodingHash(str):
    def __hash__(self):
        raise RuntimeError("hostile hash")


class ExplodingFormat(str):
    def __format__(self, format_spec):
        raise RuntimeError("hostile format")


class ExplodingEquality(str):
    __hash__ = str.__hash__

    def __eq__(self, other):
        raise RuntimeError("hostile equality")


class Boom(str):
    def __format__(self, format_spec):
        raise RuntimeError("hostile session")


class HostileClockDate:
    def isoformat(self):
        return Boom("2026-09-01")


class HostileClockValue:
    def date(self):
        return HostileClockDate()


class ExplodingClockNow(datetime):
    def utcoffset(self):
        raise RuntimeError("hostile clock")


class ExplodingClockDate(date):
    def __eq__(self, other):
        raise RuntimeError("hostile clock date")


class ExplodingRearmClock(datetime):
    def date(self):
        return ExplodingClockDate(2026, 9, 2)


@pytest.fixture
def now():
    return datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def risk(now):
    return RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")


def test_position_size_uses_initial_paper_position_cap():
    rm = RiskManager(InitialPaperCfg())

    assert rm.position_size("AAPL", price=100.0, equity=100_000.0) == 2


def test_restore_persisted_safety_state_rebuilds_pending_buy_tracking_without_private_access(now):
    rm = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = Reservation("entry-2026-09-01-AAPL", "AAPL", 2.0, 100.0, now)
    pending = Order(
        "broker-1", "AAPL", Side.BUY, 2.0, status="accepted",
        client_order_id=reservation.client_order_id, timestamp=now, observed_at=now,
        filled_qty=0.0, filled_notional=0.0,
    )

    assert rm.restore_persisted_safety_state(
        positions=[],
        reservations=[reservation],
        pending_orders=[pending],
        risk_state=RiskState.ACTIVE,
        halt_reason=None,
        session_id="2026-09-01",
        session_entry_count=1,
        cutoff_latched=False,
    ) is True
    assert rm.apply_terminal_order("broker-1", "rejected", 0.0, 0.0) is True
    assert rm.reservations == {}


def test_hostile_session_id_is_halted_before_entry_reservation(now):
    risk = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id=Boom("2026-09-01"))

    admission = risk.reserve_entry("AAPL", 1, 100, 100_000, now)
    assert risk.state is RiskState.HALTING
    assert admission.accepted is False
    assert admission.reason == "invalid_session"
    assert risk.reservations == {}


def test_hostile_clock_derived_session_is_halted_before_entry_reservation(now):
    risk = RiskManager(InitialPaperCfg(), clock=lambda: HostileClockValue())

    admission = risk.reserve_entry("AAPL", 1, 100, 100_000, now)

    assert risk.state is RiskState.HALTING
    assert admission.accepted is False
    assert admission.reason == "invalid_session"
    assert risk.reservations == {}


def test_first_reservation_blocks_second_symbol_in_same_scan(risk, now):
    assert risk.reserve_entry("AAPL", 2, 100, 100_000, now).accepted

    second = risk.reserve_entry("MSFT", 1, 100, 100_000, now)

    assert second.accepted is False
    assert second.reason == "max_positions"


def test_concurrent_admission_reserves_only_one_initial_profile_position(risk, now, monkeypatch):
    original_position_count = risk._position_count
    call_lock = Lock()
    first_call_waiting = Event()
    second_call_waiting = Event()
    release_first_call = Event()
    calls = 0

    def synchronized_position_count():
        nonlocal calls
        position_count = original_position_count()
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_call_waiting.set()
            release_first_call.wait(timeout=1)
        else:
            second_call_waiting.set()
            release_first_call.set()
        return position_count

    monkeypatch.setattr(risk, "_position_count", synchronized_position_count)
    admissions = []

    first = Thread(target=lambda: admissions.append(risk.reserve_entry("AAPL", 1, 100, 100_000, now)))
    first.start()
    assert first_call_waiting.wait(timeout=1)
    second = Thread(target=lambda: admissions.append(risk.reserve_entry("MSFT", 1, 100, 100_000, now)))
    second.start()
    second_call_waiting.wait(timeout=0.1)
    release_first_call.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sum(admission.accepted for admission in admissions) == 1
    assert len(risk.reservations) == 1


def test_duplicate_ticker_is_blocked_across_open_pending_and_reserved_states(risk, now):
    risk.positions = [Position(ticker="AAPL", qty=1, avg_entry_price=100.0)]
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "duplicate_ticker"

    risk.positions = []
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "duplicate_ticker"

    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "duplicate_ticker"


@pytest.mark.parametrize("ticker", [None, "", " ", [], {}, 1])
def test_can_enter_rejects_malformed_tickers(risk, ticker):
    assert risk.can_enter(ticker) is False


def test_entry_admission_rejects_a_ticker_with_hostile_strip_override(risk, now):
    ticker = ExplodingStrip("AAPL")

    assert risk.can_enter(ticker) is False
    admission = risk.reserve_entry(ticker, 1, 100, 100_000, now)
    assert admission.accepted is False
    assert admission.reason == "invalid_input"


def test_entry_admission_rejects_a_ticker_with_hostile_format_override(risk, now):
    ticker = ExplodingFormat("AAPL")

    assert risk.can_enter(ticker) is False
    admission = risk.reserve_entry(ticker, 1, 100, 100_000, now)
    assert admission.accepted is False
    assert admission.reason == "invalid_input"


def test_initial_profile_enforces_per_position_gross_and_session_limits(risk, now):
    assert risk.reserve_entry("AAPL", 3, 100, 100_000, now).reason == "max_position_exposure"

    accepted = risk.reserve_entry("AAPL", 2, 100, 100_000, now)
    assert accepted.accepted
    assert risk.reserved_notional == 200.0
    assert risk.gross_exposure_notional == 200.0
    risk.bind_acknowledgement(accepted.reservation.client_order_id, "broker-1")
    risk.apply_terminal_order("broker-1", "rejected", 0, 0)

    assert risk.reserve_entry("MSFT", 1, 100, 100_000, now).reason == "max_entries_per_session"


@pytest.mark.parametrize(
    ("qty", "price", "equity"),
    [
        (0, 100, 100_000),
        (-1, 100, 100_000),
        (nan, 100, 100_000),
        (1, 0, 100_000),
        (1, inf, 100_000),
        (1, 100, 0),
        (1, 100, nan),
    ],
)
def test_invalid_nonfinite_or_zero_entry_inputs_are_rejected(risk, now, qty, price, equity):
    admission = risk.reserve_entry("AAPL", qty, price, equity, now)

    assert admission.accepted is False
    assert admission.reason == "invalid_input"


@pytest.mark.parametrize(
    ("qty", "price", "equity"),
    [
        pytest.param(10**100000, 100, 100_000, id="huge_qty"),
        pytest.param(1, 10**100000, 100_000, id="huge_price"),
        pytest.param(1, 100, 10**100000, id="huge_equity"),
    ],
)
def test_enormous_entry_numbers_are_rejected_without_throwing(risk, now, qty, price, equity):
    admission = risk.reserve_entry("AAPL", qty, price, equity, now)

    assert admission.accepted is False
    assert admission.reason == "invalid_input"


def test_quote_freshness_accepts_exactly_120_seconds_and_rejects_older_or_naive(risk, now):
    boundary = risk.reserve_entry("AAPL", 1, 100, 100_000, now - timedelta(seconds=120))
    assert boundary.accepted

    risk.release_reservation(boundary.reservation.client_order_id)
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now - timedelta(seconds=121)).reason == "stale_quote"
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now.replace(tzinfo=None)).reason == "invalid_timestamp"
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, "not-a-time").reason == "invalid_timestamp"


@pytest.mark.parametrize(
    "clock",
    [
        lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
        lambda: object(),
        lambda: ExplodingClockNow(2026, 9, 1, 14, 30, tzinfo=timezone.utc),
    ],
)
def test_clock_failures_halt_timestamp_admission_without_throwing(now, clock):
    risk = RiskManager(InitialPaperCfg(), clock=clock, session_id="2026-09-01")

    admission = risk.reserve_entry("AAPL", 1, 100, 100_000, now)

    assert admission.accepted is False
    assert admission.reason == "invalid_timestamp"
    assert risk.state is RiskState.HALTING
    assert risk.reservations == {}


def test_acknowledgement_permanently_consumes_budget_after_rejection_and_cancellation(risk, now):
    rejected = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(rejected.client_order_id, "broker-rejected")
    risk.apply_terminal_order("broker-rejected", "rejected", 0, 0)

    assert risk.session_entry_count == 1
    assert risk.reserve_entry("MSFT", 1, 100, 100_000, now).reason == "max_entries_per_session"

    other = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    cancelled = other.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    other.bind_acknowledgement(cancelled.client_order_id, "broker-cancelled")
    other.apply_terminal_order("broker-cancelled", "cancelled", 0, 0)
    assert other.reserve_entry("MSFT", 1, 100, 100_000, now).reason == "max_entries_per_session"


def test_acknowledgement_is_idempotent_only_for_its_original_broker_order(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation

    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-1") is True
    assert risk.session_entry_count == 1
    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-1") is True
    assert risk.session_entry_count == 1
    assert list(risk._pending_entries) == ["broker-1"]

    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-2") is False
    assert risk.state is RiskState.HALTING
    assert risk.session_entry_count == 1
    assert list(risk._pending_entries) == ["broker-1"]


def test_completed_acknowledgement_replay_keeps_its_original_broker_binding(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-1") is True
    assert risk.apply_terminal_order("broker-1", "rejected", 0, 0) is True

    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-1") is True
    assert risk.state is RiskState.ACTIVE
    assert risk.session_entry_count == 1
    assert risk._pending_entries == {}

    assert risk.bind_acknowledgement(reservation.client_order_id, "broker-2") is False
    assert risk.state is RiskState.HALTING
    assert risk.session_entry_count == 1
    assert risk._pending_entries == {}


def test_partial_fill_counts_filled_exposure_and_pending_remainder(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", filled_qty=1, filled_notional=90)

    assert len(risk.positions) == 1
    assert risk.positions[0].ticker == "AAPL"
    assert risk.positions[0].qty == 1
    assert risk.positions[0].avg_entry_price == 90.0
    assert risk.reserved_notional == 100.0
    assert risk.gross_exposure_notional == 190.0


def test_cumulative_fills_accept_later_fill_at_limit_after_price_improvement(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", filled_qty=1, filled_notional=90)
    assert risk.apply_order_delta("broker-1", filled_qty=2, filled_notional=190)
    assert risk.state is RiskState.ACTIVE
    assert risk.positions[0].qty == 2
    assert risk.positions[0].avg_entry_price == 95


def test_cumulative_fill_rejects_incremental_slice_above_entry_limit(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", filled_qty=1, filled_notional=90)
    assert risk.apply_order_delta("broker-1", filled_qty=2, filled_notional=200) is False
    assert risk.state is RiskState.HALTING
    assert risk.positions[0].qty == 1
    assert risk.positions[0].avg_entry_price == 90


def test_fill_notional_cannot_exceed_the_entry_limit_price(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", filled_qty=1, filled_notional=200) is False
    assert risk.state is RiskState.HALTING
    assert risk.positions == []


def test_terminal_fill_is_safe_after_a_nonterminal_full_fill_update(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", filled_qty=1, filled_notional=100)
    assert risk.apply_terminal_order("broker-1", "filled", filled_qty=1, filled_notional=100)
    assert risk.apply_terminal_order("broker-1", "filled", filled_qty=1, filled_notional=100)
    assert risk.state is RiskState.ACTIVE
    assert risk.reservations == {}


@pytest.mark.parametrize(("filled_qty", "filled_notional"), [(1, 100), (0, 0)])
def test_terminal_filled_requires_the_reserved_total_quantity(risk, now, filled_qty, filled_notional):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_terminal_order("broker-1", "filled", filled_qty, filled_notional) is False
    assert risk.state is RiskState.HALTING
    assert reservation.client_order_id in risk.reservations
    assert "broker-1" in risk._pending_entries


def test_terminal_filled_accepts_a_complete_limit_compatible_fill(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_terminal_order("broker-1", "filled", filled_qty=2, filled_notional=180)
    assert risk.state is RiskState.ACTIVE
    assert risk.reservations == {}
    assert risk._pending_entries == {}
    assert risk.positions[0].qty == 2
    assert risk.positions[0].avg_entry_price == 90


def test_conflicting_terminal_snapshot_after_completion_halts_for_reconciliation(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")
    assert risk.apply_terminal_order("broker-1", "rejected", filled_qty=0, filled_notional=0)

    assert risk.apply_terminal_order("broker-1", "filled", filled_qty=1, filled_notional=100) is False
    assert risk.state is RiskState.HALTING


def test_direct_terminal_release_fails_closed_while_broker_order_is_pending(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.release_terminal_remainder("broker-1") is False
    assert risk.state is RiskState.HALTING
    assert "broker-1" in risk._pending_entries
    assert risk.complete_halt(clean_reconciliation=True) is False


def test_terminal_remainder_release_is_idempotent_after_terminal_reconciliation(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")
    assert risk.apply_terminal_order("broker-1", "rejected", 0, 0)

    assert risk.release_terminal_remainder("broker-1") is True
    assert risk.release_terminal_remainder("broker-1") is True
    assert risk.state is RiskState.ACTIVE


def test_reservation_release_is_idempotent_for_known_ids_and_halts_unknown_ids(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation

    assert risk.release_reservation(reservation.client_order_id) is True
    assert risk.release_reservation(reservation.client_order_id) is True
    assert risk.state is RiskState.ACTIVE
    assert risk.release_reservation("unknown-reservation") is False
    assert risk.state is RiskState.HALTING


@pytest.mark.parametrize("client_order_id", [None, "", " ", [], {}, 1])
def test_invalid_client_order_ids_fail_closed_without_throwing(risk, now, client_order_id):
    assert risk.bind_acknowledgement(client_order_id, "broker-1") is False
    assert risk.state is RiskState.HALTING

    release = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert release.release_reservation(client_order_id) is False
    assert release.state is RiskState.HALTING


def test_unhashable_string_ids_fail_closed_on_every_public_ledger_path(risk, now):
    unhashable_client = NoHash("entry-unsafe")
    unhashable_broker = NoHash("broker-unsafe")
    assert risk.bind_acknowledgement(unhashable_client, "broker-1") is False
    assert risk.state is RiskState.HALTING

    binding = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = binding.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert binding.bind_acknowledgement(reservation.client_order_id, unhashable_broker) is False
    assert binding.state is RiskState.HALTING

    delta = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert delta.apply_order_delta(unhashable_broker, 0, 0) is False
    assert delta.state is RiskState.HALTING

    terminal = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert terminal.apply_terminal_order(unhashable_broker, "rejected", 0, 0) is False
    assert terminal.state is RiskState.HALTING
    assert terminal.release_terminal_remainder(unhashable_broker) is False

    release = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert release.release_reservation(unhashable_client) is False
    assert release.state is RiskState.HALTING


@pytest.mark.parametrize(
    ("filled_qty", "filled_notional"),
    [(None, 0), (1, None), (0.5, 50), (1, 90)],
)
def test_missing_or_decreasing_broker_cumulative_values_halt_entries(risk, now, filled_qty, filled_notional):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")
    assert risk.apply_order_delta("broker-1", 1, 100)

    assert risk.apply_order_delta("broker-1", filled_qty, filled_notional) is False
    assert risk.state is RiskState.HALTING
    assert risk.reserve_entry("MSFT", 1, 100, 100_000, now).reason == "risk_halted"


def test_enormous_cumulative_fill_is_rejected_without_throwing(risk, now):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta("broker-1", 10**100000, 0) is False
    assert risk.state is RiskState.HALTING


@pytest.mark.parametrize("broker_order_id", [None, "", " ", [], {}, 1])
def test_invalid_broker_order_ids_fail_closed_without_throwing(risk, now, broker_order_id):
    reservation = risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")

    assert risk.apply_order_delta(broker_order_id, 0, 0) is False
    assert risk.state is RiskState.HALTING

    terminal = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert terminal.apply_terminal_order(broker_order_id, "rejected", 0, 0) is False
    assert terminal.state is RiskState.HALTING


@pytest.mark.parametrize("status", [None, "", " ", [], {}, 1])
def test_invalid_terminal_statuses_fail_closed_without_throwing(risk, now, status):
    assert risk.apply_terminal_order("broker-1", status, 0, 0) is False
    assert risk.state is RiskState.HALTING


def test_hostile_broker_fields_fail_closed_without_throwing(risk, now):
    hostile_broker_id = ExplodingHash("broker-unsafe")
    hostile_status = ExplodingStrip("rejected")

    binding = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = binding.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert binding.bind_acknowledgement(reservation.client_order_id, hostile_broker_id) is False
    assert binding.state is RiskState.HALTING

    delta = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert delta.apply_order_delta(hostile_broker_id, 0, 0) is False
    assert delta.state is RiskState.HALTING

    terminal = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert terminal.apply_terminal_order("broker-1", hostile_status, 0, 0) is False
    assert terminal.state is RiskState.HALTING
    assert terminal.release_terminal_remainder(hostile_broker_id) is False


def test_hashable_hostile_string_ids_and_statuses_fail_closed_without_throwing(risk, now):
    hostile_id = ExplodingEquality("unsafe")

    binding = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = binding.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert binding.bind_acknowledgement(hostile_id, "broker-1") is False
    assert binding.state is RiskState.HALTING

    broker_binding = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = broker_binding.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    assert broker_binding.bind_acknowledgement(reservation.client_order_id, hostile_id) is False
    assert broker_binding.state is RiskState.HALTING

    delta = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert delta.apply_order_delta(hostile_id, 0, 0) is False
    assert delta.state is RiskState.HALTING

    terminal = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert terminal.apply_terminal_order(hostile_id, "rejected", 0, 0) is False
    assert terminal.state is RiskState.HALTING

    terminal_status = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert terminal_status.apply_terminal_order("broker-1", hostile_id, 0, 0) is False
    assert terminal_status.state is RiskState.HALTING
    assert terminal_status.release_terminal_remainder(hostile_id) is False

    release = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert release.release_reservation(hostile_id) is False
    assert release.state is RiskState.HALTING


def test_hard_and_daily_stop_latch_entry_blocking(risk, now):
    assert risk.hard_stop_triggered(90_000.0)
    assert risk.state is RiskState.HALTING
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "risk_halted"

    daily = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert daily.daily_stop_triggered(95_000.0)
    assert daily.state is RiskState.HALTING
    assert daily.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "risk_halted"


@pytest.mark.parametrize("stop_method", ["hard_stop_triggered", "daily_stop_triggered"])
def test_invalid_account_equity_latches_entry_blocking(risk, now, stop_method):
    assert getattr(risk, stop_method)(nan) is True
    assert risk.state is RiskState.HALTING
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "risk_halted"


def test_halt_completion_requires_clean_reconciliation_and_is_idempotent(risk):
    risk.begin_halt("invalid_cumulative_fill")

    assert risk.state is RiskState.HALTING
    assert risk.complete_halt(clean_reconciliation=False) is False
    assert risk.state is RiskState.HALTING
    assert risk.complete_halt(clean_reconciliation=True) is True
    assert risk.state is RiskState.HALTED
    assert risk.complete_halt(clean_reconciliation=True) is True
    assert risk.state is RiskState.HALTED


def test_halt_completion_waits_for_empty_reservations_pending_orders_and_positions(now):
    reservation_risk = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    reservation = reservation_risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    reservation_risk.begin_halt("hard_stop")
    assert reservation_risk.complete_halt(clean_reconciliation=True) is False
    assert reservation_risk.state is RiskState.HALTING
    assert reservation_risk.release_reservation(reservation.client_order_id) is True
    assert reservation_risk.complete_halt(clean_reconciliation=True) is True

    pending_risk = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    pending = pending_risk.reserve_entry("AAPL", 1, 100, 100_000, now).reservation
    pending_risk.bind_acknowledgement(pending.client_order_id, "broker-1")
    pending_risk.begin_halt("daily_stop")
    assert pending_risk.complete_halt(clean_reconciliation=True) is False
    assert pending_risk.apply_terminal_order("broker-1", "rejected", 0, 0) is True
    assert pending_risk.complete_halt(clean_reconciliation=True) is True

    position_risk = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    position_risk.positions = [Position(ticker="AAPL", qty=1, avg_entry_price=100)]
    position_risk.begin_halt("invalid_cumulative_fill")
    assert position_risk.complete_halt(clean_reconciliation=True) is False
    position_risk.positions = []
    assert position_risk.complete_halt(clean_reconciliation=True) is True


def test_cutoff_latches_entry_blocking(risk, now):
    risk.latch_cutoff()

    assert risk.cutoff_latched is True
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "cutoff_latched"
    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is False

    next_session = RiskManager(
        InitialPaperCfg(),
        clock=lambda: now + timedelta(days=1),
        session_id="2026-09-01",
    )
    next_session.latch_cutoff()
    assert next_session.can_rearm("2026-09-02", clean_reconciliation=True) is False
    next_session.begin_halt("cutoff")
    assert next_session.state is RiskState.HALTING
    assert next_session.can_rearm("2026-09-02", clean_reconciliation=True) is False
    assert next_session.complete_halt(clean_reconciliation=True) is True
    assert next_session.can_rearm("2026-09-02", clean_reconciliation=True) is True
    assert next_session.rearm("2026-09-02", clean_reconciliation=True) is True
    assert next_session.cutoff_latched is False


def test_rearm_requires_a_new_session_and_clean_reconciliation(now):
    clock = [now]
    risk = RiskManager(InitialPaperCfg(), clock=lambda: clock[0], session_id="2026-09-01")
    risk.begin_halt("daily_stop")
    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is False
    assert risk.complete_halt(clean_reconciliation=True) is True

    assert risk.can_rearm("2026-09-01", clean_reconciliation=True) is False
    assert risk.can_rearm("not-a-session", clean_reconciliation=True) is False
    assert risk.can_rearm("2026-08-31", clean_reconciliation=True) is False
    assert risk.can_rearm("2026-09-02", clean_reconciliation=False) is False
    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is False
    clock[0] += timedelta(days=1)
    assert risk.can_rearm("2026-09-02", clean_reconciliation="yes") is False
    assert risk.rearm("2026-09-02", clean_reconciliation="yes") is False
    assert risk.can_rearm("2026-09-02", clean_reconciliation=object()) is False
    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is True
    assert risk.rearm("2026-09-02", clean_reconciliation=True) is True
    assert risk.state is RiskState.ACTIVE


def test_rearm_rejects_hostile_session_and_normalizes_valid_session_id(now):
    clock = [now + timedelta(days=1)]
    risk = RiskManager(InitialPaperCfg(), clock=lambda: clock[0], session_id="2026-09-01")
    risk.begin_halt("daily_stop")
    assert risk.complete_halt(clean_reconciliation=True) is True

    assert risk.can_rearm(Boom("2026-09-02"), clean_reconciliation=True) is False
    assert risk.rearm(Boom("2026-09-02"), clean_reconciliation=True) is False
    assert risk.state is RiskState.HALTED

    assert risk.can_rearm("20260902", clean_reconciliation=True) is False
    assert risk.rearm("20260902", clean_reconciliation=True) is False
    assert risk.state is RiskState.HALTED

    assert risk.rearm("2026-09-02", clean_reconciliation=True) is True
    admission = risk.reserve_entry("AAPL", 1, 100, 100_000, clock[0])
    assert admission.accepted is True
    assert admission.reservation.client_order_id == "entry-2026-09-02-AAPL"


def test_noncanonical_session_is_halted_at_construction(now):
    risk = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="20260901")

    admission = risk.reserve_entry("AAPL", 1, 100, 100_000, now)

    assert risk.state is RiskState.HALTING
    assert admission.accepted is False
    assert admission.reason == "invalid_session"


def test_rearm_refuses_hostile_clock_date_without_changing_halted_state(now):
    risk = RiskManager(
        InitialPaperCfg(),
        clock=lambda: ExplodingRearmClock(2026, 9, 2, 14, 30, tzinfo=timezone.utc),
        session_id="2026-09-01",
    )
    risk.begin_halt("daily_stop")
    assert risk.complete_halt(clean_reconciliation=True) is True

    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is False
    assert risk.rearm("2026-09-02", clean_reconciliation=True) is False
    assert risk.state is RiskState.HALTED


def test_rearm_refuses_clock_exception_without_reviving_halted_state(now):
    clock = [now + timedelta(days=1)]

    def current_clock():
        value = clock[0]
        if isinstance(value, Exception):
            raise value
        return value

    risk = RiskManager(InitialPaperCfg(), clock=current_clock, session_id="2026-09-01")
    risk.begin_halt("daily_stop")
    assert risk.complete_halt(clean_reconciliation=True) is True
    clock[0] = RuntimeError("clock failed")

    assert risk.can_rearm("2026-09-02", clean_reconciliation=True) is False
    assert risk.rearm("2026-09-02", clean_reconciliation=True) is False
    assert risk.state is RiskState.HALTED
