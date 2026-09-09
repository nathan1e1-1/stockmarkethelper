import sys

from autotrader.exits import DynamicExitEvaluator
from autotrader.runner import Runner
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from autotrader.models import Decision, AgentDecision, SignalSet, Signal, Equity, Order, Position, RiskState, Side
from autotrader.providers.fixtures import FixtureProvider
from autotrader.risk import RiskManager
from autotrader.state import StateStore
import pytest


class BuyAgent:
    def decide(self, ss):
        return AgentDecision(ticker=ss.ticker, decision=Decision.BUY, rationale="t", confidence=0.7, signals=ss)


class FakeMomentum:
    def __init__(self, detail):
        self.detail = detail

    def compute(self, ticker, bars):
        return Signal(name="momentum", value=0.5, detail=self.detail)


class FakeSentiment:
    def __init__(self, value):
        self.value = value

    def compute(self, ticker, news):
        return Signal(name="sentiment", value=self.value, detail={})


class FakeExec:
    def __init__(self):
        self.submitted = []
        self.flat = False

    def market_order(self, ticker, qty, side):
        self.submitted.append((ticker, qty))
        from autotrader.models import Order
        return Order(id="o1", ticker=ticker, side=side, qty=qty)

    def positions(self):
        return []

    def flatten_all(self):
        self.flat = True


def test_runner_without_risk_manager_never_submits_a_market_entry():
    runner = Runner(provider=FixtureProvider(), agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["AAPL"])
    assert runner.executor.submitted == []


def test_runner_records_decisions():
    runner = Runner(provider=FixtureProvider(), agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["AAPL"])
    assert len(runner.decisions) == 1


def test_runner_requests_scan_bars_instead_of_chart_history():
    class ChartRangeProvider(FixtureProvider):
        def __init__(self):
            self.calls = []

        def bars(self, ticker, history_range):
            raise AssertionError("runner must not use chart history for a strategy scan")

        def scan_bars(self, ticker):
            self.calls.append(ticker)
            return super().scan_bars(ticker)

    provider = ChartRangeProvider()
    runner = Runner(provider=provider, agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")

    runner.run_once(universe=["AAPL"])

    assert provider.calls == ["AAPL"]


class PriceProvider:
    def __init__(self, price):
        self.price = price

    def latest_price(self, ticker):
        return self.price

    def latest_quote(self, ticker, *, now=None):
        from autotrader.models import Quote

        timestamp = now or NOW
        return Quote(ticker=ticker, price=self.price, source_timestamp=timestamp, observed_at=timestamp)


class ExitCfg:
    stop_loss_pct = 0.02
    take_profit_pct = 0.03
    max_snapshot_age_seconds = 120


class FakeRisk:
    def __init__(self, positions):
        self.positions = positions


class SellExec:
    def __init__(self):
        self.sold = []

    def sell(self, ticker, qty):
        self.sold.append((ticker, qty))
        from autotrader.models import Order
        return Order(id="s", ticker=ticker, side=Side.SELL, qty=qty)


def test_manage_exits_triggers_stop_loss():
    risk = FakeRisk([Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0)])
    ex = SellExec()
    runner = Runner(provider=PriceProvider(97.0), agent=None, executor=ex, risk=risk, cfg=ExitCfg())
    runner._clock = lambda: NOW
    runner.manage_exits()
    assert ex.sold == []
    assert runner.closed_trades == []
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 10.0)]
    assert len(runner.pending_orders) == 1
    assert runner.pending_orders[0].side is Side.SELL


def test_manage_exits_no_trigger_when_within_band():
    risk = FakeRisk([Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0)])
    ex = SellExec()
    runner = Runner(provider=PriceProvider(101.0), agent=None, executor=ex, risk=risk, cfg=ExitCfg())
    runner.manage_exits()
    assert ex.sold == []
    assert runner.closed_trades == []


def test_runner_skips_bad_ticker_and_continues():
    class BadTickerProvider(FixtureProvider):
        def scan_bars(self, ticker):
            if ticker == "BAD":
                raise RuntimeError("no data")
            return super().scan_bars(ticker)

    ex = FakeExec()
    runner = Runner(provider=BadTickerProvider(), agent=BuyAgent(), executor=ex, risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["BAD", "AAPL"])
    assert ex.submitted == []
    assert [decision.ticker for decision in runner.decisions] == ["AAPL"]


