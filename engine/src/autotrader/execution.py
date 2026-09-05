from alpaca.trading.client import TradingClient
from datetime import datetime, timezone
from math import isfinite

from alpaca.common.exceptions import APIError
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce

from autotrader.config import Config
from autotrader.models import AccountSnapshot, Order, Position, PositionsSnapshot, Side


class AlpacaExecutor:
    def __init__(self, cfg: Config):
        if cfg.alpaca_paper is not True:
            raise ValueError("paper trading must be enabled; live trading is not supported")
        self._paper = True
        self.client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=cfg.alpaca_paper)

    def get_equity(self) -> float:
        equity = self.account_snapshot().equity
        if equity is None:
            raise ValueError("broker account equity is invalid")
        return equity

    def account_snapshot(self, *, now: datetime | None = None) -> AccountSnapshot:
        account = self.client.get_account()
        return AccountSnapshot(
            equity=self._finite_positive(getattr(account, "equity", None)),
            observed_at=now or datetime.now(timezone.utc),
        )

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

    def submit_limit_buy(
        self,
        ticker: str,
        qty: float,
        limit_price: float,
        client_order_id: str,
    ) -> Order:
        req = LimitOrderRequest(
            symbol=ticker,
            qty=float(qty),
            side=OrderSide.BUY,
            type="limit",
            time_in_force=TimeInForce.DAY,
            limit_price=float(limit_price),
            client_order_id=client_order_id,
        )
        return self._normalize_order(self.client.submit_order(req))

    def submit_exit(self, ticker: str, qty: float, client_order_id: str) -> Order:
        req = MarketOrderRequest(
            symbol=ticker,
            qty=float(qty),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        return self._normalize_order(self.client.submit_order(req))

    def order(self, broker_order_id: str, *, now: datetime | None = None) -> Order:
        return self._normalize_order(self.client.get_order_by_id(broker_order_id), now=now)

    def order_by_client_id(self, client_order_id: str, *, now: datetime | None = None) -> Order | None:
        try:
            raw = self.client.get_order_by_client_id(client_order_id)
        except APIError as exc:
            if self._is_not_found(exc):
                return None
            raise
        if raw is None:
            return None
        return self._normalize_order(raw, now=now)

    def open_orders(self, *, now: datetime | None = None) -> list[Order]:
        raw_orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return [self._normalize_order(raw, now=now) for raw in raw_orders]

    def cancel(self, broker_order_id: str, *, now: datetime | None = None) -> Order:
        raw = self.client.cancel_order_by_id(broker_order_id)
        if raw is None:
            raw = self.client.get_order_by_id(broker_order_id)
        return self._normalize_order(raw, now=now)

    @staticmethod
    def _normalize_order(raw, *, now: datetime | None = None) -> Order:
        filled_qty, filled_notional = AlpacaExecutor._filled_values(raw)
        submitted_at = getattr(raw, "submitted_at", None)
        timestamp = submitted_at if isinstance(submitted_at, datetime) else datetime.now(timezone.utc)
        return Order(
            id=str(raw.id),
            ticker=str(raw.symbol),
            side=AlpacaExecutor._side(raw.side),
            qty=float(raw.qty),
            filled_avg_price=AlpacaExecutor._finite_positive(getattr(raw, "filled_avg_price", None)),
            status=AlpacaExecutor._value(raw.status),
            timestamp=timestamp,
            client_order_id=getattr(raw, "client_order_id", None),
            filled_qty=filled_qty,
            filled_notional=filled_notional,
            observed_at=now or datetime.now(timezone.utc),
        )

    @staticmethod
    def _filled_values(raw) -> tuple[float | None, float | None]:
        filled_qty = AlpacaExecutor._finite_nonnegative(getattr(raw, "filled_qty", None))
        filled_avg_price = AlpacaExecutor._finite_positive(getattr(raw, "filled_avg_price", None))
        if filled_qty is None or filled_avg_price is None:
            return None, None
        return filled_qty, filled_qty * filled_avg_price

    @staticmethod
    def _finite_nonnegative(value) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        return normalized if isfinite(normalized) and normalized >= 0 else None

    @staticmethod
    def _finite_positive(value) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        return normalized if isfinite(normalized) and normalized > 0 else None

    @staticmethod
    def _side(value) -> Side:
        return Side(AlpacaExecutor._value(value).lower())

    @staticmethod
    def _value(value) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _is_not_found(exc: APIError) -> bool:
        if exc.status_code == 404:
            return True
        try:
            return exc.code == 404
        except (KeyError, TypeError, ValueError):
            return False

    def positions(self) -> list[Position]:
        positions = self.positions_snapshot().positions
        if positions is None:
            raise ValueError("broker positions are invalid")
        return positions

    def positions_snapshot(self, *, now: datetime | None = None) -> PositionsSnapshot:
        observed_at = now or datetime.now(timezone.utc)
        positions = []
        for raw in self.client.get_all_positions():
            position = self._normalize_position(raw)
            if position is None:
                return PositionsSnapshot(positions=None, observed_at=observed_at)
            positions.append(position)
        return PositionsSnapshot(positions=positions, observed_at=observed_at)

    @staticmethod
    def _normalize_position(raw) -> Position | None:
        ticker = str(getattr(raw, "symbol", "")).strip()
        qty = AlpacaExecutor._finite_positive(getattr(raw, "qty", None))
        avg_entry_price = AlpacaExecutor._finite_positive(getattr(raw, "avg_entry_price", None))
        if not ticker or qty is None or avg_entry_price is None:
            return None
        return Position(ticker=ticker, qty=qty, avg_entry_price=avg_entry_price)

    def flatten_all(self) -> None:
        self.client.close_all_positions()
