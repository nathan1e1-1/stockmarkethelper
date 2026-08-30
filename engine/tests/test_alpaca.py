from autotrader.providers.fixtures import FixtureProvider
from datetime import datetime, timedelta, timezone

from alpaca.data.timeframe import TimeFrameUnit

from autotrader.history import HistoryRange
from autotrader.providers.alpaca import AlpacaProvider


def test_fixture_provider_latest_price():
    p = FixtureProvider()
    assert p.latest_price("AAPL") == 190.0


def test_fixture_provider_bars_length():
    p = FixtureProvider()
    bars = p.bars("AAPL", history_range=HistoryRange.ONE_DAY)
    assert len(bars) == 390
    assert all(b["close"] > 0 for b in bars)


def test_fixture_provider_search_assets_matches_ticker_or_name():
    p = FixtureProvider()

    assert p.search_assets("app") == [{"ticker": "AAPL", "name": "Apple Inc."}]


def test_fixture_provider_one_year_bars_are_daily_full_ohlcv_and_cover_a_year():
    bars = FixtureProvider().bars("AAPL", history_range=HistoryRange.ONE_YEAR)
    timestamps = [datetime.fromisoformat(bar["t"]) for bar in bars]

    assert set(bars[0]) == {"t", "open", "high", "low", "close", "volume"}
    assert timestamps[-1] - timestamps[0] >= timedelta(days=365)
    assert all(after - before == timedelta(days=1) for before, after in zip(timestamps, timestamps[1:]))


def test_fixture_provider_max_bars_are_bounded_and_retain_full_available_history():
    bars = FixtureProvider().bars("AAPL", history_range=HistoryRange.MAX)
    timestamps = [datetime.fromisoformat(bar["t"]) for bar in bars]

    assert len(bars) == 500
    assert timestamps[0] == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert timestamps[-1] - timestamps[0] >= timedelta(days=365 * 50)
    assert timestamps == sorted(timestamps)


def test_fixture_provider_news():
    p = FixtureProvider()
    news = p.news("AAPL", limit=5)
    assert len(news) == 5
    assert all("headline" in n for n in news)


class FakeAsset:
    def __init__(self, symbol, name, tradable=True):
        self.symbol = symbol
        self.name = name
        self.tradable = tradable


class FakeTradingClient:
    def __init__(self, assets):
        self.assets = assets
        self.requests = []

    def get_all_assets(self, request):
        self.requests.append(request)
        return self.assets


class FakeBar:
    def __init__(self, timestamp, close):
        self.timestamp = timestamp
        self.open = close - 1
        self.high = close + 1
        self.low = close - 2
        self.close = close
        self.volume = 100


class FakeDataClient:
    def __init__(self, bars):
        self.bars = bars
        self.requests = []

    def get_stock_bars(self, request):
        self.requests.append(request)
        return {"AAPL": self.bars}


def provider_with(data=None, trading=None):
    provider = object.__new__(AlpacaProvider)
    provider._data = data
    provider._trading = trading
    provider._asset_search_cache = None
    return provider


def test_search_assets_filters_tradable_active_equities_and_caches_result():
    trading = FakeTradingClient(
        [
            FakeAsset("MSFT", "Microsoft Corporation"),
            FakeAsset("MSTR", "MicroStrategy Incorporated"),
            FakeAsset("META", "Meta Platforms", tradable=False),
        ]
    )
    provider = provider_with(trading=trading)

    first = provider.search_assets("mic", limit=1)
    second = provider.search_assets("m", limit=10)

    assert first == [{"ticker": "MSFT", "name": "Microsoft Corporation"}]
    assert second == [
        {"ticker": "MSFT", "name": "Microsoft Corporation"},
        {"ticker": "MSTR", "name": "MicroStrategy Incorporated"},
    ]
    assert len(trading.requests) == 1
    request = trading.requests[0]
    assert request.status.value == "active"
    assert request.asset_class.value == "us_equity"


def test_search_assets_prioritizes_symbol_matches_over_name_only_matches():
    trading = FakeTradingClient(
        [
            FakeAsset("AAA", "Book Holdings"),
            FakeAsset("ZZOO", "Zoologic Holdings"),
        ]
    )
    provider = provider_with(trading=trading)

    result = provider.search_assets("oo")

    assert result == [
        {"ticker": "ZZOO", "name": "Zoologic Holdings"},
        {"ticker": "AAA", "name": "Book Holdings"},
    ]


def test_bars_builds_max_range_request_and_thins_ohlcv_results():
    bars = [
        FakeBar(datetime(1970, 1, 1, tzinfo=timezone.utc), 100.0),
        FakeBar(datetime(2026, 8, 30, tzinfo=timezone.utc), 200.0),
    ]
    data = FakeDataClient(bars)
    provider = provider_with(data=data)

    result = provider.bars("AAPL", HistoryRange.MAX)

    request = data.requests[0]
    assert request.timeframe.amount == 1
    assert request.timeframe.unit is TimeFrameUnit.Day
    assert request.start == datetime(1970, 1, 1)
    assert request.limit is None
    assert result[0] == {
        "t": "1970-01-01T00:00:00+00:00",
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 100.0,
    }
    assert result[-1]["t"] == "2026-08-30T00:00:00+00:00"


def test_bars_builds_one_year_daily_request():
    data = FakeDataClient([])
    provider = provider_with(data=data)

    provider.bars("AAPL", HistoryRange.ONE_YEAR)

    request = data.requests[0]
    assert request.timeframe.amount == 1
    assert request.timeframe.unit is TimeFrameUnit.Day
    assert timedelta(days=365) <= request.end - request.start <= timedelta(days=367)
