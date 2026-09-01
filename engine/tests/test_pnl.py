from datetime import datetime, timezone

from autotrader.models import ClosedTrade, Equity, Position
from autotrader.pnl import build_pnl_snapshot, enrich_pnl_snapshot
from autotrader.main import publish_pnl_attribution, restore_same_day_state
from autotrader.state import State, StateStore


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
    assert snapshot["realized_trades"] == [
        {
            "ticker": "MSFT",
            "qty": 1,
            "entry_price": 90,
            "exit_price": 100,
            "realized_pnl": 10,
            "exit_reason": "take profit",
            "closed_at": "2026-08-31T15:00:00+00:00",
        }
    ]
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


def test_enrich_pnl_snapshot_attaches_one_day_move_news_and_reconciliation_facts():
    base = build_pnl_snapshot(
        equity=Equity(equity=1_015, day_start_equity=1_000, peak_equity=1_020, day="2026-09-01"),
        positions=[Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        prices={"AAPL": 110},
        closed_trades=[
            ClosedTrade(
                ticker="MSFT",
                qty=1,
                entry_price=90,
                exit_price=95,
                realized_pnl=5,
                exit_reason="recorded exit",
                closed_at=datetime(2026, 9, 1, 15, tzinfo=timezone.utc),
            )
        ],
    )

    snapshot = enrich_pnl_snapshot(
        base,
        bars_by_ticker={
            "AAPL": [
                {"open": 100.0, "close": 103.0},
                {"open": 103.0, "close": 105.0},
            ]
        },
        news_by_ticker={
            "AAPL": [
                {
                    "headline": "AAPL headline",
                    "summary": "Verified summary",
                    "created_at": "2026-09-01T14:00:00+00:00",
                    "source": "Newswire",
                }
            ]
        },
    )

    assert snapshot["open_positions"][0]["day_open"] == 100.0
    assert snapshot["open_positions"][0]["day_close"] == 105.0
    assert snapshot["open_positions"][0]["day_change"] == 5.0
    assert snapshot["open_positions"][0]["day_change_pct"] == 5.0
    assert snapshot["realized_trades"][0]["closed_at"] == "2026-09-01T15:00:00+00:00"
    assert snapshot["reconciliation_pnl"] == -10.0
    assert snapshot["news_by_ticker"]["AAPL"][0]["headline"] == "AAPL headline"


def test_enrich_pnl_snapshot_handles_malformed_bars_and_missing_news_without_exception():
    base = build_pnl_snapshot(
        equity=Equity(equity=1_000, day_start_equity=1_000, peak_equity=1_000, day="2026-09-01"),
        positions=[Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        prices={"AAPL": 110},
        closed_trades=[],
    )

    snapshot = enrich_pnl_snapshot(
        base,
        bars_by_ticker={"AAPL": [{"high": 110.0}, "not-a-bar", {"close": 105.0}]},
        news_by_ticker={},
    )

    assert snapshot["open_positions"][0]["day_open"] is None
    assert snapshot["open_positions"][0]["day_close"] is None
    assert snapshot["open_positions"][0]["day_change"] is None
    assert snapshot["open_positions"][0]["day_change_pct"] is None
    assert snapshot["news_by_ticker"]["AAPL"] == []


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


def test_pnl_snapshot_uses_eastern_trading_date_for_realized_trades():
    snapshot = build_pnl_snapshot(
        equity=Equity(equity=1000, day_start_equity=1000, peak_equity=1000, day="2026-08-31"),
        positions=[],
        prices={},
        closed_trades=[
            ClosedTrade(
                ticker="AAPL",
                qty=1,
                entry_price=100,
                exit_price=110,
                realized_pnl=10,
                exit_reason="take profit",
                closed_at=datetime(2026, 9, 1, 3, 59, tzinfo=timezone.utc),
            ),
            ClosedTrade(
                ticker="MSFT",
                qty=1,
                entry_price=100,
                exit_price=120,
                realized_pnl=20,
                exit_reason="take profit",
                closed_at=datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    assert snapshot["realized_pnl"] == 10
    assert [trade["ticker"] for trade in snapshot["realized_trades"]] == ["AAPL"]


def test_publish_pnl_attribution_keeps_other_positions_when_a_price_lookup_fails():
    class FakeProvider:
        def latest_price(self, ticker):
            if ticker == "MSFT":
                raise RuntimeError("price unavailable")
            return 110

    class FakeSharedState:
        pnl_attribution = None

    shared = FakeSharedState()
    publish_pnl_attribution(
        shared=shared,
        provider=FakeProvider(),
        equity=Equity(equity=1000, day_start_equity=1000, peak_equity=1000, day="2026-08-31"),
        positions=[
            Position(ticker="AAPL", qty=2, avg_entry_price=100),
            Position(ticker="MSFT", qty=1, avg_entry_price=200),
        ],
        closed_trades=[],
    )

    assert shared.pnl_attribution["unrealized_pnl"] == 20
    assert shared.pnl_attribution["open_positions"][1]["ticker"] == "MSFT"
    assert shared.pnl_attribution["open_positions"][1]["current_price"] is None


def test_same_day_restart_restores_journalled_closed_trades_before_publishing_pnl_attribution(tmp_path):
    class FakeProvider:
        def latest_price(self, ticker):
            return 110

    class FakeRunner:
        decisions = []
        closed_trades = []

    class FakeRisk:
        day_start_equity = 1_050
        peak_equity = 1_050

    class FakeSharedState:
        pnl_attribution = None

    journalled_state = State(
        equity=Equity(equity=1_040, day_start_equity=1_000, peak_equity=1_060, day="2026-08-31"),
        closed_trades=[
            ClosedTrade(
                ticker="MSFT",
                qty=1,
                entry_price=90,
                exit_price=100,
                realized_pnl=10,
                exit_reason="take profit",
                closed_at=datetime(2026, 8, 31, 15, tzinfo=timezone.utc),
            )
        ],
    )
    runner = FakeRunner()
    risk = FakeRisk()
    shared = FakeSharedState()
    store = StateStore(tmp_path)
    store.save(journalled_state)
    restored_state = store.load()

    assert restore_same_day_state(restored_state, "2026-08-31", runner, risk) is True
    publish_pnl_attribution(
        shared=shared,
        provider=FakeProvider(),
        equity=Equity(equity=1_050, day_start_equity=risk.day_start_equity, peak_equity=risk.peak_equity, day="2026-08-31"),
        positions=[Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        closed_trades=runner.closed_trades,
    )

    assert shared.pnl_attribution["daily_pnl"] == 50
    assert shared.pnl_attribution["realized_pnl"] == 10
