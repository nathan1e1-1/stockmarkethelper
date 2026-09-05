import inspect
import math
from datetime import datetime, timezone

from autotrader.exits import ExitManager
from autotrader.market import EASTERN
from autotrader.models import ClosedTrade, Decision, Equity, Order, Side, SignalSet
from autotrader.scoring import composite_score
from autotrader.signals.momentum import MomentumSignal
from autotrader.signals.regime import RegimeFilter
from autotrader.signals.sentiment import SentimentSignal
from autotrader.state import State


_TERMINAL_STATUSES = frozenset({"filled", "cancelled", "canceled", "rejected", "expired"})
_KNOWN_STATUSES = _TERMINAL_STATUSES | frozenset({
    "submitted", "new", "pending_new", "accepted", "accepted_for_bidding",
    "partially_filled", "pending_cancel", "pending_replace", "stopped",
    "suspended", "calculated", "done_for_day", "replaced",
})


class Runner:
    def __init__(self, provider, agent, executor, risk, cfg, sentiment_llm=None, state_store=None, clock=None):
        self.provider = provider
        self.agent = agent
        self.executor = executor
        self.risk = risk
        self.cfg = cfg
        self.state_store = state_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.momentum = MomentumSignal()
        self.regime = RegimeFilter()
        self.sentiment = SentimentSignal(sentiment_llm) if sentiment_llm else None
        self.equity: Equity | None = None
        self.decisions: list = []
        self.exit_manager = ExitManager(cfg.stop_loss_pct, cfg.take_profit_pct) if cfg else None
        self.closed_trades: list = []
        self.pending_orders: list[Order] = []
        self.flattened = False

    def compute_signalset(self, ticker: str) -> SignalSet:
        bars = self.provider.scan_bars(ticker)
        signals = [self.momentum.compute(ticker, bars)]
        if self.sentiment is not None:
            signals.append(self.sentiment.compute(ticker, self.provider.news(ticker)))
        weights = self.regime.weights(bars, dict(self.cfg.signal_weights)) if self.cfg else {"momentum": 0.6, "sentiment": 0.4}
        comp = composite_score(signals, weights)
        return SignalSet(ticker=ticker, signals=signals, composite=comp, regime=self.regime.label(bars))

    def run_once(self, universe: list[str]) -> None:
        if self.equity is None:
            self.equity = Equity(
                equity=self.cfg.paper_capital,
                day_start_equity=self.cfg.paper_capital,
                peak_equity=self.cfg.paper_capital,
                day="",
            )
        if self.risk and (self.risk.hard_stop_triggered(self.equity.equity) or self.risk.daily_stop_triggered(self.equity.equity)):
            return
        threshold = self.cfg.entry_threshold if self.cfg else 0.5
        for ticker in universe:
            try:
                ss = self.compute_signalset(ticker)
                sigs = ", ".join(f"{s.name}={s.value}" for s in ss.signals)
                print(f"[scan] {ticker}: composite={ss.composite} regime={ss.regime} signals=[{sigs}]")
                if ss.composite < threshold:
                    print(f"[scan] {ticker}: below threshold {threshold}, skipping")
                    continue
                decision = self.agent.decide(ss)
                self.decisions.append(decision)
                print(f"[scan] {ticker}: decision={decision.decision.value} confidence={decision.confidence} rationale={decision.rationale!r}")
                if decision.decision is not Decision.BUY:
                    continue
                if self.risk is None:
                    self._fail_closed("missing_risk_manager")
                    continue
                self._submit_reserved_entry(ticker)
            except Exception as error:
                print(f"[error] {ticker}: {error}")
                self._fail_closed("entry_exception")

    def _submit_reserved_entry(self, ticker: str) -> None:
        quote = self._call_with_now(self.provider.latest_quote, ticker)
        if not self._valid_quote(quote, ticker):
            self._fail_closed("invalid_quote")
            return
        qty = self.risk.position_size(ticker, quote.price, self.equity.equity)
        admission = self.risk.reserve_entry(ticker, qty, quote.price, self.equity.equity, quote.observed_at)
        if not admission.accepted:
            print(f"[scan] {ticker}: risk blocked ({admission.reason})")
            return
        reservation = admission.reservation
        intent = Order(
            id=reservation.client_order_id,
            ticker=reservation.ticker,
            side=Side.BUY,
            qty=reservation.qty,
            status="submitted",
            client_order_id=reservation.client_order_id,
            filled_qty=0.0,
            filled_notional=0.0,
            observed_at=quote.observed_at,
            timestamp=quote.source_timestamp,
        )
        self.pending_orders.append(intent)
        if not self._persist():
            self._fail_closed("pre_submit_persistence_failure", persist=False)
            return
        try:
            acknowledged = self.executor.submit_limit_buy(
                reservation.ticker, reservation.qty, reservation.limit_price, reservation.client_order_id
            )
        except Exception:
            # The client ID is already durable. It is the only safe retry key.
            self._fail_closed("entry_submission_unknown")
            return
        if not self._valid_acknowledgement(acknowledged, intent):
            self._fail_closed("invalid_entry_acknowledgement")
            return
        if not self.risk.bind_acknowledgement(reservation.client_order_id, acknowledged.id):
            self._fail_closed("invalid_entry_acknowledgement")
            return
        self._replace_pending(intent.id, self._acknowledged_order(acknowledged, intent))
        if not self._persist():
            # The broker knows the order but the pre-submit client intent remains durable.
            self._fail_closed("post_acknowledgement_persistence_failure", persist=False)
            return
        print(f"[order] BUY {ticker} x{reservation.qty} limit {reservation.limit_price}")

    def reconcile_orders(self) -> bool:
        """Apply only monotonic, broker-confirmed cumulative fill deltas."""
        for pending in list(self.pending_orders):
            snapshot = self._broker_snapshot(pending)
            if snapshot is None:
                # A client-ID lookup returning no record is an uncertain submission,
                # not proof that it can be released or retried.
                if self.risk is not None and self.risk.state.value != "active":
                    return False
                continue
            if not self._valid_snapshot(snapshot, pending):
                self._fail_closed("invalid_order_snapshot")
                return False
            if pending.id == pending.client_order_id and snapshot.id != pending.id:
                if pending.side is Side.BUY and not self.risk.bind_acknowledgement(pending.client_order_id, snapshot.id):
                    self._fail_closed("invalid_entry_acknowledgement")
                    return False
                replacement = self._unprocessed_order(snapshot, pending)
                self._replace_pending(pending.id, replacement)
                pending = replacement
                if not self._persist():
                    self._fail_closed("timeout_reconciliation_persistence_failure", persist=False)
                    return False
            if pending.side is Side.BUY:
                if not self._reconcile_buy(pending, snapshot):
                    return False
            elif pending.side is Side.SELL:
                if not self._reconcile_sell(pending, snapshot):
                    return False
            else:
                self._fail_closed("invalid_order_side")
                return False
        return True

    def _broker_snapshot(self, pending: Order) -> Order | None:
        try:
            if pending.id == pending.client_order_id:
                lookup = getattr(self.executor, "order_by_client_id", None)
                if lookup is None:
                    self._fail_closed("unreconcilable_client_order")
                    return None
                return self._call_with_now(lookup, pending.client_order_id)
            return self._call_with_now(self.executor.order, pending.id)
        except Exception:
            self._fail_closed("order_lookup_failed")
            return None

    def _reconcile_buy(self, pending: Order, snapshot: Order) -> bool:
        if self.risk is None:
            self._fail_closed("missing_risk_manager")
            return False
        status = self._status(snapshot.status)
        if status in _TERMINAL_STATUSES:
            applied = self.risk.apply_terminal_order(snapshot.id, status, snapshot.filled_qty, snapshot.filled_notional)
        else:
            applied = self.risk.apply_order_delta(snapshot.id, snapshot.filled_qty, snapshot.filled_notional)
        if not applied:
            self._fail_closed("invalid_buy_fill")
            return False
        updated = self._processed_order(snapshot, pending)
        if status in _TERMINAL_STATUSES:
            self._remove_pending(pending.id)
        else:
            self._replace_pending(pending.id, updated)
        if not self._persist():
            self._fail_closed("fill_persistence_failure", persist=False)
            return False
        return True

    def _reconcile_sell(self, pending: Order, snapshot: Order) -> bool:
        status = self._status(snapshot.status)
        if status == "filled" and not self._same_number(snapshot.filled_qty, pending.qty):
            self._fail_closed("invalid_terminal_sell_fill")
            return False
        delta_qty = snapshot.filled_qty - pending.processed_filled_qty
        delta_notional = snapshot.filled_notional - pending.processed_filled_notional
        if delta_qty < 0 or delta_notional < 0 or (delta_qty == 0) != (delta_notional == 0):
            self._fail_closed("decreasing_or_invalid_sell_fill")
            return False
        if delta_qty and not self._book_sell_fill(pending, delta_qty, delta_notional, snapshot.observed_at):
            self._fail_closed("invalid_sell_fill")
            return False
        if status in _TERMINAL_STATUSES:
            self._remove_pending(pending.id)
        else:
            self._replace_pending(pending.id, self._processed_order(snapshot, pending))
        if not self._persist():
            self._fail_closed("fill_persistence_failure", persist=False)
            return False
        return True

    def _book_sell_fill(self, pending: Order, qty: float, notional: float, closed_at: datetime) -> bool:
        if not self._positive(qty) or not self._positive(notional):
            return False
        position = next((item for item in self.risk.positions if item.ticker == pending.ticker), None)
        if position is None or qty > position.qty or not self._aware_datetime(closed_at):
            return False
        exit_price = notional / qty
        if not self._positive(exit_price):
            return False
        self.closed_trades.append(ClosedTrade(
            ticker=position.ticker,
            qty=qty,
            entry_price=position.avg_entry_price,
            exit_price=exit_price,
            realized_pnl=(exit_price - position.avg_entry_price) * qty,
            exit_reason=self._exit_reason(pending.client_order_id),
            opened_at=position.opened_at,
            closed_at=closed_at,
        ))
        remaining = position.qty - qty
        if self._same_number(remaining, 0.0):
            self.risk.positions = [item for item in self.risk.positions if item is not position]
        else:
            position.qty = remaining
        return True

    def reconcile(self) -> None:
        """Legacy startup reconciliation is unsafe without lifecycle intent state."""
        self._fail_closed("lifecycle_reconciliation_required")

    def manage_exits(self, flatten_time=None, now=None) -> None:
        if self.exit_manager is None or self.risk is None:
            return
        try:
            if flatten_time and now and now.astimezone(EASTERN).time() >= flatten_time and not self.flattened:
                for pos in list(self.risk.positions):
                    price = self._exit_decision_price(pos.ticker)
                    if price is None:
                        return
                    self._close(pos, price, "flatten")
                self.flattened = True
                return
            for pos in list(self.risk.positions):
                price = self._exit_decision_price(pos.ticker)
                if price is None:
                    return
                reason = self.exit_manager.evaluate(pos, price)
                if reason:
                    self._close(pos, price, reason)
        except Exception as error:
            print(f"[error] manage_exits: {error}")
            self._fail_closed("exit_exception")

    def _close(self, pos, price: float, reason: str) -> None:
        """Record a durable exit intent; only reconcile_orders can book its P&L."""
        del price  # A quote can request an exit, never price a realised trade.
        if not self._positive(pos.qty):
            self._fail_closed("invalid_exit_quantity")
            return
        client_order_id = self._exit_client_order_id(pos.ticker, reason)
        if any(order.side is Side.SELL and order.ticker == pos.ticker for order in self.pending_orders):
            return
        observed_at = self._clock_now()
        if observed_at is None:
            self._fail_closed("invalid_clock")
            return
        intent = Order(
            id=client_order_id,
            ticker=pos.ticker,
            side=Side.SELL,
            qty=pos.qty,
            status="submitted",
            client_order_id=client_order_id,
            filled_qty=0.0,
            filled_notional=0.0,
            observed_at=observed_at,
            timestamp=observed_at,
        )
        self.pending_orders.append(intent)
        if not self._persist():
            self._fail_closed("pre_exit_persistence_failure", persist=False)
            return
        try:
            submit_exit = getattr(self.executor, "submit_exit", None)
            if not callable(submit_exit):
                self._fail_closed("exit_submission_unavailable")
                return
            acknowledged = submit_exit(pos.ticker, pos.qty, client_order_id)
        except Exception:
            self._fail_closed("exit_submission_unknown")
            return
        if not self._valid_acknowledgement(acknowledged, intent):
            self._fail_closed("invalid_exit_acknowledgement")
            return
        self._replace_pending(intent.id, self._acknowledged_order(acknowledged, intent))
        if not self._persist():
            self._fail_closed("post_exit_acknowledgement_persistence_failure", persist=False)

    def _persist(self) -> bool:
        if self.state_store is None:
            return False
        try:
            self.state_store.save_or_raise(self._state())
            return True
        except Exception:
            return False

    def _state(self) -> State:
        return State(
            equity=self.equity,
            positions=list(self.risk.positions),
            decisions=list(self.decisions),
            closed_trades=list(self.closed_trades),
            risk_state=self.risk.state,
            halt_reason=self.risk.halt_reason,
            session_id=self.risk.session_id,
            session_entry_count=self.risk.session_entry_count,
            cutoff_latched=self.risk.cutoff_latched,
            reservations=list(self.risk.reservations.values()),
            pending_orders=list(self.pending_orders),
        )

    def _fail_closed(self, reason: str, *, persist: bool = True) -> None:
        if self.risk is not None and hasattr(self.risk, "begin_halt"):
            self.risk.begin_halt(reason)
        if persist:
            self._persist()

    def _valid_quote(self, quote, ticker: str) -> bool:
        return (
            getattr(quote, "ticker", None) == ticker
            and self._positive(getattr(quote, "price", None))
            and self._snapshot_is_fresh(getattr(quote, "source_timestamp", None))
            and self._snapshot_is_fresh(getattr(quote, "observed_at", None))
        )

    def _call_with_now(self, operation, *args):
        """Use the injected clock whenever the adapter explicitly supports it."""
        now = self._clock_now()
        if now is None:
            raise ValueError("runner clock must return an aware datetime")
        try:
            parameters = inspect.signature(operation).parameters.values()
        except (TypeError, ValueError):
            return operation(*args)
        supports_now = any(
            (
                parameter.name == "now"
                and parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            )
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        return operation(*args, now=now) if supports_now else operation(*args)

    def _exit_decision_price(self, ticker: str) -> float | None:
        quote = self._call_with_now(self.provider.latest_quote, ticker)
        if not self._valid_quote(quote, ticker):
            self._fail_closed("invalid_exit_quote")
            return None
        return quote.price

    def _valid_acknowledgement(self, order, intent: Order) -> bool:
        status = self._status(getattr(order, "status", None))
        return (
            status in _KNOWN_STATUSES
            and
            isinstance(getattr(order, "id", None), str)
            and bool(order.id)
            and getattr(order, "client_order_id", None) == intent.client_order_id
            and getattr(order, "ticker", None) == intent.ticker
            and getattr(order, "side", None) is intent.side
            and self._same_number(getattr(order, "qty", None), intent.qty)
            and self._snapshot_is_fresh(getattr(order, "observed_at", None))
            and self._valid_acknowledgement_fill(order, intent.qty, status)
        )

    def _valid_acknowledgement_fill(self, order, expected_qty: float, status: str | None) -> bool:
        filled_qty = getattr(order, "filled_qty", None)
        filled_notional = getattr(order, "filled_notional", None)
        if filled_qty is None or filled_notional is None:
            return filled_qty is None and filled_notional is None and status not in _TERMINAL_STATUSES
        if not (self._nonnegative(filled_qty) and self._nonnegative(filled_notional)):
            return False
        if filled_qty > expected_qty or (filled_qty == 0) != (filled_notional == 0):
            return False
        if filled_qty == 0:
            return status != "filled"
        if not (
            self._positive(getattr(order, "filled_avg_price", None))
            and self._same_number(filled_notional, filled_qty * order.filled_avg_price)
        ):
            return False
        return status != "filled" or self._same_number(filled_qty, expected_qty)

    def _valid_snapshot(self, snapshot: Order, pending: Order) -> bool:
        status = self._status(getattr(snapshot, "status", None))
        if (
            status not in _KNOWN_STATUSES
            or (pending.id != pending.client_order_id and snapshot.id != pending.id)
            or snapshot.client_order_id != pending.client_order_id
            or snapshot.ticker != pending.ticker
            or snapshot.side is not pending.side
            or not self._same_number(snapshot.qty, pending.qty)
            or not self._snapshot_is_fresh(snapshot.observed_at)
        ):
            return False
        if not (self._nonnegative(snapshot.filled_qty) and self._nonnegative(snapshot.filled_notional)):
            return False
        if snapshot.filled_qty > pending.qty:
            return False
        if (snapshot.filled_qty == 0) != (snapshot.filled_notional == 0):
            return False
        return snapshot.filled_qty == 0 or (
            self._positive(snapshot.filled_avg_price)
            and self._same_number(snapshot.filled_notional, snapshot.filled_qty * snapshot.filled_avg_price)
        )

    def _snapshot_is_fresh(self, observed_at) -> bool:
        if not self._aware_datetime(observed_at):
            return False
        try:
            now = self._clock_now()
            max_age_seconds = self.cfg.max_snapshot_age_seconds
            if now is None or isinstance(max_age_seconds, bool):
                return False
            max_age_seconds = float(max_age_seconds)
            if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
                return False
            age_seconds = (now - observed_at).total_seconds()
            return math.isfinite(age_seconds) and 0 <= age_seconds <= max_age_seconds
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return False

    def _clock_now(self) -> datetime | None:
        try:
            now = self._clock()
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return None
        return now if self._aware_datetime(now) else None

    def _acknowledged_order(self, acknowledged: Order, intent: Order) -> Order:
        observed_at = acknowledged.observed_at
        timestamp = acknowledged.timestamp if self._aware_datetime(acknowledged.timestamp) else observed_at
        return Order(
            id=acknowledged.id,
            ticker=intent.ticker,
            side=intent.side,
            qty=intent.qty,
            status=self._status(acknowledged.status) or "submitted",
            client_order_id=intent.client_order_id,
            filled_avg_price=acknowledged.filled_avg_price,
            filled_qty=acknowledged.filled_qty,
            filled_notional=acknowledged.filled_notional,
            observed_at=observed_at,
            timestamp=timestamp,
        )

    @staticmethod
    def _processed_order(snapshot: Order, pending: Order) -> Order:
        return Order(
            id=pending.id,
            ticker=pending.ticker,
            side=pending.side,
            qty=pending.qty,
            status=Runner._status(snapshot.status),
            client_order_id=pending.client_order_id,
            filled_avg_price=snapshot.filled_avg_price,
            filled_qty=snapshot.filled_qty,
            filled_notional=snapshot.filled_notional,
            processed_filled_qty=snapshot.filled_qty,
            processed_filled_notional=snapshot.filled_notional,
            observed_at=snapshot.observed_at,
            timestamp=snapshot.timestamp,
        )

    @staticmethod
    def _unprocessed_order(snapshot: Order, pending: Order) -> Order:
        return Order(
            id=snapshot.id,
            ticker=pending.ticker,
            side=pending.side,
            qty=pending.qty,
            status=Runner._status(snapshot.status),
            client_order_id=pending.client_order_id,
            filled_avg_price=snapshot.filled_avg_price,
            filled_qty=snapshot.filled_qty,
            filled_notional=snapshot.filled_notional,
            observed_at=snapshot.observed_at,
            timestamp=snapshot.timestamp,
        )

    def _replace_pending(self, order_id: str, replacement: Order) -> None:
        self.pending_orders = [replacement if order.id == order_id else order for order in self.pending_orders]

    def _remove_pending(self, order_id: str) -> None:
        self.pending_orders = [order for order in self.pending_orders if order.id != order_id]

    def _exit_client_order_id(self, ticker: str, reason: str) -> str:
        session_id = getattr(self.risk, "session_id", "unknown-session")
        return f"exit-{session_id}-{ticker}-{reason}"

    @staticmethod
    def _exit_reason(client_order_id: str | None) -> str:
        if isinstance(client_order_id, str) and client_order_id.startswith("exit-"):
            return client_order_id.rsplit("-", 1)[-1]
        return "broker_confirmed_exit"

    @staticmethod
    def _status(value) -> str | None:
        return value.lower() if isinstance(value, str) else None

    @staticmethod
    def _aware_datetime(value) -> bool:
        try:
            return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
        except (AttributeError, OverflowError, RuntimeError, TypeError, ValueError):
            return False

    @staticmethod
    def _positive(value) -> bool:
        return Runner._nonnegative(value) and value > 0

    @staticmethod
    def _nonnegative(value) -> bool:
        if isinstance(value, bool):
            return False
        try:
            normalized = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(normalized) and normalized >= 0

    @staticmethod
    def _same_number(left, right) -> bool:
        if not (Runner._nonnegative(left) and Runner._nonnegative(right)):
            return False
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
