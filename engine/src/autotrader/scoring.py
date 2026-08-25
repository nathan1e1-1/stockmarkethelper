from autotrader.models import Signal


def composite_score(signals: list[Signal], weights: dict[str, float]) -> float:
    total = 0.0
    for s in signals:
        total += s.value * weights.get(s.name, 0.0)
    return round(max(-1.0, min(1.0, total)), 4)
