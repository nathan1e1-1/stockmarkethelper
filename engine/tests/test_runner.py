from autotrader.runner import Runner
from autotrader.models import Decision, AgentDecision, SignalSet, Signal, Equity, Position, Side
from autotrader.providers.fixtures import FixtureProvider
import pytest


class BuyAgent:
    def decide(self, ss):
        return AgentDecision(ticker=ss.ticker, decision=Decision.BUY, rationale="t", confidence=0.7, signals=ss)


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


def test_runner_scans_and_buys_candidate():
    runner = Runner(provider=FixtureProvider(), agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["AAPL"])
    assert len(runner.executor.submitted) >= 1


def test_runner_records_decisions():
    runner = Runner(provider=FixtureProvider(), agent=BuyAgent(), executor=FakeExec(), risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["AAPL"])
    assert len(runner.decisions) == 1


class PriceProvider:
    def __init__(self, price):
        self.price = price

    def latest_price(self, ticker):
        return self.price


class ExitCfg:
    stop_loss_pct = 0.02
    take_profit_pct = 0.03


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
    runner.manage_exits()
    assert ex.sold == [("AAPL", 10)]
    assert len(runner.closed_trades) == 1
    t = runner.closed_trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.realized_pnl == pytest.approx(-30.0)
    assert risk.positions == []


def test_manage_exits_no_trigger_when_within_band():
    risk = FakeRisk([Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0)])
    ex = SellExec()
    runner = Runner(provider=PriceProvider(101.0), agent=None, executor=ex, risk=risk, cfg=ExitCfg())
    runner.manage_exits()
    assert ex.sold == []
    assert runner.closed_trades == []


def test_runner_skips_bad_ticker_and_continues():
    class BadTickerProvider(FixtureProvider):
        def bars(self, ticker, limit=50):
            if ticker == "BAD":
                raise RuntimeError("no data")
            return super().bars(ticker, limit)

    ex = FakeExec()
    runner = Runner(provider=BadTickerProvider(), agent=BuyAgent(), executor=ex, risk=None, cfg=None)
    runner.equity = Equity(equity=100000.0, day_start_equity=100000.0, peak_equity=100000.0, day="d")
    runner.run_once(universe=["BAD", "AAPL"])
    assert len(ex.submitted) >= 1


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
    assert ex.sold == [("INTC", 22)]


def test_reconcile_no_positions_is_noop():
    class EmptyExec:
        def positions(self):
            return []

        def sell(self, ticker, qty):
            raise AssertionError("should not sell")

    runner = Runner(provider=FixtureProvider(), agent=None, executor=EmptyExec(), risk=None, cfg=None)
    runner.reconcile()  # must not raise or sell
