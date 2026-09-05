"""Fail-closed paper-engine lifecycle coordination.

This module deliberately owns the transition between persisted local intent and
the broker's current view.  A successful submission is never reconciliation;
only a fresh broker snapshot can unblock the next lifecycle step.
"""

from __future__ import annotations

import inspect
import math
from datetime import datetime, time, timezone

from autotrader.market import EASTERN
from autotrader.models import Equity, Position, RiskState, Side


_TERMINAL = frozenset({"filled", "cancelled", "canceled", "rejected", "expired"})


class EngineLifecycle:
    """Own paper startup reconciliation, latching cleanup, and local re-arm."""

    def __init__(self, cfg, executor, risk, runner, state_store, *, clock=None):
        if state_store is None:
            raise ValueError("a durable state store is required")
        if cfg.alpaca_paper is not True:
            raise ValueError("paper trading must be enabled")
        if runner.state_store is not state_store:
            raise ValueError("runner must use the lifecycle state store")
        self.cfg = cfg
        self.executor = executor
        self.risk = risk
        self.runner = runner
        self.store = state_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._restored = False
        self._broker_clean = False
        self._account_valid = False
        self._requires_rearm = False

    @property
    def can_scan(self) -> bool:
        return (
            self._restored
            and self._account_valid
            and self._broker_clean
            and self.risk.state is RiskState.ACTIVE
            and not self.risk.cutoff_latched
        )

    def startup_reconcile(self) -> bool:
        """Restore then compare both local intent and broker state before scans."""
        self._require_paper_mode()
        if not self._restored:
            self._restore_state()
            self._restored = True
        return self._reconcile_and_cleanup() and self._account_valid and not self._requires_rearm

    def tick(self, now: datetime, universe: list[str]) -> bool:
        """Perform a single safe cycle; entries are last and only after reconciliation."""
        self._require_paper_mode()
        if not self._aware(now):
            self._begin_halt("invalid_lifecycle_clock")
            return False
        if not self._restored and not self.startup_reconcile():
            return False
        if self._at_cutoff(now):
            self.risk.latch_cutoff()
            self._begin_halt("session_cutoff")
        if not self._reconcile_and_cleanup():
            return False
        if not self.can_scan:
            return False
        snapshot = self._account_snapshot(now)
        if snapshot is None:
            self._account_valid = False
            self._begin_halt("invalid_account_snapshot")
            return False
        self._account_valid = True
        equity = snapshot.equity
        self.risk.peak_equity = max(self.risk.peak_equity, equity)
        self.runner.equity = Equity(equity, self.risk.day_start_equity, self.risk.peak_equity, self._session_id(now))
        if self.risk.hard_stop_triggered(equity) or self.risk.daily_stop_triggered(equity):
            self._persist_or_halt("halt_persistence_failure")
            self._reconcile_and_cleanup()
            return False
        self.runner.manage_exits(flatten_time=None, now=now)
        if self.risk.state is not RiskState.ACTIVE:
            return False
        self.runner.run_once(universe)
        return self.can_scan

    def request_rearm(self, session_id: str) -> bool:
        """Locally re-arm only a next-session, flat, broker-reconciled engine."""
        self._require_paper_mode()
        if not self._restored:
            self.startup_reconcile()
        snapshot = self._account_snapshot(self._now())
        if snapshot is None:
            self._account_valid = False
            return False
        self._account_valid = True
        self._reconcile_and_cleanup()
        if not self._broker_clean:
            return False
        rearmed = self.risk.rearm(session_id, clean_reconciliation=True)
        if not rearmed:
            return False
        if not self._persist_or_halt("rearm_persistence_failure"):
            return False
        self._requires_rearm = False
        return True

    def _restore_state(self) -> None:
        loaded = self.store.load()
        self.runner.equity = loaded.equity or self.runner.equity
        self.runner.decisions = list(loaded.decisions)
        self.runner.closed_trades = list(loaded.closed_trades)
        self.runner.pending_orders = list(loaded.pending_orders)
        if not self.risk.restore_persisted_safety_state(
            positions=loaded.positions,
            reservations=loaded.reservations,
            pending_orders=loaded.pending_orders,
            risk_state=loaded.risk_state,
            halt_reason=loaded.halt_reason,
            session_id=loaded.session_id or self._session_id(self._now()),
            session_entry_count=loaded.session_entry_count,
            cutoff_latched=loaded.cutoff_latched,
        ):
            self.risk.begin_halt("invalid_persisted_risk_state")
        snapshot = self._account_snapshot(self._now())
        if snapshot is None:
            self._account_valid = False
            self.risk.begin_halt("invalid_account_snapshot")
            return
        self._account_valid = True
        self.risk.day_start_equity = snapshot.equity
        self.risk.peak_equity = snapshot.equity
        self.runner.equity = Equity(
            snapshot.equity,
            snapshot.equity,
            snapshot.equity,
            self._session_id(self._now()),
        )
        if self.risk.state is RiskState.ACTIVE and self.risk.session_id != self._session_id(self._now()):
            self._requires_rearm = True
            self.risk.begin_halt("prior_session_requires_rearm")

    def _require_paper_mode(self) -> None:
        if self.cfg.alpaca_paper is not True:
            raise ValueError("paper trading must be enabled")

    def _reconcile_and_cleanup(self) -> bool:
        now = self._now()
        positions = self._positions_snapshot(now)
        orders = self._open_orders(now)
        if positions is None or orders is None:
            self._begin_halt("invalid_broker_snapshot")
            return False

        local_orders = {order.id: order for order in self.runner.pending_orders}
        local_client_ids = {order.client_order_id for order in self.runner.pending_orders}
        orphan_orders = [order for order in orders if order.id not in local_orders and order.client_order_id not in local_client_ids]
        missing_local_orders = self._missing_local_orders()
        broker_by_ticker = {position.ticker: position for position in positions}
        local_by_ticker = {position.ticker: position for position in self.risk.positions}
        orphan_positions = [position for ticker, position in broker_by_ticker.items() if not self._same_position(local_by_ticker.get(ticker), position)]
        missing_broker_positions = [position for ticker, position in local_by_ticker.items() if not self._same_position(broker_by_ticker.get(ticker), position)]

        if orphan_orders or missing_local_orders or orphan_positions or missing_broker_positions:
            self._begin_halt("broker_reconciliation_required")
        if self.risk.state is RiskState.HALTING:
            blocked_sells = self._adopt_orphan_sells(orphan_orders, positions)
            self._cancel_open_entries(orders)
            self._ensure_exits(positions, blocked_sells)

        if not self.runner.reconcile_orders():
            self._broker_clean = False
            return False

        # Re-read after reconciliation, since a terminal fill can remove a local intent.
        positions = self._positions_snapshot(now)
        orders = self._open_orders(now)
        if positions is None or orders is None:
            self._begin_halt("invalid_broker_snapshot")
            return False
        local_orders = {order.id: order for order in self.runner.pending_orders}
        local_client_ids = {order.client_order_id for order in self.runner.pending_orders}
        unmatched_orders = [order for order in orders if order.id not in local_orders and order.client_order_id not in local_client_ids]
        broker_by_ticker = {position.ticker: position for position in positions}
        local_by_ticker = {position.ticker: position for position in self.risk.positions}
        position_mismatch = any(
            not self._same_position(local_by_ticker.get(ticker), position)
            for ticker, position in broker_by_ticker.items()
        ) or any(
            not self._same_position(broker_by_ticker.get(ticker), position)
            for ticker, position in local_by_ticker.items()
        )
        reconciled = not unmatched_orders and not position_mismatch and not self._missing_local_orders()
        terminal_cleanup = (
            reconciled
            and not positions
            and not orders
            and not self.runner.pending_orders
            and not self.risk.reservations
            and not self.risk.positions
        )
        if self.risk.state is RiskState.HALTING and terminal_cleanup:
            self.risk.complete_halt(clean_reconciliation=True)
            self._persist_or_halt("halt_persistence_failure")
            self._broker_clean = self.risk.state is RiskState.HALTED
        elif unmatched_orders or position_mismatch:
            self._begin_halt("broker_reconciliation_required")
        elif self.risk.state is RiskState.ACTIVE:
            self._broker_clean = reconciled
        else:
            self._broker_clean = terminal_cleanup and self.risk.state is RiskState.HALTED
        return self._broker_clean

    def _missing_local_orders(self) -> bool:
        for pending in self.runner.pending_orders:
            try:
                if pending.id == pending.client_order_id:
                    found = self._call(self.executor.order_by_client_id, pending.client_order_id)
                else:
                    found = self._call(self.executor.order, pending.id)
            except Exception:
                return True
            if found is None or not self._fresh(getattr(found, "observed_at", None)):
                return True
        return False

    def _cancel_open_entries(self, orders) -> None:
        for order in orders:
            if order.side is Side.BUY:
                try:
                    self._call(self.executor.cancel, order.id)
                except Exception:
                    # Reconciliation is intentionally incomplete after a failed cancel.
                    pass

    def _adopt_orphan_sells(self, orphan_orders, broker_positions: list[Position]) -> set[str]:
        """Track a valid broker-originated sell before attempting any cleanup exit.

        An orphan sell is already reducing the broker position.  It must block
        a duplicate local exit even when its fields are too unsafe to adopt;
        a valid snapshot is persisted as a normal pending sell so fill deltas
        can be reconciled through the runner.
        """
        blocked_tickers: set[str] = set()
        positions_by_ticker = {position.ticker: position for position in broker_positions}
        pending_ids = {order.id for order in self.runner.pending_orders}
        pending_sell_tickers = {order.ticker for order in self.runner.pending_orders if order.side is Side.SELL}
        for order in orphan_orders:
            if order.side is not Side.SELL or order.ticker not in positions_by_ticker:
                continue
            blocked_tickers.add(order.ticker)
            position = positions_by_ticker[order.ticker]
            if order.ticker in pending_sell_tickers or order.id in pending_ids:
                continue
            if not self._safe_orphan_sell(order, position):
                continue
            self.runner.pending_orders.append(order)
            pending_ids.add(order.id)
            pending_sell_tickers.add(order.ticker)
            if not self.runner._persist():
                self._begin_halt("orphan_sell_persistence_failure")
        return blocked_tickers

    def _ensure_exits(self, broker_positions: list[Position], blocked_sells: set[str] | None = None) -> None:
        pending_sell_tickers = {order.ticker for order in self.runner.pending_orders if order.side is Side.SELL}
        pending_sell_tickers.update(blocked_sells or set())
        known = {position.ticker: position for position in self.risk.positions}
        for position in broker_positions:
            if position.ticker not in known or not self._same_position(known[position.ticker], position):
                self.risk.positions = [item for item in self.risk.positions if item.ticker != position.ticker] + [position]
            if position.ticker not in pending_sell_tickers:
                self.runner._close(position, 1.0, "orphan")

    @staticmethod
    def _safe_orphan_sell(order, position: Position) -> bool:
        return (
            isinstance(getattr(order, "id", None), str)
            and bool(order.id)
            and isinstance(getattr(order, "client_order_id", None), str)
            and bool(order.client_order_id)
            and order.side is Side.SELL
            and order.ticker == position.ticker
            and EngineLifecycle._positive(getattr(order, "qty", None))
            and order.qty <= position.qty
            and isinstance(getattr(order, "status", None), str)
            and EngineLifecycle._aware(getattr(order, "observed_at", None))
        )

    def _begin_halt(self, reason: str) -> None:
        self.risk.begin_halt(reason)
        self._broker_clean = False
        self._persist_or_halt(reason)

    def _persist_or_halt(self, reason: str) -> bool:
        if self.runner._persist():
            return True
        self.risk.begin_halt(reason)
        self._broker_clean = False
        return False

    def _account_snapshot(self, now):
        try:
            snapshot = self._call(self.executor.account_snapshot, now=now)
        except Exception:
            return None
        equity = getattr(snapshot, "equity", None)
        return snapshot if self._positive(equity) and self._fresh(getattr(snapshot, "observed_at", None)) else None

    def _positions_snapshot(self, now):
        try:
            snapshot = self._call(self.executor.positions_snapshot, now=now)
        except Exception:
            return None
        positions = getattr(snapshot, "positions", None)
        if not self._fresh(getattr(snapshot, "observed_at", None)) or not isinstance(positions, list):
            return None
        return positions if all(self._valid_position(position) for position in positions) else None

    def _open_orders(self, now):
        try:
            orders = self._call(self.executor.open_orders, now=now)
        except Exception:
            return None
        if not isinstance(orders, list):
            return None
        return orders if all(self._fresh(getattr(order, "observed_at", None)) for order in orders) else None

    def _call(self, method, *args, now=None):
        try:
            supports_now = "now" in inspect.signature(method).parameters
        except (TypeError, ValueError):
            supports_now = False
        return method(*args, now=now) if supports_now else method(*args)

    def _at_cutoff(self, now: datetime) -> bool:
        if not getattr(self.cfg, "flatten_at_close", False):
            return False
        try:
            cutoff = time.fromisoformat(self.cfg.flatten_time)
            return now.astimezone(EASTERN).time() >= cutoff
        except (AttributeError, TypeError, ValueError):
            self._begin_halt("invalid_flatten_time")
            return True

    def _session_id(self, now: datetime) -> str:
        return now.date().isoformat()

    def _now(self) -> datetime:
        now = self._clock()
        if not self._aware(now):
            raise ValueError("lifecycle clock must return an aware datetime")
        return now

    def _fresh(self, observed_at) -> bool:
        if not self._aware(observed_at):
            return False
        try:
            age = (self._now() - observed_at).total_seconds()
            maximum = float(self.cfg.max_snapshot_age_seconds)
            return math.isfinite(age) and math.isfinite(maximum) and 0 <= age <= maximum
        except (AttributeError, OverflowError, TypeError, ValueError):
            return False

    @staticmethod
    def _same_position(left, right) -> bool:
        return left is not None and left.ticker == right.ticker and math.isclose(left.qty, right.qty, rel_tol=1e-9, abs_tol=1e-9)

    @staticmethod
    def _valid_position(position) -> bool:
        return isinstance(getattr(position, "ticker", None), str) and EngineLifecycle._positive(getattr(position, "qty", None)) and EngineLifecycle._positive(getattr(position, "avg_entry_price", None))

    @staticmethod
    def _positive(value) -> bool:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0

    @staticmethod
    def _aware(value) -> bool:
        return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
