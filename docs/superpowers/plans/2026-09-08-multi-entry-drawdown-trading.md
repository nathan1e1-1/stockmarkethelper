# Multi-Entry Drawdown Trading Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second approved paper-trading profile, `multi-entry`, that allows up to 5 concurrent positions, unlimited entries per session (until a realized-loss gate trips), trades through drawdowns to market close, sizes positions risk-first, and replaces fixed stops with two independent exit checks per tick.

**Architecture:** A new `multi-entry` branch in `_validate_paper_profile` (the `initial` profile stays byte-for-byte intact). `RiskManager` learns risk-based `position_size`, a persisted `daily_realized_loss_pct` accumulator with an entry gate, and a `max_daily_risk_pct` reason. `ExitManager` keeps its legacy `evaluate` for `initial` and gains an unconditional `hard_stop`; a new `DynamicExitEvaluator` owns hold/exit/take-profit and never receives stop data. `Runner.manage_exits` runs the hard stop first (no veto), then the dynamic model. `EngineLifecycle.tick` drops the daily-stop halt under `multi-entry`. `/api/status` exposes the new metrics.

**Tech Stack:** Python 3.11+, pytest, existing `autotrader` package. Run all commands from `engine/`.

**Test command:** `.venv/bin/python -m pytest tests/<file>::<test> -q` (or file/path level). Full suite: `.venv/bin/python -m pytest -q`.

**Environment note:** Worktree/branch — follow execution-handoff; do not modify `initial`-profile behavior. `config/config.yaml` is the live engine config; the final task switches it to `multi-entry` deliberately.

**State baseline note:** Current `engine/state/state.json` is `halted` for session 2026-09-08 (expected fail-closed state). Tests use `tmp_path` stores, never the live directory.

---

### Task 1: Config — `multi-entry` profile validation + new fields

**Files:**
- Modify: `engine/src/autotrader/config.py`
- Modify: `engine/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_config.py`:

```python
def test_load_config_accepts_multi_entry_profile(tmp_path, monkeypatch):
    path = write_config(tmp_path, profile="multi-entry")
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    cfg = load_config(str(path))

    assert cfg.max_positions == 5
    assert cfg.risk_per_position_pct == 0.01
    assert cfg.max_daily_risk_pct == 0.05
    assert cfg.max_entries_per_session == sys.maxsize
    assert cfg.kill_switch_pct == 0.25
    assert cfg.stop_loss_pct == 0.05
    assert cfg.take_profit_pct == 0.05


@pytest.mark.parametrize(
    "risk_overrides",
    [
        {"max_positions": 4},
        {"max_entries_per_session": 10},
        {"max_snapshot_age_seconds": 1000},
        {"risk_per_position_pct": 0.02},
        {"risk_per_position_pct": 0.01, "max_daily_risk_pct": 0.05, "max_positions": 4},
        {"kill_switch_pct": 0.10},
    ],
)
def test_load_config_rejects_invalid_multi_entry_profile(tmp_path, monkeypatch, risk_overrides):
    path = write_config(tmp_path, profile="multi-entry", risk_overrides=risk_overrides)
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError):
        load_config(str(path))


def test_load_config_multi_entry_requires_single_shared_stop_distance(tmp_path, monkeypatch):
    path = write_config(
        tmp_path,
        profile="multi-entry",
        exit_overrides={"stop_loss_pct": 0.06},
    )
    monkeypatch.setenv("ALPACA_API_KEY", "pk_test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk_test")

    with pytest.raises(ValueError):
        load_config(str(path))
```

Update the helper in `engine/tests/test_config.py` so `write_config` accepts the new params (replace the existing `write_config`):

```python
def write_config(tmp_path, *, paper=True, risk_overrides=None, exit_overrides=None, profile="initial"):
    risk = {
        "profile": profile,
        "paper_capital": 100000.0,
        "max_position_pct": 0.0025,
        "max_gross_exposure_pct": 0.0025,
        "max_positions": 1,
        "max_entries_per_session": 1,
        "max_snapshot_age_seconds": 120,
        "kill_switch_pct": 0.10,
        "daily_loss_pct": 0.05,
    }
    if profile == "multi-entry":
        risk.update({
            "max_position_pct": 0.05,
            "max_gross_exposure_pct": 0.05,
            "max_positions": 5,
            "max_entries_per_session": sys.maxsize,
            "max_snapshot_age_seconds": 120,
            "risk_per_position_pct": 0.01,
            "max_daily_risk_pct": 0.05,
            "kill_switch_pct": 0.25,
        })
    risk.update(risk_overrides or {})
    exits = {
        "stop_loss_pct": 0.02 if profile == "initial" else 0.05,
        "take_profit_pct": 0.03 if profile == "initial" else 0.05,
        "flatten_at_close": True,
        "flatten_time": "15:55",
    }
    exits.update(exit_overrides or {})
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "alpaca": {"paper": paper},
                "ollama": {"base_url": "http://localhost:11434", "model": "llama3.2"},
                "risk": risk,
                "universe": {"size": 20, "min_price": 5.0, "min_volume": 500000},
                "loop": {"scan_interval_seconds": 60},
                "scoring": {"entry_threshold": 0.5, "weights": {"momentum": 0.6, "sentiment": 0.4}},
                "exits": exits,
            }
        )
    )
    return path
```

