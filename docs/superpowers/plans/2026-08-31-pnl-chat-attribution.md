# P&L Attribution for AI Trade Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the read-only chat assistant an accurate daily P&L breakdown and enough contributor detail to explain it.

**Architecture:** A pure P&L snapshot helper derives daily totals, open-position unrealized P&L, and current-day realized P&L from existing models and prices. `main.py` publishes that snapshot to `SharedState`; `ipc.py` includes it in the factual JSON context and instructs the model to distinguish realized and unrealized contributors.

**Tech Stack:** Python 3.11, FastAPI, existing Alpaca provider, pytest, local Ollama.

---

### Task 1: Publish factual P&L attribution to the read-only chat

**Files:**
- Create: `engine/src/autotrader/pnl.py`
- Create: `engine/tests/test_pnl.py`
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/src/autotrader/main.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write failing pure-calculation tests**

```python
def test_pnl_snapshot_separates_daily_realized_and_unrealized_contributors():
    snapshot = build_pnl_snapshot(
        equity=Equity(equity=1050, day_start_equity=1000, peak_equity=1050, day="2026-08-31"),
        positions=[Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        prices={"AAPL": 110},
        closed_trades=[ClosedTrade(ticker="MSFT", qty=1, entry_price=90, exit_price=100, realized_pnl=10, exit_reason="take profit")],
    )
    assert snapshot["daily_pnl"] == 50
    assert snapshot["unrealized_pnl"] == 20
    assert snapshot["realized_pnl"] == 10
    assert snapshot["open_positions"][0]["unrealized_pnl"] == 20
```

Also test an unavailable symbol price produces `current_price: None`, `unrealized_pnl: None`, and does not prevent other positions or total daily P&L from being included.

- [ ] **Step 2: Verify the tests fail**

Run: `cd engine && PYTHONPATH=src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/pytest tests/test_pnl.py -q`

Expected: FAIL because `autotrader.pnl` does not exist.

- [ ] **Step 3: Implement the pure snapshot helper**

Create `build_pnl_snapshot(equity, positions, prices, closed_trades) -> dict`. Return numeric `daily_pnl`, `daily_pnl_pct`, `unrealized_pnl`, and `realized_pnl`; include `open_positions` records with ticker, quantity, average entry, current price, unrealized P&L, and unrealized P&L percentage; include only closed trades whose `closed_at` matches `equity.day`. Sort available open positions by absolute unrealized P&L descending. Do not call a provider from this helper.

- [ ] **Step 4: Verify the pure helper and commit**

Run: `cd engine && PYTHONPATH=src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/pytest tests/test_pnl.py -q`

Expected: PASS.

```bash
git add engine/src/autotrader/pnl.py engine/tests/test_pnl.py
git commit -m "feat: calculate chat P&L attribution"
```

- [ ] **Step 5: Write failing publication and prompt tests**

In `test_ipc.py`, create a `SharedState` with `pnl_attribution` and assert `POST /api/chat` passes JSON containing its daily, realized, and unrealized values to the fake LLM. Assert the prompt requires a distinction between realized and unrealized contributors. Add a main-level focused test or extract a small publish helper so a fake provider’s one failing `latest_price` still produces a P&L snapshot with that position marked unavailable.

- [ ] **Step 6: Verify the new tests fail**

Run: `cd engine && PYTHONPATH=src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/pytest tests/test_ipc.py -q`

Expected: FAIL because `SharedState` has no P&L attribution and chat context omits it.

- [ ] **Step 7: Publish and consume the snapshot**

Add `pnl_attribution: dict | None` to `SharedState`. In startup and each scan refresh, obtain a latest price per open position with per-symbol exception handling, call `build_pnl_snapshot`, and publish it along with equity/positions. In `_chat_context`, include `pnl_attribution`. Update the chat prompt: when P&L is requested, report the daily total and identify the largest available realized and unrealized contributors; clearly label unknown data and do not infer a price. Preserve all read-only/no-recommendation safeguards.

- [ ] **Step 8: Verify and commit Task 1**

Run: `cd engine && PYTHONPATH=src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/pytest -q`

Expected: PASS.

```bash
git add engine/src/autotrader/pnl.py engine/src/autotrader/main.py engine/src/autotrader/ipc.py engine/tests/test_pnl.py engine/tests/test_ipc.py
git commit -m "feat: explain P&L contributors in trade desk"
```

## Plan self-review

- The one task covers all approved data, prompt, unavailable-price, and verification requirements without changing orders, signals, or risk controls.
- Names are consistent: `build_pnl_snapshot`, `pnl_attribution`, and the resulting `open_positions` records are defined before use.
- No incomplete implementation markers are present.
