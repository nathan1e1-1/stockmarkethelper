import sys
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone

import pytest

from autotrader.lifecycle import EngineLifecycle
from autotrader.main import _parse_args
from autotrader.models import AccountSnapshot, Equity, Order, Position, PositionsSnapshot, RiskState, Side
from autotrader.risk import RiskManager
from autotrader.runner import Runner
from autotrader.state import State, StateStore


NOW = datetime(2026, 9, 2, 14, 30, tzinfo=timezone.utc)


class Config:
    alpaca_paper = True
    paper_capital = 100_000.0
    max_position_pct = 0.0025
    max_gross_exposure_pct = 0.0025
    max_positions = 1
    max_entries_per_session = 1
    max_snapshot_age_seconds = 120
    kill_switch_pct = 0.10
    daily_loss_pct = 0.05
    flatten_at_close = True
    flatten_time = "15:55"
    stop_loss_pct = 0.02
    take_profit_pct = 0.03
    entry_threshold = 2.0
    signal_weights = {"momentum": 1.0}


class Store:
    def __init__(self, loaded=None):
        self.loaded = loaded or State()
        self.saved = []

    def load(self):
        return deepcopy(self.loaded)

    def save_or_raise(self, state):
        self.saved.append(deepcopy(state))


class Executor:
    def __init__(self, positions=None, orders=None, equity=100_000.0):
        self.positions_value = positions or []
        self.orders_value = orders or []
        self.equity = equity
        self.exit_requests = []
        self.cancel_requests = []

    def account_snapshot(self, *, now=None):
        return AccountSnapshot(self.equity, now or NOW)

    def positions_snapshot(self, *, now=None):
        return PositionsSnapshot(deepcopy(self.positions_value), now or NOW)

    def open_orders(self, *, now=None):
        return deepcopy([order for order in self.orders_value if order.status not in {"filled", "cancelled", "canceled", "rejected", "expired"}])

    def submit_exit(self, ticker, qty, client_order_id):
        self.exit_requests.append((ticker, qty, client_order_id))
        order = Order("exit-broker", ticker, Side.SELL, qty, status="accepted", client_order_id=client_order_id,
                      observed_at=NOW, timestamp=NOW, filled_qty=0.0, filled_notional=0.0)
        self.orders_value.append(order)
        return order

    def cancel(self, broker_order_id, *, now=None):
        self.cancel_requests.append(broker_order_id)
        return next(order for order in self.orders_value if order.id == broker_order_id)

    def order(self, broker_order_id, *, now=None):
        return next(order for order in self.orders_value if order.id == broker_order_id)

    def order_by_client_id(self, client_order_id, *, now=None):
        return next((order for order in self.orders_value if order.client_order_id == client_order_id), None)


class Provider:
    pass


def lifecycle(*, store=None, executor=None):
    cfg = Config()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-02")
    executor = executor or Executor()
    store = store or Store()
    runner = Runner(Provider(), None, executor, risk, cfg, state_store=store, clock=lambda: NOW)
    runner.equity = Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02")
    return EngineLifecycle(cfg, executor, risk, runner, store, clock=lambda: NOW), risk, runner, executor, store


def test_startup_reconciliation_orphan_position_halts_until_broker_reports_flat():
    engine, risk, _, executor, _ = lifecycle(executor=Executor(positions=[Position("AAPL", 4, 100.0)]))

    assert engine.startup_reconcile() is False

    assert risk.state is RiskState.HALTING
    assert executor.exit_requests == [("AAPL", 4, "exit-2026-09-02-AAPL-orphan")]
    assert engine.can_scan is False