def test_reconcile_closes_stale_positions():
    class ReconcileExec:
        def __init__(self, positions):
            self._positions = positions
            self.sold = []

        def positions(self):
            return self._positions

        def sell(self, ticker, qty):
            self.sold.append((ticker, qty))

    ex = ReconcileExec([Position(ticker="INTC", qty=22.0, avg_entry_price=90.9)])
    runner = Runner(provider=FixtureProvider(), agent=None, executor=ex, risk=None, cfg=None)
    runner.reconcile()
    assert ex.sold == []


def test_reconcile_no_positions_is_noop():
    class EmptyExec:
        def positions(self):
            return []

        def sell(self, ticker, qty):
            raise AssertionError("should not sell")

    runner = Runner(provider=FixtureProvider(), agent=None, executor=EmptyExec(), risk=None, cfg=None)
    runner.reconcile()  # must not raise or sell


@dataclass
class PaperCfg:
    paper_capital: float = 100_000.0
    max_position_pct: float = 0.0025
    max_gross_exposure_pct: float = 0.0025
    max_positions: int = 1
    max_entries_per_session: int = 1
    max_snapshot_age_seconds: int = 120
    kill_switch_pct: float = 0.10
    daily_loss_pct: float = 0.05
    entry_threshold: float = 0.5
    signal_weights: dict = None
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.03

    def __post_init__(self):
        if self.signal_weights is None:
            self.signal_weights = {"momentum": 1.0}


NOW = datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)


class FreshProvider(FixtureProvider):
    def latest_quote(self, ticker, *, now=None):
        from autotrader.models import Quote

        return Quote(ticker=ticker, price=100.0, source_timestamp=NOW, observed_at=NOW)


class RecordingStore:
    def __init__(self):
        self.saved_states = []

    def save_or_raise(self, state):
        self.saved_states.append(deepcopy(state))


class FillExec:
    def __init__(self):
        self.limit_buys = []
        self.exit_requests = []
        self.orders = {}
        self.order_now = None
        self.client_lookup_now = None

    def submit_limit_buy(self, ticker, qty, limit_price, client_order_id):
        self.limit_buys.append((ticker, qty, limit_price, client_order_id))
        order = Order(
            id="buy-1", ticker=ticker, side=Side.BUY, qty=qty,
            status="accepted", client_order_id=client_order_id, observed_at=NOW,
        )
        self.orders[order.id] = order
        return order

    def submit_exit(self, ticker, qty, client_order_id):
        self.exit_requests.append((ticker, qty, client_order_id))
        order = Order(
            id="sell-1", ticker=ticker, side=Side.SELL, qty=qty,
            status="accepted", client_order_id=client_order_id, observed_at=NOW,
        )
        self.orders[order.id] = order
        return order

    def order(self, broker_order_id, *, now=None):
        self.order_now = now
        return self.orders[broker_order_id]

    def order_by_client_id(self, client_order_id, *, now=None):
        self.client_lookup_now = now
        return next((order for order in self.orders.values() if order.client_order_id == client_order_id), None)


def paper_runner():
    cfg = PaperCfg()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-01")
    store = RecordingStore()
    executor = FillExec()
    runner = Runner(
        provider=FreshProvider(), agent=BuyAgent(), executor=executor, risk=risk, cfg=cfg,
        state_store=store,
    )
    runner._clock = lambda: NOW
    runner.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")
    return runner, risk, executor, store


def test_runner_persists_entry_intent_before_limit_submission():
    runner, risk, executor, store = paper_runner()

    runner.run_once(["AAPL"])

    assert store.saved_states[0].pending_orders[0].client_order_id == "entry-2026-09-01-AAPL"
    assert executor.limit_buys == [("AAPL", 2, 100.0, "entry-2026-09-01-AAPL")]
    assert risk.positions == []


def test_pending_buy_becomes_a_position_only_from_a_broker_fill_delta():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="partially_filled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=NOW,
    )

    runner.reconcile_orders()
    runner.reconcile_orders()

    assert [(position.qty, position.avg_entry_price) for position in risk.positions] == [(1, 99)]


def test_cancelled_buy_keeps_only_its_confirmed_fill():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="cancelled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=NOW,
    )

    runner.reconcile_orders()

    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 1)]
    assert runner.pending_orders == []


