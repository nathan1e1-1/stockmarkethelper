# AI Trade Desk and Historical Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Ollama-powered dashboard assistant and all-tradable-US-equity discovery with multi-range, zoomable historical charts.

**Architecture:** The FastAPI engine gains three read-only endpoints: cached asset search, range-aware OHLCV retrieval, and chat that builds a factual prompt from `SharedState`. The SwiftUI client gains typed request models, an `AITradeDeskView`, and a rewritten Charts view. The chat endpoint receives only the shared snapshot and an LLM completion interface—never the executor or an order client.

**Tech Stack:** Python 3.11, FastAPI, Alpaca `alpaca-py`, local Ollama, pytest, Swift 5.9, SwiftUI, Swift Charts.

---

## File structure

- `engine/src/autotrader/history.py` — central definition of valid chart ranges, their date windows, and point caps.
- `engine/src/autotrader/providers/base.py` — market-data protocol extended with asset search and range-aware bars.
- `engine/src/autotrader/providers/alpaca.py` — Alpaca asset catalogue cache and historical bar retrieval.
- `engine/src/autotrader/ipc.py` — input validation, API response shaping, and read-only chat context/prompt construction.
- `engine/tests/test_history.py` — pure range validation and bar thinning tests.
- `engine/tests/test_alpaca.py` — provider cache/search and range-request tests.
- `engine/tests/test_ipc.py` — endpoint and read-only chat tests using fakes.
- `app/TradingAgentApp/Models.swift` — API payload models for assets, ranges, chats, and bars.
- `app/TradingAgentApp/EngineClient.swift` — actor-isolated requests for assets, ranged bars, and chat.
- `app/TradingAgentApp/AITradeDeskView.swift` — reusable read-only conversation panel.
- `app/TradingAgentApp/DashboardView.swift` — responsive dashboard/panel placement.
- `app/TradingAgentApp/ChartsView.swift` — searchable, ranged, scrollable chart experience.
- `app/TradingAgentApp/Package.swift` and `app/TradingAgentApp/Tests/TradingAgentAppTests.swift` — package test target and request-model tests.

### Task 1: Define historical ranges and Alpaca market-data support

**Files:**
- Create: `engine/src/autotrader/history.py`
- Modify: `engine/src/autotrader/providers/base.py`
- Modify: `engine/src/autotrader/providers/alpaca.py`
- Create: `engine/tests/test_history.py`
- Modify: `engine/tests/test_alpaca.py`

- [ ] **Step 1: Write failing range and thinning tests**

```python
from autotrader.history import HistoryRange, history_request, thin_bars

def test_history_request_uses_daily_bars_for_maximum_history():
    request = history_request(HistoryRange.MAX)
    assert request.timeframe == "1Day"
    assert request.max_points == 500

def test_thin_bars_preserves_the_first_and_last_bar():
    bars = [{"t": str(i)} for i in range(10)]
    result = thin_bars(bars, max_points=4)
    assert len(result) == 4
    assert result[0] == bars[0]
    assert result[-1] == bars[-1]
```

- [ ] **Step 2: Run the failing tests**

Run: `cd engine && .venv/bin/pytest tests/test_history.py -q`

Expected: FAIL because `autotrader.history` does not exist.

- [ ] **Step 3: Implement the range value object and deterministic thinning**

```python
class HistoryRange(str, Enum):
    ONE_DAY = "1D"
    FIVE_DAYS = "5D"
    ONE_MONTH = "1M"
    SIX_MONTHS = "6M"
    ONE_YEAR = "1Y"
    MAX = "MAX"

def history_request(value: HistoryRange) -> HistoryRequest:
    return {
        HistoryRange.ONE_DAY: HistoryRequest(days=1, timeframe="1Min", max_points=390),
        HistoryRange.FIVE_DAYS: HistoryRequest(days=5, timeframe="5Min", max_points=500),
        HistoryRange.ONE_MONTH: HistoryRequest(days=31, timeframe="1Hour", max_points=500),
        HistoryRange.SIX_MONTHS: HistoryRequest(days=183, timeframe="1Day", max_points=500),
        HistoryRange.ONE_YEAR: HistoryRequest(days=366, timeframe="1Day", max_points=500),
        HistoryRange.MAX: HistoryRequest(days=None, timeframe="1Day", max_points=500),
    }[value]

def thin_bars(bars: list[dict], max_points: int) -> list[dict]:
    if len(bars) <= max_points:
        return bars
    step = (len(bars) - 1) / (max_points - 1)
    return [bars[round(index * step)] for index in range(max_points)]
```

