from autotrader.risk import RiskManager
from autotrader.models import Position


def cfg():
    from dataclasses import dataclass
    @dataclass
    class C:
        paper_capital: float = 100000.0
        max_position_pct: float = 0.02
        max_positions: int = 3
        kill_switch_pct: float = 0.10
        daily_loss_pct: float = 0.05
    return C()


def test_position_size_is_pct_of_equity():
    rm = RiskManager(cfg())
    qty = rm.position_size("AAPL", price=100.0, equity=100000.0)
    assert qty == 20  # 2% of 100k / $100 = 20 shares


def test_max_positions_reached_blocks_entry():
    rm = RiskManager(cfg())
    rm.positions = [
        Position(ticker="A", qty=1, avg_entry_price=100.0),
        Position(ticker="B", qty=1, avg_entry_price=100.0),
        Position(ticker="C", qty=1, avg_entry_price=100.0),
    ]
    assert rm.can_enter("D") is False


def test_kill_switch_triggers_on_drawdown():
    rm = RiskManager(cfg())
    rm.peak_equity = 100000.0
    assert rm.hard_stop_triggered(89000.0) is True
    assert rm.hard_stop_triggered(91000.0) is False


def test_daily_loss_limit():
    rm = RiskManager(cfg())
    rm.day_start_equity = 100000.0
    assert rm.daily_stop_triggered(94999.0) is True
    assert rm.daily_stop_triggered(95001.0) is False
