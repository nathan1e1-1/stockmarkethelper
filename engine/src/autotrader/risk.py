import math

from autotrader.models import Position


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.positions: list[Position] = []
        self.peak_equity: float = cfg.paper_capital
        self.day_start_equity: float = cfg.paper_capital

    def position_size(self, ticker: str, price: float, equity: float) -> int:
        budget = equity * self.cfg.max_position_pct
        qty = math.floor(budget / price)
        return max(0, qty)

    def can_enter(self, ticker: str) -> bool:
        if len(self.positions) >= self.cfg.max_positions:
            return False
        if any(p.ticker == ticker for p in self.positions):
            return False
        return True

    def hard_stop_triggered(self, equity: float) -> bool:
        return equity <= self.peak_equity * (1.0 - self.cfg.kill_switch_pct)

    def daily_stop_triggered(self, equity: float) -> bool:
        return equity <= self.day_start_equity * (1.0 - self.cfg.daily_loss_pct)