Use a UTC start of `datetime(1970, 1, 1, tzinfo=timezone.utc)` for `MAX`; Alpaca determines the earliest available bar. Construct `TimeFrame` objects from the defined `timeframe` value and return only thinned OHLCV dictionaries.

- [ ] **Step 4: Add provider tests before changing the provider**

Extend `engine/tests/test_alpaca.py` with fake trading/data clients. Assert that `search_assets("aa", 10)` returns only active, tradable `us_equity` assets whose symbol or name contains `aa`, caps the result at 10, and calls the trading client once across two searches. Assert `bars("AAPL", HistoryRange.ONE_YEAR)` requests a daily timeframe and a start about one year before the mocked clock.

- [ ] **Step 5: Extend the protocol and provider minimally**

```python
class MarketDataProvider(Protocol):
    def search_assets(self, query: str, limit: int = 10) -> list[dict]: ...
    def bars(self, ticker: str, history_range: HistoryRange = HistoryRange.ONE_DAY) -> list[dict]: ...
```

In `AlpacaProvider`, cache the filtered output of `self._trading.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))`. Each cached item is `{"ticker": asset.symbol, "name": asset.name}`. Filter case-insensitively by either field, sort symbol-first, and enforce `limit`. Do not cache error responses. Replace the seven-day fixed `bars` implementation with the `HistoryRange` request data and `thin_bars`.

- [ ] **Step 6: Verify and commit Task 1**

Run: `cd engine && .venv/bin/pytest tests/test_history.py tests/test_alpaca.py -q`

Expected: PASS.

```bash
git add engine/src/autotrader/history.py engine/src/autotrader/providers/base.py engine/src/autotrader/providers/alpaca.py engine/tests/test_history.py engine/tests/test_alpaca.py
git commit -m "feat: add ranged market history and asset search"
```

### Task 2: Expose validated, read-only search, history, and chat APIs

**Files:**
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/src/autotrader/main.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write endpoint tests with a recording fake provider and LLM**

Add fakes exposing `search_assets`, `bars(ticker, history_range)`, and `complete(prompt)`. Add tests asserting:

```python
assert client.get("/api/assets", params={"query": "aa"}).json() == {
    "assets": [{"ticker": "AAPL", "name": "Apple Inc."}]
}
assert client.get("/api/bars", params={"ticker": "aapl", "range": "1Y"}).status_code == 200
assert provider.requested_range == HistoryRange.ONE_YEAR
assert client.get("/api/bars", params={"ticker": "AAPL", "range": "bad"}).status_code == 422
response = client.post("/api/chat", json={"question": "What is my open risk?"})
assert response.status_code == 200
assert "What is my open risk?" in llm.prompt
assert "order" not in llm.prompt.lower() or "cannot" in llm.prompt.lower()
```

Also verify blank chat questions return 422, missing LLM returns a 503 response with a recoverable message, and the chat route is constructed without an executor argument.

- [ ] **Step 2: Run the focused endpoint tests**

Run: `cd engine && .venv/bin/pytest tests/test_ipc.py -q`

Expected: FAIL because the new routes and `create_app(..., llm=...)` interface do not exist.

- [ ] **Step 3: Implement the API boundary**

Change app construction in `main.py` to:

```python
app = create_app(shared, provider=provider, llm=agent)
```

In `ipc.py`, add `ChatRequest(BaseModel)` with a stripped non-empty `question` of at most 2,000 characters. Add the three routes below. Keep their dependencies limited to `state`, `provider`, `llm`, `HistoryRange`, and standard library formatting.

```python
@app.get("/api/assets")
def assets(query: str = "", limit: int = 10) -> dict[str, list[dict]]: ...

@app.get("/api/bars")
def bars(ticker: str = "", range: HistoryRange = HistoryRange.ONE_DAY) -> dict[str, Any]: ...

@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]: ...
```

The chat prompt must contain the user's question plus JSON-safe current equity, positions, decisions, kill-switch/daily-stop flags, and daily summary. Its system instruction states: analyse only supplied state; do not imply an order was placed; do not guarantee profit; do not advise disabling risk controls; if data is missing, say so. Return `{"answer": answer}`. Convert provider/LLM exceptions into `HTTPException(status_code=503, detail="…retry…")` without exposing secrets.

