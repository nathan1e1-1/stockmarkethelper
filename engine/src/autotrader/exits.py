import logging

from autotrader.signals.momentum import MomentumSignal


logger = logging.getLogger(__name__)


class ExitManager:
    def __init__(self, stop_loss_pct: float, take_profit_pct: float):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def evaluate(self, position, current_price: float) -> str | None:
        """Legacy initial-profile exit: fixed stop-loss then fixed take-profit."""
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        pct = current_price / entry - 1.0
        if pct <= -self.stop_loss_pct:
            return "stop_loss"
        if pct >= self.take_profit_pct:
            return "take_profit"
        return None

    def hard_stop(self, position, current_price: float) -> str | None:
        """Unconditional hard stop-loss at the shared stop distance; no signal can veto it."""
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        if current_price <= entry * (1.0 - self.stop_loss_pct):
            return "stop_loss"
        return None


class DynamicExitEvaluator:
    """Decides hold / exit_early / take_profit from trend, regime, and sentiment.

    Structurally independent of the hard stop: this evaluator never receives the
    stop price or stop-loss configuration, so it cannot veto or modify the
    unconditional stop-loss check. Any raised exception resolves to a no-op hold.
    """

    def __init__(self, take_profit_pct: float, provider, momentum=None, regime=None, sentiment=None):
        self.take_profit_pct = take_profit_pct
        self.provider = provider
        self.momentum = momentum or MomentumSignal()
        self.regime = regime
        self.sentiment = sentiment

    def decide(self, position, current_price: float) -> str | None:
        try:
            momentum = self.momentum.compute(position.ticker, self.provider.scan_bars(position.ticker))
            sma_short = momentum.detail.get("sma_short")
            sma_long = momentum.detail.get("sma_long")
            sma_present = isinstance(sma_short, (int, float)) and isinstance(sma_long, (int, float))
            uptrend = sma_present and sma_short > sma_long
            sentiment_value = 0.0
            if self.sentiment is not None:
                news = self.provider.news(position.ticker, limit=5)
                sentiment_value = self.sentiment.compute(position.ticker, news).value
            entry = position.avg_entry_price
            if entry <= 0 or current_price <= 0:
                return None
            pct = current_price / entry - 1.0
            if sma_present and pct >= self.take_profit_pct and not uptrend:
                return "take_profit"
            if sma_present and not uptrend and sentiment_value < 0.0:
                return "exit_early"
            return None  # hold: dip with intact trend stays open
        except Exception:
            logger.exception("dynamic exit evaluator degraded to hold for %s", position.ticker)
            return None  # no-op hold; the hard stop still covers downside
