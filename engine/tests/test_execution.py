from autotrader.execution import AlpacaExecutor
from autotrader.models import Order, Side, Position


class FakeExec:
    def __init__(self):
        self.submitted = []

    def market_order(self, ticker, qty, side):
        self.submitted.append((ticker, qty, side))
        return Order(id="fake-1", ticker=ticker, side=side, qty=qty)

    def positions(self):
        return []


def test_executor_buys():
    ex = FakeExec()
    ex.market_order("AAPL", 20, Side.BUY)
    assert ex.submitted == [("AAPL", 20, Side.BUY)]


def test_executor_lists_positions_empty():
    ex = FakeExec()
    assert ex.positions() == []