- [ ] **Step 4: Verify and commit Task 2**

Run: `cd engine && .venv/bin/pytest tests/test_ipc.py -q`

Expected: PASS.

```bash
git add engine/src/autotrader/ipc.py engine/src/autotrader/main.py engine/tests/test_ipc.py
git commit -m "feat: expose read-only assistant and chart APIs"
```

### Task 3: Add typed Swift client models and requests

**Files:**
- Modify: `app/TradingAgentApp/Models.swift`
- Modify: `app/TradingAgentApp/EngineClient.swift`
- Modify: `app/TradingAgentApp/Package.swift`
- Create: `app/TradingAgentApp/Tests/TradingAgentAppTests.swift`

- [ ] **Step 1: Add a Swift package test target and failing decoding tests**

Add `.testTarget(name: "TradingAgentAppTests", dependencies: ["TradingAgentApp"], path: "Tests")`. Test that `AssetSearchResponse` decodes a ticker/name, `ChartRange.oneYear` encodes as `1Y`, and a chat response decodes `answer`.

```swift
func testAssetSearchDecodesTickerAndName() throws {
    let data = #"{"assets":[{"ticker":"AAPL","name":"Apple Inc."}]}"#.data(using: .utf8)!
    XCTAssertEqual(try JSONDecoder().decode(AssetSearchResponse.self, from: data).assets[0].ticker, "AAPL")
}
```

- [ ] **Step 2: Run the failing Swift tests**

Run: `cd app/TradingAgentApp && swift test`

Expected: FAIL because the types and test target do not exist.

- [ ] **Step 3: Implement models and client requests**

Add `Asset`, `AssetSearchResponse`, `ChatRequest`, `ChatResponse`, and a string-backed `ChartRange: String, CaseIterable, Codable, Identifiable` with cases `oneDay = "1D"`, `fiveDays = "5D"`, `oneMonth = "1M"`, `sixMonths = "6M"`, `oneYear = "1Y"`, and `max = "MAX"`.

Add these actor-isolated client methods; they return empty values only for an asset/bar network failure, while chat throws so the view can display its error:

```swift
func assets(matching query: String) async -> [Asset]
func bars(for ticker: String, range: ChartRange) async -> [Bar]
func ask(_ question: String) async throws -> String
```

Use `URLComponents` for `query`/`range`; use `URLRequest` with `POST`, `Content-Type: application/json`, and encoded `ChatRequest` for chat. Decode FastAPI errors and throw a user-presentable `EngineClientError.message` instead of hiding them.

- [ ] **Step 4: Verify and commit Task 3**

Run: `cd app/TradingAgentApp && swift test && swift build`

Expected: PASS.

```bash
git add app/TradingAgentApp/Models.swift app/TradingAgentApp/EngineClient.swift app/TradingAgentApp/Package.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: add typed market and assistant client requests"
```

### Task 4: Build the searchable, ranged historical Charts experience

**Files:**
- Modify: `app/TradingAgentApp/ChartsView.swift`
- Modify: `app/TradingAgentApp/Components.swift`

- [ ] **Step 1: Add a pure view-state helper and test its range label mapping**

Put a small `ChartViewState` in `ChartsView.swift` with `selectedRange: ChartRange = .oneDay` and `visibleDomain: ClosedRange<Date>?`. Add a unit test asserting `ChartRange.oneDay.displayName == "1D"` and `ChartRange.max.displayName == "Max"`.

- [ ] **Step 2: Run Swift tests and confirm the missing state fails**

Run: `cd app/TradingAgentApp && swift test`

Expected: FAIL until the range display/state is added.

- [ ] **Step 3: Replace immediate symbol loading with cancellable type-ahead selection**

Keep `SInput`, but add a focus-aware suggestion list directly beneath it. Query `client.assets(matching:)` after a 250 ms task sleep; cancel the prior task using `.task(id: query)`. Limit display to ten results. Support up/down selection, Return to choose, Escape to dismiss, and pointer selection. Once selected, store `selectedTicker`, clear suggestions, and only then load bars. Display explicit loading, no-results, and engine-offline states.

- [ ] **Step 4: Add chart ranges, zoom/pan, reset, and accessible fallback**