def test_orphan_nonterminal_sell_is_tracked_without_submitting_a_second_exit():
    orphan_sell = Order(
        "orphan-sell", "AAPL", Side.SELL, 4, status="accepted", client_order_id="broker-sell-aapl",
        timestamp=NOW, observed_at=NOW, filled_qty=0.0, filled_notional=0.0,
    )
    engine, risk, runner, executor, _ = lifecycle(
        executor=Executor(positions=[Position("AAPL", 4, 100.0)], orders=[orphan_sell])
    )

    assert engine.startup_reconcile() is False

    assert risk.state is RiskState.HALTING
    assert executor.exit_requests == []
    assert [order.id for order in runner.pending_orders] == ["orphan-sell"]
    assert engine.can_scan is False
    executor.positions_value = []
    executor.orders_value = [Order(
        "orphan-sell", "AAPL", Side.SELL, 4, status="filled", client_order_id="broker-sell-aapl",
        timestamp=NOW, observed_at=NOW, filled_qty=4.0, filled_notional=400.0, filled_avg_price=100.0,
    )]

    assert engine.startup_reconcile() is True
    assert risk.state is RiskState.HALTED
    executor.positions_value = []
    executor.orders_value = [Order("exit-broker", "AAPL", Side.SELL, 4, status="filled",
                                   client_order_id="exit-2026-09-02-AAPL-orphan", timestamp=NOW, observed_at=NOW,
                                   filled_qty=4.0, filled_notional=400.0, filled_avg_price=100.0)]

    assert engine.startup_reconcile() is True
    assert risk.state is RiskState.HALTED
    assert engine.can_scan is False


def test_cutoff_latches_before_cleanup_and_never_runs_an_entry_scan():
    engine, risk, runner, executor, _ = lifecycle(executor=Executor(positions=[Position("AAPL", 4, 100.0)]))
    engine.startup_reconcile()
    runner.run_once = lambda universe: pytest.fail("cutoff must prevent entry scans")

    engine.tick(datetime(2026, 9, 2, 19, 56, tzinfo=timezone.utc), ["MSFT"])

    assert risk.cutoff_latched is True
    assert executor.exit_requests == [("AAPL", 4, "exit-2026-09-02-AAPL-orphan")]


def test_rearm_requires_next_session_and_clean_broker_reconciliation():
    engine, risk, _, executor, _ = lifecycle(executor=Executor())
    assert engine.startup_reconcile() is True
    risk.begin_halt("daily_stop")
    assert risk.complete_halt(clean_reconciliation=True) is True

    assert engine.request_rearm("2026-09-02") is False
    assert engine.request_rearm("2026-09-03") is False

    next_day = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
    engine._clock = lambda: next_day
    risk._clock = lambda: next_day
    assert engine.request_rearm("2026-09-03") is True
    assert risk.state is RiskState.ACTIVE


def test_rearm_refetches_account_truth_and_keeps_halted_state_when_invalid():
    engine, risk, _, executor, _ = lifecycle(executor=Executor())
    assert engine.startup_reconcile() is True
    risk.begin_halt("daily_stop")
    assert risk.complete_halt(clean_reconciliation=True) is True
    executor.equity = 0.0
    next_day = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
    engine._clock = lambda: next_day
    risk._clock = lambda: next_day

    assert engine.request_rearm("2026-09-03") is False

    assert risk.state is RiskState.HALTED


def test_normal_tick_manages_exits_before_running_entry_scan():
    engine, _, runner, _, _ = lifecycle()
    assert engine.startup_reconcile() is True
    events = []
    runner.manage_exits = lambda **_: events.append("exits")
    runner.run_once = lambda universe: events.append("scan")

    engine.tick(NOW, ["AAPL"])

    assert events == ["exits", "scan"]


def test_lifecycle_refuses_to_start_without_paper_mode_or_state_store():
    engine, _, _, _, _ = lifecycle()
    engine.cfg.alpaca_paper = False
    with pytest.raises(ValueError, match="paper"):
        engine.startup_reconcile()

    cfg = Config()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-02")
    runner = Runner(Provider(), None, Executor(), risk, cfg, state_store=None, clock=lambda: NOW)
    with pytest.raises(ValueError, match="state store"):
        EngineLifecycle(cfg, runner.executor, risk, runner, None, clock=lambda: NOW)


def test_persisted_pending_order_missing_from_broker_keeps_engine_halting():
    pending = Order("buy-1", "AAPL", Side.BUY, 2, status="accepted", client_order_id="entry-2026-09-02-AAPL",
                    timestamp=NOW, observed_at=NOW, filled_qty=0.0, filled_notional=0.0)
    loaded = State(risk_state=RiskState.ACTIVE, session_id="2026-09-02", pending_orders=[pending])
    engine, risk, _, _, _ = lifecycle(store=Store(loaded))

    assert engine.startup_reconcile() is False

    assert risk.state is RiskState.HALTING
    assert engine.can_scan is False


def test_main_exposes_local_only_rearm_flag():
    args = _parse_args(["--rearm"])

    assert args.rearm is True