Add `import sys` at the top of `engine/tests/test_config.py` (next to the existing `import os`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL — attribute errors (`risk_per_position_pct`, `max_daily_risk_pct`, `max_entries_per_session`), and multi-entry load raises for the wrong reason (unapproved profile).

- [ ] **Step 3: Implement config changes**

Modify `engine/src/autotrader/config.py`:

Add imports at top:
```python
import math
import sys
```

Add the sentinel after `load_dotenv` import block, before the `Config` dataclass:
```python
UNLIMITED_ENTRIES = sys.maxsize
```

Add two fields to the `Config` dataclass (append after `max_entries_per_session: int`):
```python
    risk_per_position_pct: float | None = None
    max_daily_risk_pct: float | None = None
```

Replace `_validate_paper_profile` to branch by profile (keep `_positive_number`/`_positive_integer` as-is):

```python
def _validate_paper_profile(raw: dict) -> None:
    alpaca = raw.get("alpaca", {})
    if alpaca.get("paper") is not True:
        raise ValueError("paper trading must be enabled; live trading is not supported")

    risk = raw.get("risk", {})
    profile = risk.get("profile")
    if profile == "initial":
        _validate_initial_profile(risk)
        return
    if profile == "multi-entry":
        _validate_multi_entry_profile(risk, raw.get("exits", {}))
        return
    raise ValueError("risk.profile must be an approved paper profile (initial or multi-entry)")


def _validate_initial_profile(risk: dict) -> None:
    position_cap = _positive_number(risk.get("max_position_pct"), "max_position_pct")
    gross_cap = _positive_number(risk.get("max_gross_exposure_pct"), "max_gross_exposure_pct")
    max_positions = _positive_integer(risk.get("max_positions"), "max_positions")
    max_entries = _positive_integer(risk.get("max_entries_per_session"), "max_entries_per_session")
    max_snapshot_age = _positive_integer(risk.get("max_snapshot_age_seconds"), "max_snapshot_age_seconds")
    if (position_cap, gross_cap, max_positions, max_entries, max_snapshot_age) != (0.0025, 0.0025, 1, 1, 120):
        raise ValueError(
            "the initial paper profile requires max_position_pct=0.0025, "
            "max_gross_exposure_pct=0.0025, max_positions=1, "
            "max_entries_per_session=1, and max_snapshot_age_seconds=120"
        )
    if gross_cap < position_cap:
        raise ValueError("max_gross_exposure_pct must be at least max_position_pct")


def _validate_multi_entry_profile(risk: dict, exits: dict) -> None:
    max_positions = _positive_integer(risk.get("max_positions"), "max_positions")
    max_entries = _positive_integer(risk.get("max_entries_per_session"), "max_entries_per_session")
    max_snapshot_age = _positive_integer(risk.get("max_snapshot_age_seconds"), "max_snapshot_age_seconds")
    kill_switch = _positive_number(risk.get("kill_switch_pct"), "kill_switch_pct")
    risk_per_position = _positive_number(risk.get("risk_per_position_pct"), "risk_per_position_pct")
    max_daily_risk = _positive_number(risk.get("max_daily_risk_pct"), "max_daily_risk_pct")
    stop_loss = _positive_number(exits.get("stop_loss_pct"), "stop_loss_pct")
    take_profit = _positive_number(exits.get("take_profit_pct"), "take_profit_pct")

    if (max_positions, max_entries, max_snapshot_age) != (5, UNLIMITED_ENTRIES, 120):
        raise ValueError(
            "the multi-entry paper profile requires max_positions=5, "
            f"max_entries_per_session={UNLIMITED_ENTRIES}, and max_snapshot_age_seconds=120"
        )
    if not math.isclose(max_daily_risk, risk_per_position * max_positions, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("max_daily_risk_pct must equal risk_per_position_pct * max_positions")
    if not math.isclose(kill_switch, 0.25, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("the multi-entry paper profile requires kill_switch_pct=0.25")
    if not math.isclose(stop_loss, 0.05, rel_tol=1e-9, abs_tol=1e-9) or not math.isclose(take_profit, 0.05, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("the multi-entry paper profile requires stop_loss_pct=take_profit_pct=0.05 (single shared stop distance)")
```

Update `load_config` to read the new fields (after `max_entries_per_session=raw["risk"]["max_entries_per_session"],`):
```python
        risk_per_position_pct=raw["risk"].get("risk_per_position_pct"),
        max_daily_risk_pct=raw["risk"].get("max_daily_risk_pct"),
```

Note: `max_position_pct` and `max_gross_exposure_pct` remain required `Config` fields read from YAML (the multi-entry test helper supplies 0.05); they simply are not asserted on under the multi-entry validation.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS — all existing `initial` tests still green plus the new multi-entry tests. Then run the full engine suite: `.venv/bin/python -m pytest -q` (expected PASS; config.py change is additive).

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/config.py tests/test_config.py
git commit -m "feat: add multi-entry paper profile validation with risk-based caps"
```

---

### Task 2: State — persist `daily_realized_loss_pct`

**Files:**
- Modify: `engine/src/autotrader/state.py`
- Modify: `engine/tests/test_state.py`

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_state.py`:

```python
def test_state_roundtrips_daily_realized_loss(tmp_path):
    store = StateStore(tmp_path)
    store.save(State(daily_realized_loss_pct=0.03))
    loaded = store.load()
    assert loaded.daily_realized_loss_pct == 0.03


def test_state_load_defaults_daily_realized_loss_to_zero(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({
        "risk_state": "active", "halt_reason": None,
        "session_id": "2026-09-01", "session_entry_count": 0,
        "cutoff_latched": False, "reservations": [], "pending_orders": [],
    }))
    loaded = store.load()
    assert loaded.daily_realized_loss_pct == 0.0


def test_state_rejects_negative_daily_realized_loss(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({
        "risk_state": "active", "halt_reason": None,
        "session_id": "2026-09-01", "session_entry_count": 0,
        "cutoff_latched": False, "reservations": [], "pending_orders": [],
        "daily_realized_loss_pct": -0.01,
    }))
    loaded = store.load()
    assert loaded.risk_state is RiskState.HALTED
```

Note: `RiskState` is already imported in `test_state.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_state.py -q`
Expected: FAIL — `State` has no attribute `daily_realized_loss_pct`.

- [ ] **Step 3: Implement state changes**

Modify `engine/src/autotrader/state.py`:

Add the field to the `State` dataclass (after `pending_orders`):
```python
    daily_realized_loss_pct: float = 0.0
```

In `_decode_safety_state`, after `base.pending_orders = [_decode_order(item) for item in pending_orders]`, add:
```python
        daily_realized_loss = raw.get("daily_realized_loss_pct", 0.0)
        if not _nonnegative_finite_number(daily_realized_loss):
            raise ValueError("daily realized loss must be finite and nonnegative")
        base.daily_realized_loss_pct = daily_realized_loss
```

In `_halted_state`, reset the counter after `state.pending_orders = []`:
```python
    state.daily_realized_loss_pct = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/state.py tests/test_state.py
git commit -m "feat: persist daily_realized_loss_pct in safety state"
```

---

### Task 3: Risk — risk-based sizing, realized-loss gate, restore/rearm

**Files:**
- Modify: `engine/src/autotrader/risk.py`
- Modify: `engine/tests/test_risk.py`

Note: `test_risk.py` imports `RiskState`/`Order`/`Position`/`Reservation`/`Side` and defines `InitialPaperCfg` + fixtures `now` and `risk`. Keep those; add the multi-entry config in this task.

- [ ] **Step 1: Write failing tests**

Add `import sys` at the top of `engine/tests/test_risk.py` (near the existing imports).

Append to `engine/tests/test_risk.py`:

```python
@dataclass
class MultiEntryPaperCfg(InitialPaperCfg):
    max_position_pct: float = 0.05
    max_gross_exposure_pct: float = 0.05
    max_positions: int = 5
    max_entries_per_session: int = sys.maxsize
    kill_switch_pct: float = 0.25
    risk_per_position_pct: float | None = 0.01
    max_daily_risk_pct: float | None = 0.05
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.05


@pytest.fixture
def multi_risk(now):
    return RiskManager(MultiEntryPaperCfg(), clock=lambda: now, session_id="2026-09-01")


def test_risk_based_position_size_uses_shared_stop_distance(now):
    rm = RiskManager(MultiEntryPaperCfg(), clock=lambda: now, session_id="2026-09-01")

    assert rm.position_size("AAPL", price=100.0, equity=100_000.0) == 20  # 1% risk / 5% stop -> 20k budget
    assert rm.position_size("AAPL", price=200.0, equity=100_000.0) == 10


def test_risk_based_sizing_returns_zero_for_zero_or_nonpositive_inputs(multi_risk):
    assert multi_risk.position_size("AAPL", price=0, equity=100_000.0) == 0
    assert multi_risk.position_size("AAPL", price=100.0, equity=0) == 0


def test_multi_entry_accepts_five_concurrent_slots_and_then_blocks(multi_risk, now):
    for ticker in ("A", "B", "C", "D", "E"):
        admission = multi_risk.reserve_entry(ticker, 20, 100.0, 100_000.0, now)
        assert admission.accepted, admission.reason
    blocked = multi_risk.reserve_entry("F", 20, 100.0, 100_000.0, now)
    assert blocked.accepted is False
    assert blocked.reason == "max_positions"


def test_multi_entry_notional_cap_tracks_risk_budget(multi_risk, now):
    budget = 100_000.0 * 0.01 / 0.05  # 20_000
    over = multi_risk.reserve_entry("AAPL", 201, 100.0, 100_000.0, now)
    assert over.accepted is False
    assert over.reason == "max_position_exposure"
    ok = multi_risk.reserve_entry("AAPL", 200, 100.0, 100_000.0, now)
    assert ok.accepted
    assert ok.reservation.qty == 200.0


def test_realized_loss_accumulates_and_gate_blocks_new_entries(multi_risk, now):
    multi_risk.record_realized_loss(1_000.0)  # 1% of 100k day_start
    assert multi_risk.daily_realized_loss_pct == pytest.approx(0.01)
    assert multi_risk.reserve_entry("AAPL", 20, 100.0, 100_000.0, now).accepted

    multi_risk.record_realized_loss(4_000.0)  # 5% total
    blocked = multi_risk.reserve_entry("MSFT", 20, 100.0, 100_000.0, now)
    assert blocked.accepted is False
    assert blocked.reason == "max_daily_risk_pct"


def test_realized_loss_gate_does_not_apply_to_initial_profile(now, risk):
    risk.record_realized_loss(99_000.0)
    blocked = risk.reserve_entry("AAPL", 1, 100.0, 100_000.0, now)
    assert blocked.reason != "max_daily_risk_pct"


def test_record_realized_loss_rejects_invalid_values(multi_risk, now):
    assert multi_risk.record_realized_loss(-1.0) is False
    assert multi_risk.record_realized_loss(float("nan")) is False
    assert multi_risk.state is RiskState.HALTING


def test_restore_persists_and_validates_daily_realized_loss(now):
    restored = RiskManager(MultiEntryPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert restored.restore_persisted_safety_state(
        positions=[], reservations=[], pending_orders=[], risk_state=RiskState.ACTIVE,
        halt_reason=None, session_id="2026-09-01", session_entry_count=0,
        cutoff_latched=False, daily_realized_loss_pct=0.03,
    ) is True
    assert restored.daily_realized_loss_pct == 0.03
    assert restored.reserve_entry("AAPL", 20, 100.0, 100_000.0, now).accepted

    bad = RiskManager(MultiEntryPaperCfg(), clock=lambda: now, session_id="2026-09-01")
    assert bad.restore_persisted_safety_state(
        positions=[], reservations=[], pending_orders=[], risk_state=RiskState.ACTIVE,
        halt_reason=None, session_id="2026-09-01", session_entry_count=0,
        cutoff_latched=False, daily_realized_loss_pct=-0.01,
    ) is False


def test_rearm_clears_daily_realized_loss(now):
    clock = [now + timedelta(days=1)]
    rm = RiskManager(MultiEntryPaperCfg(), clock=lambda: clock[0], session_id="2026-09-01")
    rm.record_realized_loss(5_000.0)
    rm.begin_halt("daily_stop")
    assert rm.complete_halt(clean_reconciliation=True) is True
    assert rm.rearm("2026-09-02", clean_reconciliation=True) is True
    assert rm.daily_realized_loss_pct == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_risk.py -q`
Expected: FAIL — `position_size` returns flat-cap qty (2), `record_realized_loss` missing, `daily_realized_loss_pct` missing, `restore_persisted_safety_state` has no such arg.

- [ ] **Step 3: Implement risk changes**

Modify `engine/src/autotrader/risk.py`:

Add `import sys` at top (after `import math`, unused for now; keep for symmetry with config sentinel — note `risk.py` itself does not need `sys`; skip adding it if nothing uses it. If unused, omit).

Add attribute in `__init__` after `self.cutoff_latched = False`:
```python
        self.daily_realized_loss_pct = 0.0
```

Rewrite `position_size` (lines ~93-99):
```python
    def position_size(self, ticker: str, price: float, equity: float) -> int:
        if not self._positive(price) or not self._positive(equity):
            return 0
        rpp = getattr(self.cfg, "risk_per_position_pct", None)
        if rpp is not None:
            budget = (equity * rpp) / getattr(self.cfg, "stop_loss_pct", 1.0)
        else:
            budget = equity * getattr(self.cfg, "max_position_pct", 0.0)
        if not self._positive(budget):
            return 0
        return max(0, math.floor(budget / price))
```

Add `_daily_risk_gate_tripped` helper (place near `_position_count`):
```python
    def _daily_risk_gate_tripped(self) -> bool:
        rpp = getattr(self.cfg, "risk_per_position_pct", None)
        maximum = getattr(self.cfg, "max_daily_risk_pct", None)
        if rpp is None or maximum is None:
            return False
        return self.daily_realized_loss_pct >= maximum
```

Update `can_enter` to include the gate (extend the `and` chain after `and not self._has_ticker(ticker)`):
```python
                and not self._has_ticker(ticker)
                and not self._daily_risk_gate_tripped()
```

In `_reserve_entry`, branch the exposure checks. Replace the current block:
```python
        notional = qty * limit_price
        if not self._positive(notional):
            return Admission(reason="invalid_input")
        if notional > equity * self.cfg.max_position_pct:
            return Admission(reason="max_position_exposure")
        if self.gross_exposure_notional + notional > equity * self.cfg.max_gross_exposure_pct:
            return Admission(reason="max_gross_exposure")
        if self.session_entry_count >= self.cfg.max_entries_per_session:
            return Admission(reason="max_entries_per_session")
```
with:
```python
        if self._daily_risk_gate_tripped():
            return Admission(reason="max_daily_risk_pct")
        notional = qty * limit_price
        if not self._positive(notional):
            return Admission(reason="invalid_input")
        rpp = getattr(self.cfg, "risk_per_position_pct", None)
        if rpp is not None:
            budget = (equity * rpp) / getattr(self.cfg, "stop_loss_pct", 1.0)
            if notional > budget:
                return Admission(reason="max_position_exposure")
        else:
            if notional > equity * self.cfg.max_position_pct:
                return Admission(reason="max_position_exposure")
            if self.gross_exposure_notional + notional > equity * self.cfg.max_gross_exposure_pct:
                return Admission(reason="max_gross_exposure")
        if self.session_entry_count >= self.cfg.max_entries_per_session:
            return Admission(reason="max_entries_per_session")
```

Add `record_realized_loss` (place after `daily_stop_triggered`):
```python
    @_synchronized
    def record_realized_loss(self, loss: float) -> bool:
        if isinstance(loss, bool) or not isinstance(loss, (int, float)) or not math.isfinite(loss) or loss < 0:
            self.begin_halt("invalid_realized_loss")
            return False
        if not self._positive(self.day_start_equity):
            self.begin_halt("invalid_equity")
            return False
        self.daily_realized_loss_pct += loss / self.day_start_equity
        return True
```

Extend `restore_persisted_safety_state`:
- Signature: add parameter `daily_realized_loss_pct: float = 0.0` after `cutoff_latched`.
- Validation: extend the `or` chain with:
```python
            or isinstance(daily_realized_loss_pct, bool)
            or not isinstance(daily_realized_loss_pct, (int, float))
            or not math.isfinite(daily_realized_loss_pct)
            or daily_realized_loss_pct < 0
```
- Assignment: after `self.cutoff_latched = cutoff_latched`:
```python
        self.daily_realized_loss_pct = daily_realized_loss_pct
```

Reset in `rearm` (after `self.cutoff_latched = False`):
```python
        self.daily_realized_loss_pct = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_risk.py -q`
Expected: PASS. Then full engine suite: `.venv/bin/python -m pytest -q` (PASS; additions are guarded by `getattr` so `initial` mocks are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/risk.py tests/test_risk.py
git commit -m "feat: risk-based sizing and daily realized-loss entry gate"
```

---

### Task 4: Exits — hard stop + dynamic evaluator

**Files:**
- Modify: `engine/src/autotrader/exits.py`
- Modify: `engine/tests/test_exits.py`

- [ ] **Step 1: Write failing tests**

Replace the contents of `engine/tests/test_exits.py`:

```python
from autotrader.exits import DynamicExitEvaluator, ExitManager
from autotrader.models import Position, Signal


def pos(entry):
    return Position(ticker="AAPL", qty=10.0, avg_entry_price=entry)


def test_legacy_evaluate_stop_loss():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 97.9) == "stop_loss"


def test_legacy_evaluate_take_profit():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 103.1) == "take_profit"


