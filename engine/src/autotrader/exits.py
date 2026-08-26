class ExitManager:
    def __init__(self, stop_loss_pct: float, take_profit_pct: float):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def evaluate(self, position, current_price: float) -> str | None:
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        pct = current_price / entry - 1.0
        if pct <= -self.stop_loss_pct:
            return "stop_loss"
        if pct >= self.take_profit_pct:
            return "take_profit"
        return None
