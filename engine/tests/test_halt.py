import re
from pathlib import Path

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


def test_every_source_halt_reason_has_explicit_class():
    """Every begin_halt/_fail_closed/_persist_or_halt reason the engine can produce must
    be a member of an explicit classification set — not silently covered by the catch-all
    default. Guards against drift: dropping or adding a reason without a class fails."""
    src_dir = Path(__file__).resolve().parents[1] / "src" / "autotrader"
    reasons = set()
    pattern = re.compile(r'(?:begin_halt|_fail_closed|_persist_or_halt)\(\s*"([a-z_]+)"')
    for path in src_dir.glob("*.py"):
        reasons.update(pattern.findall(path.read_text()))
    explicit = _HALT_REASONS | _SKIP_REASONS | _RECOVERABLE_REASONS
    # Admission/decision reason strings, not halt reasons.
    not_halt_reasons = {
        "cutoff_latched",
        "duplicate_ticker",
        "invalid_input",
        "max_daily_risk_pct",
        "max_entries_per_session",
        "max_gross_exposure",
        "max_position_exposure",
        "max_positions",
    }
    missing = sorted((reasons - explicit) - not_halt_reasons)
    assert not missing, f"reason(s) with no explicit class: {missing}"