def test_repeated_partial_sell_snapshot_books_one_actual_fill_slice():
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    executor.orders["sell-1"] = Order(
        id="sell-1", ticker="AAPL", side=Side.SELL, qty=10, status="partially_filled",
        client_order_id=executor.exit_requests[0][2], filled_qty=2, filled_notional=202,
        filled_avg_price=101, observed_at=NOW,
    )

    runner.reconcile_orders()
    runner.reconcile_orders()

    assert [(trade.qty, trade.exit_price, trade.realized_pnl) for trade in runner.closed_trades] == [(2, 101, 2)]
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 8)]


def test_missing_or_decreasing_broker_fills_halt_reconciliation_without_booking():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="accepted",
        client_order_id="entry-2026-09-01-AAPL", observed_at=NOW,
    )

    runner.reconcile_orders()

    assert risk.state is RiskState.HALTING
    assert risk.positions == []


def test_order_lookup_failure_stops_reconciliation():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])

    def unavailable(_):
        raise TimeoutError("broker unavailable")

    executor.order = unavailable

    assert runner.reconcile_orders() is False
    assert risk.state is RiskState.HALTING


def test_timeout_intent_reconciles_by_client_id_without_resubmitting():
    runner, risk, executor, _ = paper_runner()

    def timeout(*_):
        raise TimeoutError("submission outcome unknown")

    executor.submit_limit_buy = timeout
    runner.run_once(["AAPL"])
    executor.orders["buy-after-timeout"] = Order(
        id="buy-after-timeout", ticker="AAPL", side=Side.BUY, qty=2, status="cancelled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=NOW,
    )

    assert runner.reconcile_orders() is True
    assert executor.limit_buys == []
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 1)]
    assert risk.state is RiskState.ACTIVE


def test_submission_timeout_stays_active_so_client_lookup_can_retry():
    """A transient submit/network failure must NOT permanently halt: the intent stays durable
    and the engine stays ACTIVE, so the next reconcile's client-ID lookup can bind a broker
    order that did land, or hold until it appears."""
    runner, risk, executor, _ = paper_runner()

    def timeout(*_):
        raise TimeoutError("submission outcome unknown")

    executor.submit_limit_buy = timeout
    runner.run_once(["AAPL"])

    assert risk.state is RiskState.ACTIVE
    assert risk.halt_reason is None
    assert len(runner.pending_orders) == 1

    # Broker never received it; with no record, reconcile keeps holdings ACTIVE (retry later).
    assert runner.reconcile_orders() is True
    assert risk.state is RiskState.ACTIVE
    assert len(runner.pending_orders) == 1
    assert risk.reservations


def test_submission_timeout_broker_acknowledged_next_tick_binds():
    """If the broker DID accept despite the timeout, the client-ID lookup on the next
    reconcile must bind the acknowledgement and keep the engine ACTIVE."""
    runner, risk, executor, _ = paper_runner()

    def timeout(*_):
        raise TimeoutError("submission outcome unknown")

    executor.submit_limit_buy = timeout
    runner.run_once(["AAPL"])
    assert risk.state is RiskState.ACTIVE

    executor.orders["buy-late-ack"] = Order(
        id="buy-late-ack", ticker="AAPL", side=Side.BUY, qty=2, status="accepted",
        client_order_id="entry-2026-09-01-AAPL", observed_at=NOW,
        filled_qty=0.0, filled_notional=0.0,
    )

    assert runner.reconcile_orders() is True
    assert risk.state is RiskState.ACTIVE
    assert [order.id for order in runner.pending_orders] == ["buy-late-ack"]
    assert risk.session_entry_count == 1


def test_inconsistent_broker_fill_average_halts_without_booking():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="partially_filled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=98, observed_at=NOW,
    )

    assert runner.reconcile_orders() is False
    assert risk.state is RiskState.HALTING
    assert risk.positions == []


def test_decreasing_cumulative_buy_fill_halts_but_keeps_confirmed_position():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="partially_filled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=NOW,
    )
    assert runner.reconcile_orders() is True
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="accepted",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=0, filled_notional=0,
        observed_at=NOW,
    )

    assert runner.reconcile_orders() is False
    assert risk.state is RiskState.HALTING
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 1)]


