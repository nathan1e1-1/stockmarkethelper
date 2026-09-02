import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import wraps
from threading import RLock
from typing import Callable

from autotrader.models import Position, Reservation, RiskState


@dataclass(frozen=True)
class Admission:
    """Result of one all-or-nothing entry admission attempt."""

    reservation: Reservation | None = None
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.reservation is not None


@dataclass
class _PendingEntry:
    reservation_id: str
    processed_filled_qty: float = 0.0
    processed_filled_notional: float = 0.0


@dataclass(frozen=True)
class _CompletedEntry:
    status: str
    filled_qty: float
    filled_notional: float


def _synchronized(method):
    @wraps(method)
    def synchronized(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return synchronized


class RiskManager:
    def __init__(
        self,
        cfg,
        *,
        clock: Callable[[], datetime] | None = None,
        session_id: str | None = None,
    ):
        self.cfg = cfg
        self._lock = RLock()
        self.positions: list[Position] = []
        self.reservations: dict[str, Reservation] = {}
        self._pending_entries: dict[str, _PendingEntry] = {}
        self._acknowledged_entries: dict[str, str] = {}
        self._completed_entries: dict[str, _CompletedEntry] = {}
        self._released_entries: set[str] = set()
        self._released_reservations: set[str] = set()
        self.peak_equity: float = cfg.paper_capital
        self.day_start_equity: float = cfg.paper_capital
        self.state = RiskState.ACTIVE
        self.halt_reason: str | None = None
        self.cutoff_latched = False
        self.session_entry_count = 0
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        session_candidate = session_id
        if session_candidate is None:
            try:
                session_candidate = self._clock().date().isoformat()
            except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
                session_candidate = None
        if self._valid_session_id(session_candidate):
            self.session_id = session_candidate
        else:
            self.session_id = ""
            self.halt_reason = "invalid_session"
            self.state = RiskState.HALTING

    @property
    def reserved_notional(self) -> float:
        with self._lock:
            return sum(reservation.qty * reservation.limit_price for reservation in self.reservations.values())

    @property
    def gross_exposure_notional(self) -> float:
        with self._lock:
            return sum(position.qty * position.avg_entry_price for position in self.positions) + self.reserved_notional

    def position_size(self, ticker: str, price: float, equity: float) -> int:
        if not self._positive(price) or not self._positive(equity):
            return 0
        budget = equity * self.cfg.max_position_pct
        if not self._positive(budget):
            return 0
        return max(0, math.floor(budget / price))

    def can_enter(self, ticker: str) -> bool:
        with self._lock:
            return (
                self._valid_ticker(ticker)
                and self.state is RiskState.ACTIVE
                and not self.cutoff_latched
                and self.session_entry_count < self.cfg.max_entries_per_session
                and not self._has_ticker(ticker)
                and self._position_count() < self.cfg.max_positions
            )

    def reserve_entry(
        self,
        ticker: str,
        qty: float,
        limit_price: float,
        equity: float,
        quote_observed_at: datetime,
    ) -> Admission:
        with self._lock:
            return self._reserve_entry(ticker, qty, limit_price, equity, quote_observed_at)

    def _reserve_entry(
        self,
        ticker: str,
        qty: float,
        limit_price: float,
        equity: float,
        quote_observed_at: datetime,
    ) -> Admission:
        if self.state is not RiskState.ACTIVE:
            return Admission(reason="invalid_session" if self.halt_reason == "invalid_session" else "risk_halted")
        if self.cutoff_latched:
            return Admission(reason="cutoff_latched")
        if not self._valid_ticker(ticker):
            return Admission(reason="invalid_input")
        if not all(self._positive(value) for value in (qty, limit_price, equity)):
            return Admission(reason="invalid_input")
        timestamp_reason = self._timestamp_reason(quote_observed_at)
        if timestamp_reason:
            return Admission(reason=timestamp_reason)
        if self._has_ticker(ticker):
            return Admission(reason="duplicate_ticker")
        if self._position_count() >= self.cfg.max_positions:
            return Admission(reason="max_positions")
        notional = qty * limit_price
        if not self._positive(notional):
            return Admission(reason="invalid_input")
        if notional > equity * self.cfg.max_position_pct:
            return Admission(reason="max_position_exposure")
        if self.gross_exposure_notional + notional > equity * self.cfg.max_gross_exposure_pct:
            return Admission(reason="max_gross_exposure")
        if self.session_entry_count >= self.cfg.max_entries_per_session:
            return Admission(reason="max_entries_per_session")

        client_order_id = f"entry-{self.session_id}-{ticker}"
        reservation = Reservation(client_order_id, ticker, float(qty), float(limit_price), quote_observed_at)
        self.reservations[client_order_id] = reservation
        return Admission(reservation=reservation)

    @_synchronized
    def bind_acknowledgement(self, client_order_id: str, broker_order_id: str) -> bool:
        if not self._valid_client_order_id(client_order_id) or not self._valid_broker_order_id(broker_order_id):
            self.begin_halt("invalid_acknowledgement")
            return False
        acknowledged_broker_order_id = self._acknowledged_entries.get(client_order_id)
        if acknowledged_broker_order_id is not None:
            if acknowledged_broker_order_id == broker_order_id:
                return True
            self.begin_halt("conflicting_acknowledgement")
            return False
        reservation = self.reservations.get(client_order_id)
        if reservation is None:
            self.begin_halt("invalid_acknowledgement")
            return False
        for existing_broker_order_id, existing_pending in self._pending_entries.items():
            if existing_pending.reservation_id == client_order_id:
                if existing_broker_order_id == broker_order_id:
                    return True
                self.begin_halt("conflicting_acknowledgement")
                return False
        pending = self._pending_entries.get(broker_order_id)
        if pending is not None:
            if pending.reservation_id != client_order_id:
                self.begin_halt("conflicting_acknowledgement")
                return False
            return True
        self._pending_entries[broker_order_id] = _PendingEntry(client_order_id)
        self._acknowledged_entries[client_order_id] = broker_order_id
        self.session_entry_count += 1
        return True

    @_synchronized
    def apply_order_delta(self, broker_order_id: str, filled_qty, filled_notional) -> bool:
        if not self._valid_broker_order_id(broker_order_id):
            self.begin_halt("invalid_broker_order_id")
            return False
        pending = self._pending_entries.get(broker_order_id)
        if pending is None:
            self.begin_halt("unknown_order")
            return False
        reservation = self.reservations.get(pending.reservation_id)
        if reservation is None or not self._nonnegative(filled_qty) or not self._nonnegative(filled_notional):
            self.begin_halt("invalid_cumulative_fill")
            return False
        filled_qty = float(filled_qty)
        filled_notional = float(filled_notional)
        if (
            filled_qty < pending.processed_filled_qty
            or filled_notional < pending.processed_filled_notional
            or filled_qty > reservation.qty + pending.processed_filled_qty
        ):
            self.begin_halt("decreasing_or_excess_fill")
            return False
        maximum_notional = filled_qty * reservation.limit_price
        if filled_notional > maximum_notional + (1e-9 * max(1.0, maximum_notional)):
            self.begin_halt("excess_fill_price")
            return False

        delta_qty = filled_qty - pending.processed_filled_qty
        delta_notional = filled_notional - pending.processed_filled_notional
        if (delta_qty == 0.0) != (delta_notional == 0.0) or (delta_qty > 0.0 and delta_notional <= 0.0):
            self.begin_halt("invalid_cumulative_fill")
            return False
        if delta_qty:
            maximum_delta_notional = delta_qty * reservation.limit_price
            if delta_notional > maximum_delta_notional + (1e-9 * max(1.0, maximum_delta_notional)):
                self.begin_halt("excess_fill_price")
                return False
        if delta_qty:
            self._add_filled_position(reservation.ticker, delta_qty, delta_notional / delta_qty)
            remaining_qty = reservation.qty - delta_qty
            self.reservations[pending.reservation_id] = Reservation(
                reservation.client_order_id,
                reservation.ticker,
                max(0.0, remaining_qty),
                reservation.limit_price,
                reservation.created_at,
            )
        pending.processed_filled_qty = filled_qty
        pending.processed_filled_notional = filled_notional
        return True

    @_synchronized
    def apply_terminal_order(self, broker_order_id: str, status: str, filled_qty, filled_notional) -> bool:
        if not self._valid_broker_order_id(broker_order_id):
            self.begin_halt("invalid_broker_order_id")
            return False
        if not self._valid_string_key(status):
            self.begin_halt("invalid_terminal_status")
            return False
        normalized_status = "cancelled" if status == "canceled" else status
        if normalized_status not in {"filled", "cancelled", "rejected", "expired"}:
            self.begin_halt("invalid_terminal_status")
            return False
        completed = self._completed_entries.get(broker_order_id)
        if completed is not None:
            if (
                self._nonnegative(filled_qty)
                and self._nonnegative(filled_notional)
                and completed == _CompletedEntry(normalized_status, float(filled_qty), float(filled_notional))
            ):
                return True
            self.begin_halt("conflicting_terminal_order")
            return False
        if normalized_status == "filled":
            pending = self._pending_entries.get(broker_order_id)
            reservation = self.reservations.get(pending.reservation_id) if pending is not None else None
            expected_filled_qty = (
                reservation.qty + pending.processed_filled_qty
                if reservation is not None and pending is not None
                else None
            )
            if (
                not self._nonnegative(filled_qty)
                or expected_filled_qty is None
                or not math.isclose(float(filled_qty), expected_filled_qty, rel_tol=1e-9, abs_tol=1e-9)
            ):
                self.begin_halt("invalid_terminal_fill")
                return False
        if not self.apply_order_delta(broker_order_id, filled_qty, filled_notional):
            return False
        if not self._release_terminal_remainder(broker_order_id):
            return False
        self._completed_entries[broker_order_id] = _CompletedEntry(
            normalized_status,
            float(filled_qty),
            float(filled_notional),
        )
        return True

    @_synchronized
    def release_terminal_remainder(self, broker_order_id: str) -> bool:
        if not self._valid_broker_order_id(broker_order_id):
            self.begin_halt("invalid_broker_order_id")
            return False
        if broker_order_id in self._completed_entries or broker_order_id in self._released_entries:
            return True
        if broker_order_id in self._pending_entries:
            self.begin_halt("unconfirmed_terminal_release")
            return False
        self.begin_halt("unknown_order")
        return False

    def _release_terminal_remainder(self, broker_order_id: str) -> bool:
        pending = self._pending_entries.pop(broker_order_id, None)
        if pending is None:
            self.begin_halt("unknown_order")
            return False
        self.reservations.pop(pending.reservation_id, None)
        self._released_entries.add(broker_order_id)
        return True

    @_synchronized
    def release_reservation(self, client_order_id: str) -> bool:
        if not self._valid_client_order_id(client_order_id):
            self.begin_halt("invalid_client_order_id")
            return False
        if any(pending.reservation_id == client_order_id for pending in self._pending_entries.values()):
            return False
        if self.reservations.pop(client_order_id, None) is not None:
            self._released_reservations.add(client_order_id)
            return True
        if client_order_id in self._released_reservations:
            return True
        self.begin_halt("unknown_reservation")
        return False

    @_synchronized
    def begin_halt(self, reason: str) -> None:
        self.halt_reason = reason
        if self.state is RiskState.ACTIVE:
            self.state = RiskState.HALTING

    @_synchronized
    def complete_halt(self, *, clean_reconciliation: bool) -> bool:
        if self.state is RiskState.HALTED:
            return clean_reconciliation is True and self._tracking_is_empty()
        if self.state is not RiskState.HALTING or clean_reconciliation is not True or not self._tracking_is_empty():
            return False
        self.state = RiskState.HALTED
        return True

    @_synchronized
    def latch_cutoff(self) -> None:
        self.cutoff_latched = True

    @_synchronized
    def can_rearm(self, session_id: str, *, clean_reconciliation: bool) -> bool:
        if not self._valid_session_id(session_id) or not self._valid_session_id(self.session_id):
            return False
        try:
            next_session = date.fromisoformat(session_id)
            current_session = date.fromisoformat(self.session_id)
            clock_now = self._clock()
            if not isinstance(clock_now, datetime) or clock_now.tzinfo is None or clock_now.utcoffset() is None:
                return False
            clock_session = clock_now.date()
            if type(clock_session) is not date:
                return False
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return False
        return (
            self.state is RiskState.HALTED
            and next_session > current_session
            and next_session == clock_session
            and clean_reconciliation is True
            and not self.reservations
            and not self._pending_entries
            and not self.positions
        )

    @_synchronized
    def rearm(self, session_id: str, *, clean_reconciliation: bool) -> bool:
        if not self.can_rearm(session_id, clean_reconciliation=clean_reconciliation):
            return False
        self.session_id = date.fromisoformat(session_id).isoformat()
        self.session_entry_count = 0
        self.cutoff_latched = False
        self.halt_reason = None
        self.state = RiskState.ACTIVE
        return True

    @_synchronized
    def hard_stop_triggered(self, equity: float) -> bool:
        if not self._positive(equity):
            self.begin_halt("invalid_equity")
            return True
        triggered = self._positive(equity) and equity <= self.peak_equity * (1.0 - self.cfg.kill_switch_pct)
        if triggered:
            self.begin_halt("hard_stop")
        return triggered

    @_synchronized
    def daily_stop_triggered(self, equity: float) -> bool:
        if not self._positive(equity):
            self.begin_halt("invalid_equity")
            return True
        triggered = self._positive(equity) and equity <= self.day_start_equity * (1.0 - self.cfg.daily_loss_pct)
        if triggered:
            self.begin_halt("daily_stop")
        return triggered

    def _has_ticker(self, ticker: str) -> bool:
        return any(position.ticker == ticker for position in self.positions) or any(
            reservation.ticker == ticker for reservation in self.reservations.values()
        )

    def _tracking_is_empty(self) -> bool:
        return not self.reservations and not self._pending_entries and not self.positions

    def _position_count(self) -> int:
        return len({position.ticker for position in self.positions} | {reservation.ticker for reservation in self.reservations.values()})

    def _add_filled_position(self, ticker: str, qty: float, price: float) -> None:
        for position in self.positions:
            if position.ticker == ticker:
                total_qty = position.qty + qty
                position.avg_entry_price = ((position.qty * position.avg_entry_price) + (qty * price)) / total_qty
                position.qty = total_qty
                return
        self.positions.append(Position(ticker=ticker, qty=qty, avg_entry_price=price))

    def _timestamp_reason(self, value) -> str | None:
        try:
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                return "invalid_timestamp"
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return "invalid_timestamp"
        try:
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                self.begin_halt("invalid_clock")
                return "invalid_timestamp"
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            self.begin_halt("invalid_clock")
            return "invalid_timestamp"
        try:
            if value > now:
                return "invalid_timestamp"
            if (now - value).total_seconds() > self.cfg.max_snapshot_age_seconds:
                return "stale_quote"
        except (OverflowError, RuntimeError, TypeError, ValueError):
            self.begin_halt("invalid_clock")
            return "invalid_timestamp"
        return None

    @staticmethod
    def _positive(value) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value) and value > 0
        except (OverflowError, TypeError):
            return False

    @staticmethod
    def _valid_broker_order_id(value) -> bool:
        return RiskManager._valid_string_key(value)

    @staticmethod
    def _valid_client_order_id(value) -> bool:
        return RiskManager._valid_string_key(value)

    @staticmethod
    def _valid_string_key(value) -> bool:
        if type(value) is not str:
            return False
        try:
            if not str.strip(value):
                return False
            hash(value)
        except (OverflowError, RuntimeError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _valid_ticker(value) -> bool:
        if type(value) is not str:
            return False
        try:
            return bool(str.strip(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _valid_session_id(value) -> bool:
        if type(value) is not str:
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _nonnegative(value) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value) and value >= 0
        except (OverflowError, TypeError):
            return False
