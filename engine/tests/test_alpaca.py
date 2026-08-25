from autotrader.providers.fixtures import FixtureProvider


def test_fixture_provider_latest_price():
    p = FixtureProvider()
    assert p.latest_price("AAPL") == 190.0


def test_fixture_provider_bars_length():
    p = FixtureProvider()
    bars = p.bars("AAPL", limit=50)
    assert len(bars) == 50
    assert all(b["close"] > 0 for b in bars)


def test_fixture_provider_news():
    p = FixtureProvider()
    news = p.news("AAPL", limit=5)
    assert len(news) == 5
    assert all("headline" in n for n in news)
