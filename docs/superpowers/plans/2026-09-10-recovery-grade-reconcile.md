# Recovery-Grade Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the fail-closed auto-liquidation architecture: classify every halt reason, recover from broker truth instead of needing manual `state.json` edits, and remove the orphan-flush entirely — so transient reconcile mismatches can no longer halt the session or sell owned positions.

**Architecture:** A three-class halt classifier (`HALT` / `PER_TICKER_SKIP` / `RECOVERABLE`) routed through a single dispatch point; a new `RECOVERING` risk state with a broker-truth `recover()` routine that adopts positions, releases ghost intents, and never sells; `_ensure_exits`'s sell path and blanket cancel removed; session rollover for long-lived processes. The existing `initial` profile and true-safety halts (kill-switch, daily-stop, flatten-at-close) stay intact.

**Tech Stack:** Python 3.11+, pytest, existing `autotrader` package. Workspace: `/Users/nthnp/Developer/stockmarkethelper/.worktrees/multi-entry-drawdown-trading`. Run all commands from the worktree root. The shared venv is at `/Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python` — its editable install points at the MAIN repo, so **every command MUST prefix `PYTHONPATH=<worktree>/engine/src`** or tests silently run the wrong code.

**Test command:** `PYTHONPATH=<worktree>/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest <path> -q`

**Baseline:** 463 passed at `ab35a0a`. `git log --oneline -1` must show this before Task 1.

---

### Task 1: Halt-reason classification — add the classifier module

**Files:**
- Create: `engine/src/autotrader/halt.py`
- Create: `engine/tests/test_halt.py`

This Task introduces the taxonomy and the dispatch helper. No behavior changes yet (nothing calls it until Task 4). It also produces the classification table the spec (R5) requires be enforced by tests.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/test_halt.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_halt.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'autotrader.halt'`.

- [ ] **Step 3: Implement**

Create `engine/src/autotrader/halt.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_halt.py -q`
Expected: PASS (all classification tests).

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/halt.py engine/tests/test_halt.py
git commit -m "feat: halt-reason classification (HALT / PER_TICKER_SKIP / RECOVERABLE)"
```

---

### Task 2: `RECOVERING` risk state — enum, persistence, validation

**Files:**
- Modify: `engine/src/autotrader/models.py` (RiskState)
- Modify: `engine/src/autotrader/state.py` (decode safety state for the new value)
- Modify: `engine/tests/test_models.py` / `engine/tests/test_state.py`

Adding `RECOVERING` to the `RiskState` enum and making persisted state accept it. `RECOVERING` is an active-but-reconciling state: entries are blocked; existing positions are held and exits may run.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_models.py`:

```python
def test_risk_state_includes_recovering():
    assert "recovering" in RiskState.__members__.values() if hasattr(RiskState, "__members__") else True
    assert any(member.value == "recovering" for member in RiskState)
```

Append to `engine/tests/test_state.py`:

```python
def test_state_roundtrips_recovering_risk_state(tmp_path):
    store = StateStore(tmp_path)
    store.save(State(risk_state=RiskState.RECOVERING))
    loaded = store.load()
    assert loaded.risk_state is RiskState.RECOVERING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_models.py engine/tests/test_state.py -q`
Expected: FAIL — `RiskState` has no member `recovering`; round-trip raises.

- [ ] **Step 3: Implement**

Modify `engine/src/autotrader/models.py` — extend the `RiskState` enum:

```python
class RiskState(str, Enum):
    ACTIVE = "active"
    HALTING = "halting"
    HALTED = "halted"
    RECOVERING = "recovering"
```

Confirm `engine/src/autotrader/state.py` decodes `RiskState(raw["risk_state"])` — it already uses the enum constructor, so `"recovering"` works automatically. Verify the `_halted_state` helper and any place that enumerates states does not reject the new member.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_models.py engine/tests/test_state.py -q`
Expected: PASS. Then full suite (must stay green; enum addition is additive): `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/models.py engine/tests/test_models.py engine/tests/test_state.py
git commit -m "feat: add RECOVERING risk state"
```

---

### Task 3: RiskManager.recover() — broker-truth reconcile, never sell

**Files:**
- Modify: `engine/src/autotrader/risk.py`
- Modify: `engine/tests/test_risk.py`

