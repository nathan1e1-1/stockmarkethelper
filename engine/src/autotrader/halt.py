"""Halt-reason classification.

Every failure that can stop or degrade engine work is partitioned into one of three
classes so the fail-closed contract only applies where the books are genuinely in
doubt, while transient data quality degrades gracefully and local↔broker divergence
self-heals from broker truth (see EngineLifecycle.recover).

Categories:
- HALT: true integrity threat; whole session stops (today's behavior).
- PER_TICKER_SKIP: transient per-ticker data quality; skip, keep session ACTIVE.
- RECOVERABLE: local↔broker divergence resolvable by re-reading broker truth.
"""

from enum import Enum


class HaltClass(str, Enum):
    HALT = "halt"
    PER_TICKER_SKIP = "per_ticker_skip"
    RECOVERABLE = "recoverable"


_HALT_REASONS = frozenset({
    "pre_submit_persistence_failure",
    "post_acknowledgement_persistence_failure",
    "fill_persistence_failure",
    "pre_exit_persistence_failure",
    "post_exit_acknowledgement_persistence_failure",
    "timeout_reconciliation_persistence_failure",
    "rearm_persistence_failure",
    "halt_persistence_failure",
    "orphan_sell_persistence_failure",
    "invalid_entry_acknowledgement",
    "invalid_exit_acknowledgement",
    "conflicting_acknowledgement",
    "conflicting_terminal_order",
    "unknown_order",
    "unknown_reservation",
    "invalid_broker_order_id",
    "invalid_client_order_id",
    "invalid_terminal_status",
    "invalid_terminal_fill",
    "invalid_cumulative_fill",
    "decreasing_or_excess_fill",
    "excess_fill_price",
    "invalid_buy_fill",
    "invalid_sell_fill",
    "invalid_terminal_sell_fill",
    "decreasing_or_invalid_sell_fill",
    "invalid_exit_quantity",
    "hard_stop",
    "daily_stop",
    "invalid_clock",
    "invalid_lifecycle_clock",
    "invalid_equity",
    "missing_risk_manager",
    "exit_submission_unavailable",
    "session_cutoff",
})

_SKIP_REASONS = frozenset({
    "invalid_quote",
    "entry_exception",
    "stale_quote",
    "invalid_timestamp",
    "invalid_exit_quote",
    "unknown_quote",
    "insufficient_data",
})

_RECOVERABLE_REASONS = frozenset({
    "broker_reconciliation_required",
    "invalid_order_snapshot",
    "invalid_broker_snapshot",
    "invalid_account_snapshot",
    "order_lookup_failed",
    "unreconcilable_client_order",
    "prior_session_requires_rearm",
    "invalid_persisted_risk_state",
    "lifecycle_reconciliation_required",
})


def classify_halt(reason: str | None) -> HaltClass:
    """Return the HaltClass for a halt/skip reason. Unknown reasons default to HALT."""
    if reason in _SKIP_REASONS:
        return HaltClass.PER_TICKER_SKIP
    if reason in _RECOVERABLE_REASONS:
        return HaltClass.RECOVERABLE
    return HaltClass.HALT
