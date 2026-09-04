from datetime import datetime, timedelta, timezone
from math import isfinite

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
from alpaca.data.timeframe import TimeFrame

from autotrader.config import Config
from autotrader.history import HistoryRange, HistoryRequest, thin_bars
from autotrader.models import Quote


class AlpacaProvider:
    def __init__(self, cfg: Config):
        self._data = StockHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._news = NewsClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._screeners = ScreenerClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._trading = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)
        self._asset_search_cache: list[dict[str, str]] | None = None

    def latest_quote(self, ticker: str, *, now: datetime | None = None) -> Quote:
        req = StockLatestTradeRequest(symbol_or_symbols=[ticker], feed=DataFeed.IEX)
        trade = self._data.get_stock_latest_trade(req)[ticker]
        try:
            price = float(trade.price)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid quote price") from exc
        source_timestamp = getattr(trade, "timestamp", None)
        observed_at = now or datetime.now(timezone.utc)
        if not isfinite(price) or price <= 0:
            raise ValueError("invalid quote price")
        if not self._is_aware_datetime(source_timestamp) or not self._is_aware_datetime(observed_at):
            raise ValueError("invalid quote timestamp")
        return Quote(
            ticker=ticker,
            price=price,
            source_timestamp=source_timestamp,
            observed_at=observed_at,
        )

    @staticmethod
    def _is_aware_datetime(value) -> bool:
        return (
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() is not None
        )

    def latest_price(self, ticker: str) -> float:
        return self.latest_quote(ticker).price

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
    ) -> list[dict]:
        history = HistoryRequest.for_range(history_range)
        req = StockBarsRequest(
            symbol_or_symbols=[ticker],
            timeframe=history.timeframe,
            start=history.start,
            end=history.end,
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
        return thin_bars(normalized_bars, history.max_bars)

    def scan_bars(self, ticker: str) -> list[dict]:
        end = datetime.now(timezone.utc)
        req = StockBarsRequest(
            symbol_or_symbols=[ticker],
            timeframe=TimeFrame.Minute,
            start=end - timedelta(days=7),
            end=end,
            limit=50,
            feed=DataFeed.IEX,
        )
        bars = self._data.get_stock_bars(req)[ticker]
        return [
            {
                "t": bar.timestamp.isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            for bar in bars
        ]

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        req = NewsRequest(symbols=ticker, limit=limit)
        news = self._news.get_news(req).data["news"]
        records = [
            {
                "headline": self._normalized_news_text(getattr(n, "headline", None)),
                "summary": self._normalized_news_text(getattr(n, "summary", None)),
                "created_at": self._normalized_news_timestamp(getattr(n, "created_at", None)),
                "source": self._normalized_news_source(getattr(n, "source", None)),
            }
            for n in news[:limit]
        ]
        return [record for record in records if record["headline"]]

    @staticmethod
    def _normalized_news_timestamp(created_at) -> str | None:
        if not isinstance(created_at, datetime):
            return None
        return created_at.isoformat()

    @staticmethod
    def _normalized_news_source(source) -> str | None:
        if source is None:
            return None
        normalized = str(source).strip()
        return normalized or None

    @staticmethod
    def _normalized_news_text(value) -> str:
        return str(value or "").strip()

    def gainers(self, limit: int) -> list[dict]:
        req = MostActivesRequest(by=MostActivesBy.VOLUME, top=limit)
        res = self._screeners.get_most_actives(req)
        return [
            {"ticker": a.symbol, "volume": int(a.volume)}
            for a in res.most_actives
        ]
