from autotrader.runner import Runner
from autotrader.models import Decision, AgentDecision, SignalSet, Signal, Equity
from autotrader.providers.fixtures import FixtureProvider


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
