"""Fail-closed paper-engine lifecycle coordination.

This module deliberately owns the transition between persisted local intent and
the broker's current view.  A successful submission is never reconciliation;
only a fresh broker snapshot can unblock the next lifecycle step.
"""

from __future__ import annotations

import inspect
import math
from datetime import datetime, time, timezone

from autotrader.halt import HaltClass, classify_halt
from autotrader.market import EASTERN
from autotrader.models import Equity, RiskState, Side


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
        now = self._now()
        # Recover a restored non-ACTIVE state from broker truth before reconciling, so a
        # recoverable halt (e.g. broker_reconciliation_required) is resolved by adopting
        # the broker's real book. A genuine safety halt is never auto-recovered, and a
        # prior-session state still awaiting an explicit local rearm is left untouched.
        if self.risk.state is not RiskState.ACTIVE and self._recovery_permitted() and not self._genuine_halt_latched():
            positions = self._positions_snapshot(now)
            orders = self._open_orders(now)
            if positions is not None and orders is not None:
                self._recover_from_broker(positions, orders, now)
        return self._reconcile_and_cleanup() and self._account_valid and not self._requires_rearm

    def _ensure_rollover(self, day: str) -> None:
        """Roll a long-lived process into a fresh session from broker truth.

        Called when the observed calendar day changes. Recovering with the new session
        id resets session-scoped counters (RiskManager.recover's new-session branch) so
        the new session starts clean instead of serving yesterday's state. A prior
        session still awaiting an explicit local rearm and a genuine safety halt are
        never auto-rolled.
        """
        if self._requires_rearm:
            return
        if self._genuine_halt_latched():
            return
        now = self._now()
        if self._session_id(now) != day:
            return
        if self.risk.session_id == day:
            return
        # Only a fresh broker snapshot can unblock a rollover. A failed read must abort
        # BEFORE recovery, never become an empty book that drops live positions.
        positions = self._positions_snapshot(now)
        orders = self._open_orders(now)
        if positions is None or orders is None:
            return
        # Fetch the account snapshot before committing recovery so a failed account read
        # leaves the pre-rollover session state untouched (no half-rolled session).
        account = self._account_snapshot(now)
        if account is None:
            return
        if not self._recover_from_broker(positions, orders, now):
            return
        # A new session re-baselines its stop levels (daily_stop/hard_stop) from a
        # fresh broker account snapshot, exactly like a cold startup would.
        self.risk.day_start_equity = account.equity
        self.risk.peak_equity = account.equity
        self.runner.equity = Equity(
            account.equity, account.equity, account.equity, self._session_id(now)
        )

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
            # The cutoff stops entries for the day; it must not also suppress the
            # end-of-day flatten. Run the one exit pass with the configured flatten time.
            self.runner.manage_exits(flatten_time=self._configured_flatten_time(), now=now)
            return False
        if not self._reconcile_and_cleanup():
            return False
        if not self.can_scan:
            return False
        snapshot = self._account_snapshot(now)
        if snapshot is None:
            self._account_valid = False
            if not self._genuine_halt_latched():
                self._begin_halt("invalid_account_snapshot")
            return False
        self._account_valid = True
        equity = snapshot.equity
        self.risk.peak_equity = max(self.risk.peak_equity, equity)
        self.runner.equity = Equity(equity, self.risk.day_start_equity, self.risk.peak_equity, self._session_id(now))
        if self.risk.hard_stop_triggered(equity):
            self._persist_or_halt("halt_persistence_failure")
            self._reconcile_and_cleanup()
            return False
        if getattr(self.cfg, "risk_profile", "initial") != "multi-entry" and self.risk.daily_stop_triggered(equity):
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
            daily_realized_loss_pct=loaded.daily_realized_loss_pct,
        ):
            self.risk.begin_halt("invalid_persisted_risk_state")
        snapshot = self._account_snapshot(self._now())
        if snapshot is None:
            self._account_valid = False
            if not self._genuine_halt_latched():
                self.risk.begin_halt("invalid_account_snapshot")
            return
        self._account_valid = True
        session = self._session_id(self._now())
        same_session = loaded.equity is not None and loaded.equity.day == session
        if same_session:
            # Same-session restart: preserve the persisted day-start baseline and peak so
            # day P&L accounting survives a mid-day engine restart. Only the live equity is
            # refreshed from the broker snapshot.
            persisted_baseline = loaded.equity.day_start_equity
            persisted_peak = max(loaded.equity.peak_equity, snapshot.equity)
            live_equity = snapshot.equity
            self.risk.day_start_equity = persisted_baseline
            self.risk.peak_equity = persisted_peak
            self.runner.equity = Equity(live_equity, persisted_baseline, persisted_peak, session)
        else:
            # Fresh session (or no persisted equity): the broker's open equity is the
            # authoritative new day-start baseline.
            self.risk.day_start_equity = snapshot.equity
            self.risk.peak_equity = snapshot.equity
            self.runner.equity = Equity(
                snapshot.equity,
                snapshot.equity,
                snapshot.equity,
                session,
            )
        if self.risk.state is RiskState.ACTIVE and self.risk.session_id != session:
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
            if not self._genuine_halt_latched():
                self._begin_halt("invalid_broker_snapshot")
            return False

        # A genuine integrity halt (kill switch, daily stop) must survive the whole
        # reconcile. RiskManager.begin_halt overwrites halt_reason unconditionally, so
        # capture it before a broker divergence can latch a recoverable reason over it.
        # State-independent: recovery must never clear a HALT-class halt_reason for any
        # non-ACTIVE state (including RECOVERING).
        safety_halt_latched = self._genuine_halt_latched()

        local_orders = {order.id: order for order in self.runner.pending_orders}
        local_client_ids = {order.client_order_id for order in self.runner.pending_orders}
        pending_buy_tickers = {order.ticker for order in self.runner.pending_orders if order.side is Side.BUY}
        orphan_orders = [order for order in orders if order.id not in local_orders and order.client_order_id not in local_client_ids]
        missing_local_orders = self._missing_local_orders()
        broker_by_ticker = {position.ticker: position for position in positions}
        local_by_ticker = {position.ticker: position for position in self.risk.positions}
        orphan_positions = [
            position
            for ticker, position in broker_by_ticker.items()
            if ticker not in pending_buy_tickers and not self._same_position(local_by_ticker.get(ticker), position)
        ]
        missing_broker_positions = [position for ticker, position in local_by_ticker.items() if not self._same_position(broker_by_ticker.get(ticker), position)]

        if orphan_orders or missing_local_orders or orphan_positions or missing_broker_positions:
            if not safety_halt_latched:
                self._begin_halt("broker_reconciliation_required")
        if self._recovery_permitted() and not safety_halt_latched:
            # Regenerate local books from broker truth (adopt real positions, release
            # ghosts, bind confirmed orders). Never submits a sell. If broker truth
            # cannot be read, risk stays HALTING/RECOVERING and the next tick retries.
            self._recover_from_broker(positions, orders, now)

        if not self.runner.reconcile_orders():
            self._broker_clean = False
            return False

        # Re-read after reconciliation, since a terminal fill can remove a local intent.
        positions = self._positions_snapshot(now)
        orders = self._open_orders(now)
        if positions is None or orders is None:
            if not self._genuine_halt_latched():
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
            if not safety_halt_latched:
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
            if pending.id == pending.client_order_id:
                # Unbound intent: a client-ID lookup returning no record is an uncertain
                # submission the runner holds for retry, never a missing broker order.
                if found is None:
                    continue
            if found is None or not self._fresh(getattr(found, "observed_at", None)):
                return True
        return False

    def _genuine_halt_latched(self) -> bool:
        """True when the current halt_reason is a fail-closed (HALT-class) reason.

        State-independent, so a genuine safety halt is never downgraded by a
        recoverable begin_halt at any lifecycle site, for any non-ACTIVE state.
        """
        reason = self.risk.halt_reason
        return reason is not None and classify_halt(reason) is HaltClass.HALT

    def _recovery_permitted(self) -> bool:
        """Only broker-truth divergence is recoverable, never a true-safety halt.

        A restored HALTING/RECOVERING state is reconciled from the broker unless it
        is a fail-closed halt (kill switch, daily stop, cutoff) or the next session
        still requires an explicit local rearm.
        """
        if self._requires_rearm:
            return False
        if self.risk.state in (RiskState.HALTING, RiskState.RECOVERING):
            reason = self.risk.halt_reason
            return reason is None or classify_halt(reason) is HaltClass.RECOVERABLE
        return False

    def _recover_from_broker(self, broker_positions, broker_orders, now) -> bool:
        """Reconcile from broker truth. Never sells.

        A local pending order can be terminal at the broker (filled/cancelled/rejected)
        between ticks, so it is absent from the open-order snapshot. This routine first
        BOOKS every broker-confirmed terminal fill through the runner's monotonic
        reconcile machinery, and only then lets risk.recover adopt broker positions,
        release true ghosts, and bind still-open orders. Booking before pruning is what
        preserves realized P&L and the daily-loss gate. No order is ever submitted here.
        """
        confirmed_client_ids = [getattr(order, "client_order_id", None) for order in broker_orders]
        confirmed_client_ids = [cid for cid in confirmed_client_ids if isinstance(cid, str)]
        confirmed = set(confirmed_client_ids)

        # A local intent is a true ghost only when the broker has no record of it at all
        # (neither open nor terminal). Drop only those, so that a terminal-but-unfilled
        # order still survives to be booked below and an open order stays bound.
        self.runner.pending_orders = [
            pending for pending in self.runner.pending_orders if self._broker_order_record(pending) is not None
        ]

        # Book broker-confirmed terminal fills and bind live orders BEFORE risk.recover
        # overwrites the local books with broker truth. This path only reports what the
        # broker already confirmed; it never submits an order.
        if not self.runner.reconcile_orders():
            return False

        ok = self.risk.recover(
            positions=list(broker_positions),
            confirmed_client_ids=confirmed_client_ids,
            session_id=self._session_id(now),
        )
        if not ok:
            return False
        self.runner.pending_orders = [o for o in self.runner.pending_orders if o.client_order_id in confirmed]
        self._broker_clean = True
        return self._persist_or_halt("recover_persistence_failure")

    def _broker_order_record(self, pending):
        """The broker's record for a local intent, or None when the broker has none.

        Looks up by client order ID while the intent is unbound and by broker order ID
        once acknowledged. Unlike open_orders(), a terminal record is returned as well,
        so a broker-confirmed fill is never mistaken for a ghost.
        """
        try:
            if pending.id == pending.client_order_id:
                return self._call(self.executor.order_by_client_id, pending.client_order_id)
            return self._call(self.executor.order, pending.id)
        except Exception:
            return None

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
        cutoff = self._configured_flatten_time()
        if cutoff is None:
            self._begin_halt("invalid_flatten_time")
            return True
        return now.astimezone(EASTERN).time() >= cutoff

    def _configured_flatten_time(self) -> time | None:
        """Parse the configured flatten time into a `time`, or None when unusable."""
        try:
            return time.fromisoformat(self.cfg.flatten_time)
        except (AttributeError, TypeError, ValueError):
            return None

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
