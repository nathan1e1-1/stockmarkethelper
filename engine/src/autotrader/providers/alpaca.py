from datetime import datetime, timedelta, timezone

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
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from autotrader.config import Config


class AlpacaProvider:
    def __init__(self, cfg: Config):
        self._data = StockHistoricalDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._news = NewsClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._screeners = ScreenerClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
        self._trading = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)

    def latest_price(self, ticker: str) -> float:
        req = StockLatestTradeRequest(symbol_or_symbols=[ticker], feed=DataFeed.IEX)
        trade = self._data.get_stock_latest_trade(req)[ticker]
        return float(trade.price)

    def bars(self, ticker: str, limit: int = 50) -> list[dict]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        req = StockBarsRequest(symbol_or_symbols=[ticker], timeframe=TimeFrame.Minute, start=start, end=end, limit=limit, feed=DataFeed.IEX)
        bars = self._data.get_stock_bars(req)[ticker]
        return [
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