def test_legacy_evaluate_no_trigger_between():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 101.0) is None


def test_legacy_evaluate_boundary_stop_exact():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(100.0), 98.0) == "stop_loss"


def test_legacy_evaluate_zero_entry_no_trigger():
    em = ExitManager(stop_loss_pct=0.02, take_profit_pct=0.03)
    assert em.evaluate(pos(0.0), 50.0) is None


def test_hard_stop_is_unconditional_at_shared_distance():
    em = ExitManager(stop_loss_pct=0.05, take_profit_pct=0.05)
    assert em.hard_stop(pos(100.0), 95.0) == "stop_loss"
    assert em.hard_stop(pos(100.0), 95.01) is None


def test_hard_stop_zero_entry_no_trigger():
    em = ExitManager(stop_loss_pct=0.05, take_profit_pct=0.05)
    assert em.hard_stop(pos(0.0), 50.0) is None


class FakeMomentum:
    def __init__(self, detail):
        self.detail = detail

    def compute(self, ticker, bars):
        return Signal(name="momentum", value=0.5, detail=self.detail)


class FakeSentiment:
    def __init__(self, value):
        self.value = value

    def compute(self, ticker, news):
        return Signal(name="sentiment", value=self.value, detail={})


class FakeProvider:
    def __init__(self, bars=None, news=None):
        self.bars = bars or []
        self.news = news or []

    def scan_bars(self, ticker):
        return self.bars

    def news(self, ticker, limit=5):
        return self.news