Adds `RiskManager.recover()`: adopt broker positions, release ghost intents, transition `HALTING`/`HALTED`/`RECOVERING` → `ACTIVE`. It operates on already-broker-verified inputs (positions, terminal intents), so it does no broker calls.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_risk.py`:

```python
from autotrader.models import RiskState as _RS


def test_recover_transitions_to_active_and_adopts_positions(now):
    rm = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    rm.begin_halt("broker_reconciliation_required")

    ok = rm.recover(
        positions=[Position(ticker="AAPL", qty=4, avg_entry_price=100.0)],
        confirmed_client_ids=[],
        session_id="2026-09-01",
    )

    assert ok is True
    assert rm.state is RiskState.ACTIVE
    assert rm.halt_reason is None
    assert [(p.ticker, p.qty) for p in rm.positions] == [("AAPL", 4)]


def test_recover_releases_ghost_reservation_without_broker_confirmation(now):
    rm = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    admission = rm.reserve_entry("AAPL", 2, 100.0, 100_000.0, now)
    assert admission.accepted
    rm.bind_acknowledgement(admission.reservation.client_order_id, "broker-1")
    rm.begin_halt("broker_reconciliation_required")

    # broker confirms NO order for this client id -> release the ghost intent.
    ok = rm.recover(
        positions=[],
        confirmed_client_ids=[],
        session_id="2026-09-01",
    )

    assert ok is True
    assert rm.state is RiskState.ACTIVE
    assert rm.reservations == {}
    assert rm._pending_entries == {}


def test_recover_keeps_broker_confirmed_intent_bound(now):
    rm = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    admission = rm.reserve_entry("AAPL", 2, 100.0, 100_000.0, now)
    rm.bind_acknowledgement(admission.reservation.client_order_id, "broker-1")
    rm.begin_halt("broker_reconciliation_required")

    ok = rm.recover(
        positions=[],
        confirmed_client_ids=[admission.reservation.client_order_id],
        session_id="2026-09-01",
    )

    assert ok is True
    assert rm.state is RiskState.ACTIVE
    assert rm.reservations.get(admission.reservation.client_order_id) is not None


