from autotrader.signals.sentiment import SentimentSignal


class FakeLLM:
    def sentiment(self, headlines: list[str]) -> float:
        return 0.7


def test_sentiment_uses_llm_result():
    sig = SentimentSignal(FakeLLM())
    s = sig.compute("AAPL", [{"headline": "AAPL beats earnings"}])
    assert s.name == "sentiment"
    assert s.value == 0.7


def test_sentiment_no_news_returns_zero():
    sig = SentimentSignal(FakeLLM())
    s = sig.compute("AAPL", [])
    assert s.value == 0.0