def make_evaluator(detail, sentiment_value=None, bars=None, news=None, boom=False):
    if boom:
        class BoomProvider(FakeProvider):
            def scan_bars(self, ticker):
                raise TimeoutError("ollama unavailable")
        provider = BoomProvider()
    else:
        provider = FakeProvider(bars=bars, news=news)
    sentiment = FakeSentiment(sentiment_value) if sentiment_value is not None else None
    return DynamicExitEvaluator(
        take_profit_pct=0.05,
        provider=provider,
        momentum=FakeMomentum(detail),
        sentiment=sentiment,
    ), provider


def test_dynamic_holds_dip_while_uptrend_intact():
    de, _ = make_evaluator({"sma_short": 102.0, "sma_long": 100.0}, sentiment_value=0.8)
    assert de.decide(pos(100.0), 96.0) is None


def test_dynamic_exit_early_on_trend_break_and_negative_sentiment():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=-0.5)
    assert de.decide(pos(100.0), 97.0) == "exit_early"


def test_dynamic_holds_when_trend_down_but_sentiment_neutral():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=0.0)
    assert de.decide(pos(100.0), 97.0) is None


def test_dynamic_take_profit_at_target_when_trend_faded():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0}, sentiment_value=-0.5)
    assert de.decide(pos(100.0), 105.5) == "take_profit"


