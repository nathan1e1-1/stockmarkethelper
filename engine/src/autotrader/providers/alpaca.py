from alpaca.data import (
    DataFeed,
    MostActivesBy,
    MostActivesRequest,
    NewsClient,
    NewsRequest,
    ScreenerClient,
    StockBarsRequest,
    StockHistoricalDataClient,
    StockLatestTradeRequest,
)
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

from autotrader.config import Config
from autotrader.history import HistoryRange, HistoryRequest, thin_bars


class AlpacaProvider:
    def __init__(self, cfg: Config):
        self._data = StockHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._news = NewsClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._screeners = ScreenerClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._trading = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)
        self._asset_search_cache: list[dict[str, str]] | None = None

    def latest_price(self, ticker: str) -> float:
        req = StockLatestTradeRequest(symbol_or_symbols=[ticker], feed=DataFeed.IEX)
        trade = self._data.get_stock_latest_trade(req)[ticker]
        return float(trade.price)

    def latest_prices(self, tickers: list[str]) -> dict[str, float]:
        if not tickers:
            return {}
        req = StockLatestTradeRequest(symbol_or_symbols=tickers, feed=DataFeed.IEX)
        trades = self._data.get_stock_latest_trade(req)
        return {t: float(v.price) for t, v in trades.items()}

    def search_assets(self, query: str, limit: int = 10) -> list[dict]:
        if self._asset_search_cache is None:
            request = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
            assets = self._trading.get_all_assets(request)
            self._asset_search_cache = [
                {"ticker": asset.symbol, "name": asset.name}
                for asset in assets
                if asset.tradable
            ]

        normalized_query = query.casefold()
        matches = [
            asset
            for asset in self._asset_search_cache
            if normalized_query in asset["ticker"].casefold()
            or normalized_query in asset["name"].casefold()
        ]
        matches.sort(
            key=lambda asset: (
                normalized_query not in asset["ticker"].casefold(),
                asset["ticker"],
            )
        )
        return matches[:limit]

    def bars(
        self,
        ticker: str,
        history_range: HistoryRange = HistoryRange.ONE_DAY,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        history = HistoryRequest.for_range(history_range)
        req = StockBarsRequest(
            symbol_or_symbols=[ticker],
            timeframe=history.timeframe,
            start=history.start,
            end=history.end,
            limit=limit,
            feed=DataFeed.IEX,
        )
        bars = self._data.get_stock_bars(req)[ticker]
        normalized_bars = [
            {
                "t": b.timestamp.isoformat(),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
            for b in bars
        ]
        return thin_bars(normalized_bars, limit if limit is not None else history.max_bars)

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        req = NewsRequest(symbols=ticker, limit=limit)
        news = self._news.get_news(req).data["news"]
        return [{"headline": n.headline, "summary": n.summary} for n in news]

    def gainers(self, limit: int) -> list[dict]:
        req = MostActivesRequest(by=MostActivesBy.VOLUME, top=limit)
        res = self._screeners.get_most_actives(req)
        return [
            {"ticker": a.symbol, "volume": int(a.volume)}
            for a in res.most_actives
        ]