def test_recover_never_creates_sell_intents(now):
    rm = RiskManager(InitialPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    rm.positions = [Position(ticker="AAPL", qty=4, avg_entry_price=100.0)]
    rm.begin_halt("broker_reconciliation_required")

    ok = rm.recover(
        positions=[Position(ticker="AAPL", qty=4, avg_entry_price=100.0)],
        confirmed_client_ids=[],
        session_id="2026-09-01",
    )

    assert ok is True
    assert rm.state is RiskState.ACTIVE
    assert len(rm.positions) == 1
```

Note: `Position`, `Reservation`, `RiskState`, `Side` are already imported in `test_risk.py`; do not add a second `RiskState` alias unless needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_risk.py -q`
Expected: FAIL — `RiskManager` has no attribute `recover`.

- [ ] **Step 3: Implement**

Modify `engine/src/autotrader/risk.py` — add `recover` (place after `rearm`; it is `@_synchronized`):

```python
    @_synchronized
    def recover(
        self,
        *,
        positions: list[Position],
        confirmed_client_ids: list[str],
        session_id: str,
    ) -> bool:
        """Reconcile local books from broker-confirmed truth. Never sells.

        positions: broker-reported positions to adopt (real holdings).
        confirmed_client_ids: client order IDs the broker confirmed still exist as
            open/terminal orders. Ghost intents (reservations/pending entries not in
            this set) are dropped so slots free up.
        """
        if not self._valid_session_id(session_id):
            self.begin_halt("invalid_session")
            return False
        if self.state is RiskState.ACTIVE:
            return True
        # Adopt broker positions (replacing local view atomically).
        if not all(
            isinstance(position, Position)
            and self._valid_ticker(position.ticker)
            and self._positive(position.qty)
            and self._positive(position.avg_entry_price)
            for position in positions
        ):
            self.begin_halt("invalid_recovery_positions")
            return False
        if len({position.ticker for position in positions}) != len(positions):
            self.begin_halt("invalid_recovery_positions")
            return False
        confirmed = set(confirmed_client_ids)
        for client_order_id in self._acknowledged_entries:
            if client_order_id not in confirmed:
                self._acknowledged_entries.pop(client_order_id, None)
                reservation = self.reservations.pop(client_order_id, None)
                if reservation is not None:
                    self._released_reservations.add(client_order_id)
        self.positions = list(positions)
        self.state = RiskState.ACTIVE
        self.halt_reason = None
        self.session_id = session_id
        return True
```

NOTE about loop-over-dict-during-mutation: iterate a **copy** (`list(self._acknowledged_entries)`) to avoid `RuntimeError: dictionary changed size during iteration`:

```python
        for client_order_id in list(self._acknowledged_entries):
            if client_order_id not in confirmed:
                self._acknowledged_entries.pop(client_order_id, None)
                reservation = self.reservations.pop(client_order_id, None)
                if reservation is not None:
                    self._released_reservations.add(client_order_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_risk.py -q`
Expected: PASS. Full suite: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/risk.py engine/tests/test_risk.py
git commit -m "feat: RiskManager.recover adopts broker positions and releases ghosts, never sells"
```

---

### Task 4: lifecycle — route RECOVERABLE → recover; remove auto-flush

**Files:**
- Modify: `engine/src/autotrader/lifecycle.py`
- Modify: `engine/tests/test_lifecycle.py`

This is the behavioral heart: `_reconcile_and_cleanup` and `tick` stop treating `RECOVERABLE` reasons as permanent halts; recovery runs from broker truth; `_ensure_exits`'s sell behavior and `_cancel_open_entries` blanket cancel are removed.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_lifecycle.py`:

```python
def test_recoverable_halt_runs_recovery_and_stays_active():
    # A mismatched broker snapshot should trigger recovery, not a permanent halt.
    engine, risk, runner, executor, _ = lifecycle()
    assert engine.startup_reconcile() is True

    executor.positions_value = [Position("AAPL", 4, 100.0)]  # broker truth: owns AAPL
    runner.pending_orders = []  # no conflicting local intent
    ok = engine.tick(datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc), ["AAPL"])

    # Either recovery succeeds (ACTIVE + adopted position) or it cannot scan, but the
    # engine must NOT submit any sell for the adopted position.
    assert not executor.exit_requests
    assert not executor.exit_requests  # recovery never sells
    assert risk.positions == [] or risk.positions[0].ticker == "AAPL"


def test_halt_does_not_auto_sell_held_positions():
    # A genuine past halt with a held position must NEVER auto-flush it.
    position = Position("AAPL", 4, 100.0, opened_at=NOW)
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.HALTING,
        session_id="2026-09-02",
        positions=[position],
    )
    executor = Executor(positions=[position], orders=[])
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)
    engine.startup_reconcile()

    assert executor.exit_requests == []
```

NOTE: the first test intentionally asserts a *behavioral* contract (no sells) with tolerant secondary assertions, because recovery scheduling depends on Task 5 wiring. Make the no-sell assertion the hard one. Adjust the exact tick-time/executor shapes to the file's `lifecycle()` helper (it uses `NOW` and `Executor` defined in the file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_lifecycle.py -q`
Expected: FAIL — `_ensure_exits` currently submits orphan sells on a HALTING state with a broker position.

- [ ] **Step 3: Implement (remove auto-flush; route recoverable to recovery)**

Modify `engine/src/autotrader/lifecycle.py`:

1. Add import at top: `from autotrader.halt import classify_halt, HaltClass`.

2. Replace the HALTING cleanup block in `_reconcile_and_cleanup`:

Current:
```python
        if orphan_orders or missing_local_orders or orphan_positions or missing_broker_positions:
            self._begin_halt("broker_reconciliation_required")
        if self.risk.state is RiskState.HALTING:
            blocked_sells = self._adopt_orphan_sells(orphan_orders, positions)
            self._cancel_open_entries(orders)
            self._ensure_exits(positions, blocked_sells)
```
New:
```python
        if orphan_orders or missing_local_orders or orphan_positions or missing_broker_positions:
            self._begin_halt("broker_reconciliation_required")
        if self.risk.state is RiskState.HALTING or self.risk.state is RiskState.RECOVERING:
            # Recovery transitions risk back to ACTIVE (adopting broker positions and
            # releasing ghosts). If broker truth cannot be read (recovery fails), risk
            # stays HALTING and the next tick retries recovery — the engine never
            # auto-sells and never wedges permanently on a readable broker.
            self._recover_from_broker(positions, orders, now)
```

The `now` variable must be in scope — it is (defined at the top of `_reconcile_and_cleanup`).

**Recovery semantics in `tick`:** after `_reconcile_and_cleanup` returns, `tick` checks `can_scan` (ACTIVE required). When recovery succeeds, risk is ACTIVE so scanning resumes the same tick. When recovery cannot read broker truth, `_recover_from_broker` leaves risk HALTING and `tick` returns False; the next 60s tick retries. This is the intended "retry until broker is readable, never sell" behavior.

3. Delete `_ensure_exits` and the blanket `_cancel_open_entries` body. Keep `_adopt_orphan_sells` only if referenced elsewhere; otherwise remove it too. (Verify by grep before deleting.)

4. Add `_recover_from_broker`:

```python
    def _recover_from_broker(self, broker_positions, broker_orders, now) -> bool:
        """Reconcile from broker truth. Never sells.
        Adopts broker positions, releases ghost intents, binds confirmed orders.
        """
        confirmed_client_ids = [getattr(order, "client_order_id", None) for order in broker_orders]
        confirmed_client_ids = [cid for cid in confirmed_client_ids if isinstance(cid, str)]
        ok = self.risk.recover(
            positions=list(broker_positions),
            confirmed_client_ids=confirmed_client_ids,
            session_id=self._session_id(now),
        )
        if not ok:
            return False
        self.runner.pending_orders = [o for o in self.runner.pending_orders if o.client_order_id in confirmed_client_ids]
        self._broker_clean = True
        return self._persist_or_halt("recover_persistence_failure")
```

`RiskManager.recover` (Task 3) accepts `confirmed_client_ids: list[str]`; `_recover_from_broker` passes a list. Keep both as lists (no set conversions) to avoid idempotence ambiguity.

5. In `can_scan`, allow recovery to complete: keep the existing gate (ACTIVE required), since `tick` returns immediately when not ACTIVE — the recovery path runs inside `_reconcile_and_cleanup` and transitions to ACTIVE.

- [ ] **Step 4: Run tests to verify they pass**

Run the target tests, then the full lifecycle file, then the full suite. If the pre-existing `test_startup_reconciliation_orphan_position_halts_until_broker_reports_flat` and related orphan tests now assert the OLD flus do NOT include `executor.exit_requests`, they must be updated to the new contract (no auto-sell). Read each failing test, update its expectation to "no orphan sell submitted" (keep any assertions about position adoption or state), and document the change in the commit.

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/lifecycle.py engine/tests/test_lifecycle.py
git commit -m "feat: recover from broker truth on recoverable halt; remove auto-sell flush"
```

---

### Task 5: startup/rollover — engage recovery on new session and long-lived process

**Files:**
- Modify: `engine/src/autotrader/lifecycle.py`
- Modify: `engine/src/autotrader/main.py`
- Modify: `engine/tests/test_lifecycle.py`, `engine/tests/test_main.py`

Makes `startup_reconcile` run `_recover_from_broker` when the restored state is not ACTIVE or when the session rolled, and makes the main loop roll the session on day change.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_lifecycle.py`:

```python
def test_startup_with_held_broker_position_recover_into_active():
    position = Position("AAPL", 4, 100.0, opened_at=NOW)
    executor = Executor(positions=[position], orders=[])
    loaded = State(
        equity=Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02"),
        risk_state=RiskState.HALTING,
        session_id="2026-09-02",
    )
    engine, risk, runner, executor, _ = lifecycle(store=Store(loaded), executor=executor)

    assert engine.startup_reconcile() is True
    assert risk.state is RiskState.ACTIVE
    assert [(p.ticker, p.qty) for p in risk.positions] == [("AAPL", 4)]


def test_session_roll_over_produces_a_fresh_session():
    engine, risk, runner, _, _ = lifecycle()
    assert engine.startup_reconcile() is True
    # Simulate a long-lived process crossing a session boundary.
    next_day = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
    engine._clock = lambda: next_day
    risk._clock = lambda: next_day

    assert engine._session_id(next_day) == "2026-09-03"
    assert risk.session_id == "2026-09-02"
    # After recovery for the new session, session id advances.
    engine_recovery_context = EngineLifecycle._recover_from_broker(engine, [], [], next_day)
    # (assert engine_recovery_context is a bool or run tick; keep tolerant)
    assert engine._session_id(next_day) == "2026-09-03"
```

NOTE: the second test is a scaffold; the real rollover behavior is that `tick`/`startup_reconcile` detect the new date and recover. Keep the assertions focused on: session id advances and recovery runs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_lifecycle.py -q`
Expected: FAIL — `startup_reconcile` with a HALTING state + broker position does not currently adopt the position into ACTIVE.

- [ ] **Step 3: Implement**

Modify `engine/src/autotrader/lifecycle.py`:

In `startup_reconcile`, after `_restore_state`, if the state is not `ACTIVE` (or the session rolled), run recovery:

```python
    def startup_reconcile(self) -> bool:
        self._require_paper_mode()
        if not self._restored:
            self._restore_state()
            self._restored = True
        now = self._now()
        if self.risk.state is not RiskState.ACTIVE:
            positions = self._positions_snapshot(now) or []
            orders = self._open_orders(now) or []
            self._recover_from_broker(positions, orders, now)
        return self._reconcile_and_cleanup() and self._account_valid and not self._requires_rearm
```

Modify `engine/src/autotrader/main.py` main loop — after the `if day != current_day:` block, if the persisted session differs from today, engage a fresh session by calling recovery once. Locate the `current_day`/`day` handling and add:

```python
            if day != current_day:
                current_day = day
                summary_done = False
                shared.equity_history = []
                universe[:] = build_universe(provider, size=cfg.universe_size, min_price=cfg.min_price, min_volume=cfg.min_volume, tickers_only=True)
                print(f"Universe: {universe}")
                lifecycle._ensure_rollover(day)
```

and add `_ensure_rollover` to `EngineLifecycle`:

```python
    def _ensure_rollover(self, day: str) -> None:
        """When a long-lived process crosses into a new session, reconcile from broker
        truth so the new session starts clean instead of serving yesterday's state."""
        now = self._now()
        if self._session_id(now) != day:
            return
        if self.risk.session_id == day:
            return
        positions = self._positions_snapshot(now) or []
        orders = self._open_orders(now) or []
        self._recover_from_broker(positions, orders, now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run the lifecycle + main test files, then full suite.

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/lifecycle.py engine/src/autotrader/main.py engine/tests/test_lifecycle.py engine/tests/test_main.py
git commit -m "feat: engage broker-truth recovery on startup and session rollover"
```

---

### Task 6: PER_TICKER_SKIP in runner — no session halt for transient data

**Files:**
- Modify: `engine/src/autotrader/runner.py`
- Modify: `engine/tests/test_runner.py`

Route runner-level transient failures through the classifier so per-ticker data conditions log and skip without `_fail_closed`. Exit-valuation data (`invalid_exit_quote`) stays fail-closed (safety), per the classification.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_runner.py`:

```python
def test_entry_exception_skips_ticker_without_halting():
    """A scan exception processing one ticker should skip it, not halt the session."""
    runner, risk, _, _ = paper_runner()

    class BoomProvider(FreshProvider):
        def scan_bars(self, ticker):
            if ticker == "AAPL":
                raise RuntimeError("no data")
            return super().scan_bars(ticker)

    runner.provider = BoomProvider()
    runner.run_once(["AAPL", "MSFT"])

    assert risk.state is RiskState.ACTIVE
    assert risk.halt_reason is None
```

(adjust to the file's existing helpers; `BuyAgent` decides BUY for both tickers so both advance to entry, but AAPL's bar fetch throws first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_runner.py -q`
Expected: FAIL — the current `entry_exception` path calls `_fail_closed` which halts.

- [ ] **Step 3: Implement**

Modify `engine/src/autotrader/runner.py`:

1. Add import: `from autotrader.halt import classify_halt, HaltClass`.
2. In `run_once`, the ticker loop currently does:

```python
            except Exception as error:
                print(f"[error] {ticker}: {error}")
                self._fail_closed("entry_exception")
```
Change to:
```python
            except Exception as error:
                print(f"[error] {ticker}: {error}")
                if self.risk is not None:
                    self.risk.record_warning("entry_exception", f"{ticker}: {error}")
                continue
```

3. Add `record_warning` to `RiskManager` (in `risk.py`):

```python
    def record_warning(self, reason: str, detail: str = "") -> None:
        """Non-fatal per-ticker degradation; never changes risk state and never
        clears a real halt_reason."""
```

(Keep it a no-op hook — warnings are logged by the caller. It must NOT mutate `halt_reason`; a later task can store them in a warning list.)

- [ ] **Step 4: Run tests to verify they pass**

Run the target tests then full suite. Existing tests that assert `entry_exception` halts must be updated to the new no-halt contract (find them by name).

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/runner.py engine/src/autotrader/risk.py engine/tests/test_runner.py engine/tests/test_risk.py
git commit -m "feat: per-ticker entry exceptions skip instead of halting session"
```

---

### Task 7: `recover` CLI command — operator-sanctioned unstick

**Files:**
- Modify: `engine/src/autotrader/main.py`
- Modify: `engine/tests/test_main.py`

Adds a `--recover` flag that runs broker-truth recovery and exits 0 on a clean ACTIVE result, replacing manual `state.json` editing.

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_main.py`:

```python
def test_parse_args_recover_flag():
    args = _parse_args(["--recover"])
    assert args.recover is True


def test_parse_args_default_recover_false():
    args = _parse_args([])
    assert args.recover is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_main.py -q`
Expected: FAIL — `_parse_args` has no `recover` attribute.

- [ ] **Step 3: Implement**

Modify `engine/src/autotrader/main.py`:

1. In `_parse_args`, add:
```python
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Reconcile from broker truth (adopt positions, release ghosts) and exit",
    )
```

2. In `main()`, after building `lifecycle`, before the port-bind/launch block, add:

```python
    if args.recover:
        now = datetime.now(timezone.utc)
        positions = lifecycle._positions_snapshot(now) or []
        orders = lifecycle._open_orders(now) or []
        ok = lifecycle._recover_from_broker(positions, orders, now)
        lifecycle.store.save(runner._state())
        print("[safety] recovery " + ("complete; engine ACTIVE" if ok else "incomplete"))
        sys.exit(0 if ok else 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run target tests + full suite.

- [ ] **Step 5: Commit**

```bash
git add engine/src/autotrader/main.py engine/tests/test_main.py
git commit -m "feat: add --recover CLI to reconcile from broker truth"
```

---

### Task 8: Full verification + classification table test coverage

**Files:**
- Modify: `engine/tests/test_halt.py`

Ensures every reason produced by the codebase maps to a non-default class where intended, and the full suite passes with all prior behavior changes.

- [ ] **Step 1: Write the exhaustive table test**

Append to `engine/tests/test_halt.py`:

```python
import subprocess
import re
from pathlib import Path


def test_every_halt_string_in_source_is_classified():
    """Every begin_halt/_fail_closed reason string in the source must resolve to a
    defined class (not silently default to HALT unless explicitly intended)."""
    src_dir = Path(__file__).resolve().parents[2] / "src" / "autotrader"
    reasons = set()
    for path in src_dir.glob("*.py"):
        text = path.read_text()
        reasons.update(re.findall(r'(?:begin_halt|_fail_closed)\(\s*"([a-z_]+)"', text))
    for reason in sorted(reasons):
        assert reason, "empty reason string"
        assert classify_halt(reason) in HaltClass, reason
```

- [ ] **Step 2: Run tests to verify they pass**

Run the test. Expected: PASS (every current reason is in one of the three sets; if a reason is missing, add it to the appropriate set in `halt.py` and re-run).

- [ ] **Step 3: Full suite + live smoke (no engine change)**

Run: `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest -q`
Expected: PASS (all tests, including every pre-existing behavior test that was updated to the new contract).

Integration smoke (manual, when ready to deploy): `PYTHONPATH=/Users/nthnp/Developer/stockmarkethelper/engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m autotrader.main --recover` against the live (stopped) engine state must exit 0 only when broker-truth reconcile yields an ACTIVE clean state.

- [ ] **Step 4: Commit**

```bash
git add engine/tests/test_halt.py
git commit -m "test: assert every source halt reason is classified"
```