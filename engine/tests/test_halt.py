from autotrader.halt import HaltClass, classify_halt


def test_halt_class_membership():
    # HALT: true integrity threats (persistence, book identity, stops, clock).
    for reason in (
        "pre_submit_persistence_failure",
        "post_acknowledgement_persistence_failure",
        "fill_persistence_failure",
        "pre_exit_persistence_failure",
        "post_exit_acknowledgement_persistence_failure",
        "timeout_reconciliation_persistence_failure",
        "rearm_persistence_failure",
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
        "invalid_exit_quantity",
        "hard_stop",
        "daily_stop",
        "invalid_clock",
        "invalid_lifecycle_clock",
        "invalid_equity",
        "missing_risk_manager",
        "exit_submission_unavailable",
        "session_cutoff",
    ):
        assert classify_halt(reason) is HaltClass.HALT, reason


def test_per_ticker_skip_membership():
    # PER_TICKER_SKIP: transient data quality; never halts the session.
    for reason in (
        "invalid_quote",
        "entry_exception",
        "stale_quote",
        "invalid_timestamp",
        "invalid_exit_quote",
        "unknown_quote",
    ):
        assert classify_halt(reason) is HaltClass.PER_TICKER_SKIP, reason


def test_recoverable_membership():
    # RECOVERABLE: local↔broker divergence resolvable from broker truth.
    for reason in (
        "broker_reconciliation_required",
        "invalid_order_snapshot",
        "invalid_broker_snapshot",
        "invalid_account_snapshot",
        "order_lookup_failed",
        "unreconcilable_client_order",
        "prior_session_requires_rearm",
        "invalid_persisted_risk_state",
    ):
        assert classify_halt(reason) is HaltClass.RECOVERABLE, reason


def test_unknown_reason_defaults_to_halt():
    assert classify_halt("some_future_reason") is HaltClass.HALT
    assert classify_halt("") is HaltClass.HALT
    assert classify_halt(None) is HaltClass.HALT
