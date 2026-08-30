from datetime import datetime, timedelta, timezone

from autotrader.history import HistoryRange, HistoryRequest


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
    ) -> list[dict]:
        # Clean uptrend so momentum is strongly positive.
        request = HistoryRequest.for_range(history_range)
        start = datetime(2026, 8, 25, tzinfo=timezone.utc)
        return [
            {"t": (start + timedelta(minutes=i)).isoformat(), "close": 100.0 + i}
            for i in range(request.max_bars)
        ]

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
