from datetime import datetime, timedelta, timezone

from alpaca.data.timeframe import TimeFrameUnit

from autotrader.history import HistoryRange, HistoryRequest, thin_bars
from autotrader.models import Quote


class FixtureProvider:
    """Deterministic in-memory provider for tests and replay."""

    _QUOTE_TIME = datetime(2026, 8, 30, tzinfo=timezone.utc)

    def latest_quote(self, ticker: str, *, now: datetime | None = None) -> Quote:
        timestamp = now or self._QUOTE_TIME
        if not self._is_aware_datetime(timestamp):
            raise ValueError("invalid quote timestamp")
        return Quote(ticker, 190.0, timestamp, timestamp)

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
        return {t: self.latest_price(t) for t in tickers}

    def search_assets(self, query: str, limit: int = 10) -> list[dict]:
        assets = [
            {"ticker": "AAPL", "name": "Apple Inc."},
            {"ticker": "MSFT", "name": "Microsoft Corporation"},
        ]
        normalized_query = query.casefold()
        matches = [
            asset
            for asset in assets
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
        # Clean uptrend so momentum is strongly positive.
        request = HistoryRequest.for_range(history_range)
        interval = {
            TimeFrameUnit.Minute: timedelta(minutes=request.timeframe.amount),
            TimeFrameUnit.Hour: timedelta(hours=request.timeframe.amount),
            TimeFrameUnit.Day: timedelta(days=request.timeframe.amount),
        }[request.timeframe.unit]
        periods = int((request.end - request.start) // interval)
        timestamps = [request.start + interval * index for index in range(periods + 1)]
        if timestamps[-1] < request.end:
            timestamps.append(request.end)

        bars = []
        for index, timestamp in enumerate(timestamps):
            close = 100.0 + index
            bars.append(
                {
                    "t": timestamp.isoformat(),
                    "open": close - 0.5,
                    "high": close + 0.5,
                    "low": close - 1.0,
                    "close": close,
                    "volume": float(1_000 + index),
                }
            )
        return thin_bars(bars, request.max_bars)

    def scan_bars(self, ticker: str) -> list[dict]:
        start = datetime(2026, 8, 25, tzinfo=timezone.utc)
        return [
            {
                "t": (start + timedelta(minutes=index)).isoformat(),
                "open": 99.5 + index,
                "high": 100.5 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": float(1_000 + index),
            }
            for index in range(50)
        ]

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        return [
            {
                "headline": f"{ticker} beats earnings expectations",
                "summary": None,
                "created_at": datetime(2026, 8, 30, tzinfo=timezone.utc).isoformat(),
                "source": "FixtureProvider",
            }
            for _ in range(limit)
        ]

    def gainers(self, limit: int) -> list[dict]:
        return [
            {"ticker": f"TICK{i:02d}", "volume": 1_000_000 + i * 1000}
            for i in range(limit)
        ]
