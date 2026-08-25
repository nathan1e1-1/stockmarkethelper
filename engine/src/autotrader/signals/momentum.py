from autotrader.models import Signal


class MomentumSignal:
    def __init__(self, short: int = 20, long: int = 50):
        self.short = short
        self.long = long

    def compute(self, ticker: str, bars: list[dict]) -> Signal:
        closes = [b["close"] for b in bars]
        if len(closes) < self.long:
            return Signal(name="momentum", value=0.0, detail={"reason": "insufficient data"})
        sma_short = sum(closes[-self.short:]) / self.short
        sma_long = sum(closes[-self.long:]) / self.long
        last = closes[-1]
        if sma_long == 0:
            return Signal(name="momentum", value=0.0, detail={})
        pct = (last / sma_long) - 1.0
        crossover = 1.0 if sma_short > sma_long else -1.0
        raw = (pct * 20.0) + (crossover * 0.3)
        value = max(-1.0, min(1.0, raw))
        return Signal(
            name="momentum",
            value=round(value, 4),
            detail={"sma_short": round(sma_short, 2), "sma_long": round(sma_long, 2), "pct_vs_sma_long": round(pct, 4)},
        )
