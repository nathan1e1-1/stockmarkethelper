import json
import math
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from autotrader.models import (
    AgentDecision,
    ClosedTrade,
    Decision,
    Equity,
    Order,
    Position,
    Reservation,
    RiskState,
    Side,
    Signal,
    SignalSet,
)


class StatePersistenceError(RuntimeError):
    """Raised when a safety-state write was not durably completed."""


_RECOGNIZED_ORDER_STATUSES = frozenset({
    "submitted",
    "new",
    "pending_new",
    "accepted",
    "accepted_for_bidding",
    "partially_filled",
    "pending_cancel",
    "pending_replace",
    "stopped",
    "suspended",
    "calculated",
    "filled",
    "done_for_day",
    "canceled",
    "cancelled",
    "expired",
    "replaced",
    "rejected",
})


@dataclass
class State:
    equity: Equity | None = None
    positions: list[Position] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    unrealized_pnl: float = 0.0
    risk_state: RiskState = RiskState.ACTIVE
    halt_reason: str | None = None
    session_id: str = ""
    session_entry_count: int = 0
    cutoff_latched: bool = False
    reservations: list[Reservation] = field(default_factory=list)
    pending_orders: list[Order] = field(default_factory=list)


def _decode_datetime(value, field_name: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an aware datetime")
    return value


def _positive_finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _nonnegative_finite_number(value) -> bool:
    return _finite_number(value) and value >= 0


def _decode_decision(d: dict) -> AgentDecision:
    decision = Decision(d["decision"]) if isinstance(d.get("decision"), str) else d["decision"]
    timestamp = d.get("timestamp")
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    signals = None
    if isinstance(d.get("signals"), dict):
        ss = d["signals"]
        signals = SignalSet(
            ticker=ss["ticker"],
            signals=[Signal(**s) for s in ss.get("signals", [])],
            composite=ss["composite"],
            regime=ss["regime"],
        )
    return AgentDecision(
        ticker=d["ticker"],
        decision=decision,
        rationale=d.get("rationale", ""),
        confidence=d.get("confidence", 0.0),
        signals=signals,
        timestamp=timestamp,
    )


def _decode_closed_trade(trade: dict) -> ClosedTrade:
    if not isinstance(trade, dict):
        raise ValueError("closed trade must be an object")
    decoded = dict(trade)
    for field_name in ("opened_at", "closed_at"):
        decoded[field_name] = _decode_datetime(decoded[field_name], f"closed trade.{field_name}")
    closed_trade = ClosedTrade(**decoded)
    if not all(isinstance(value, str) and value for value in (closed_trade.ticker, closed_trade.exit_reason)):
        raise ValueError("closed trade identifiers must be nonempty")
    if not all(_positive_finite_number(value) for value in (closed_trade.qty, closed_trade.entry_price, closed_trade.exit_price)):
        raise ValueError("closed trade quantity and prices must be finite and positive")
    if not _finite_number(closed_trade.realized_pnl):
        raise ValueError("closed trade realized P&L must be finite")
    return closed_trade


def _decode_reservation(raw: dict) -> Reservation:
    if not isinstance(raw, dict):
        raise ValueError("reservation must be an object")
    reservation = Reservation(
        client_order_id=raw["client_order_id"],
        ticker=raw["ticker"],
        qty=raw["qty"],
        limit_price=raw["limit_price"],
        created_at=_decode_datetime(raw["created_at"], "reservation.created_at"),
    )
    if not all(isinstance(value, str) and value for value in (reservation.client_order_id, reservation.ticker)):
        raise ValueError("reservation identifiers must be nonempty")
    if not all(_positive_finite_number(value) for value in (reservation.qty, reservation.limit_price)):
        raise ValueError("reservation values must be positive")
    return reservation


def _decode_order(raw: dict) -> Order:
    if not isinstance(raw, dict):
        raise ValueError("pending order must be an object")
    decoded = dict(raw)
    decoded["side"] = Side(decoded["side"])
    decoded["timestamp"] = _decode_datetime(decoded["timestamp"], "order.timestamp")
    decoded["observed_at"] = _decode_datetime(decoded.get("observed_at"), "order.observed_at")
    order = Order(**decoded)
    if not all(isinstance(value, str) and value for value in (order.id, order.client_order_id, order.ticker, order.status)):
        raise ValueError("pending order identifiers must be nonempty")
    if order.status not in _RECOGNIZED_ORDER_STATUSES:
        raise ValueError("pending order status is unrecognized")
    if not _positive_finite_number(order.qty):
        raise ValueError("pending order quantity must be positive")
    if order.filled_avg_price is not None and not _positive_finite_number(order.filled_avg_price):
        raise ValueError("pending order average fill price must be positive")
    if not all(_nonnegative_finite_number(value) for value in (order.processed_filled_qty, order.processed_filled_notional)):
        raise ValueError("processed fills must be finite and nonnegative")
    if (order.filled_qty is None) != (order.filled_notional is None):
        raise ValueError("cumulative fills must be known together")
    if order.filled_qty is None:
        if order.processed_filled_qty != 0 or order.processed_filled_notional != 0:
            raise ValueError("unknown cumulative fills cannot be processed")
    else:
        if not all(_nonnegative_finite_number(value) for value in (order.filled_qty, order.filled_notional)):
            raise ValueError("cumulative fills must be finite and nonnegative")
        if order.filled_qty > order.qty:
            raise ValueError("cumulative fill quantity cannot exceed order quantity")
        if (order.filled_qty == 0) != (order.filled_notional == 0):
            raise ValueError("cumulative fill quantity and notional must agree")
        if (order.processed_filled_qty == 0) != (order.processed_filled_notional == 0):
            raise ValueError("processed fill quantity and notional must agree")
        if order.filled_qty > 0:
            if order.filled_avg_price is None or not math.isclose(
                order.filled_notional,
                order.filled_qty * order.filled_avg_price,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError("cumulative fill notional must match its average price")
        if order.processed_filled_qty > order.filled_qty or order.processed_filled_notional > order.filled_notional:
            raise ValueError("processed fills cannot exceed cumulative fills")
    if order.status == "filled" and (
        order.filled_qty is None or not math.isclose(order.filled_qty, order.qty, rel_tol=1e-9, abs_tol=1e-9)
    ):
        raise ValueError("filled order must have a complete known cumulative fill")
    return order


def _validate_order_intent_coherence(reservations: list[Reservation], pending_orders: list[Order]) -> None:
    reservation_ids = [reservation.client_order_id for reservation in reservations]
    order_ids = [order.id for order in pending_orders]
    order_client_ids = [order.client_order_id for order in pending_orders]
    if len(reservation_ids) != len(set(reservation_ids)):
        raise ValueError("reservation client IDs must be unique")
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("pending broker order IDs must be unique")
    if len(order_client_ids) != len(set(order_client_ids)):
        raise ValueError("pending client IDs must be unique")
    reservations_by_client_id = {reservation.client_order_id: reservation for reservation in reservations}
    for order in pending_orders:
        reservation = reservations_by_client_id.get(order.client_order_id)
        if order.side is Side.BUY:
            # Broker fill quantities are normalized floats, so retain only a tiny
            # comparison tolerance when checking the unfilled reservation remainder.
            if (
                reservation is None
                or reservation.ticker != order.ticker
                or not math.isclose(
                    reservation.qty,
                    order.qty - order.processed_filled_qty,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError("pending buy must match one reservation")
            if order.filled_avg_price is not None and order.filled_avg_price > reservation.limit_price:
                raise ValueError("pending buy fill price cannot exceed reservation limit")
            if order.filled_qty is not None:
                remaining_fill_qty = order.filled_qty - order.processed_filled_qty
                remaining_fill_notional = order.filled_notional - order.processed_filled_notional
                if (remaining_fill_qty == 0) != (remaining_fill_notional == 0):
                    raise ValueError("unprocessed fill quantity and notional must agree")
                for fill_qty, fill_notional in (
                    (order.processed_filled_qty, order.processed_filled_notional),
                    (remaining_fill_qty, remaining_fill_notional),
                ):
                    maximum_notional = fill_qty * reservation.limit_price
                    if fill_notional > maximum_notional + (1e-9 * max(1.0, maximum_notional)):
                        raise ValueError("buy fill slice cannot exceed reservation limit")
        elif reservation is not None:
            raise ValueError("reservation client ID cannot be reused by a non-buy order")


def _halted_state(reason: str, *, base: State | None = None) -> State:
    state = base or State()
    state.risk_state = RiskState.HALTED
    state.halt_reason = reason
    state.session_id = ""
    state.session_entry_count = 0
    state.cutoff_latched = False
    state.reservations = []
    state.pending_orders = []
    return state


def _decode_base_state(raw: dict) -> State:
    eq = raw.get("equity")
    if eq is not None:
        if not isinstance(eq, dict):
            raise ValueError("equity must be an object")
        equity = Equity(**eq)
        if not all(_positive_finite_number(value) for value in (equity.equity, equity.day_start_equity, equity.peak_equity)):
            raise ValueError("equity values must be finite and positive")
        if not isinstance(equity.day, str) or not equity.day:
            raise ValueError("equity day must be nonempty")
    else:
        equity = None
    raw_positions = raw.get("positions", [])
    if not isinstance(raw_positions, list):
        raise ValueError("positions must be a list")
    positions = []
    for raw_position in raw_positions:
        if not isinstance(raw_position, dict):
            raise ValueError("position must be an object")
        decoded_position = dict(raw_position)
        decoded_position["opened_at"] = _decode_datetime(decoded_position["opened_at"], "position.opened_at")
        position = Position(**decoded_position)
        if not isinstance(position.ticker, str) or not position.ticker:
            raise ValueError("position ticker must be nonempty")
        if not all(_positive_finite_number(value) for value in (position.qty, position.avg_entry_price)):
            raise ValueError("position values must be finite and positive")
        positions.append(position)
    unrealized_pnl = raw.get("unrealized_pnl", 0.0)
    if not _finite_number(unrealized_pnl):
        raise ValueError("unrealized P&L must be finite")
    return State(
        equity=equity,
        positions=positions,
        decisions=[_decode_decision(d) for d in raw.get("decisions", [])],
        closed_trades=[_decode_closed_trade(c) for c in raw.get("closed_trades", [])],
        unrealized_pnl=unrealized_pnl,
    )


def _decode_safety_state(raw: dict, base: State, *, fail_closed: bool = True) -> State:
    if "risk_state" not in raw:
        if fail_closed:
            return _halted_state("legacy_state_requires_reconciliation", base=base)
        raise ValueError("legacy safety state cannot be persisted")
    try:
        required_fields = {
            "risk_state",
            "halt_reason",
            "session_id",
            "session_entry_count",
            "cutoff_latched",
            "reservations",
            "pending_orders",
        }
        if not required_fields.issubset(raw):
            raise ValueError("partial safety state")
        base.risk_state = RiskState(raw["risk_state"])
        halt_reason = raw["halt_reason"]
        if halt_reason is not None and not isinstance(halt_reason, str):
            raise ValueError("halt_reason must be a string")
        session_id = raw["session_id"]
        session_entry_count = raw["session_entry_count"]
        cutoff_latched = raw["cutoff_latched"]
        reservations = raw["reservations"]
        pending_orders = raw["pending_orders"]
        if not isinstance(session_id, str) or not isinstance(session_entry_count, int) or isinstance(session_entry_count, bool):
            raise ValueError("invalid session fields")
        if session_entry_count < 0 or not isinstance(cutoff_latched, bool):
            raise ValueError("invalid session fields")
        if not isinstance(reservations, list) or not isinstance(pending_orders, list):
            raise ValueError("safety records must be lists")
        base.halt_reason = halt_reason
        base.session_id = session_id
        base.session_entry_count = session_entry_count
        base.cutoff_latched = cutoff_latched
        base.reservations = [_decode_reservation(item) for item in reservations]
        base.pending_orders = [_decode_order(item) for item in pending_orders]
        _validate_order_intent_coherence(base.reservations, base.pending_orders)
        return base
    except (KeyError, TypeError, ValueError):
        if not fail_closed:
            raise
        return _halted_state("invalid_persisted_safety_state", base=base)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value)!r}")


def same_day(state: State, day: str) -> bool:
    return state.equity is not None and state.equity.day == day


class StateStore:
    def __init__(self, directory: Path | str):
        self.path = Path(directory) / "state.json"

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            raw = json.loads(self.path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("state root must be an object")
            base = _decode_base_state(raw)
            return _decode_safety_state(raw, base)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return _halted_state("invalid_persisted_safety_state")

    def save_or_raise(self, state: State) -> None:
        temporary_path: Path | None = None
        file_descriptor: int | None = None
        try:
            serialized_state = json.dumps(asdict(state), default=_json_default, indent=2, allow_nan=False)
            raw_state = json.loads(serialized_state)
            if not isinstance(raw_state, dict):
                raise ValueError("serialized state root must be an object")
            _decode_safety_state(raw_state, _decode_base_state(raw_state), fail_closed=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                file_descriptor = None
                temporary_file.write(serialized_state)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except (OSError, TypeError, ValueError) as exc:
            if file_descriptor is not None:
                with suppress(OSError):
                    os.close(file_descriptor)
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
            raise StatePersistenceError(f"failed to persist safety state at {self.path}") from exc

    def save(self, state: State) -> None:
        try:
            self.save_or_raise(state)
        except StatePersistenceError as exc:
            print(f"[warn] failed to write journal {self.path}: {exc}")