def test_startup_uses_a_fresh_broker_equity_snapshot_as_the_risk_baseline():
    engine, risk, runner, _, _ = lifecycle(executor=Executor(equity=80_000.0))

    assert engine.startup_reconcile() is True

    assert risk.day_start_equity == 80_000.0
    assert risk.peak_equity == 80_000.0
    assert runner.equity.equity == 80_000.0


def test_same_session_restart_preserves_persisted_day_start_baseline():
    """A same-session restart must NOT clobber day_start_equity with the current broker
    equity (which zeroes the dashboard's day P&L). The persisted baseline must survive."""
    loaded = State(
        equity=Equity(60_000.0, 100_000.0, 100_000.0, "2026-09-02"),  # current 60k, day-start 100k
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
    )
    engine, risk, runner, _, _ = lifecycle(store=Store(loaded), executor=Executor(equity=60_000.0))

    assert engine.startup_reconcile() is True

    assert risk.day_start_equity == 100_000.0, "day-start baseline must be preserved on same-day restart"
    assert runner.equity.equity == 60_000.0


def test_persisted_position_missing_from_broker_stays_halting_and_cannot_scan():
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        positions=[Position("AAPL", 2, 100.0)],
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
    )
    engine, risk, _, _, _ = lifecycle(store=Store(loaded), executor=Executor(positions=[]))

    assert engine.startup_reconcile() is False

    assert risk.state is RiskState.HALTING
    assert engine.can_scan is False


def test_persisted_equity_never_bypasses_invalid_fresh_broker_account_snapshot():
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
    )
    engine, risk, _, _, _ = lifecycle(store=Store(loaded), executor=Executor(equity=0.0))

    assert engine.startup_reconcile() is False

    assert risk.state is not RiskState.ACTIVE
    assert engine.can_scan is False


def test_restored_active_prior_session_requires_local_next_session_rearm():
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-01"),
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-01",
    )
    engine, risk, _, _, _ = lifecycle(store=Store(loaded), executor=Executor())

    assert engine.startup_reconcile() is False

    assert risk.state is RiskState.HALTED
    assert engine.can_scan is False
    assert engine.request_rearm("2026-09-02") is True
    assert risk.state is RiskState.ACTIVE


def test_local_pending_buy_backed_position_is_not_treated_as_orphan():
    """A broker position created by OUR OWN in-flight acknowledged buy (fill not yet reconciled)
    must not be orphan-flushed. The earlier design decided orphan-ness on a pre-reconcile snapshot,
    then _ensure_exits force-sold the position the engine itself had just bought."""
    local_pending = Order(
        "buy-broker-1", "AAPL", Side.BUY, 4, status="accepted", client_order_id="entry-2026-09-02-AAPL",
        timestamp=NOW, observed_at=NOW, filled_qty=0.0, filled_notional=0.0,
    )
    from autotrader.models import Reservation
    reservation = Reservation("entry-2026-09-02-AAPL", "AAPL", 4.0, 100.0, NOW)
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
        session_entry_count=1,
        reservations=[reservation],
        pending_orders=[local_pending],
    )
    # Broker truth: the buy already filled into a position; the committed broker buy order is filled.
    broker_filled_buy = Order(
        "buy-broker-1", "AAPL", Side.BUY, 4, status="filled", client_order_id="entry-2026-09-02-AAPL",
        timestamp=NOW, observed_at=NOW, filled_qty=4.0, filled_notional=400.0, filled_avg_price=100.0,
    )
    executor = Executor(positions=[Position("AAPL", 4, 100.0)], orders=[broker_filled_buy])
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)

    assert engine.startup_reconcile() is True
    assert risk.state is RiskState.ACTIVE
    assert executor.exit_requests == []
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 4)]


def test_ensure_exits_skips_broker_position_with_local_pending_buy():
    """Direct guard test for the destructive NVDA bug: during a HALTING cleanup, _ensure_exits
    must not orphan-flush a broker position that our own in-flight BUY is about to reconcile."""
    position = Position("NVDA", 121, 224.43, opened_at=NOW)
    local_pending_buy = Order(
        "buy-broker-1", "NVDA", Side.BUY, 121, status="accepted",
        client_order_id="entry-2026-09-02-NVDA", timestamp=NOW, observed_at=NOW,
        filled_qty=0.0, filled_notional=0.0,
    )
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.HALTING,
        session_id="2026-09-02",
        positions=[position],
        pending_orders=[local_pending_buy],
    )
    executor = Executor(positions=[position], orders=[])
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)
    engine._restore_state()

    engine._ensure_exits(executor.positions_value)

    assert executor.exit_requests == []
    assert len(runner.pending_orders) == 1
    assert runner.pending_orders[0].side is Side.BUY


