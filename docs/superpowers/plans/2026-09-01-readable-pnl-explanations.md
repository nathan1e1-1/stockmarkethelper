# Readable P&L Explanations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make AI Trade Desk P&L-driver responses readable, factual explanations backed by account trades, price data, and verified relevant market news.

**Architecture:** The local model remains a strict JSON topic selector. A pure P&L enrichment layer combines existing account attribution with canonical one-day price movement and news metadata; a dedicated server renderer writes all visible P&L prose. main.py collects only bounded context for current positions and current-day recorded trades; no chat path receives order or risk-mutation capabilities.

**Tech Stack:** Python 3, FastAPI, pytest, Alpaca Python SDK, existing Ollama selector, SwiftUI client (no client changes).

---

## File structure

- Modify: engine/src/autotrader/pnl.py — enrich the pure account P&L snapshot.
- Create: engine/src/autotrader/pnl_explanation.py — deterministic human-readable renderer.
- Modify: engine/src/autotrader/main.py — collect bounded bars/news while publishing state.
- Modify: engine/src/autotrader/ipc.py — add and safely route pnl_explanation.
- Modify: engine/src/autotrader/providers/alpaca.py and engine/src/autotrader/providers/fixtures.py — canonical news metadata.
- Modify: engine/tests/test_pnl.py, engine/tests/test_alpaca.py, and engine/tests/test_ipc.py — fakes-only coverage.

### Task 1: Enrich the pure P&L snapshot

**Files:**
- Modify: engine/src/autotrader/pnl.py
- Test: engine/tests/test_pnl.py

- [ ] **Step 1: Write failing enrichment tests**

Add this test and a second test with malformed bars/no news. The second test must prove the function returns None day-move fields and an empty news list without raising.

~~~python
from autotrader.pnl import build_pnl_snapshot, enrich_pnl_snapshot

def test_enriched_pnl_snapshot_keeps_price_news_trade_and_reconciliation_facts():
    base = build_pnl_snapshot(
        Equity(equity=1_015, day_start_equity=1_000, peak_equity=1_020, day="2026-09-01"),
        [Position(ticker="AAPL", qty=2, avg_entry_price=100)],
        {"AAPL": 110},
        [ClosedTrade(ticker="MSFT", qty=1, entry_price=90, exit_price=95,
                     realized_pnl=5, exit_reason="recorded exit",
                     closed_at=datetime(2026, 9, 1, 15, tzinfo=timezone.utc))],
    )
    snapshot = enrich_pnl_snapshot(
        base,
        {"AAPL": [{"open": 100.0, "close": 103.0}, {"open": 103.0, "close": 105.0}]},
        {"AAPL": [{"headline": "AAPL headline", "summary": "Verified summary",
                   "created_at": "2026-09-01T14:00:00+00:00", "source": "Wire"}]},
    )
    assert snapshot["open_positions"][0]["day_open"] == 100.0
    assert snapshot["open_positions"][0]["day_close"] == 105.0
    assert snapshot["open_positions"][0]["day_change"] == 5.0
    assert snapshot["open_positions"][0]["day_change_pct"] == 5.0
    assert snapshot["realized_trades"][0]["closed_at"] == "2026-09-01T15:00:00+00:00"
    assert snapshot["reconciliation_pnl"] == -10.0
    assert snapshot["news_by_ticker"]["AAPL"][0]["headline"] == "AAPL headline"
~~~

- [ ] **Step 2: Verify the tests fail**

Run:

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_pnl.py -q
~~~

Expected: FAIL because enrich_pnl_snapshot, close-time, and reconciliation fields do not exist.

- [ ] **Step 3: Add the minimal pure implementation**

In build_pnl_snapshot, add "closed_at": trade.closed_at.isoformat() to each recorded trade and set "reconciliation_pnl": daily_pnl - realized_pnl - unrealized_pnl.

Add these functions. They must perform no provider calls and must copy, not mutate, snapshot records.

