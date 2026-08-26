from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from autotrader.config import Config
from autotrader.models import Order, Position, Side


class AlpacaExecutor:
    def __init__(self, cfg: Config):
        self.client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)

    def get_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)

    def market_order(self, ticker: str, qty: int, side: Side) -> Order:
        req = MarketOrderRequest(
            symbol=ticker,
            qty=float(qty),
            side=OrderSide.BUY if side is Side.BUY else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        raw = self.client.submit_order(req)
        return Order(id=str(raw.id), ticker=ticker, side=side, qty=float(qty), status=raw.status)

    def sell(self, ticker: str, qty: int) -> Order:
        return self.market_order(ticker, qty, Side.SELL)

    def positions(self) -> list[Position]:
        out = []
        for p in self.client.get_all_positions():
            out.append(
                Position(
                    ticker=p.symbol,
                    qty=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                )
            )
        return out

    def flatten_all(self) -> None:
        self.client.close_all_positions()
