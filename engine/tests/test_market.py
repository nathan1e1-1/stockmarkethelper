from datetime import datetime
from zoneinfo import ZoneInfo

from autotrader.market import is_market_open, is_trading_day, is_after_close

EASTERN = ZoneInfo("America/New_York")


def mk(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=EASTERN)


def test_weekend_is_not_trading_day():
    assert is_trading_day(mk(2026, 8, 22, 10, 0)) is False  # Saturday
    assert is_trading_day(mk(2026, 8, 23, 10, 0)) is False  # Sunday


def test_weekday_is_trading_day():
    assert is_trading_day(mk(2026, 8, 24, 10, 0)) is True  # Monday


def test_before_open_is_closed():
    assert is_market_open(mk(2026, 8, 24, 8, 0)) is False


def test_during_hours_is_open():
    assert is_market_open(mk(2026, 8, 24, 9, 30)) is True
    assert is_market_open(mk(2026, 8, 24, 15, 59)) is True


def test_at_and_after_close_is_closed():
    assert is_market_open(mk(2026, 8, 24, 16, 0)) is False
    assert is_market_open(mk(2026, 8, 24, 16, 30)) is False


def test_weekend_is_not_open():
    assert is_market_open(mk(2026, 8, 22, 10, 0)) is False


def test_after_close_on_trading_day():
    assert is_after_close(mk(2026, 8, 24, 16, 30)) is True
    assert is_after_close(mk(2026, 8, 24, 10, 0)) is False


def test_after_close_on_weekend_is_false():
    assert is_after_close(mk(2026, 8, 22, 16, 30)) is False
