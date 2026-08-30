from autotrader.providers.base import MarketDataProvider


def build_universe(
    provider: MarketDataProvider,
    size: int = 20,
    min_price: float = 5.0,
    min_volume: int = 500000,
    tickers_only: bool = False,
) -> list:
    candidates = provider.gainers(limit=size * 3)
    tickers = [c["ticker"] for c in candidates]
    prices = provider.latest_prices(tickers) if tickers else {}
    filtered = [
        c for c in candidates
        if c.get("volume", 0) >= min_volume
        and prices.get(c["ticker"], 0.0) >= min_price
    ][:size]
    if tickers_only:
        return [c["ticker"] for c in filtered]
    return filtered
