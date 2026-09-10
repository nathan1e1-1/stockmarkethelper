import pytest

from autotrader.halt import (
    HaltClass,
    _HALT_REASONS,
    _RECOVERABLE_REASONS,
    _SKIP_REASONS,
    classify_halt,
)


@pytest.mark.parametrize("reason", sorted(_HALT_REASONS))
def test_halt_reasons_classify_halt(reason):
    assert classify_halt(reason) is HaltClass.HALT


@pytest.mark.parametrize("reason", sorted(_SKIP_REASONS))
def test_skip_reasons_classify_per_ticker(reason):
    assert classify_halt(reason) is HaltClass.PER_TICKER_SKIP


@pytest.mark.parametrize("reason", sorted(_RECOVERABLE_REASONS))
def test_recoverable_reasons_classify_recoverable(reason):
    assert classify_halt(reason) is HaltClass.RECOVERABLE


def test_sets_are_disjoint():
    assert not (_HALT_REASONS & _SKIP_REASONS)
    assert not (_HALT_REASONS & _RECOVERABLE_REASONS)
    assert not (_SKIP_REASONS & _RECOVERABLE_REASONS)


def test_unknown_reason_defaults_to_halt():
    assert classify_halt("some_future_reason") is HaltClass.HALT
    assert classify_halt("") is HaltClass.HALT
    assert classify_halt(None) is HaltClass.HALT
