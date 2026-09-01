# Paper-Trading Safety Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox syntax.

**Goal:** Enforce a small, paper-only exposure profile with durable order intent, broker-confirmed accounting, and a latching safety lifecycle.

**Architecture:** Typed quote and broker snapshots enter through adapters. RiskManager becomes the atomic admission/state authority, StateStore persists the safety snapshot atomically, Runner reconciles actual order-fill deltas, and a new EngineLifecycle owns startup reconciliation, cutoff, halts, and re-arm.

**Tech Stack:** Python, dataclasses, Alpaca Python SDK, PyYAML, pytest, and the existing macOS build script.

---

## Planned file boundaries

| Files | Responsibility |
| --- | --- |
| engine/config/config.yaml; engine/src/autotrader/config.py | Paper-only initial profile and validation. |
| engine/src/autotrader/models.py | Quote, risk state, reservation, and normalized order records. |
| engine/src/autotrader/providers/base.py; providers/alpaca.py; providers/fixtures.py | Timestamped quote interface. |
| engine/src/autotrader/execution.py | Paper-only bounded entry, order lookup, cancellation, normalized snapshots. |
| engine/src/autotrader/risk.py | Atomic admission, reservations, halt/cutoff/re-arm rules. |
| engine/src/autotrader/state.py | Atomic safety-state writes and legacy-safe decoding. |
| engine/src/autotrader/runner.py | Signal-to-intent flow and fill-delta accounting. |
| engine/src/autotrader/lifecycle.py | New startup/tick coordinator and orphan cleanup. |
| engine/src/autotrader/main.py | Lifecycle wiring, local-only re-arm, UI-state publication. |

### Task 1: Add the locked paper profile and safety records

**Files:**
- Modify: engine/config/config.yaml
- Modify: engine/src/autotrader/config.py
- Modify: engine/src/autotrader/models.py
- Modify: engine/tests/test_config.py
- Modify: engine/tests/test_models.py

- [ ] Step 1: Write failing tests for live-mode rejection, the 0.25% one-position/one-entry profile, and normalized order fields.

~~~python
def test_load_config_rejects_live_trading(tmp_path, monkeypatch):
    path = write_config(tmp_path, paper=False)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")
    with pytest.raises(ValueError, match="paper trading"):
        load_config(str(path))

def test_initial_profile_is_small():
    cfg = load_config_for_test()
    assert cfg.max_position_pct == 0.0025
    assert cfg.max_gross_exposure_pct == 0.0025
    assert cfg.max_positions == cfg.max_entries_per_session == 1
    assert cfg.max_snapshot_age_seconds == 120
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_config.py engine/tests/test_models.py -q
~~~

Expected: FAIL because profile validation and safety data types do not exist.

- [ ] Step 3: Implement the minimal records and validation.

~~~python
class RiskState(str, Enum):
    ACTIVE = "active"
    HALTING = "halting"
    HALTED = "halted"

@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    source_timestamp: datetime
    observed_at: datetime

@dataclass
class Reservation:
    client_order_id: str
    ticker: str
    qty: float
    limit_price: float
    created_at: datetime
~~~

Extend Order with client_order_id, filled_qty, filled_notional, processed_filled_qty, processed_filled_notional, and observed_at; preserve defaults for legacy JSON. Add and validate the approved YAML defaults. Reject every config whose paper flag is not exactly true, whose caps are nonpositive, or whose gross cap is below the position cap.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/config/config.yaml engine/src/autotrader/config.py engine/src/autotrader/models.py engine/tests/test_config.py engine/tests/test_models.py
git commit -m "feat: lock paper safety profile"
~~~

### Task 2: Expose fresh quotes and normalized paper-broker operations

**Files:**
- Modify: engine/src/autotrader/providers/base.py
- Modify: engine/src/autotrader/providers/alpaca.py
- Modify: engine/src/autotrader/providers/fixtures.py
- Modify: engine/src/autotrader/execution.py
- Modify: engine/tests/test_alpaca.py
- Modify: engine/tests/test_execution.py

- [ ] Step 1: Write failing fake-SDK tests.

~~~python
def test_latest_quote_preserves_source_and_observation_time():
    provider = provider_with(data=FakeDataClient(FakeTrade(190.0, SOURCE_TIME)))
    assert provider.latest_quote("AAPL", now=OBSERVED_TIME) == Quote(
        "AAPL", 190.0, SOURCE_TIME, OBSERVED_TIME
    )

def test_executor_submits_limit_buy_with_durable_client_id(fake_client, cfg):
    order = executor_with(fake_client, cfg).submit_limit_buy(
        "AAPL", qty=2, limit_price=100.0, client_order_id="entry-20260901-AAPL"
    )
    assert fake_client.request.limit_price == 100.0
    assert order.client_order_id == "entry-20260901-AAPL"
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_alpaca.py engine/tests/test_execution.py -q
~~~

