from autotrader.exits import ExitManager
from autotrader.market import EASTERN
from autotrader.models import ClosedTrade, Decision, Equity, Side, SignalSet
from autotrader.scoring import composite_score
from autotrader.signals.momentum import MomentumSignal
from autotrader.signals.regime import RegimeFilter
from autotrader.signals.sentiment import SentimentSignal


class Runner:
    def __init__(self, provider, agent, executor, risk, cfg, sentiment_llm=None):
        self.provider = provider
        self.agent = agent
        self.executor = executor
        self.risk = risk
        self.cfg = cfg
        self.momentum = MomentumSignal()
        self.regime = RegimeFilter()
        self.sentiment = SentimentSignal(sentiment_llm) if sentiment_llm else None
        self.equity: Equity | None = None
        self.decisions: list = []
        self.exit_manager = ExitManager(cfg.stop_loss_pct, cfg.take_profit_pct) if cfg else None
        self.closed_trades: list = []
        self.flattened = False

    def compute_signalset(self, ticker: str) -> SignalSet:
        bars = self.provider.scan_bars(ticker)
        signals = [self.momentum.compute(ticker, bars)]
        if self.sentiment is not None:
            signals.append(self.sentiment.compute(ticker, self.provider.news(ticker)))
        weights = self.regime.weights(bars, dict(self.cfg.signal_weights)) if self.cfg else {"momentum": 0.6, "sentiment": 0.4}
        comp = composite_score(signals, weights)
        return SignalSet(ticker=ticker, signals=signals, composite=comp, regime=self.regime.label(bars))

    def run_once(self, universe: list[str]) -> None:
        if self.equity is None:
            self.equity = Equity(
                equity=self.cfg.paper_capital,
                day_start_equity=self.cfg.paper_capital,
                peak_equity=self.cfg.paper_capital,
                day="",
            )
        if self.risk and (self.risk.hard_stop_triggered(self.equity.equity) or self.risk.daily_stop_triggered(self.equity.equity)):
            return
        threshold = self.cfg.entry_threshold if self.cfg else 0.5
        for ticker in universe:
            try:
                ss = self.compute_signalset(ticker)
                sigs = ", ".join(f"{s.name}={s.value}" for s in ss.signals)
                print(f"[scan] {ticker}: composite={ss.composite} regime={ss.regime} signals=[{sigs}]")
                if ss.composite < threshold:
                    print(f"[scan] {ticker}: below threshold {threshold}, skipping")
                    continue
                decision = self.agent.decide(ss)
                self.decisions.append(decision)
                print(f"[scan] {ticker}: decision={decision.decision.value} confidence={decision.confidence} rationale={decision.rationale!r}")
                if decision.decision is not Decision.BUY:
                    continue
                if self.risk and not self.risk.can_enter(ticker):
                    print(f"[scan] {ticker}: risk blocked (max positions or duplicate)")
                    continue
                price = self.provider.latest_price(ticker)
                qty = self.risk.position_size(ticker, price, self.equity.equity) if self.risk else 0
                self.executor.market_order(ticker, qty, Side.BUY)
                print(f"[order] BUY {ticker} x{qty} @ {price}")
            except Exception as e:
                print(f"[error] {ticker}: {e}")
                continue

    def reconcile(self) -> None:
        if self.executor is None:
            return
        positions = self.executor.positions()
        if not positions:
            return
        print(f"[reconcile] closing {len(positions)} stale positions")
        for pos in positions:
            try:
                self.executor.sell(pos.ticker, int(pos.qty))
                print(f"[reconcile] closed {pos.ticker}")
            except Exception as e:
                print(f"[reconcile] failed to close {pos.ticker}: {e}")

    def manage_exits(self, flatten_time=None, now=None) -> None:
        if self.exit_manager is None or self.risk is None:
            return
        try:
            if flatten_time and now and now.astimezone(EASTERN).time() >= flatten_time and not self.flattened:
                for pos in list(self.risk.positions):
                    price = self.provider.latest_price(pos.ticker)
                    self._close(pos, price, "flatten")
                self.flattened = True
                return
            for pos in list(self.risk.positions):
                price = self.provider.latest_price(pos.ticker)
                reason = self.exit_manager.evaluate(pos, price)
                if reason:
                    self._close(pos, price, reason)
        except Exception as e:
            print(f"[error] manage_exits: {e}")

    def _close(self, pos, price: float, reason: str) -> None:
        qty = int(pos.qty)
        self.executor.sell(pos.ticker, qty)
        self.closed_trades.append(ClosedTrade(
            ticker=pos.ticker,
            qty=pos.qty,
            entry_price=pos.avg_entry_price,
            exit_price=price,
            realized_pnl=(price - pos.avg_entry_price) * pos.qty,
            exit_reason=reason,
        ))
        self.risk.positions = [p for p in self.risk.positions if p.ticker != pos.ticker]