def test_dynamic_evaluator_failure_resolves_to_hold():
    de, provider = make_evaluator({}, boom=True)
    assert de.decide(pos(100.0), 96.0) is None


def test_dynamic_evaluator_without_sentiment_treats_value_as_zero():
    de, _ = make_evaluator({"sma_short": 98.0, "sma_long": 100.0})
    assert de.decide(pos(100.0), 97.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_exits.py -q`
Expected: FAIL — `DynamicExitEvaluator` and `hard_stop` missing.

- [ ] **Step 3: Implement exit changes**

Replace the contents of `engine/src/autotrader/exits.py`:

```python
from autotrader.signals.momentum import MomentumSignal


class ExitManager:
    def __init__(self, stop_loss_pct: float, take_profit_pct: float):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def evaluate(self, position, current_price: float) -> str | None:
        """Legacy initial-profile exit: fixed stop-loss then fixed take-profit."""
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        pct = current_price / entry - 1.0
        if pct <= -self.stop_loss_pct:
            return "stop_loss"
        if pct >= self.take_profit_pct:
            return "take_profit"
        return None

    def hard_stop(self, position, current_price: float) -> str | None:
        """Unconditional hard stop-loss at the shared stop distance; no signal can veto it."""
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        if current_price <= entry * (1.0 - self.stop_loss_pct):
            return "stop_loss"
        return None


class DynamicExitEvaluator:
    """Decides hold / exit_early / take_profit from trend, regime, and sentiment.

    Structurally independent of the hard stop: this evaluator never receives the
    stop price or stop-loss configuration, so it cannot veto or modify the
    unconditional stop-loss check. Any raised exception resolves to a no-op hold.
    """

    def __init__(self, take_profit_pct: float, provider, momentum=None, regime=None, sentiment=None):
        self.take_profit_pct = take_profit_pct
        self.provider = provider
        self.momentum = momentum or MomentumSignal()
        self.regime = regime
        self.sentiment = sentiment

    def decide(self, position, current_price: float) -> str | None:
        try:
            momentum = self.momentum.compute(position.ticker, self.provider.scan_bars(position.ticker))
            sma_short = momentum.detail.get("sma_short")
            sma_long = momentum.detail.get("sma_long")
            uptrend = isinstance(sma_short, (int, float)) and isinstance(sma_long, (int, float)) and sma_short > sma_long
            sentiment_value = 0.0
            if self.sentiment is not None:
                news = self.provider.news(position.ticker, limit=5)
                sentiment_value = self.sentiment.compute(position.ticker, news).value
            entry = position.avg_entry_price
            if entry <= 0 or current_price <= 0:
                return None
            pct = current_price / entry - 1.0
            if pct >= self.take_profit_pct and not uptrend:
                return "take_profit"
            if not uptrend and sentiment_value < 0.0:
                return "exit_early"
            return None  # hold: dip with intact trend stays open
        except Exception:
            return None  # no-op hold; the hard stop still covers downside
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_exits.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/exits.py tests/test_exits.py
git commit -m "feat: two-check exit model (unconditional hard stop + dynamic hold/exit)"
```

---

### Task 5: Runner — split exit passes, wire dynamic evaluator, feed realized loss

**Files:**
- Modify: `engine/src/autotrader/runner.py`
- Modify: `engine/tests/test_runner.py`

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_runner.py`:

```python
import sys
from autotrader.exits import DynamicExitEvaluator
from autotrader.models import Signal


class FakeMomentum:
    def __init__(self, detail):
        self.detail = detail

    def compute(self, ticker, bars):
        return Signal(name="momentum", value=0.5, detail=self.detail)


class FakeSentiment:
    def __init__(self, value):
        self.value = value

    def compute(self, ticker, news):
        return Signal(name="sentiment", value=self.value, detail={})


@dataclass
class MultiCfg(PaperCfg):
    max_position_pct: float = 0.05
    max_gross_exposure_pct: float = 0.05
    max_positions: int = 5
    max_entries_per_session: int = sys.maxsize
    kill_switch_pct: float = 0.25
    risk_per_position_pct: float | None = 0.01
    max_daily_risk_pct: float | None = 0.05
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.05
    risk_profile: str = "multi-entry"


def make_multi_runner():
    cfg = MultiCfg()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-01")
    store = RecordingStore()
    executor = FillExec()
    runner = Runner(
        provider=FreshProvider(), agent=BuyAgent(), executor=executor, risk=risk, cfg=cfg,
        state_store=store, clock=lambda: NOW,
    )
    runner.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="2026-09-01")
    return runner, risk, executor, store


def test_manage_exits_runs_hard_stop_first_and_skips_dynamic_for_stopped(monkeypatch):
    runner, risk, _, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    calls = []
    original = runner.provider.scan_bars
    runner.provider.scan_bars = lambda ticker: calls.append(ticker) or original(ticker)

    class StopProvider(PriceProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=94.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = StopProvider(94.0)
    runner.dynamic_exit = DynamicExitEvaluator(take_profit_pct=0.05, provider=runner.provider)

    runner.manage_exits()

    assert runner.pending_orders[0].client_order_id.startswith("exit-2026-09-01-AAPL-stop_loss")
    assert calls == []


def test_manage_exits_hold_from_dynamic_leaves_position_open():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    class DipProvider(PriceProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=96.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = DipProvider(96.0)
    runner.dynamic_exit = DynamicExitEvaluator(
        take_profit_pct=0.05, provider=runner.provider,
        momentum=FakeMomentum({"sma_short": 102.0, "sma_long": 100.0}),
    )

    runner.manage_exits()

    assert runner.pending_orders == []
    assert executor.exit_requests == []


def test_dynamic_early_exit_closes_position():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]

    class EarlyProvider(PriceProvider):
        def latest_quote(self, ticker, *, now=None):
            from autotrader.models import Quote
            return Quote(ticker=ticker, price=97.0, source_timestamp=now or NOW, observed_at=now or NOW)
    runner.provider = EarlyProvider(97.0)
    runner.dynamic_exit = DynamicExitEvaluator(
        take_profit_pct=0.05, provider=runner.provider,
        momentum=FakeMomentum({"sma_short": 98.0, "sma_long": 100.0}),
        sentiment=FakeSentiment(-0.5),
    )

    runner.manage_exits()

    assert runner.pending_orders[0].client_order_id.endswith("-exit_early")


def test_stop_loss_fill_increments_daily_realized_loss():
    runner, risk, executor, _ = make_multi_runner()
    risk.positions = [Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0, opened_at=NOW)]
    runner._close(risk.positions[0], price=1.0, reason="stop_loss")
    executor.orders["sell-1"] = Order(
        id="sell-1", ticker="AAPL", side=Side.SELL, qty=10, status="filled",
        client_order_id=runner.pending_orders[0].client_order_id,
        filled_qty=10, filled_notional=940.0, filled_avg_price=94.0,
        observed_at=NOW, timestamp=NOW,
    )

    runner.reconcile_orders()

    assert risk.daily_realized_loss_pct == pytest.approx(60.0 / 100_000.0)  # (100-94)*10 / day_start
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_runner.py -q`
Expected: FAIL — `runner.dynamic_exit` attribute missing and `manage_exits` does not feed realized loss + no split passes.

- [ ] **Step 3: Implement runner changes**

Modify `engine/src/autotrader/runner.py`:

Add import at top:
```python
from autotrader.exits import DynamicExitEvaluator, ExitManager
```

Replace the import line `from autotrader.exits import ExitManager` (already present) with the combined import above.

In `__init__`, replace:
```python
        self.exit_manager = ExitManager(cfg.stop_loss_pct, cfg.take_profit_pct) if cfg else None
```
with:
```python
        self.exit_manager = ExitManager(cfg.stop_loss_pct, cfg.take_profit_pct) if cfg else None
        self.dynamic_exit = None
        if cfg is not None and getattr(cfg, "risk_profile", "initial") == "multi-entry":
            self.dynamic_exit = DynamicExitEvaluator(
                take_profit_pct=cfg.take_profit_pct,
                provider=provider,
                momentum=self.momentum,
                sentiment=self.sentiment,
            )
```

Replace `manage_exits`' position loop (lines ~264-270):
```python
            for pos in list(self.risk.positions):
                price = self._exit_decision_price(pos.ticker)
                if price is None:
                    return
                reason = self.exit_manager.evaluate(pos, price)
                if reason:
                    self._close(pos, price, reason)
```
with:
```python
            for pos in list(self.risk.positions):
                price = self._exit_decision_price(pos.ticker)
                if price is None:
                    return
                if self.dynamic_exit is not None:
                    stop_reason = self.exit_manager.hard_stop(pos, price)
                    if stop_reason:
                        self._close(pos, price, stop_reason)
                    else:
                        dynamic_reason = self.dynamic_exit.decide(pos, price)
                        if dynamic_reason:
                            self._close(pos, price, dynamic_reason)
                else:
                    reason = self.exit_manager.evaluate(pos, price)
                    if reason:
                        self._close(pos, price, reason)
```

In `_book_sell_fill`, feed realized loss to risk. The function already computes `realized_pnl = (exit_price - position.avg_entry_price) * qty` and appends to `self.closed_trades`. After the `remaining = position.qty - qty` block (end of `_book_sell_fill`), add before `return True`:
```python
        if realized_pnl < 0:
            record = getattr(self.risk, "record_realized_loss", None)
            if callable(record):
                record(-realized_pnl)
        return True
```
Note: the risk `record_realized_loss` is only present on `RiskManager`; the `FakeRisk` in earlier tests uses a duck-typed `getattr` guard, so failed returns do not halt there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_runner.py -q`
Expected: PASS. Then full suite: `.venv/bin/python -m pytest -q` (PASS).

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/runner.py tests/test_runner.py
git commit -m "feat: split exit passes into hard stop + dynamic; feed realized loss to risk"
```

---

### Task 6: Lifecycle — drop daily-stop halt under `multi-entry`

**Files:**
- Modify: `engine/src/autotrader/lifecycle.py`
- Modify: `engine/tests/test_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_lifecycle.py`:

```python
import sys


class MultiEntryConfig(Config):
    max_position_pct = 0.05
    max_gross_exposure_pct = 0.05
    max_positions = 5
    max_entries_per_session = sys.maxsize
    kill_switch_pct = 0.25
    daily_loss_pct = 0.05
    stop_loss_pct = 0.05
    take_profit_pct = 0.05
    risk_per_position_pct = 0.01
    max_daily_risk_pct = 0.05
    risk_profile = "multi-entry"


def test_multi_entry_tick_keeps_trading_when_equity_above_daily_stop():
    cfg = MultiEntryConfig()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-02")
    executor = Executor()
    store = Store()
    runner = Runner(Provider(), None, executor, risk, cfg, state_store=store, clock=lambda: NOW)
    runner.equity = Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02")
    engine = EngineLifecycle(cfg, executor, risk, runner, store, clock=lambda: NOW)

    assert engine.startup_reconcile() is True
    # 94k < day_start*(1-0.05)=95k: daily-stop band; multi-entry must NOT halt on it.
    executor.equity = 94_000.0
    runner.run_once = lambda universe: None
    assert engine.tick(datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc), ["AAPL"]) is True
    assert risk.state is RiskState.ACTIVE


def test_multi_entry_tick_hard_stop_floor_still_halts():
    cfg = MultiEntryConfig()
    risk = RiskManager(cfg, clock=lambda: NOW, session_id="2026-09-02")
    executor = Executor()
    store = Store()
    runner = Runner(Provider(), None, executor, risk, cfg, state_store=store, clock=lambda: NOW)
    runner.equity = Equity(100_000.0, 100_000.0, 100_000.0, "2026-09-02")
    engine = EngineLifecycle(cfg, executor, risk, runner, store, clock=lambda: NOW)

    assert engine.startup_reconcile() is True
    executor.equity = 74_000.0  # <= 100k*(1-0.25)
    runner.run_once = lambda universe: None
    engine.tick(datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc), ["AAPL"])
    assert risk.state is not RiskState.ACTIVE
```

Note: existing imports already include `sys`-related need; add `import sys` at top of `test_lifecycle.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lifecycle.py -q`
Expected: FAIL — `test_multi_entry_tick_keeps_trading_when_equity_above_daily_stop` halts (daily stop triggers), `test_multi_entry_tick_hard_stop_floor_still_halts` passes spuriously.

- [ ] **Step 3: Implement lifecycle changes**

Modify `engine/src/autotrader/lifecycle.py`, in `tick`, replace:
```python
        if self.risk.hard_stop_triggered(equity) or self.risk.daily_stop_triggered(equity):
            self._persist_or_halt("halt_persistence_failure")
            self._reconcile_and_cleanup()
            return False
```
with:
```python
        if self.risk.hard_stop_triggered(equity):
            self._persist_or_halt("halt_persistence_failure")
            self._reconcile_and_cleanup()
            return False
        if getattr(self.cfg, "risk_profile", "initial") != "multi-entry" and self.risk.daily_stop_triggered(equity):
            self._persist_or_halt("halt_persistence_failure")
            self._reconcile_and_cleanup()
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lifecycle.py -q`
Expected: PASS. Existing tests (`test_...daily_stop...`) run under the default `Config` (risk_profile "initial" via `getattr` default) and keep passing. Full suite: `.venv/bin/python -m pytest -q` (PASS).

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/lifecycle.py tests/test_lifecycle.py
git commit -m "feat: disable daily-stop halt for multi-entry; keep hard-stop floor"
```

---

### Task 7: IPC — expose realized-loss metrics in `/api/status`

**Files:**
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write failing tests**

Append to `engine/tests/test_ipc.py`:

```python
from autotrader.risk import RiskManager


class StatusRiskCfg:
    max_positions = 5
    max_entries_per_session = 10**9
    risk_per_position_pct = 0.01
    max_daily_risk_pct = 0.05
    stop_loss_pct = 0.05
    take_profit_pct = 0.05
    kill_switch_pct = 0.25
    daily_loss_pct = 0.05
    paper_capital = 100_000.0
    max_position_pct = 0.05
    max_gross_exposure_pct = 0.05
    max_snapshot_age_seconds = 120


def _status_risk():
    return RiskManager(StatusRiskCfg(), clock=lambda: datetime.now(timezone.utc), session_id="2026-09-02")


def test_status_exposes_daily_realized_loss_and_slots():
    state = SharedState()
    state.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="d")
    state.risk = _status_risk()
    state.risk.record_realized_loss(2_000.0)
    client = TestClient(create_app(state))
    body = client.get("/api/status").json()
    assert body["daily_realized_loss_pct"] == pytest.approx(0.02)
    assert body["daily_risk_gate_tripped"] is False
    assert body["open_slots"] == 5


