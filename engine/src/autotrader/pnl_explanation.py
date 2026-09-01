"""Render supplied P&L attribution facts into a compact factual explanation."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any


_EASTERN = ZoneInfo("America/New_York")


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _amount(value: float) -> str:
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.2f}%"


def _price(value: Any) -> str | None:
    number = _number(value)
    return f"${number:,.2f}" if number is not None else None


def _quantity(value: Any) -> str | None:
    number = _number(value)
    return f"{number:g}" if number is not None else None


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _eastern_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    eastern = timestamp.astimezone(_EASTERN)
    hour = eastern.strftime("%I").lstrip("0") or "0"
    return f"{eastern.strftime('%b')} {eastern.day}, {eastern.year}, {hour}:{eastern:%M %p %Z}"


def _position_sentence(position: Mapping[str, Any]) -> tuple[str | None, tuple[float, str] | None]:
    ticker = position.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None, None
    quantity = _quantity(position.get("qty"))
    entry = _price(position.get("avg_entry_price"))
    current = _price(position.get("current_price"))
    details = []
    if quantity is not None:
        details.append(f"{quantity} {'share' if quantity == '1' else 'shares'}")
    if entry is not None:
        details.append(f"entry {entry}")
    if current is not None:
        details.append(f"current {current}")
    unrealized = _number(position.get("unrealized_pnl"))
    unrealized_pct = _number(position.get("unrealized_pnl_pct"))
    if unrealized is not None:
        pnl_text = f"unrealized {_amount(unrealized)}"
        if unrealized_pct is not None:
            pnl_text += f" ({_percent(unrealized_pct)})"
        details.append(pnl_text)
    elif position.get("current_price") is None:
        details.append("current price unavailable")

    if not details:
        return None, None
    sentence = f"{ticker} position: {', '.join(details)}."
    day_open = _price(position.get("day_open"))
    day_close = _price(position.get("day_close"))
    day_change = _number(position.get("day_change"))
    day_change_pct = _number(position.get("day_change_pct"))
    if day_change is not None:
        move = f"one-day move {_amount(day_change)}"
        if day_change_pct is not None:
            move += f" ({_percent(day_change_pct)})"
        if day_open is not None and day_close is not None:
            move += f", from {day_open} open to {day_close} close"
        sentence = f"{sentence[:-1]}; {move}."
    elif day_open is None and day_close is None:
        sentence = f"{sentence[:-1]}; one-day move unavailable."
    contributor = (unrealized, f"{ticker} unrealized P&L") if unrealized is not None else None
    return sentence, contributor


def _trade_sentence(trade: Mapping[str, Any]) -> tuple[str | None, tuple[float, str] | None]:
    ticker = trade.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None, None
    details = []
    quantity = _quantity(trade.get("qty"))
    entry = _price(trade.get("entry_price"))
    exit_price = _price(trade.get("exit_price"))
    if quantity is not None:
        details.append(f"{quantity} {'share' if quantity == '1' else 'shares'}")
    if entry is not None:
        details.append(f"entry {entry}")
    if exit_price is not None:
        details.append(f"exit {exit_price}")
    realized = _number(trade.get("realized_pnl"))
    timestamp = _eastern_timestamp(trade.get("closed_at"))
    if timestamp is not None:
        details.append(f"closed {timestamp}")
    if not details:
        return None, None
    contributor = (realized, f"{ticker} realized trade") if realized is not None else None
    if realized is not None:
        return (
            f"A recorded exit for {ticker} contributed {_amount(realized)} realized P&L. "
            f"{ticker} trade details: {', '.join(details)}.",
            contributor,
        )
    return f"{ticker} recorded trade: {', '.join(details)}.", contributor


def render_pnl_explanation(snapshot: Mapping[str, Any] | Any) -> str | None:
    """Render only the supplied snapshot; never query providers or generate advice."""
    if not isinstance(snapshot, Mapping):
        return None

    daily_pnl = _number(snapshot.get("daily_pnl"))
    daily_pct = _number(snapshot.get("daily_pnl_pct"))
    realized_pnl = _number(snapshot.get("realized_pnl"))
    unrealized_pnl = _number(snapshot.get("unrealized_pnl"))
    if daily_pnl is None and realized_pnl is None and unrealized_pnl is None:
        return None

    sentences = []
    if daily_pnl is not None:
        daily = f"Today's P&L is {_amount(daily_pnl)}"
        if daily_pct is not None:
            daily += f" ({_percent(daily_pct)})"
        sentences.append(f"{daily}.")
    if realized_pnl is not None or unrealized_pnl is not None:
        realized = _amount(realized_pnl) if realized_pnl is not None else "unavailable"
        unrealized = _amount(unrealized_pnl) if unrealized_pnl is not None else "unavailable"
        sentences.append(f"Realized P&L: {realized}; unrealized P&L: {unrealized}.")

    contributors: list[tuple[float, str]] = []
    details = []
    for trade in _items(snapshot.get("realized_trades")):
        sentence, contributor = _trade_sentence(trade)
        if sentence is not None:
            details.append(sentence)
        if contributor is not None:
            contributors.append(contributor)
    for position in _items(snapshot.get("open_positions")):
        sentence, contributor = _position_sentence(position)
        if sentence is not None:
            details.append(sentence)
        if contributor is not None:
            contributors.append(contributor)

    negative = min((item for item in contributors if item[0] < 0), default=None, key=lambda item: item[0])
    positive = max((item for item in contributors if item[0] > 0), default=None, key=lambda item: item[0])
    if negative is not None:
        sentences.append(f"Largest negative contributor: {negative[1]} {_amount(negative[0])}.")
    if positive is not None:
        sentences.append(f"Largest positive contributor: {positive[1]} {_amount(positive[0])}.")
    if not contributors:
        sentences.append("No realized or open-position contributors are recorded in this snapshot.")

    reconciliation = _number(snapshot.get("reconciliation_pnl"))
    if reconciliation is not None and abs(reconciliation) >= 0.01:
        sentences.append(
            "Reconciliation: daily P&L minus realized and unrealized P&L is "
            f"{_amount(reconciliation)}."
        )
        sentences.append("The current ledger does not attribute this amount.")

    sentences.extend(details)
    return " ".join(sentences)
