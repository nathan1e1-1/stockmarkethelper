import statistics


class RegimeFilter:
    def __init__(self, window: int = 20):
        self.window = window

    def label(self, bars: list[dict]) -> str:
        if len(bars) < self.window:
            return "choppy"
        closes = [b["close"] for b in bars][-self.window:]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        vol = statistics.pstdev(rets) if rets else 0.0
        trend = (closes[-1] / closes[0] - 1) if closes[0] else 0.0
        return "trending" if abs(trend) > vol * 3 else "choppy"

    def weights(self, bars: list[dict], base: dict[str, float]) -> dict[str, float]:
        label = self.label(bars)
        weights = dict(base)
        momentum = weights.get("momentum", 0.5)
        if label == "trending":
            weights["momentum"] = min(0.9, momentum * 1.4)
        else:
            weights["momentum"] = momentum * 0.5
        # renormalize so weights still sum to 1
        total = sum(weights.values())
        return {k: round(v / total, 4) for k, v in weights.items()}