def test_status_daily_risk_gate_tripped_blocks_entries():
    state = SharedState()
    state.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="d")
    state.risk = _status_risk()
    state.risk.record_realized_loss(5_000.0)
    client = TestClient(create_app(state))
    body = client.get("/api/status").json()
    assert body["daily_risk_gate_tripped"] is True
    assert body["open_slots"] == 5


def test_status_without_risk_reports_nulls():
    state = SharedState()
    state.equity = Equity(equity=100_000.0, day_start_equity=100_000.0, peak_equity=100_000.0, day="d")
    client = TestClient(create_app(state))
    body = client.get("/api/status").json()
    assert body["daily_realized_loss_pct"] is None
    assert body["daily_risk_gate_tripped"] is None
    assert body["open_slots"] is None
```

Add `import pytest` and `from autotrader.risk import RiskManager` if not already present at the top of `test_ipc.py`. `RiskManager` import: add at top with the other autotrader imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ipc.py -q`
Expected: FAIL — keys absent from `/api/status` response.

- [ ] **Step 3: Implement ipc changes**

Modify `engine/src/autotrader/ipc.py`, in `create_app`, in the `status()` body, add keys after `daily_stop`:

```python
            "daily_realized_loss_pct": state.risk.daily_realized_loss_pct if state.risk else None,
            "daily_risk_gate_tripped": state.risk._daily_risk_gate_tripped() if state.risk else None,
            "open_slots": max(0, state.risk.cfg.max_positions - state.risk._position_count()) if state.risk else None,
```

