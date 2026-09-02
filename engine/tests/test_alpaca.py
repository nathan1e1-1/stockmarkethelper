from autotrader.providers.fixtures import FixtureProvider
from datetime import datetime, timedelta, timezone

import pytest
from alpaca.data.timeframe import TimeFrameUnit

from autotrader.history import HistoryRange
from autotrader.providers.alpaca import AlpacaProvider
from autotrader.models import Quote


SOURCE_TIME = datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)
OBSERVED_TIME = datetime(2026, 9, 1, 14, 31, tzinfo=timezone.utc)


def test_fixture_provider_latest_price():
    p = FixtureProvider()
    assert p.latest_price("AAPL") == 190.0


def test_fixture_provider_latest_quote_is_deterministic():
    assert FixtureProvider().latest_quote("AAPL") == Quote(
        "AAPL",
        190.0,
        datetime(2026, 8, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 30, tzinfo=timezone.utc),
    )


def test_fixture_provider_uses_injected_time_for_fresh_quote():
    assert FixtureProvider().latest_quote("AAPL", now=OBSERVED_TIME) == Quote(
        "AAPL", 190.0, OBSERVED_TIME, OBSERVED_TIME
    )


def test_fixture_provider_rejects_naive_injected_time():
    with pytest.raises(ValueError, match="invalid quote timestamp"):
        FixtureProvider().latest_quote("AAPL", now=datetime(2026, 9, 1, 14, 31))


def test_fixture_provider_bars_length():
    p = FixtureProvider()
    bars = p.bars("AAPL", history_range=HistoryRange.ONE_DAY)
    assert len(bars) == 390
    assert all(b["close"] > 0 for b in bars)


def test_fixture_provider_scan_bars_are_fixed_to_fifty_one_minute_bars():
    bars = FixtureProvider().scan_bars("AAPL")
    timestamps = [datetime.fromisoformat(bar["t"]) for bar in bars]

    assert len(bars) == 50
    assert all(after - before == timedelta(minutes=1) for before, after in zip(timestamps, timestamps[1:]))


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
    assert all(set(n) == {"headline", "summary", "created_at", "source"} for n in news)
    assert all(n["created_at"] == "2026-08-30T00:00:00+00:00" for n in news)
    assert all(n["source"] == "FixtureProvider" for n in news)


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


class FakeTrade:
    def __init__(self, price, timestamp):
        self.price = price
        self.timestamp = timestamp


class FakeLatestTradeDataClient:
    def __init__(self, trade):
        self.trade = trade
        self.requests = []

    def get_stock_latest_trade(self, request):
        self.requests.append(request)
        return {"AAPL": self.trade}


class FakeNewsArticle:
    def __init__(self, headline, summary, created_at, source):
        self.headline = headline
        self.summary = summary
        self.created_at = created_at
        self.source = source


class FakeNewsClient:
    def __init__(self, news):
        self.news = news
        self.requests = []

    def get_news(self, request):
        self.requests.append(request)
        return type("FakeNewsResponse", (), {"data": {"news": self.news}})()


def provider_with(data=None, trading=None, news=None):
    provider = object.__new__(AlpacaProvider)
    provider._data = data
    provider._trading = trading
    provider._news = news
    provider._asset_search_cache = None
    return provider


def test_latest_quote_preserves_source_and_observation_time():
    provider = provider_with(data=FakeLatestTradeDataClient(FakeTrade(190.0, SOURCE_TIME)))

    assert provider.latest_quote("AAPL", now=OBSERVED_TIME) == Quote(
        "AAPL", 190.0, SOURCE_TIME, OBSERVED_TIME
    )


def test_latest_price_remains_a_compatibility_wrapper():
    provider = provider_with(data=FakeLatestTradeDataClient(FakeTrade(190.0, SOURCE_TIME)))

    assert provider.latest_price("AAPL") == 190.0


def test_latest_quote_rejects_naive_injected_time():
    provider = provider_with(data=FakeLatestTradeDataClient(FakeTrade(190.0, SOURCE_TIME)))

    with pytest.raises(ValueError, match="invalid quote timestamp"):
        provider.latest_quote("AAPL", now=datetime(2026, 9, 1, 14, 31))


@pytest.mark.parametrize(
    ("price", "source_timestamp"),
    [
        (0.0, SOURCE_TIME),
        (-1.0, SOURCE_TIME),
        (float("nan"), SOURCE_TIME),
        (190.0, None),
        (190.0, datetime(2026, 9, 1, 14, 30)),
    ],
)
def test_latest_quote_fails_closed_for_invalid_broker_data(price, source_timestamp):
    provider = provider_with(data=FakeLatestTradeDataClient(FakeTrade(price, source_timestamp)))

    with pytest.raises(ValueError, match="invalid quote"):
        provider.latest_quote("AAPL", now=OBSERVED_TIME)

    with pytest.raises(ValueError, match="invalid quote"):
        provider.latest_price("AAPL")


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


def test_scan_bars_builds_the_legacy_seven_day_one_minute_fifty_bar_request():
    data = FakeDataClient([])
    provider = provider_with(data=data)

    provider.scan_bars("AAPL")

    request = data.requests[0]
    assert request.timeframe.amount == 1
    assert request.timeframe.unit is TimeFrameUnit.Minute
    assert request.limit == 50
    assert timedelta(days=7) <= request.end - request.start <= timedelta(days=7, seconds=1)


def test_news_normalizes_created_at_and_source():
    created_at = datetime(2026, 8, 30, 15, 45, tzinfo=timezone.utc)
    news = [
        FakeNewsArticle(
            "AAPL launches new product",
            "Apple announced a new product line.",
            created_at,
            "Reuters",
        )
    ]
    provider = provider_with(news=FakeNewsClient(news))

    result = provider.news("AAPL", limit=1)

    assert result == [
        {
            "headline": "AAPL launches new product",
            "summary": "Apple announced a new product line.",
            "created_at": "2026-08-30T15:45:00+00:00",
            "source": "Reuters",
        }
    ]


def test_news_maps_blank_source_and_non_datetime_created_at_to_none():
    news = [
        FakeNewsArticle(
            "AAPL launches new product",
            "Apple announced a new product line.",
            "not-a-datetime",
            "   ",
        )
    ]
    provider = provider_with(news=FakeNewsClient(news))

    result = provider.news("AAPL", limit=1)

    assert result == [
        {
            "headline": "AAPL launches new product",
            "summary": "Apple announced a new product line.",
            "created_at": None,
            "source": None,
        }
    ]


def test_news_excludes_blank_headlines_and_strips_summary():
    news = [
        FakeNewsArticle(None, "  skip me  ", datetime(2026, 8, 30, tzinfo=timezone.utc), "Reuters"),
        FakeNewsArticle("   ", "  skip me too  ", datetime(2026, 8, 30, tzinfo=timezone.utc), "Reuters"),
        FakeNewsArticle(
            "AAPL launches new product",
            "  Apple announced a new product line.  ",
            datetime(2026, 8, 30, 15, 45, tzinfo=timezone.utc),
            "Reuters",
        ),
    ]
    provider = provider_with(news=FakeNewsClient(news))

    result = provider.news("AAPL", limit=3)

    assert result == [
        {
            "headline": "AAPL launches new product",
            "summary": "Apple announced a new product line.",
            "created_at": "2026-08-30T15:45:00+00:00",
            "source": "Reuters",
        }
    ]