~~~python
def _one_day_move(bars: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    valid = [
        bar for bar in bars
        if isinstance(bar, Mapping)
        and isinstance(bar.get("open"), (int, float)) and not isinstance(bar.get("open"), bool)
        and isinstance(bar.get("close"), (int, float)) and not isinstance(bar.get("close"), bool)
    ]
    if not valid:
        return {"day_open": None, "day_close": None, "day_change": None, "day_change_pct": None}
    opening, closing = float(valid[0]["open"]), float(valid[-1]["close"])
    change = closing - opening
    return {
        "day_open": opening, "day_close": closing, "day_change": change,
        "day_change_pct": (change / opening) * 100 if opening else None,
    }

def enrich_pnl_snapshot(snapshot, bars_by_ticker, news_by_ticker) -> dict[str, Any]:
    result = dict(snapshot)
    result["open_positions"] = [
        dict(position, **_one_day_move(bars_by_ticker.get(position["ticker"], [])))
        for position in snapshot.get("open_positions", [])
    ]
    result["news_by_ticker"] = {
        ticker: [dict(item) for item in items]
        for ticker, items in news_by_ticker.items()
        if isinstance(ticker, str) and isinstance(items, Sequence)
    }
    result["reconciliation_pnl"] = (
        float(result.get("daily_pnl", 0.0))
        - float(result.get("realized_pnl", 0.0))
        - float(result.get("unrealized_pnl", 0.0))
    )
    return result
~~~

- [ ] **Step 4: Verify and commit**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_pnl.py -q
git add engine/src/autotrader/pnl.py engine/tests/test_pnl.py
git commit -m "feat: enrich P&L attribution facts"
~~~

Expected: P&L tests PASS, then one focused commit.

### Task 2: Normalize verified market-news data

**Files:**
- Modify: engine/src/autotrader/providers/alpaca.py
- Modify: engine/src/autotrader/providers/fixtures.py
- Test: engine/tests/test_alpaca.py

- [ ] **Step 1: Write failing production/fixture news tests**

Add a fake news client exposing one article with headline, summary, created_at, and source. Assert provider.news("AAPL", limit=2) returns exactly:

~~~python
[{
    "headline": "AAPL headline",
    "summary": "Short verified summary",
    "created_at": "2026-09-01T14:00:00+00:00",
    "source": "Newswire",
}]
~~~

Update test_fixture_provider_news to assert the same four keys for every fixture item.

- [ ] **Step 2: Verify the test fails**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_alpaca.py -q
~~~

Expected: FAIL because the current providers omit creation time and source.

- [ ] **Step 3: Normalize only display-safe metadata**

Replace AlpacaProvider.news with:

~~~python
def news(self, ticker: str, limit: int = 5) -> list[dict]:
    articles = self._news.get_news(NewsRequest(symbols=ticker, limit=limit)).data["news"]
    records = []
    for article in articles:
        created_at = getattr(article, "created_at", None)
        record = {
            "headline": str(getattr(article, "headline", "")).strip(),
            "summary": str(getattr(article, "summary", "")).strip(),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
            "source": str(getattr(article, "source", "")).strip() or None,
        }
        if record["headline"]:
            records.append(record)
    return records
~~~

Make FixtureProvider.news return the same four fields with a fixed UTC timestamp and source. Do not expose article bodies.

- [ ] **Step 4: Verify and commit**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_alpaca.py -q
git add engine/src/autotrader/providers/alpaca.py engine/src/autotrader/providers/fixtures.py engine/tests/test_alpaca.py
git commit -m "feat: normalize verified market news"
~~~

Expected: provider tests PASS, then one focused commit.

### Task 3: Publish bounded account-relevant context

**Files:**
- Modify: engine/src/autotrader/main.py
- Test: engine/tests/test_pnl.py

- [ ] **Step 1: Write failing publication tests**

Use a fake provider with latest_price, bars, and news. After publish_pnl_attribution, assert an AAPL position has day-move fields and a headline. Add a second fake that raises for MSFT bars and news; assert AAPL stays intact, MSFT has None price fields, news_by_ticker["MSFT"] == [], and no exception escapes.

- [ ] **Step 2: Verify the tests fail**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_pnl.py -q
~~~

Expected: FAIL because publication currently requests latest prices only.

- [ ] **Step 3: Collect context without adding execution access**

Import HistoryRange and enrich_pnl_snapshot. Add:

~~~python
def _pnl_tickers(snapshot: dict) -> list[str]:
    tickers = [record["ticker"] for record in snapshot.get("open_positions", [])]
    tickers.extend(record["ticker"] for record in snapshot.get("realized_trades", []))
    return list(dict.fromkeys(ticker for ticker in tickers if isinstance(ticker, str) and ticker))

def _pnl_context(provider, tickers: list[str]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    bars_by_ticker, news_by_ticker = {}, {}
    for ticker in tickers:
        try:
            bars_by_ticker[ticker] = provider.bars(ticker, history_range=HistoryRange.ONE_DAY)
        except Exception:
            bars_by_ticker[ticker] = []
        try:
            news_by_ticker[ticker] = provider.news(ticker, limit=2)
        except Exception:
            news_by_ticker[ticker] = []
    return bars_by_ticker, news_by_ticker
~~~

Change publish_pnl_attribution to build the base snapshot once, call those helpers only for _pnl_tickers(snapshot), and assign:

~~~python
snapshot = build_pnl_snapshot(equity, positions, prices, closed_trades)
bars_by_ticker, news_by_ticker = _pnl_context(provider, _pnl_tickers(snapshot))
shared.pnl_attribution = enrich_pnl_snapshot(snapshot, bars_by_ticker, news_by_ticker)
~~~

The helpers must make only market-data/news calls and must not receive an executor or risk object.

- [ ] **Step 4: Verify and commit**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_pnl.py -q
git add engine/src/autotrader/main.py engine/tests/test_pnl.py
git commit -m "feat: publish P&L price and news context"
~~~

Expected: P&L tests PASS, then one focused commit.

### Task 4: Render and select readable P&L explanations

**Files:**
- Create: engine/src/autotrader/pnl_explanation.py
- Modify: engine/src/autotrader/ipc.py
- Test: engine/tests/test_ipc.py

- [ ] **Step 1: Write failing chat tests**

Use a fake selector returning {"topics": ["pnl_explanation", "pnl", "decisions"]} and a snapshot with positive AAPL unrealized P&L, negative MSFT realized P&L, a non-zero reconciliation amount, and canonical AAPL news. Assert:

~~~python
assert answer.startswith("Today’s account P&L is -$100.00")
assert "AAPL contributes $20.00 of unrealized P&L" in answer
assert "MSFT recorded -$30.00 realized P&L" in answer
assert "The current ledger does not attribute -$90.00" in answer
assert "Related verified news context for AAPL" in answer
assert "does not establish that this news caused the price move" in answer
assert "Engine decision log recorded" not in answer
assert response.json()["disclaimer"] == _INFORMATIONAL_DISCLAIMER
~~~

Add an empty-contributor/no-news case that returns HTTP 200 and a factual limitation, never an unavailable-assistant error.

- [ ] **Step 2: Verify the tests fail**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
~~~

Expected: FAIL because pnl_explanation is not an allowed selector topic.

- [ ] **Step 3: Implement the deterministic renderer**

Create pnl_explanation.py with render_pnl_explanation(snapshot: dict) -> str. It must render, in order: account daily amount/percentage, realized/unrealized amounts, the largest positive/negative open and recorded-close contributors, reconciliation when abs(value) >= 0.01, bounded relevant news, and compact remaining details. It must identify prices as observed, format valid timestamps in Eastern Time as %b %-d, %Y %-I:%M %p ET, and state once after news: “The available data does not establish that this news caused the price move.” It must not emit a recommendation or raw decision log.

Use this helper shape:

~~~python
def render_pnl_explanation(snapshot: dict) -> str:
    daily = float(snapshot["daily_pnl"])
    daily_pct = float(snapshot.get("daily_pnl_pct", 0.0))
    parts = [
        f"Today’s account P&L is {_money(daily)} ({daily_pct:+.2f}%).",
        f"Realized P&L is {_money(float(snapshot.get('realized_pnl', 0.0)))}.",
        f"Unrealized P&L is {_money(float(snapshot.get('unrealized_pnl', 0.0)))}.",
    ]
    # Append only verified records from snapshot, then return " ".join(parts).
    return " ".join(parts)
~~~

- [ ] **Step 4: Route, narrow, and de-duplicate the topic**

In ipc.py, add pnl_explanation to _ALLOWED_CHAT_TOPICS; update the selector prompt to require it for questions asking to drive, explain, or summarize P&L; and remove pnl and decisions from a selected list whenever pnl_explanation is present. Import the renderer and add:

~~~python
elif topic == "pnl_explanation" and isinstance(state.pnl_attribution, dict):
    sentences.append(render_pnl_explanation(state.pnl_attribution))
~~~

Do not modify create_app to accept an executor.

- [ ] **Step 5: Verify and commit**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
git add engine/src/autotrader/pnl_explanation.py engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "feat: render readable P&L explanations"
~~~

Expected: all chat tests PASS, including malformed-selector and actionable-prose safety tests.

### Task 5: Verify the feature against the approved specification

**Files:**
- Verify: docs/specs/readable-pnl-explanations.md
- Verify: engine/tests/
- Verify: app/

- [ ] **Step 1: Check scope and whitespace**

~~~bash
git diff origin/main...HEAD --check
git diff --stat origin/main...HEAD
~~~

Expected: no whitespace errors; only planned P&L, provider, chat, test, spec, and plan files.

- [ ] **Step 2: Run the full engine suite**

~~~bash
PYTHONPATH=engine/src engine/.venv/bin/python -m pytest engine/tests -q
~~~

Expected: PASS. A pre-existing third-party deprecation warning is acceptable; a test failure is not.

- [ ] **Step 3: Build the macOS app**

~~~bash
bash app/build-app.sh
~~~

Expected: Build complete!. Existing SwiftPM warnings for unhandled Info.plist and Assets.xcassets do not block the build.

- [ ] **Step 4: Commit the approved plan document**

~~~bash
git add docs/superpowers/plans/2026-09-01-readable-pnl-explanations.md
git commit -m "docs: plan readable P&L explanations"
~~~
