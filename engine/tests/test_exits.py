from autotrader.exits import DynamicExitEvaluator, ExitManager
from autotrader.models import Position, Signal


def pos(entry):
    return Position(ticker="AAPL", qty=10.0, avg_entry_price=entry)


def test_legacy_evaluate_stop_loss():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 97.9) == "stop_loss"


def test_legacy_evaluate_take_profit():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 103.1) == "take_profit"


def test_legacy_evaluate_no_trigger_between():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 101.0) is None


def test_legacy_evaluate_boundary_stop_exact():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 98.0) == "stop_loss"


def test_legacy_evaluate_zero_entry_no_trigger():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(0.0), 50.0) is None


def test_hard_stop_is_unconditional_at_shared_distance():
    em = ExitManager(stop_loss_pct=0.05, take_profit_pct=0.05)
    assert em.hard_stop(pos(100.0), 95.0) == "stop_loss"
    assert em.hard_stop(pos(100.0), 95.01) is None


def test_hard_stop_zero_entry_no_trigger():
    em = ExitManager(stop_loss_pct=0.05, take_profit_pct=0.05)
    assert em.hard_stop(pos(0.0), 50.0) is None


class FakeMomentum:
    def __init__(self, detail):
        self.detail = detail

    def compute(self, ticker, bars):
        return Signal(name="momentum", value=0.5, detail=self.detail)


class FakeSentiment:
    def __init__(self, value):
        self.value = value

    def compute(self, ticker, news):
        return Signal(name="sentiment", value=self.value, detail={})


class FakeProvider:
    def __init__(self, bars=None, news=None):
        self.bars = bars or []
        self._news = news or []

    def scan_bars(self, ticker):
        return self.bars

    def news(self, ticker, limit=5):
        return self._news


def make_evaluator(detail, sentiment_value=None, bars=None, news=None, boom=False):
    if boom:
        class BoomProvider(FakeProvider):
            def scan_bars(self, ticker):
                raise TimeoutError("ollama unavailable")
        provider = BoomProvider()
    else:
        provider = FakeProvider(bars=bars, news=news)
    sentiment = FakeSentiment(sentiment_value) if sentiment_value is not None else None
    return DynamicExitEvaluator(
        take_profit_pct=0.05,
        provider=provider,
        momentum=FakeMomentum(detail),
        sentiment=sentiment,
    ), provider


def test_dynamic_holds_dip_while_uptrend_intact():
    de, _ = make_evaluator({"sma_short": 102.0, "sma_long": 100.0}, sentiment_value=0.8)
    assert de.decide(pos(100.0), 96.0) is None


def test_dynamic_exit_early_on_trend_break_and_negative_sentiment():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=-0.5)
    assert de.decide(pos(100.0), 97.0) == "exit_early"


def test_dynamic_holds_when_trend_down_but_sentiment_neutral():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=0.0)
    assert de.decide(pos(100.0), 97.0) is None


def test_dynamic_take_profit_at_target_when_trend_faded():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=-0.5)
    assert de.decide(pos(100.0), 105.5) == "take_profit"


def test_dynamic_evaluator_failure_resolves_to_hold():
    de, provider = make_evaluator({}, boom=True)
    assert de.decide(pos(100.0), 96.0) is None


def test_dynamic_evaluator_without_sentiment_treats_value_as_zero():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0})
    assert de.decide(pos(100.0), 97.0) is None