def test_mismatched_entry_acknowledgement_client_id_halts_without_binding():
    runner, risk, executor, _ = paper_runner()

    def wrong_client_id(ticker, qty, limit_price, client_order_id):
        return Order(
            id="buy-1", ticker=ticker, side=Side.BUY, qty=qty, status="accepted",
            client_order_id="another-entry", observed_at=NOW,
        )

    executor.submit_limit_buy = wrong_client_id
    runner.run_once(["AAPL"])

    assert risk.state is RiskState.HALTING
    assert risk.session_entry_count == 0
    assert runner.pending_orders[0].id == "entry-2026-09-01-AAPL"


def test_missing_state_store_blocks_safety_entry_before_submission():
    runner, risk, executor, _ = paper_runner()
    runner.state_store = None

    runner.run_once(["AAPL"])

    assert executor.limit_buys == []
    assert risk.state is RiskState.HALTING


def test_invalid_terminal_sell_does_not_book_or_reduce_before_halt():
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]
    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    executor.orders["sell-1"] = Order(
        id="sell-1", ticker="AAPL", side=Side.SELL, qty=10, status="filled",
        client_order_id=executor.exit_requests[0][2], filled_qty=2, filled_notional=202,
        filled_avg_price=101, observed_at=NOW,
    )

    assert runner.reconcile_orders() is False
    assert runner.closed_trades == []
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 10)]
    assert risk.state is RiskState.HALTING


def test_any_pending_sell_blocks_a_second_exit_reason_for_the_same_symbol():
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    runner._close(risk.positions[0], price=1.0, reason="take_profit")

    assert len(executor.exit_requests) == 1
    assert len(runner.pending_orders) == 1


def test_stale_order_snapshot_halts_before_booking_a_fill():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="partially_filled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=NOW - timedelta(seconds=121),
    )

    assert runner.reconcile_orders() is False
    assert risk.state is RiskState.HALTING
    assert risk.positions == []


@pytest.mark.parametrize("observed_at", [None, NOW.replace(tzinfo=None), NOW + timedelta(seconds=1)])
def test_missing_naive_or_future_order_snapshot_halts_before_booking(observed_at):
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="partially_filled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=1, filled_notional=99,
        filled_avg_price=99, observed_at=observed_at,
    )

    assert runner.reconcile_orders() is False
    assert risk.state is RiskState.HALTING
    assert risk.positions == []


def test_missing_submit_exit_capability_halts_without_direct_sell_fallback():
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]
    executor.submit_exit = None
    direct_sells = []
    executor.sell = lambda ticker, qty: direct_sells.append((ticker, qty))

    runner._close(risk.positions[0], price=1.0, reason="stop_loss")

    assert executor.exit_requests == []
    assert direct_sells == []
    assert risk.state is RiskState.HALTING


@pytest.mark.parametrize("source_timestamp", [NOW - timedelta(seconds=121), NOW + timedelta(seconds=1)])
def test_stale_or_future_quote_source_timestamp_blocks_submission(source_timestamp):
    runner, risk, executor, _ = paper_runner()

    class UnsafeSourceProvider(FreshProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote

            return Quote(ticker=ticker, price=100.0, source_timestamp=source_timestamp, observed_at=NOW)

    runner.provider = UnsafeSourceProvider()
    runner.run_once(["AAPL"])

    assert executor.limit_buys == []
    assert risk.state is RiskState.HALTING


def test_runner_passes_its_clock_to_quote_provider_when_supported():
    cfg = PaperCfg()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-01")
    executor = FillExec()
    runner = Runner(
        provider=FixtureProvider(), agent=BuyAgent(), executor=executor, risk=risk, cfg=cfg,
        state_store=RecordingStore(), clock=lambda: NOW,
    )
    runner.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")

    runner.run_once(["AAPL"])

    assert len(executor.limit_buys) == 1


def test_runner_passes_its_clock_to_executor_order_lookup_when_supported():
    runner, _, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="accepted",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=0, filled_notional=0,
        observed_at=NOW,
    )

    assert runner.reconcile_orders() is True
    assert executor.order_now == NOW


def test_exit_intent_uses_the_injected_clock_before_submission():
    runner, risk, _, store = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    runner._close(risk.positions[0], price=1.0, reason="stop_loss")

    intent = store.saved_states[0].pending_orders[0]
    assert intent.timestamp == NOW
    assert intent.observed_at == NOW