Use a public accessor for the gate to avoid reaching into a private helper — add to `RiskManager` (in `risk.py`, placed after `daily_stop_triggered`):

```python
    @_synchronized
    def daily_risk_gate_tripped(self) -> bool:
        return self._daily_risk_gate_tripped()

    @_synchronized
    def open_position_slots(self) -> int:
        slots = self.cfg.max_positions - self._position_count()
        return max(0, slots)
```

Then in `ipc.py` status body reference the public methods:

```python
            "daily_realized_loss_pct": state.risk.daily_realized_loss_pct if state.risk else None,
            "daily_risk_gate_tripped": state.risk.daily_risk_gate_tripped() if state.risk else None,
            "open_slots": state.risk.open_position_slots() if state.risk else None,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ipc.py -q`
Expected: PASS. Full suite: `.venv/bin/python -m pytest -q` (PASS).

- [ ] **Step 5: Commit**

```bash
git add src/autotrader/ipc.py src/autotrader/risk.py tests/test_ipc.py
git commit -m "feat: expose daily realized loss and open slots in /api/status"
```

---

### Task 8: Live config — switch engine profile to `multi-entry` + full verification

**Files:**
- Modify: `engine/config/config.yaml`
- Test reference: `engine/tests/test_config.py` for a guarded live-config check