Expected: FAIL because timestamped quotes, limit entry, lookup, and cancellation are missing.

- [ ] Step 3: Implement the adapter contract.

Add latest_quote to MarketDataProvider. Keep latest_price as a display/P&L compatibility wrapper around latest_quote(). Add these executor methods:

~~~python
def submit_limit_buy(self, ticker, qty, limit_price, client_order_id) -> Order: ...
def submit_exit(self, ticker, qty, client_order_id) -> Order: ...
def order(self, broker_order_id) -> Order: ...
def order_by_client_id(self, client_order_id) -> Order | None: ...
def open_orders(self) -> list[Order]: ...
def cancel(self, broker_order_id) -> Order: ...
~~~

All reads record observed_at. Map only valid broker cumulative fill data; a missing filled quantity or average price remains unknown, never zero. The fixture provider returns a deterministic current Quote.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/src/autotrader/providers/base.py engine/src/autotrader/providers/alpaca.py engine/src/autotrader/providers/fixtures.py engine/src/autotrader/execution.py engine/tests/test_alpaca.py engine/tests/test_execution.py
git commit -m "feat: normalize fresh paper broker snapshots"
~~~

### Task 3: Make RiskManager the atomic entry authority

**Files:**
- Modify: engine/src/autotrader/risk.py
- Modify: engine/tests/test_risk.py

- [ ] Step 1: Write failing admission and state-transition tests.

~~~python
def test_first_reservation_blocks_second_symbol_in_same_scan(risk, now):
    assert risk.reserve_entry("AAPL", 2, 100, 100_000, now).accepted
    assert risk.reserve_entry("MSFT", 2, 100, 100_000, now).reason == "max_positions"

def test_acknowledged_rejection_does_not_restore_session_budget(risk, now):
    reservation = risk.reserve_entry("AAPL", 2, 100, 100_000, now).reservation
    risk.bind_acknowledgement(reservation.client_order_id, "broker-1")
    risk.apply_terminal_order("broker-1", "rejected", 0, 0)
    assert risk.reserve_entry("MSFT", 2, 100, 100_000, now).reason == "max_entries_per_session"

def test_stale_or_halted_entry_is_rejected(risk, now):
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now - timedelta(seconds=121)).reason == "stale_quote"
    risk.begin_halt("daily_stop")
    assert risk.reserve_entry("AAPL", 1, 100, 100_000, now).reason == "risk_halted"
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_risk.py -q
~~~

Expected: FAIL because reservations, reason-coded rejections, and risk state do not exist.

- [ ] Step 3: Implement reserve_entry, bind_acknowledgement, apply_order_delta, release_terminal_remainder, begin_halt, latch_cutoff, and can_rearm. reserve_entry must mutate the reservation list before returning, count open plus pending plus reserved exposure, reject invalid/nonfinite/stale values, and reserve quantity times limit price. A missing/decreasing broker cumulative fill value moves state to HALTED.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/src/autotrader/risk.py engine/tests/test_risk.py
git commit -m "feat: reserve paper exposure atomically"
~~~

### Task 4: Persist risk and order intent atomically

**Files:**
- Modify: engine/src/autotrader/state.py
- Modify: engine/tests/test_state.py

- [ ] Step 1: Write failing persistence tests.

~~~python
def test_state_roundtrips_halt_and_pending_order(tmp_path):
    state = State(risk_state=RiskState.HALTING, pending_orders=[pending_order("entry-1")])
    StateStore(tmp_path).save_or_raise(state)
    assert StateStore(tmp_path).load().pending_orders[0].client_order_id == "entry-1"

def test_pre_submit_write_failure_is_signalled(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "replace", raise_os_error)
    with pytest.raises(StatePersistenceError):
        StateStore(tmp_path).save_or_raise(State())

def test_legacy_state_is_halted_until_reconciled(tmp_path):
    StateStore(tmp_path).path.write_text('{"positions": []}')
    assert StateStore(tmp_path).load().risk_state is RiskState.HALTED
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_state.py -q
~~~

Expected: FAIL because safety fields and save_or_raise are absent.

- [ ] Step 3: Add risk_state, halt_reason, session_id, session_entry_count, cutoff_latched, and pending_orders to State. Implement save_or_raise using a temporary file in the target directory, file flush/fsync, os.replace, and parent-directory fsync; clean the temporary file and raise StatePersistenceError on failure. Decode missing legacy risk fields as HALTED. Lifecycle code must use save_or_raise for every reservation and lifecycle transition.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/src/autotrader/state.py engine/tests/test_state.py
git commit -m "feat: persist paper safety state atomically"
~~~

### Task 5: Reconcile broker fills before changing positions or P&L

**Files:**
- Modify: engine/src/autotrader/runner.py
- Modify: engine/tests/test_runner.py

- [ ] Step 1: Write failing runner tests with a stateful fake executor.

