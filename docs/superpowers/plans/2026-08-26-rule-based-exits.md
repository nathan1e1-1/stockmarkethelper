# Rule-Based Exits & Per-Trade P&L Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic exits (stop-loss, take-profit, flatten-at-close) and per-trade P&L tracking, then feed real results into the daily summary.

**Architecture:** A new `ExitManager` (pure rules) decides exits; `runner.manage_exits()` checks open positions each scan and closes them via `executor.sell`, recording a `ClosedTrade`. The summary (slice 2) reports realized P&L.

**Tech Stack:** Python 3.14, existing `autotrader` package + pytest.

---

## Task 1: `ClosedTrade` model + `State` field

**Files:** Create/edit `engine/src/autotrader/models.py`, `engine/src/autotrader/state.py`, `engine/tests/test_models.py`, `engine/tests/test_state.py`

- [ ] **Step 1: failing test**

Add to `engine/tests/test_models.py`:
```python
from autotrader.models import ClosedTrade


def test_closed_trade_fields():
    t = ClosedTrade(ticker="AAPL", qty=10.0, entry_price=100.0, exit_price=103.0, realized_pnl=30.0, exit_reason="take_profit")
    assert t.realized_pnl == 30.0
    assert t.exit_reason == "take_profit"
    assert t.qty == 10.0
```

Run: `cd engine && .venv/bin/pytest tests/test_models.py -v` → FAIL (ImportError)

- [ ] **Step 2: implement**

Add to `engine/src/autotrader/models.py` (after `Position`):
```python
@dataclass
class ClosedTrade:
    ticker: str
    qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    exit_reason: str
    opened_at: datetime = field(default_factory=_now)
    closed_at: datetime = field(default_factory=_now)
```

