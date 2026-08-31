from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from autotrader.models import ClosedTrade, Equity, Position
from autotrader.market import EASTERN


def build_pnl_snapshot(
    equity: Equity,
    positions: Sequence[Position],
    prices: Mapping[str, float | None],
    closed_trades: Sequence[ClosedTrade],
) -> dict[str, Any]:
    """Build a factual daily P&L snapshot without querying external services."""
    available_positions: list[dict[str, Any]] = []
    unavailable_positions: list[dict[str, Any]] = []

    for position in positions:
        current_price = prices.get(position.ticker)
        record = {
            "ticker": position.ticker,
            "qty": position.qty,
            "avg_entry_price": position.avg_entry_price,
            "current_price": current_price,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
        }
        if current_price is None:
            unavailable_positions.append(record)
            continue

        unrealized_pnl = (current_price - position.avg_entry_price) * position.qty
        record["unrealized_pnl"] = unrealized_pnl
        record["unrealized_pnl_pct"] = (
            ((current_price - position.avg_entry_price) / position.avg_entry_price) * 100
            if position.avg_entry_price
            else None
        )
        available_positions.append(record)

    available_positions.sort(key=lambda position: abs(position["unrealized_pnl"]), reverse=True)
    realized_trades = [
        {
            "ticker": trade.ticker,
            "qty": trade.qty,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "realized_pnl": trade.realized_pnl,
            "exit_reason": trade.exit_reason,
        }
        for trade in closed_trades
        if _closed_on_day(trade.closed_at, equity.day)
    ]
    realized_trades.sort(key=lambda trade: abs(trade["realized_pnl"]), reverse=True)
    realized_pnl = sum(trade["realized_pnl"] for trade in realized_trades)
    unrealized_pnl = sum(position["unrealized_pnl"] for position in available_positions)
    daily_pnl = equity.equity - equity.day_start_equity

    return {
        "equity": equity.equity,
        "day_start_equity": equity.day_start_equity,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": (daily_pnl / equity.day_start_equity) * 100 if equity.day_start_equity else 0.0,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "open_positions": available_positions + unavailable_positions,
        "realized_trades": realized_trades,
    }


def _closed_on_day(closed_at: datetime, day: str) -> bool:
    return closed_at.astimezone(EASTERN).date().isoformat() == day