~~~python
def test_runner_persists_reservation_before_limit_submission(runner, store):
    runner.run_once(["AAPL"])
    assert store.saved_states[0].pending_orders[0].client_order_id.startswith("entry-")
    assert runner.executor.limit_buys == [("AAPL", 2, 100.0)]

def test_pending_buy_is_not_an_open_position(runner):
    runner.run_once(["AAPL"])
    runner.reconcile_orders()
    assert runner.risk.positions == []

def test_repeated_partial_sell_snapshot_books_one_fill_delta(runner):
    runner.reconcile_orders()
    runner.reconcile_orders()
    assert [(trade.qty, trade.exit_price) for trade in runner.closed_trades] == [(2, 101.0)]
    assert runner.risk.positions[0].qty == 8
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_runner.py -q
~~~

Expected: FAIL because Runner submits market orders and books quote P&L immediately.

- [ ] Step 3: On a qualifying signal, obtain Quote, call reserve_entry, persist the reservation, submit_limit_buy, bind the acknowledgement, and persist again. A submit timeout retains the durable unknown-pending intent and does not retry.

Implement reconcile_orders(): compare broker cumulative filled quantity/notional with the persisted processed values, apply only a positive delta, persist the processed values, and process terminal remainders. Create a Position only from a confirmed buy delta. Create a ClosedTrade only from a confirmed sell delta; retain a cancelled remainder as an open position. Replace _close with durable deterministic exit intent plus submit_exit, without deleting a position or booking quote P&L.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/src/autotrader/runner.py engine/tests/test_runner.py
git commit -m "feat: reconcile paper fills before booking trades"
~~~

### Task 6: Coordinate startup reconciliation, cutoff, halt, and local re-arm

**Files:**
- Create: engine/src/autotrader/lifecycle.py
- Create: engine/tests/test_lifecycle.py
- Modify: engine/src/autotrader/main.py

- [ ] Step 1: Write failing lifecycle tests.

~~~python
def test_orphan_position_stays_halting_until_exit_is_terminal(lifecycle):
    lifecycle.startup_reconcile()
    assert lifecycle.risk.state is RiskState.HALTING
    assert lifecycle.executor.exit_requests == [("AAPL", 4)]
    assert lifecycle.can_scan is False

def test_cutoff_blocks_entry_even_when_exit_submission_fails(lifecycle, after_flatten):
    lifecycle.tick(after_flatten, ["AAPL"])
    assert lifecycle.risk.cutoff_latched is True
    assert lifecycle.executor.limit_buys == []

def test_rearm_requires_next_session_and_clean_two_way_reconciliation(lifecycle, next_day):
    lifecycle.risk.begin_halt("daily_stop")
    assert lifecycle.request_rearm(next_day) is False
    lifecycle.executor.resolve_all_orders_and_positions()
    assert lifecycle.request_rearm(next_day) is True
~~~

- [ ] Step 2: Confirm RED.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_lifecycle.py -q
~~~

Expected: FAIL because EngineLifecycle and local re-arm do not exist.

- [ ] Step 3: Implement EngineLifecycle.startup_reconcile() as a two-way comparison of persisted intents against broker orders and broker positions/orders against local records. An unmatched broker position or nonterminal order becomes an orphan: begin HALTING, generate its deterministic cancel/exit ID, and wait for broker-confirmed terminal/flat state. Submission is never reconciliation completion.

Implement tick(now, universe) to refresh timestamped snapshots, evaluate hard/daily stops, latch cutoff before exits, reconcile pending orders, and permit Runner.run_once only while ACTIVE, uncapped, fresh, and fully reconciled. Add local-only argparse flag --rearm in main.py; it invokes request_rearm only after a new session and clean reconciliation, never changes paper mode or profile. Continue publishing SharedState from lifecycle results.

- [ ] Step 4: Confirm GREEN with the Step 2 command.

- [ ] Step 5: Commit.

~~~bash
git add engine/src/autotrader/lifecycle.py engine/tests/test_lifecycle.py engine/src/autotrader/main.py
git commit -m "feat: halt paper engine until broker reconciliation"
~~~

### Task 7: Verify the complete safety boundary

**Files:**
- Modify only the exact implementation and test files required by a newly reproduced review finding.

- [ ] Step 1: Run the complete engine test suite.

~~~bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests -q
~~~

Expected: all tests pass; document pre-existing warnings separately.

- [ ] Step 2: Build the app and check the merge diff.

~~~bash
bash app/build-app.sh
git diff origin/main...HEAD --check
git diff --stat origin/main...HEAD
~~~

Expected: build passes, no whitespace errors, and only approved safety files changed.

- [ ] Step 3: Compare the implementation line-by-line to docs/specs/paper-trading-safety-foundation.md. Request spec-compliance review first, then code-quality review. For every finding, write a new focused failing test before production changes and repeat the affected review.

- [ ] Step 4: Commit verified review fixes.

~~~bash
git add engine/src/autotrader engine/tests
git commit -m "fix: close paper safety review findings"
~~~
