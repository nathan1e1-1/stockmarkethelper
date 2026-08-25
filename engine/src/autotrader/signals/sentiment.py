from autotrader.models import Signal


class SentimentSignal:
    def __init__(self, llm):
        self.llm = llm

    def compute(self, ticker: str, news: list[dict]) -> Signal:
        if not news:
            return Signal(name="sentiment", value=0.0, detail={"reason": "no news"})
        headlines = [n["headline"] for n in news if n.get("headline")]
        value = self.llm.sentiment(headlines)
        return Signal(name="sentiment", value=value, detail={"headline_count": len(headlines)})