Render one native `Button` for each `ChartRange`, label selected state in accessibility, and reload when `selectedTicker` or `selectedRange` changes. Use `chartScrollableAxes(.horizontal)`, `chartXVisibleDomain`, and `chartScrollPosition` to support scroll/pan; provide zoom-in, zoom-out, and reset buttons that adjust `visibleDomain` without mutating bars. Use a range-specific x-axis label formatter. Cap visible candles at the server response size. Add a compact OHLC `Table`/`DisclosureGroup` fallback and an accessibility summary of symbol, range, last close, and period change.

- [ ] **Step 5: Verify and commit Task 4**

Run: `cd app/TradingAgentApp && swift test && swift build`

Expected: PASS.

Manual check: search `A`, select Apple with the keyboard, switch every range, pan/zoom/reset, and view the no-results/offline states.

```bash
git add app/TradingAgentApp/ChartsView.swift app/TradingAgentApp/Components.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: add searchable historical stock charts"
```

### Task 5: Build and place the read-only AI Trade Desk

**Files:**
- Create: `app/TradingAgentApp/AITradeDeskView.swift`
- Modify: `app/TradingAgentApp/DashboardView.swift`
- Modify: `app/TradingAgentApp/Components.swift`
- Modify: `app/TradingAgentApp/Tests/TradingAgentAppTests.swift`

- [ ] **Step 1: Write tests for chat request validation state**

Add tests for a small pure `ChatComposerState` type: whitespace-only input cannot submit, non-empty input can submit when not loading, and it cannot submit while loading.

- [ ] **Step 2: Run the failing tests**

Run: `cd app/TradingAgentApp && swift test`

Expected: FAIL because `ChatComposerState` and `AITradeDeskView` do not exist.

- [ ] **Step 3: Implement the reusable panel**

Create `AITradeDeskView` with local `@State` for messages, draft, loading, and error. Its initial messages include concise prompts such as “What is driving today’s P&L?” and “Summarize my open risk.” Submitting appends the user message, calls `await client.ask(draft)`, appends the response, and presents an inline retryable error on failure. The panel must:

```swift
struct ChatComposerState {
    var draft = ""
    var isLoading = false
    var canSubmit: Bool { !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isLoading }
}
```

Use a visible “Ask about your trades” label, a multiline `TextField`, and a disabled loading button. The panel does not save data to disk and exposes no trading controls.

- [ ] **Step 4: Place it responsively and preserve dashboard availability**

In `DashboardView`, wrap the existing dashboard content and `AITradeDeskView` in a `ViewThatFits(in: .horizontal)` arrangement: the first child is an `HStack` with the 320–360 point panel at the trailing edge, and the fallback is a vertical stack with the panel after metrics/alerts. Preserve the existing `ScrollView`, engine status, waiting card, and market-closed behavior. Add only shared loading/error card styling to `Components.swift` if it removes duplication; do not change color tokens.

- [ ] **Step 5: Verify and commit Task 5**

Run: `cd app/TradingAgentApp && swift test && swift build`

Expected: PASS.

Manual check: open the app with the engine offline, send an empty question, send a valid question with Ollama available, trigger a 503/retry path, resize the window to force both layouts, and confirm no control can create or change an order.

```bash
git add app/TradingAgentApp/AITradeDeskView.swift app/TradingAgentApp/DashboardView.swift app/TradingAgentApp/Components.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: add read-only AI trade desk"
```

### Task 6: Full specification verification and final review

**Files:**
- Modify only if verification reveals a defect in an in-scope file above.

- [ ] **Step 1: Run the full engine suite**

Run: `cd engine && .venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 2: Run the complete macOS package verification**

Run: `cd app/TradingAgentApp && swift test && swift build`

Expected: PASS.

- [ ] **Step 3: Check the final diff against the approved spec**

Run: `git diff d8cad5e..HEAD -- engine app`

Confirm every spec requirement is present and that no order/executor dependency was introduced into the chat route or UI.

## Plan self-review

- **Spec coverage:** Tasks 1–2 implement cached all-US-equity search, all six historical ranges, validation, factual read-only chat, and no execution dependency. Tasks 3–5 implement the Swift client, accessible searchable chart controls, zoom/pan/reset, responsive dashboard side panel, and error states. Task 6 verifies the full spec.
- **Placeholder scan:** No incomplete requirements or deferred implementation markers are present. The only conditional in Task 6 prevents an empty verification commit.
- **Type consistency:** Python uses `HistoryRange` from `autotrader.history` through provider and API. Swift uses `ChartRange` for the matching wire values. Chat always uses `ChatRequest` and returns `ChatResponse`/`{"answer": ...}`.
