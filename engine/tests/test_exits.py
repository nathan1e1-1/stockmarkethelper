from autotrader.exits import ExitManager
from autotrader.models import Position


def pos(entry):
    return Position(ticker="AAPL", qty=10.0, avg_entry_price=entry)


def test_stop_loss_triggers():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 97.9) == "stop_loss"


def test_take_profit_triggers():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 103.1) == "take_profit"


def test_no_trigger_between():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 101.0) is None


def test_boundary_stop_exact():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 98.0) == "stop_loss"


def test_zero_entry_no_trigger():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(0.0), 50.0) is None
