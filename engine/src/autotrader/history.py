from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


class HistoryRange(str, Enum):
    ONE_DAY = "1D"
    FIVE_DAYS = "5D"
    ONE_MONTH = "1M"
    SIX_MONTHS = "6M"
    ONE_YEAR = "1Y"
    MAX = "MAX"


@dataclass(frozen=True)
class HistoryRequest:
    timeframe: TimeFrame
    start: datetime
    end: datetime
    max_bars: int

    @classmethod
    def for_range(
        cls,
        history_range: HistoryRange | str,
        *,
        end: datetime | None = None,
    ) -> "HistoryRequest":
        history_range = HistoryRange(history_range)
        end = end or datetime.now(timezone.utc)
        settings = {
            HistoryRange.ONE_DAY: (TimeFrame.Minute, 1, 390),
            HistoryRange.FIVE_DAYS: (TimeFrame(5, TimeFrameUnit.Minute), 5, 500),
            HistoryRange.ONE_MONTH: (TimeFrame.Hour, 31, 500),
            HistoryRange.SIX_MONTHS: (TimeFrame.Day, 183, 500),
            HistoryRange.ONE_YEAR: (TimeFrame.Day, 366, 500),
        }
        if history_range is HistoryRange.MAX:
            return cls(
                timeframe=TimeFrame.Day,
                start=datetime(1970, 1, 1, tzinfo=timezone.utc),
                end=end,
                max_bars=500,
            )

        timeframe, days, max_bars = settings[history_range]
        return cls(
            timeframe=timeframe,
            start=end - timedelta(days=days),
            end=end,
            max_bars=max_bars,
        )


def thin_bars(bars: list[dict[str, Any]], max_bars: int) -> list[dict[str, Any]]:
    if max_bars <= 0:
        return []
    if len(bars) <= max_bars:
        return bars
    if max_bars == 1:
        return [bars[0]]

    last_index = len(bars) - 1
    return [bars[index * last_index // (max_bars - 1)] for index in range(max_bars)]