- [ ] **Step 1: Verify intent with the human (checkpoint)**

Before touching the live engine config, confirm with the user that switching `engine/config/config.yaml` to `multi-entry` is intended (it changes what the running engine does from the next launch).

- [ ] **Step 2: Update the live config**

Replace `engine/config/config.yaml`:

```yaml
alpaca:
  paper: true
ollama:
  base_url: "http://localhost:11434"
  model: "llama3.2"
risk:
  profile: multi-entry
  paper_capital: 100000.0
  max_position_pct: 0.05
  max_gross_exposure_pct: 0.05
  max_positions: 5
  max_entries_per_session: 9223372036854775807
  max_snapshot_age_seconds: 120
  risk_per_position_pct: 0.01
  max_daily_risk_pct: 0.05
  kill_switch_pct: 0.25
  daily_loss_pct: 0.05
universe:
  size: 20
  min_price: 5.0
  min_volume: 500000
loop:
  scan_interval_seconds: 60
scoring:
  entry_threshold: 0.3
  weights:
    momentum: 0.6
    sentiment: 0.4
exits:
  stop_loss_pct: 0.05
  take_profit_pct: 0.05
  flatten_at_close: true
  flatten_time: "15:55"
```

(9223372036854775807 is `sys.maxsize` on macOS 64-bit — matches `UNLIMITED_ENTRIES`. Verify with `python3 -c "import sys; print(sys.maxsize)"`.)

- [ ] **Step 3: Add a guarded live-config validation test**

Append to `engine/tests/test_config.py`:

```python
def test_live_config_yaml_uses_an_approved_profile():
    from pathlib import Path

    repo_config = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
    assert repo_config.exists(), "repo config.yaml must exist for the live engine"
    with open(repo_config) as fh:
        raw = yaml.safe_load(fh)
    assert raw["risk"]["profile"] in {"initial", "multi-entry"}
```

The canonical validation is running `load_config` against the repo config — do this from `engine/`:

Run: `cd engine && .venv/bin/python -c "from autotrader.config import load_config; c=load_config('config/config.yaml'); print(c.risk_profile, c.max_positions, c.risk_per_position_pct, c.max_daily_risk_pct, c.stop_loss_pct)"`
Expected: `multi-entry 5 0.01 0.05 0.05`

If `load_config` raises (e.g. env keys missing during CI), the loader itself performs the profile validation — a ValueError about `risk.profile must be an approved paper profile` is the guard. The unit test above covers the YAML surface without requiring secrets.

- [ ] **Step 4: Full test suite**

Run from `engine/`: `.venv/bin/python -m pytest -q`
Expected: PASS, full suite.

- [ ] **Step 5: Commit**

```bash
git add config/config.yaml tests/test_config.py
git commit -m "chore: switch live engine config to multi-entry paper profile"
```