def test_invalid_exit_clock_halts_before_submission():
    runner, risk, executor, _ = paper_runner()
    runner._clock = lambda: NOW.replace(tzinfo=None)
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    runner._close(risk.positions[0], price=1.0, reason="stop_loss")

    assert executor.exit_requests == []
    assert risk.state is RiskState.HALTING


def test_stale_exit_decision_quote_halts_without_submitting_exit():
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    class StaleExitProvider(PriceProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote

            return Quote(
                ticker=ticker, price=97.0, source_timestamp=NOW - timedelta(seconds=121), observed_at=NOW,
            )

    runner.provider = StaleExitProvider(97.0)
    runner.manage_exits()

    assert executor.exit_requests == []
    assert risk.state is RiskState.HALTING


def test_acknowledgement_without_observation_time_halts_without_binding():
    runner, risk, executor, _ = paper_runner()

    def no_observation_time(ticker, qty, limit_price, client_order_id):
        return Order(
            id="buy-1", ticker=ticker, side=Side.BUY, qty=qty, status="accepted",
            client_order_id=client_order_id,
        )

    executor.submit_limit_buy = no_observation_time
    runner.run_once(["AAPL"])

    assert risk.state is RiskState.HALTING
    assert risk.session_entry_count == 0


def test_immediately_filled_buy_acknowledgement_persists_and_reconciles(tmp_path):
    runner, risk, executor, _ = paper_runner()
    runner.state_store = StateStore(tmp_path)

    def filled_buy(ticker, qty, limit_price, client_order_id):
        order = Order(
            id="buy-1", ticker=ticker, side=Side.BUY, qty=qty, status="filled",
            client_order_id=client_order_id, filled_qty=qty, filled_notional=198,
            filled_avg_price=99, observed_at=NOW,
        )
        executor.orders[order.id] = order
        return order

    executor.submit_limit_buy = filled_buy
    runner.run_once(["AAPL"])

    persisted = runner.state_store.load().pending_orders[0]
    assert persisted.status == "filled"
    assert persisted.filled_qty == 2
    assert persisted.filled_notional == 198
    assert risk.state is RiskState.ACTIVE
    assert runner.reconcile_orders() is True
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 2)]


def test_immediately_filled_sell_acknowledgement_persists_and_reconciles(tmp_path):
    runner, risk, executor, _ = paper_runner()
    runner.state_store = StateStore(tmp_path)
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]

    def filled_exit(ticker, qty, client_order_id):
        order = Order(
            id="sell-1", ticker=ticker, side=Side.SELL, qty=qty, status="filled",
            client_order_id=client_order_id, filled_qty=qty, filled_notional=1_010,
            filled_avg_price=101, observed_at=NOW,
        )
        executor.orders[order.id] = order
        return order

    executor.submit_exit = filled_exit
    runner._close(risk.positions[0], price=1.0, reason="stop_loss")

    persisted = runner.state_store.load().pending_orders[0]
    assert persisted.status == "filled"
    assert persisted.filled_qty == 10
    assert persisted.filled_notional == 1_010
    assert risk.state is RiskState.ACTIVE
    assert runner.reconcile_orders() is True
    assert [(trade.qty, trade.exit_price) for trade in runner.closed_trades] == [(10, 101)]
    assert risk.positions == []


@dataclass
class MultiCfg(PaperCfg):
    max_position_pct: float = 0.05
    max_gross_exposure_pct: float = 0.05
    max_positions: int = 5
    max_entries_per_session: int = sys.maxsize
    kill_switch_pct: float = 0.25
    risk_per_position_pct: float | None = 0.01
    max_daily_risk_pct: float | None = 0.05
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.05
    risk_profile: str = "multi-entry"


def make_multi_runner():
    cfg = MultiCfg()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-01")
    store = RecordingStore()
    executor = FillExec()
    runner = Runner(
        provider=FreshProvider(), agent=BuyAgent(), executor=executor, risk=risk, cfg=cfg,
        state_store=store, clock=lambda: NOW,
    )
    runner.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")
    return runner, risk, executor, store


def test_manage_exits_runs_hard_stop_first_and_skips_dynamic_for_stopped():
    runner, risk, _, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    calls = []

    class StopProvider(FreshProvider):
        def scan_bars(self, ticker):
            calls.append(ticker)
            return super().scan_bars(ticker)

        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=94.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = StopProvider()
    runner.dynamic_exit = DynamicExitEvaluator(take_profit_pct=0.05, provider=runner.provider)

    runner.manage_exits()

    assert runner.pending_orders[0].client_order_id.startswith("exit-2026-09-01-AAPL-stop_loss")
    assert calls == []


