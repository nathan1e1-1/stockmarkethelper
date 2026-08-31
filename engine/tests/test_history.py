from datetime import datetime, timedelta, timezone

from alpaca.data.timeframe import TimeFrameUnit

from autotrader.history import HistoryRange, HistoryRequest, thin_bars


def test_max_history_request_uses_epoch_start_and_daily_bounded_output():
    end = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)

    request = HistoryRequest.for_range(HistoryRange.MAX.value, end=end)

    assert request.start == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert request.end == end
    assert request.timeframe.amount == 1
    assert request.timeframe.unit is TimeFrameUnit.Day
    assert request.max_bars == 500


def test_history_request_maps_each_range_to_expected_timeframe_and_window():
    end = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)

    expected = {
        HistoryRange.ONE_DAY: (1, TimeFrameUnit.Minute, 1, 390),
        HistoryRange.FIVE_DAYS: (5, TimeFrameUnit.Minute, 5, 500),
        HistoryRange.ONE_MONTH: (1, TimeFrameUnit.Hour, 31, 500),
        HistoryRange.SIX_MONTHS: (1, TimeFrameUnit.Day, 183, 500),
        HistoryRange.ONE_YEAR: (1, TimeFrameUnit.Day, 366, 500),
    }

    for history_range, (amount, unit, days, max_bars) in expected.items():
        request = HistoryRequest.for_range(history_range, end=end)
        assert request.timeframe.amount == amount
        assert request.timeframe.unit is unit
        assert request.start == end - timedelta(days=days)
        assert request.max_bars == max_bars


def test_thin_bars_bounds_output_and_preserves_whole_selected_span():
    bars = [{"t": str(index)} for index in range(1_001)]

    result = thin_bars(bars, max_bars=5)

    assert len(result) == 5
    assert result[0] == bars[0]
    assert result[-1] == bars[-1]
    assert result == [bars[index] for index in (0, 250, 500, 750, 1_000)]
