from autotrader.signals.momentum import MomentumSignal


def test_momentum_positive_when_price_above_sma():
    bars = [{"close": float(i)} for i in range(1, 51)]  # steadily rising
    sig = MomentumSignal()
    s = sig.compute("AAPL", bars)
    assert s.name == "momentum"
    assert s.value > 0
    assert -1.0 <= s.value <= 1.0


def test_momentum_negative_when_price_below_sma():
    bars = [{"close": float(50 - i)} for i in range(50)]  # steadily falling
    sig = MomentumSignal()
    s = sig.compute("AAPL", bars)
    assert s.value < 0
