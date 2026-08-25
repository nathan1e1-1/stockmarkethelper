from autotrader.scoring import composite_score
from autotrader.models import Signal


def test_composite_is_weighted_sum():
    signals = [Signal(name="momentum", value=0.6), Signal(name="sentiment", value=0.3)]
    weights = {"momentum": 0.6, "sentiment": 0.4}
    score = composite_score(signals, weights)
    assert score == round(0.6 * 0.6 + 0.3 * 0.4, 4)


def test_composite_ignores_unknown_signals():
    signals = [Signal(name="momentum", value=0.6), Signal(name="other", value=1.0)]
    weights = {"momentum": 1.0}
    assert composite_score(signals, weights) == 0.6