def test_manage_exits_hold_from_dynamic_leaves_position_open():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    class DipProvider(FreshProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=96.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = DipProvider()
    runner.dynamic_exit = DynamicExitEvaluator(
        take_profit_pct=0.05, provider=runner.provider,
        momentum=FakeMomentum({"sma_short": 102.0, "sma_long": 100.0}),
    )

    runner.manage_exits()

    assert runner.pending_orders == []
    assert executor.exit_requests == []


def test_dynamic_early_exit_closes_position():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    class EarlyProvider(FreshProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=97.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = EarlyProvider()
    runner.dynamic_exit = DynamicExitEvaluator(
        take_profit_pct=0.05, provider=runner.provider,
        momentum=FakeMomentum({"sma_short": 98.0, "sma_long": 100.0}),
        sentiment=FakeSentiment(-0.5),
    )

    runner.manage_exits()

    assert runner.pending_orders[0].client_order_id.endswith("-exit_early")


def test_stop_loss_fill_increments_daily_realized_loss():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]
    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    executor.orders["sell-1"] = Order(
        id="sell-1", ticker="AAPL", side=Side.SELL, qty=10, status="filled",
        client_order_id=runner.pending_orders[0].client_order_id,
        filled_qty=10, filled_notional=940.0, filled_avg_price=94.0,
        observed_at=NOW, timestamp=NOW,
    )

    runner.reconcile_orders()

    assert risk.daily_realized_loss_pct == pytest.approx(60.0 / 100_000.0)  # (100-94)*10 / day_start


def test_multi_entry_run_once_ignores_daily_stop_band():
    runner, risk, executor, _ = make_multi_runner()
    runner.equity = Equity(equity=94_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")
    runner.run_once([])
    assert risk.state is RiskState.ACTIVE
    assert risk.halt_reason is None


def test_initial_run_once_still_halts_in_daily_stop_band():
    runner, risk, _, _ = paper_runner()
    runner.equity = Equity(equity=94_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")
    runner.run_once([])
    assert risk.state is not RiskState.ACTIVE
    assert risk.halt_reason == "daily_stop"


def test_terminal_cancelled_buy_with_zero_fills_is_absorbed_not_halting():
    """Root-cause regression: a broker-confirmed cancelled buy (zero fills, filled_qty/notional
    normalized to None) must be absorbable as a no-op trade, not permanently halt the engine."""
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="cancelled",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=None, filled_notional=None,
        filled_avg_price=None, observed_at=NOW,
    )

    assert runner.reconcile_orders() is True
    assert runner.pending_orders == []
    assert risk.positions == []
    assert risk.state is RiskState.ACTIVE
    assert risk.halt_reason is None


def test_terminal_rejected_buy_with_zero_fills_is_absorbed_not_halting():
    runner, risk, executor, _ = paper_runner()
    runner.run_once(["AAPL"])
    executor.orders["buy-1"] = Order(
        id="buy-1", ticker="AAPL", side=Side.BUY, qty=2, status="rejected",
        client_order_id="entry-2026-09-01-AAPL", filled_qty=None, filled_notional=None,
        filled_avg_price=None, observed_at=NOW,
    )

    assert runner.reconcile_orders() is True
    assert runner.pending_orders == []
    assert risk.positions == []
    assert risk.state is RiskState.ACTIVE


def test_terminal_cancelled_sell_with_zero_fills_is_absorbed_not_halting():
    """A sell that is terminal (cancelled) with zero fills must not block; position stays intact."""
    runner, risk, executor, _ = paper_runner()
    risk.positions = [Position(ticker="AAPL", qty=10, avg_entry_price=100, opened_at=NOW)]
    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    executor.orders["sell-1"] = Order(
        id="sell-1", ticker="AAPL", side=Side.SELL, qty=10, status="cancelled",
        client_order_id=runner.pending_orders[0].client_order_id,
        filled_qty=None, filled_notional=None, filled_avg_price=None,
        observed_at=NOW, timestamp=NOW,
    )

    assert runner.reconcile_orders() is True
    assert runner.pending_orders == []
    assert [(position.ticker, position.qty) for position in risk.positions] == [("AAPL", 10)]
    assert risk.state is RiskState.ACTIVE
