from datetime import datetime, timezone

from autotrader.models import ClosedTrade, Equity, Position
from autotrader.pnl import build_pnl_snapshot


def test_pnl_snapshot_separates_daily_realized_and_unrealized_contributors():
    snapshot = build_pnl_snapshot(
        equity=Equity(equity=1050, day_start_equity=1000, peak_equity=1050, day="2026-08-31"),
        positions=[Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        prices={"AAPL": 110},
        closed_trades=[
            ClosedTrade(
                ticker="MSFT",
                qty=1,
                entry_price=90,
                exit_price=100,
                realized_pnl=10,
                exit_reason="take profit",
                closed_at=datetime(2026, 8, 31, 15, tzinfo=timezone.utc),
            ),
            ClosedTrade(
                ticker="NVDA",
                qty=1,
                entry_price=90,
                exit_price=95,
                realized_pnl=5,
                exit_reason="take profit",
                closed_at=datetime(2026, 8, 30, 15, tzinfo=timezone.utc),
            ),
        ],
    )

    assert snapshot["equity"] == 1050
    assert snapshot["day_start_equity"] == 1000
    assert snapshot["daily_pnl"] == 50
    assert snapshot["daily_pnl_pct"] == 5
    assert snapshot["unrealized_pnl"] == 20
    assert snapshot["realized_pnl"] == 10
    assert snapshot["open_positions"] == [
        {
            "ticker": "AAPL",
            "qty": 2,
            "avg_entry_price": 100,
            "current_price": 110,
            "unrealized_pnl": 20,
            "unrealized_pnl_pct": 10,
        }
    ]


def test_pnl_snapshot_marks_missing_price_unavailable_without_losing_other_contributors():
    snapshot = build_pnl_snapshot(
        equity=Equity(equity=1000, day_start_equity=1000, peak_equity=1000, day="2026-08-31"),
        positions=[
            Position(ticker="AAPL", qty=2, avg_entry_price=100),
            Position(ticker="MSFT", qty=1, avg_entry_price=200),
        ],
        prices={"AAPL": 110},
        closed_trades=[],
    )

    assert snapshot["unrealized_pnl"] == 20
    assert snapshot["open_positions"] == [
        {
            "ticker": "AAPL",
            "qty": 2,
            "avg_entry_price": 100,
            "current_price": 110,
            "unrealized_pnl": 20,
            "unrealized_pnl_pct": 10,
        },
        {
            "ticker": "MSFT",
            "qty": 1,
            "avg_entry_price": 200,
            "current_price": None,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
        },
    ]


def test_pnl_snapshot_sorts_available_positions_by_absolute_unrealized_pnl():
    snapshot = build_pnl_snapshot(
        equity=Equity(equity=1000, day_start_equity=1000, peak_equity=1000, day="2026-08-31"),
        positions=[
            Position(ticker="AAPL", qty=1, avg_entry_price=100),
            Position(ticker="MSFT", qty=2, avg_entry_price=100),
        ],
        prices={"AAPL": 110, "MSFT": 90},
        closed_trades=[],
    )

    assert [position["ticker"] for position in snapshot["open_positions"]] == ["MSFT", "AAPL"]
