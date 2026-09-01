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
            "closed_at": trade.closed_at.isoformat(),
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
        "reconciliation_pnl": daily_pnl - realized_pnl - unrealized_pnl,
        "open_positions": available_positions + unavailable_positions,
        "realized_trades": realized_trades,
    }


def _closed_on_day(closed_at: datetime, day: str) -> bool:
    return closed_at.astimezone(EASTERN).date().isoformat() == day


def _one_day_move(bars: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Return the observed move from the first valid bar to the last valid bar."""
    valid = [
        bar
        for bar in bars
        if isinstance(bar, Mapping)
        and isinstance(bar.get("open"), (int, float))
        and not isinstance(bar.get("open"), bool)
        and isinstance(bar.get("close"), (int, float))
        and not isinstance(bar.get("close"), bool)
    ] if isinstance(bars, Sequence) and not isinstance(bars, (str, bytes)) else []
    if not valid:
        return {"day_open": None, "day_close": None, "day_change": None, "day_change_pct": None}

    opening, closing = float(valid[0]["open"]), float(valid[-1]["close"])
    change = closing - opening
    return {
        "day_open": opening,
        "day_close": closing,
        "day_change": change,
        "day_change_pct": (change / opening) * 100 if opening else None,
    }


def enrich_pnl_snapshot(
    snapshot: Mapping[str, Any],
    bars_by_ticker: Mapping[str, Sequence[Mapping[str, Any]]],
    news_by_ticker: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Attach supplied market facts to a snapshot without provider calls or mutation."""
    result = dict(snapshot)
    result["open_positions"] = [
        dict(position, **_one_day_move(bars_by_ticker.get(position["ticker"], [])))
        for position in snapshot.get("open_positions", [])
    ]

    copied_news = {
        ticker: [dict(item) for item in items if isinstance(item, Mapping)]
        for ticker, items in news_by_ticker.items()
        if isinstance(ticker, str)
        and isinstance(items, Sequence)
        and not isinstance(items, (str, bytes))
    }
    for position in snapshot.get("open_positions", []):
        copied_news.setdefault(position["ticker"], [])
    result["news_by_ticker"] = copied_news
    result["reconciliation_pnl"] = (
        float(result.get("daily_pnl", 0.0))
        - float(result.get("realized_pnl", 0.0))
        - float(result.get("unrealized_pnl", 0.0))
    )
    return result
