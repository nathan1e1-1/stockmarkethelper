from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace

import pytest
from alpaca.common.exceptions import APIError

from autotrader.execution import AlpacaExecutor
from autotrader.models import AccountSnapshot, Order, Position, PositionsSnapshot, Side


class FakeExec:
    def __init__(self):
        self.submitted = []

    def market_order(self, ticker, qty, side):
        self.submitted.append((ticker, qty, side))
        return Order(id="fake-1", ticker=ticker, side=side, qty=qty)

    def positions(self):
        return []

    def sell(self, ticker, qty):
        return self.market_order(ticker, qty, Side.SELL)


def test_executor_buys():
    ex = FakeExec()
    ex.market_order("AAPL", 20, Side.BUY)
    assert ex.submitted == [("AAPL", 20, Side.BUY)]


def test_executor_sells():
    ex = FakeExec()
    ex.sell("AAPL", 20)
    assert ex.submitted == [("AAPL", 20, Side.SELL)]


def test_executor_lists_positions_empty():
    ex = FakeExec()
    assert ex.positions() == []


OBSERVED_TIME = datetime(2026, 9, 1, 14, 31, tzinfo=timezone.utc)


class FakeBrokerOrder:
    def __init__(
        self,
        *,
        id="broker-1",
        symbol="AAPL",
        side="buy",
        qty="2",
        status="new",
        client_order_id="entry-20260901-AAPL",
        filled_qty="1.5",
        filled_avg_price="101.25",
    ):
        self.id = id
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.status = status
        self.client_order_id = client_order_id
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price


class FakeOrderStatus(str, Enum):
    FILLED = "filled"


class FakeBrokerAccount:
    def __init__(self, equity="100000.50"):
        self.equity = equity


class FakeBrokerPosition:
    def __init__(self, symbol="AAPL", qty="2", avg_entry_price="100.25"):
        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price


class FakeBrokerClient:
    def __init__(self, order=None, account=None, positions=None):
        self.order = order or FakeBrokerOrder()
        self.account = account or FakeBrokerAccount()
        self.broker_positions = positions if positions is not None else [FakeBrokerPosition()]
        self.request = None

    def submit_order(self, request):
        self.request = request
        return self.order

    def get_account(self):
        return self.account

    def get_all_positions(self):
        return self.broker_positions

    def get_order_by_id(self, broker_order_id):
        assert broker_order_id == self.order.id
        return self.order

    def get_order_by_client_id(self, client_order_id):
        if client_order_id == self.order.client_order_id:
            return self.order
        raise APIError('{"code": 404, "message": "order not found"}')

    def get_orders(self, request):
        self.open_request = request
        return [self.order]

    def cancel_order_by_id(self, broker_order_id):
        assert broker_order_id == self.order.id
        self.order.status = "canceled"
        return self.order


def paper_config(*, paper=True):
    return SimpleNamespace(alpaca_api_key="key", alpaca_secret_key="secret", alpaca_paper=paper)


def executor_with(client, cfg=None):
    executor = object.__new__(AlpacaExecutor)
    executor.client = client
    executor._paper = True if cfg is None else cfg.alpaca_paper
    return executor


def test_executor_rejects_nonpaper_config_defensively():
    with pytest.raises(ValueError, match="paper trading"):
        AlpacaExecutor(paper_config(paper=False))


def test_executor_returns_timestamped_account_snapshot():
    snapshot = executor_with(FakeBrokerClient()).account_snapshot(now=OBSERVED_TIME)

    assert snapshot == AccountSnapshot(equity=100000.50, observed_at=OBSERVED_TIME)
    assert executor_with(FakeBrokerClient()).get_equity() == 100000.50


def test_executor_returns_timestamped_positions_snapshot():
    snapshot = executor_with(FakeBrokerClient()).positions_snapshot(now=OBSERVED_TIME)

    assert isinstance(snapshot, PositionsSnapshot)
    assert snapshot.observed_at == OBSERVED_TIME
    assert [(position.ticker, position.qty, position.avg_entry_price) for position in snapshot.positions] == [
        ("AAPL", 2.0, 100.25)
    ]
    assert [(position.ticker, position.qty, position.avg_entry_price) for position in executor_with(FakeBrokerClient()).positions()] == [
        ("AAPL", 2.0, 100.25)
    ]


@pytest.mark.parametrize("equity", [None, "not-a-number", "nan", "0", True])
def test_executor_keeps_invalid_account_equity_unknown(equity):
    snapshot = executor_with(FakeBrokerClient(account=FakeBrokerAccount(equity))).account_snapshot(
        now=OBSERVED_TIME
    )

    assert snapshot.equity is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("qty", "not-a-number"), ("avg_entry_price", "not-a-number"), ("qty", True)],
)
def test_executor_keeps_invalid_position_snapshot_unknown(field, value):
    position = FakeBrokerPosition()
    setattr(position, field, value)

    snapshot = executor_with(FakeBrokerClient(positions=[position])).positions_snapshot(now=OBSERVED_TIME)

    assert snapshot.positions is None


def test_executor_submits_day_limit_buy_with_durable_client_id():
    client = FakeBrokerClient()
    order = executor_with(client).submit_limit_buy(
        "AAPL", qty=2, limit_price=100.0, client_order_id="entry-20260901-AAPL"
    )

    assert client.request.symbol == "AAPL"
    assert client.request.qty == 2.0
    assert client.request.limit_price == 100.0
    assert client.request.time_in_force.value == "day"
    assert client.request.side.value == "buy"
    assert client.request.client_order_id == "entry-20260901-AAPL"
    assert order.client_order_id == "entry-20260901-AAPL"


def test_executor_normalizes_lookup_open_order_and_cancel_snapshots():
    client = FakeBrokerClient()
    executor = executor_with(client)

    snapshots = [
        executor.order("broker-1", now=OBSERVED_TIME),
        executor.order_by_client_id("entry-20260901-AAPL", now=OBSERVED_TIME),
        executor.open_orders(now=OBSERVED_TIME)[0],
        executor.cancel("broker-1", now=OBSERVED_TIME),
    ]

    assert [snapshot.observed_at for snapshot in snapshots] == [OBSERVED_TIME] * 4
    assert [snapshot.filled_qty for snapshot in snapshots] == [1.5] * 4
    assert [snapshot.filled_notional for snapshot in snapshots] == [151.875] * 4
    assert snapshots[-1].status == "canceled"


def test_executor_normalizes_enum_order_status_value():
    client = FakeBrokerClient(FakeBrokerOrder(status=FakeOrderStatus.FILLED))

    assert executor_with(client).order("broker-1", now=OBSERVED_TIME).status == "filled"


def test_executor_returns_none_for_unknown_client_order_id():
    assert executor_with(FakeBrokerClient()).order_by_client_id("missing", now=OBSERVED_TIME) is None


@pytest.mark.parametrize(
    ("filled_qty", "filled_avg_price"),
    [(None, "101.25"), ("bad", "101.25"), ("1.5", None), ("1.5", "not-a-price")],
)
def test_executor_keeps_malformed_broker_fill_data_unknown(filled_qty, filled_avg_price):
    client = FakeBrokerClient(FakeBrokerOrder(filled_qty=filled_qty, filled_avg_price=filled_avg_price))

    order = executor_with(client).order("broker-1", now=OBSERVED_TIME)

    assert order.filled_qty is None
    assert order.filled_notional is None
