from datetime import datetime, time
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_trading_day(now: datetime) -> bool:
    return now.astimezone(EASTERN).weekday() < 5


def is_market_open(now: datetime) -> bool:
    if not is_trading_day(now):
        return False
    t = now.astimezone(EASTERN).time()
    return MARKET_OPEN <= t < MARKET_CLOSE


def is_after_close(now: datetime) -> bool:
    if not is_trading_day(now):
        return False
    return now.astimezone(EASTERN).time() >= MARKET_CLOSE
