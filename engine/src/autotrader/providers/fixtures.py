from datetime import timedelta

from alpaca.data.timeframe import TimeFrameUnit

from autotrader.history import HistoryRange, HistoryRequest, thin_bars


class FixtureProvider:
    """Deterministic in-memory provider for tests and replay."""

    def latest_price(self, ticker: str) -> float:
        return 190.0

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
        *,
        limit: int | None = None,
        timeframe: str | None = None,
    ) -> list[dict]:
        # Clean uptrend so momentum is strongly positive.
        if timeframe is not None and timeframe != "1min":
            raise ValueError(f"unsupported timeframe: {timeframe}")
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
        return thin_bars(bars, limit if limit is not None else request.max_bars)

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        return [
            {"headline": f"{ticker} beats earnings expectations", "sentiment_hint": "positive"}
            for _ in range(limit)
        ]

    def gainers(self, limit: int) -> list[dict]:
        return [
            {"ticker": f"TICK{i:02d}", "volume": 1_000_000 + i * 1000}
            for i in range(limit)
        ]
