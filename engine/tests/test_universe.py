from autotrader.universe import build_universe
from autotrader.providers.fixtures import FixtureProvider


def test_build_universe_filters_by_volume():
    p = FixtureProvider()
    result = build_universe(p, size=10, min_volume=500000)
    assert len(result) <= 10
    assert all(r["volume"] >= 500000 for r in result)


def test_build_universe_returns_tickers_only():
    p = FixtureProvider()
    tickers = build_universe(p, size=10, min_volume=500000, tickers_only=True)
    assert isinstance(tickers, list)
    assert all(isinstance(t, str) for t in tickers)
