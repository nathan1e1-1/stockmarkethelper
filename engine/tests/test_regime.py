from autotrader.signals.regime import RegimeFilter


def test_trending_regime_rewards_momentum():
    rf = RegimeFilter()
    bars = [{"close": float(i)} for i in range(50)]  # clean uptrend, low vol
    weights = rf.weights(bars, base={"momentum": 0.6, "sentiment": 0.4})
    assert weights["momentum"] > 0.6


def test_choppy_regime_reduces_momentum():
    rf = RegimeFilter()
    import math
    bars = [{"close": 100.0 + math.sin(i / 3) * 3} for i in range(50)]  # choppy
    weights = rf.weights(bars, base={"momentum": 0.6, "sentiment": 0.4})
    assert weights["momentum"] < 0.6


def test_regime_label_present():
    rf = RegimeFilter()
    bars = [{"close": float(i)} for i in range(50)]
    label = rf.label(bars)
    assert label in ("trending", "choppy")