def test_unbound_intent_without_broker_record_is_not_missing_local_order():
    """An unbound (submitted, id==client) intent whose client-ID lookup returns no broker
    record is an uncertain submission that the runner holds for retry. It must NOT be
    reported as a missing local order (which would fatal-halt reconciliation)."""
    from autotrader.models import Reservation

    local_pending = Order(
        "entry-2026-09-02-AAPL", "AAPL", Side.BUY, 2, status="submitted",
        client_order_id="entry-2026-09-02-AAPL", timestamp=NOW, observed_at=NOW,
        filled_qty=0.0, filled_notional=0.0,
    )
    reservation = Reservation("entry-2026-09-02-AAPL", "AAPL", 2.0, 100.0, NOW)
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
        reservations=[reservation],
        pending_orders=[local_pending],
    )
    # Broker has no record for this client ID.
    executor = Executor(positions=[], orders=[])
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)

    engine._restore_state()

    assert engine._missing_local_orders() is False
    assert risk.state is RiskState.ACTIVE


def test_bound_intent_without_broker_record_still_counts_as_missing():
    """An acknowledged (bound) pending order whose broker-id lookup returns nothing is a
    genuine missing-broker-order and MUST still halt reconciliation (fail-closed)."""
    local_pending = Order(
        "broker-ack-1", "AAPL", Side.BUY, 2, status="accepted",
        client_order_id="entry-2026-09-02-AAPL", timestamp=NOW, observed_at=NOW,
        filled_qty=0.0, filled_notional=0.0,
    )
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.HALTING,
        session_id="2026-09-02",
        session_entry_count=1,
        pending_orders=[local_pending],
    )
    executor = Executor(positions=[], orders=[])
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)

    engine._restore_state()

    assert engine._missing_local_orders() is True


class MultiEntryConfig(Config):
    max_position_pct = 0.05
    max_gross_exposure_pct = 0.05
    max_positions = 5
    max_entries_per_session = sys.maxsize
    kill_switch_pct = 0.25
    daily_loss_pct = 0.05
    stop_loss_pct = 0.05
    take_profit_pct = 0.05
    risk_per_position_pct = 0.01
    max_daily_risk_pct = 0.05
    risk_profile = "multi-entry"


def multi_lifecycle(*, store=None, executor=None):
    cfg = MultiEntryConfig()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-02")
    executor = executor or Executor()
    store = store or Store()
    runner = Runner(Provider(), None, executor, risk, cfg, state_store=store, clock=lambda: NOW)
    runner.equity = Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02")
    return EngineLifecycle(cfg, executor, risk, runner, store, clock=lambda: NOW), risk, runner, executor, store


def test_multi_entry_tick_keeps_trading_when_equity_above_daily_stop():
    engine, risk, runner, executor, _ = multi_lifecycle()

    assert engine.startup_reconcile() is True
    # 94k < day_start*(1-0.05)=95k: inside the daily-stop band; multi-entry must NOT halt.
    executor.equity = 94_000.0
    assert engine.tick(NOW, []) is True
    assert risk.state is RiskState.ACTIVE


def test_multi_entry_tick_hard_stop_floor_still_halts():
    engine, risk, runner, executor, _ = multi_lifecycle()

    assert engine.startup_reconcile() is True
    executor.equity = 74_000.0  # <= 100k*(1-0.25): hard stop floor still halts
    runner.run_once = lambda universe: None
    engine.tick(NOW, ["AAPL"])
    assert risk.state is not RiskState.ACTIVE


def test_multi_entry_restore_keeps_daily_realized_loss_across_restart():
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.ACTIVE,
        session_id="2026-09-02",
        daily_realized_loss_pct=0.04,
    )
    engine, risk, runner, executor, _ = multi_lifecycle(store=Store(loaded))

    assert engine.startup_reconcile() is True
    assert risk.daily_realized_loss_pct == 0.04
