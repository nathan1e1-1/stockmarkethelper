import socket
import threading
import time

from autotrader.main import _port_busy, _wait_port_free


def test_port_busy_true_when_something_is_listening():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _port_busy("127.0.0.1", port) is True
    finally:
        server.close()


def test_port_busy_false_when_port_is_free():
    assert _port_busy("127.0.0.1", 0) is False


def test_port_busy_ignores_time_wait_from_closed_connection():
    # A freshly closed connection leaves a TIME_WAIT socket on the listener port.
    # Nothing is listening, so the probe must report the port as free (SO_REUSEADDR),
    # not misread the leftover TIME_WAIT as "busy".
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    connection, _ = server.accept()
    client.close()
    connection.close()
    server.close()
    assert _port_busy("127.0.0.1", port) is False


def test_wait_port_free_returns_false_when_still_busy():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _wait_port_free("127.0.0.1", port, attempts=1, interval=0.01) is False
    finally:
        server.close()


def test_wait_port_free_returns_true_when_freed_within_attempts():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def release():
        time.sleep(0.2)
        server.close()

    releaser = threading.Thread(target=release)
    releaser.start()
    try:
        assert _wait_port_free("127.0.0.1", port, attempts=20, interval=0.05) is True
    finally:
        releaser.join(timeout=2)
        try:
            server.close()
        except OSError:
            pass

from dataclasses import dataclass
from datetime import datetime, timezone

from autotrader.main import publish_pnl_attribution
from autotrader.models import Equity, Position
from autotrader.ipc import SharedState


class StubProvider:
    """In-memory provider whose latest_price changes without a real broker."""

    def __init__(self):
        self.prices = {}

    def latest_price(self, ticker):
        return self.prices.get(ticker)

    def latest_prices(self, tickers):
        return {ticker: self.prices.get(ticker) for ticker in tickers}

    def bars(self, ticker, history_range=None):
        return []

    def news(self, ticker, limit=2):
        return []


def test_publish_pnl_attribution_is_independent_of_scan_cadence():
    """A: publish_pnl_attribution can run on its own fast timer (independent of the 60s
    scan), so the app's 5s poll gets near-real-time position prices + P&L."""
    provider = StubProvider()
    provider.prices["NVDA"] = 104.5
    shared = SharedState()
    shared.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-09")
    positions = [Position(ticker="NVDA", qty=10, avg_entry_price=100.0)]
    shared.positions = positions

    publish_pnl_attribution(shared, provider, shared.equity, positions, [])

    assert shared.pnl_attribution is not None
    opens = shared.pnl_attribution["open_positions"]
    assert opens[0]["ticker"] == "NVDA"
    assert opens[0]["current_price"] == 104.5
    assert opens[0]["unrealized_pnl"] == 45.0


def test_refresh_live_prices_updates_in_place_via_batch():
    """The fast 5s publisher refreshes current_price/unrealized in place from a batched
    latest_prices call, without replacing position records (no write-ordering race)."""
    provider = StubProvider()
    provider.prices = {"NVDA": 101.0}
    shared = SharedState()
    shared.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-09")
    shared.pnl_attribution = {
        "open_positions": [
            {"ticker": "NVDA", "qty": 10.0, "avg_entry_price": 100.0, "current_price": 100.0, "unrealized_pnl": 0.0},
        ],
    }
    original_record = shared.pnl_attribution["open_positions"][0]

    from autotrader.main import refresh_live_prices
    refresh_live_prices(shared, provider)

    assert shared.pnl_attribution["open_positions"][0] is original_record  # in place
    assert original_record["current_price"] == 101.0
    assert original_record["unrealized_pnl"] == 10.0


def test_main_loop_day_change_engages_session_rollover():
    """The main loop's day-change branch must roll the lifecycle into the freshly
    observed session (unit-tested via the factored helper; main() itself loops forever)."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    from autotrader.main import _handle_day_change

    lifecycle_stub = Mock()
    provider = Mock()
    provider.gainers.return_value = []
    shared = SharedState()
    shared.equity_history = [{"t": 1.0, "equity": 1.0}]
    cfg = SimpleNamespace(universe_size=5, min_price=1.0, min_volume=0)
    universe = ["OLD"]

    _handle_day_change(
        "2026-09-03",
        lifecycle=lifecycle_stub,
        shared=shared,
        provider=provider,
        cfg=cfg,
        universe=universe,
    )

    lifecycle_stub._ensure_rollover.assert_called_once_with("2026-09-03")
    assert shared.equity_history == []
    assert universe == []
