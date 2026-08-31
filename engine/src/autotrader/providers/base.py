from typing import Protocol

from autotrader.history import HistoryRange


class MarketDataProvider(Protocol):
    def latest_price(self, ticker: str) -> float: ...
    def latest_prices(self, tickers: list[str]) -> dict[str, float]: ...
    def search_assets(self, query: str, limit: int = 10) -> list[dict]: ...
    def bars(
        self,
        ticker: str,
        history_range: HistoryRange = HistoryRange.ONE_DAY,
        *,
        limit: int | None = None,
    ) -> list[dict]: ...
    def gainers(self, limit: int) -> list[dict]: ...


class NewsProvider(Protocol):
    def news(self, ticker: str, limit: int = 5) -> list[dict]: ...
