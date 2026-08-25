class FixtureProvider:
    """Deterministic in-memory provider for tests and replay."""

    def latest_price(self, ticker: str) -> float:
        return 190.0

    def bars(self, ticker: str, limit: int = 50) -> list[dict]:
        # Clean uptrend so momentum is strongly positive.
        return [
            {"t": f"2026-08-25T13:{i:02d}:00Z", "close": 100.0 + i}
            for i in range(limit)
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