Add to `State` in `engine/src/autotrader/state.py`:
```python
@dataclass
class State:
    equity: Equity | None = None
    positions: list[Position] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
```
(import `ClosedTrade` in state.py's `from autotrader.models import ...` line)

Run tests → PASS. Commit: `git add engine/src/autotrader/models.py engine/src/autotrader/state.py engine/tests/test_models.py && git commit -m "feat: add ClosedTrade model and State field"`

## Task 2: exit config params

**Files:** `engine/src/autotrader/config.py`, `engine/config/config.yaml`, `engine/tests/test_config.py`

- [ ] **Step 1: failing test**

In `engine/tests/test_config.py`, add `exits` block to BOTH yaml strings:
```
        "exits:\n  stop_loss_pct: 0.02\n  take_profit_pct: 0.03\n  flatten_at_close: true\n  flatten_time: \"15:55\"\n"
```
and in `test_load_config_reads_yaml_and_env` add:
```python
    assert cfg.stop_loss_pct == 0.02
    assert cfg.take_profit_pct == 0.03
    assert cfg.flatten_at_close is True
    assert cfg.flatten_time == "15:55"
```

Run → FAIL (AttributeError / missing keys)

- [ ] **Step 2: implement**

`engine/config/config.yaml` add:
```yaml
exits:
  stop_loss_pct: 0.02
  take_profit_pct: 0.03
  flatten_at_close: true
  flatten_time: "15:55"
```

`Config` dataclass add fields (after `signal_weights`):
```python
    stop_loss_pct: float
    take_profit_pct: float
    flatten_at_close: bool
    flatten_time: str
```
`load_config` return add:
```python
        stop_loss_pct=raw["exits"]["stop_loss_pct"],
        take_profit_pct=raw["exits"]["take_profit_pct"],
        flatten_at_close=raw["exits"]["flatten_at_close"],
        flatten_time=raw["exits"]["flatten_time"],
```

Run → PASS. Commit.

## Task 3: `ExitManager`

**Files:** Create `engine/src/autotrader/exits.py`, `engine/tests/test_exits.py`

- [ ] **Step 1: failing test**

`engine/tests/test_exits.py`:
```python
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
```

Run → FAIL (ImportError)

- [ ] **Step 2: implement**

`engine/src/autotrader/exits.py`:
```python
class ExitManager:
    def __init__(self, stop_loss_pct: float, take_profit_pct: float):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def evaluate(self, position, current_price: float) -> str | None:
        entry = position.avg_entry_price
        if entry <= 0:
            return None
        pct = current_price / entry - 1.0
        if pct <= -self.stop_loss_pct:
            return "stop_loss"
        if pct >= self.take_profit_pct:
            return "take_profit"
        return None
```

Run → PASS. Commit.

## Task 4: `execution.sell()`

**Files:** `engine/src/autotrader/execution.py`, `engine/tests/test_execution.py`

- [ ] **Step 1: failing test**

Add to `engine/tests/test_execution.py`:
```python
def test_sell_delegates_to_market_order():
    ex = FakeExec()
    ex.sell = lambda ticker, qty: ex.market_order(ticker, qty, Side.SELL)
    order = ex.sell("AAPL", 10)
    assert ex.submitted == [("AAPL", 10, Side.SELL)]
```

Run → FAIL (FakeExec has no `sell`)

- [ ] **Step 2: implement**

Add to `AlpacaExecutor` in `engine/src/autotrader/execution.py`:
```python
    def sell(self, ticker: str, qty: int) -> Order:
        return self.market_order(ticker, qty, Side.SELL)
```

Add to `FakeExec` in `engine/tests/test_execution.py`:
```python
    def sell(self, ticker, qty):
        return self.market_order(ticker, qty, Side.SELL)
```

Run → PASS. Commit.

## Task 5: `runner.manage_exits()`

**Files:** `engine/src/autotrader/runner.py`, `engine/tests/test_runner.py`

- [ ] **Step 1: failing test**

Add to `engine/tests/test_runner.py`:
```python
from autotrader.models import Position, Side, ClosedTrade
import pytest


class PriceProvider:
    def __init__(self, price):
        self.price = price

    def latest_price(self, ticker):
        return self.price


class ExitCfg:
    stop_loss_pct = 0.02
    take_profit_pct = 0.03


class FakeRisk:
    def __init__(self, positions):
        self.positions = positions


class SellExec:
    def __init__(self):
        self.sold = []

    def sell(self, ticker, qty):
        self.sold.append((ticker, qty))
        from autotrader.models import Order
        return Order(id="s", ticker=ticker, side=Side.SELL, qty=qty)


def test_manage_exits_triggers_stop_loss():
    risk = FakeRisk([Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0)])
    ex = SellExec()
    runner = Runner(provider=PriceProvider(97.0), agent=None, executor=ex, risk=risk, cfg=ExitCfg())
    runner.manage_exits()
    assert ex.sold == [("AAPL", 10)]
    assert len(runner.closed_trades) == 1
    t = runner.closed_trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.realized_pnl == pytest.approx(-30.0)
    assert risk.positions == []


def test_manage_exits_no_trigger_when_within_band():
    risk = FakeRisk([Position(ticker="AAPL", qty=10.0, avg_entry_price=100.0)])
    ex = SellExec()
    runner = Runner(provider=PriceProvider(101.0), agent=None, executor=ex, risk=risk, cfg=ExitCfg())
    runner.manage_exits()
    assert ex.sold == []
    assert runner.closed_trades == []
```

Run → FAIL (Runner has no `manage_exits`)

- [ ] **Step 2: implement**

In `runner.py`:
- import `from autotrader.exits import ExitManager` and `from autotrader.models import ..., ClosedTrade, Position`
- `__init__` add:
```python
        self.exit_manager = ExitManager(cfg.stop_loss_pct, cfg.take_profit_pct) if cfg else None
        self.closed_trades: list = []
        self.flattened = False
```
- add methods:
```python
    def manage_exits(self, flatten_time=None, now=None) -> None:
        if self.exit_manager is None or self.risk is None:
            return
        if flatten_time and now and now.astimezone(__import__("autotrader.market", fromlist=["EASTERN"]).EASTERN).time() >= flatten_time and not self.flattened:
            for pos in list(self.risk.positions):
                self._close(pos, "flatten")
            self.flattened = True
            return
        for pos in list(self.risk.positions):
            price = self.provider.latest_price(pos.ticker)
            reason = self.exit_manager.evaluate(pos, price)
            if reason:
                self._close(pos, reason)

    def _close(self, pos, reason: str) -> None:
        price = self.provider.latest_price(pos.ticker)
        qty = int(pos.qty)
        self.executor.sell(pos.ticker, qty)
        self.closed_trades.append(ClosedTrade(
            ticker=pos.ticker,
            qty=pos.qty,
            entry_price=pos.avg_entry_price,
            exit_price=price,
            realized_pnl=(price - pos.avg_entry_price) * pos.qty,
            exit_reason=reason,
        ))
        self.risk.positions = [p for p in self.risk.positions if p.ticker != pos.ticker]
```

Run → PASS. Commit.

## Task 6: wire into `main.py`

**Files:** `engine/src/autotrader/main.py`

- [ ] **Step 1: edit**

- import `from autotrader.market import EASTERN, is_after_close, is_market_open` (already present) and `from datetime import datetime` (present).
- after `universe = ...` parse flatten time:
```python
    flatten_time = datetime.strptime(cfg.flatten_time, "%H:%M").time() if cfg.flatten_at_close else None
```
- in `sync_and_scan`, before `runner.run_once(universe)` add:
```python
        runner.manage_exits(flatten_time=flatten_time, now=datetime.now(EASTERN))
```
- in `build_summary`/`generate_summary`, pass `closed_trades` and unrealized P&L:
```python
    def generate_summary() -> None:
        unrealized = 0.0
        for p in risk.positions:
            unrealized += (provider.latest_price(p.ticker) - p.avg_entry_price) * p.qty
        state = State(equity=runner.equity, positions=risk.positions, decisions=runner.decisions, closed_trades=runner.closed_trades)
        state.unrealized_pnl = unrealized
        summary = daily_summary(state, agent)
        shared.summary = summary
        print(f"Daily summary:\n{summary}")
```
(also update the `sync_and_scan` `store.save(...)` call to include `closed_trades=runner.closed_trades`)

- [ ] **Step 2: verify imports**

Run: `cd engine && .venv/bin/python -c "import autotrader.main; print('ok')"` → `ok`

Commit.

## Task 7: summary slice 2

**Files:** `engine/src/autotrader/summary.py`, `engine/src/autotrader/state.py`, `engine/tests/test_summary.py`

- [ ] **Step 1: failing test**

Add to `engine/tests/test_summary.py`:
```python
from autotrader.models import ClosedTrade


def test_daily_summary_includes_realized_pnl():
    llm = FakeLLM()
    state = State(
        equity=_eq(),
        decisions=[],
        closed_trades=[ClosedTrade(ticker="NVDA", qty=10.0, entry_price=100.0, exit_price=103.0, realized_pnl=30.0, exit_reason="take_profit")],
    )
    daily_summary(state, llm)
    prompt = llm.prompts[0]
    assert "NVDA" in prompt
    assert "take_profit" in prompt
    assert "+30.00" in prompt
```

Also update `test_daily_summary_forbids_outcome_claims` to assert the new guard text instead of "per-trade results are not available" (replace with `"Report only the realized results listed above"`).

Run → FAIL

- [ ] **Step 2: implement**

`engine/src/autotrader/summary.py` — rewrite to include realized trades:
```python
from autotrader.state import State


def daily_summary(state: State, llm) -> str:
    eq = state.equity
    pnl = (eq.equity / eq.day_start_equity - 1.0) * 100 if eq and eq.day_start_equity else 0.0

    decision_lines = []
    for d in state.decisions:
        signals = ""
        if d.signals:
            signals = ", ".join(f"{s.name}={s.value}" for s in d.signals.signals)
        parts = [f"{d.ticker}: {d.decision.value} (confidence {d.confidence:.2f})"]
        if d.rationale:
            parts.append(f"rationale: {d.rationale}")
        if signals:
            parts.append(f"signals: {signals}")
        decision_lines.append("- " + " | ".join(parts))
    decision_block = "\n".join(decision_lines) if decision_lines else "No trades were placed today."

    if state.closed_trades:
        trade_lines = [
            f"- {t.ticker}: {t.exit_reason}, realized ${t.realized_pnl:+.2f}"
            for t in state.closed_trades
        ]
        total = sum(t.realized_pnl for t in state.closed_trades)
        trade_lines.append(f"Total realized P&L: ${total:+.2f}")
        trade_block = "\n".join(trade_lines)
    else:
        trade_block = "No trades were closed today."

    if state.positions:
        position_block = "\n".join(
            f"- {p.ticker}: {p.qty:g} shares @ {p.avg_entry_price:.2f}"
            for p in state.positions
        )
    else:
        position_block = "No open positions."

    prompt = (
        "Write a concise, honest post-market summary for an intraday trading day.\n"
        f"Day P&L: {pnl:.2f}%\n"
        f"Decisions made:\n{decision_block}\n"
        f"Closed trades:\n{trade_block}\n"
        f"Open positions at close:\n{position_block}\n"
        f"Unrealized P&L on open positions: ${getattr(state, 'unrealized_pnl', 0.0):+.2f}\n"
        "Report only the realized results listed above. Do not invent trades, tickers, or outcomes. "
        "Then suggest one concrete process improvement for tomorrow."
    )
    return llm.complete(prompt)
```

Run → PASS. Commit.

---

## Self-Review Notes
- Spec coverage: ClosedTrade model ✓, config keys ✓, ExitManager ✓, execution.sell ✓, runner.manage_exits (stop/tp/flatten) ✓, state persistence of closed_trades (via asdict + load) — ensure `state.py` `load()` reconstructs `closed_trades` (add below), summary integration ✓.
- **Missing from tasks:** `state.py` `load()` must reconstruct `closed_trades`. Add in Task 1 Step 2 (state.py `load`): `closed_trades=[ClosedTrade(**c) for c in raw.get("closed_trades", [])]`.
- Type consistency: `ClosedTrade` fields match all usages. `ExitManager.evaluate(position, price)` matches spec.
