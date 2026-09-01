# AI Agent Analysis and Chart Crosshair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the read-only assistant explain supplied trading data with a clear informational disclaimer, and add exact hover inspection to stock and dashboard P&L charts.

**Architecture:** The FastAPI chat endpoint will retain the existing output guardrail but return a structured answer plus a required disclaimer, and its prompt will explicitly permit factual analysis. The Swift app will render the response disclaimer and use reusable nearest-datum helpers plus Swift Charts overlays to draw a crosshair and contextual tooltip in both existing charts.

**Tech Stack:** Python 3.11, FastAPI, pytest, Swift 5.9, SwiftUI, Swift Charts, XCTest.

---

## File structure

- `engine/src/autotrader/ipc.py` — owns the informational disclosure, assistant prompt, and safe chat response shape.
- `engine/tests/test_ipc.py` — verifies the analysis prompt, disclosure, and output guardrail.
- `app/TradingAgentApp/Models.swift` — decodes the structured chat response and provides testable nearest-datum helpers.
- `app/TradingAgentApp/EngineClient.swift` — returns the structured response to the view layer.
- `app/TradingAgentApp/AITradeDeskView.swift` — displays the API disclosure below each assistant response and in the panel footer.
- `app/TradingAgentApp/ChartsView.swift` — adds stock-candle crosshair state, hover handling, and OHLC/volume tooltip.
- `app/TradingAgentApp/DashboardView.swift` — adds dashboard P&L crosshair state, hover handling, and equity/P&L tooltip.
- `app/TradingAgentApp/Tests/TradingAgentAppTests.swift` — tests response decoding and nearest-datum selection.

### Task 1: Return analysis-ready, guarded chat responses

**Files:**
- Modify: `engine/tests/test_ipc.py`
- Modify: `engine/src/autotrader/ipc.py`

- [ ] **Step 1: Write failing API tests for permitted analysis, disclosure, and blocked advice**

Add these tests to `engine/tests/test_ipc.py` using a `FakeLLM` that returns the literal answer shown:

```python
def test_chat_endpoint_explicitly_permits_factual_analysis_and_returns_disclosure():
    class FakeLLM:
        def __init__(self):
            self.prompt = ""

        def complete(self, prompt):
            self.prompt = prompt
            return "Today's loss is primarily unrealized and comes from the supplied open-position data."

    llm = FakeLLM()
    client = TestClient(create_app(SharedState(), llm=llm))

    response = client.post("/api/chat", json={"question": "What is driving today's P&L?"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Today's loss is primarily unrealized and comes from the supplied open-position data.",
        "disclaimer": "For informational purposes only — not investment advice. Use your own judgment.",
    }
    assert "You may explain factual account, P&L, position, decision, and market data" in llm.prompt
    assert "Do not give personalized buy, sell, or hold instructions" in llm.prompt


def test_chat_endpoint_keeps_disclosure_when_output_is_unsafe():
    class UnsafeLLM:
        def complete(self, prompt):
            return "You should buy AAPL now."

    client = TestClient(create_app(SharedState(), llm=UnsafeLLM()))

    response = client.post("/api/chat", json={"question": "What should I do?"})

    assert response.status_code == 200
    assert response.json()["answer"] == _SAFE_READ_ONLY_LIMITATION
    assert response.json()["disclaimer"] == _INFORMATIONAL_DISCLAIMER
```

Update all existing successful chat response assertions to include the exact `disclaimer` field, and import `_INFORMATIONAL_DISCLAIMER` and `_SAFE_READ_ONLY_LIMITATION` from `autotrader.ipc` where tests compare constants.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q`

Expected: failures because successful `/api/chat` responses do not yet include `disclaimer`, and the prompt does not include the factual-analysis instruction.

- [ ] **Step 3: Implement explicit analysis permission and a structured disclosure**

In `engine/src/autotrader/ipc.py`, define the disclosure next to `_UNAVAILABLE_LLM_RESPONSE`:

```python
_INFORMATIONAL_DISCLAIMER = (
    "For informational purposes only — not investment advice. Use your own judgment."
)
```

Replace the first sentence of the chat prompt with wording that both enables and bounds analysis:

```python
"You may explain factual account, P&L, position, decision, and market data; identify "
"observed trends, contributors, uncertainty, and non-prescriptive risk context. "
"Do not give personalized buy, sell, or hold instructions, order actions, promised "
"returns, or guidance to disable or bypass risk controls. "
```

Keep the untrusted-data delimiters, missing-data rule, and P&L attribution instructions unchanged. Change both successful return paths so they always return this exact shape:

```python
{"answer": answer_or_safe_limitation, "disclaimer": _INFORMATIONAL_DISCLAIMER}
```

Do not change `_UNSAFE_ANSWER_PATTERNS`; it remains the server-side enforcement point for LLM output.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q`

Expected: all IPC tests pass.

- [ ] **Step 5: Commit the isolated backend change**

```bash
git add engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "feat: enable factual chat analysis with disclosure"
```

### Task 2: Decode and display the server disclosure

**Files:**
- Modify: `app/TradingAgentApp/Models.swift`
- Modify: `app/TradingAgentApp/EngineClient.swift`
- Modify: `app/TradingAgentApp/AITradeDeskView.swift`
- Modify: `app/TradingAgentApp/Tests/TradingAgentAppTests.swift`

- [ ] **Step 1: Write the failing Swift decoding test**

Replace `testChatResponseDecodesAnswer` in `app/TradingAgentApp/Tests/TradingAgentAppTests.swift` with:

```swift
func testChatResponseDecodesAnswerAndDisclosure() throws {
    let data = #"{"answer":"Your account has no open positions.","disclaimer":"For informational purposes only — not investment advice. Use your own judgment."}"#.data(using: .utf8)!

    let response = try JSONDecoder().decode(ChatResponse.self, from: data)

    XCTAssertEqual(response.answer, "Your account has no open positions.")
    XCTAssertEqual(response.disclaimer, "For informational purposes only — not investment advice. Use your own judgment.")
}
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd app/TradingAgentApp && swift test --filter TradingAgentAppTests/testChatResponseDecodesAnswerAndDisclosure`

Expected: compilation failure because `ChatResponse` has no `disclaimer` property.

- [ ] **Step 3: Carry the structured result through the app and render it**

In `Models.swift`, update the model:

```swift
struct ChatResponse: Codable {
    let answer: String
    let disclaimer: String
}
```

In `EngineClient.swift`, change `ask(_:)` from `async throws -> String` to `async throws -> ChatResponse` and return the decoded response instead of `.answer`.

In `AITradeDeskView.swift`, extend the assistant message payload and view:

```swift
private struct ChatMessage: Identifiable {
    // existing Role declaration
    let id = UUID()
    let role: Role
    let text: String
    let disclaimer: String?
}
```

For user messages set `disclaimer: nil`. In `requestAnswer(for:)`, append the assistant message with `text: response.answer` and `disclaimer: response.disclaimer`. In `messageBubble(_:)`, render `message.disclaimer` below an assistant answer with `.font(.caption2)` and `Color.mutedForeground`. Replace the existing panel footer with the same viewer-discretion language so the boundary remains visible before the first reply.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `cd app/TradingAgentApp && swift test --filter TradingAgentAppTests/testChatResponseDecodesAnswerAndDisclosure`

Expected: PASS.

- [ ] **Step 5: Commit the isolated Swift chat change**

```bash
git add app/TradingAgentApp/Models.swift app/TradingAgentApp/EngineClient.swift app/TradingAgentApp/AITradeDeskView.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: show chat informational disclosure"
```

### Task 3: Add testable nearest-datum selection helpers

**Files:**
- Modify: `app/TradingAgentApp/Models.swift`
- Modify: `app/TradingAgentApp/Tests/TradingAgentAppTests.swift`

- [ ] **Step 1: Write failing nearest-datum tests**

Add these tests to `TradingAgentAppTests`:

```swift
func testNearestBarSelectsTheClosestTimestamp() {
    let first = Bar(t: "2026-08-28T14:00:00Z", o: 100, h: 102, l: 99, c: 101, v: 1000)
    let second = Bar(t: "2026-08-28T14:05:00Z", o: 101, h: 103, l: 100, c: 102, v: 1200)

    XCTAssertEqual(nearestBar(to: first.date.addingTimeInterval(230), in: [first, second])?.id, second.id)
}

func testNearestEquityPointSelectsTheClosestTimestamp() {
    let first = EquityPoint(t: 1_000, equity: 100_000)
    let second = EquityPoint(t: 1_300, equity: 100_200)

    XCTAssertEqual(nearestEquityPoint(to: Date(timeIntervalSince1970: 1_250), in: [first, second])?.id, second.id)
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd app/TradingAgentApp && swift test --filter TradingAgentAppTests/testNearest`

Expected: compilation failure because the nearest-datum helpers do not exist.

- [ ] **Step 3: Implement deterministic nearest-datum helpers**

Add these pure functions below `Bar` in `Models.swift`:

```swift
func nearestBar(to date: Date, in bars: [Bar]) -> Bar? {
    bars.min { lhs, rhs in
        abs(lhs.date.timeIntervalSince(date)) < abs(rhs.date.timeIntervalSince(date))
    }
}

func nearestEquityPoint(to date: Date, in points: [EquityPoint]) -> EquityPoint? {
    points.min { lhs, rhs in
        abs(lhs.date.timeIntervalSince(date)) < abs(rhs.date.timeIntervalSince(date))
    }
}
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `cd app/TradingAgentApp && swift test --filter TradingAgentAppTests/testNearest`

Expected: both nearest-datum tests pass.

- [ ] **Step 5: Commit the isolated model helper change**

```bash
git add app/TradingAgentApp/Models.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: add chart nearest datum helpers"
```

### Task 4: Add crosshair and value tooltips to both existing charts

**Files:**
- Modify: `app/TradingAgentApp/ChartsView.swift`
- Modify: `app/TradingAgentApp/DashboardView.swift`

- [ ] **Step 1: Implement the stock candle crosshair**

In `ChartsView.swift`, add `@State private var highlightedBar: Bar?` alongside the existing chart view state. Add a small private `candleTooltip(for:)` view that shows the bar date, `O`, `H`, `L`, `C`, and `Vol` in monospaced labels.

```swift
private func candleTooltip(for bar: Bar) -> some View {
    VStack(alignment: .leading, spacing: 3) {
        Text(bar.date, format: .dateTime.month(.abbreviated).day().hour().minute())
        Text("O \(bar.o, format: .number.precision(.fractionLength(2)))  H \(bar.h, format: .number.precision(.fractionLength(2)))")
        Text("L \(bar.l, format: .number.precision(.fractionLength(2)))  C \(bar.c, format: .number.precision(.fractionLength(2)))")
        Text("Vol \(bar.v, format: .number.notation(.compactName))")
    }
    .font(.caption2.monospacedDigit())
    .foregroundStyle(Color.foreground)
    .padding(8)
    .background(Color.background)
    .clipShape(RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous))
    .overlay(RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous).stroke(Color.border, lineWidth: 1))
}
```

Inside the existing `Chart` in `candleChart(for:)`, append this conditional mark after the `ForEach`:

```swift
if let highlightedBar {
    RuleMark(x: .value("Selected time", highlightedBar.date))
        .foregroundStyle(Color.accentColor)
        .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
        .annotation(position: .top) {
            candleTooltip(for: highlightedBar)
        }
}
```

Attach this overlay to the same chart, using its local plot-area x coordinate and the pure helper from Task 3:

```swift
.chartOverlay { proxy in
    GeometryReader { geometry in
        Rectangle()
            .fill(.clear)
            .contentShape(Rectangle())
            .onContinuousHover { phase in
                switch phase {
                case .active(let location):
                    let plotFrame = geometry[proxy.plotAreaFrame]
                    guard let date = proxy.value(atX: location.x - plotFrame.origin.x, as: Date.self) else { return }
                    highlightedBar = nearestBar(to: date, in: bars)
                case .ended:
                    highlightedBar = nil
                }
            }
    }
}
```

Reset `highlightedBar` to `nil` whenever a new ticker or range starts loading, so a stale tooltip cannot be paired with a new data series. Preserve existing scrollable axes, zoom, range controls, and accessible OHLC summary.

- [ ] **Step 2: Implement the dashboard P&L crosshair**

In `DashboardView.swift`, add `@State private var highlightedEquityPoint: EquityPoint?`. Add this tooltip view:

```swift
private func pnlTooltip(for point: EquityPoint, dayStart: Double) -> some View {
    VStack(alignment: .leading, spacing: 3) {
        Text(point.date, format: .dateTime.hour().minute())
        Text("Equity \(point.equity, format: .currency(code: \"USD\"))")
        Text("P&L \(point.equity - dayStart, format: .currency(code: \"USD\").sign(strategy: .always()))")
    }
    .font(.caption2.monospacedDigit())
    .foregroundStyle(Color.foreground)
    .padding(8)
    .background(Color.background)
    .clipShape(RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous))
    .overlay(RoundedRectangle(cornerRadius: SRadius.sm, style: .continuous).stroke(Color.border, lineWidth: 1))
}
```

In the existing P&L chart, conditionally add a `RuleMark` at `highlightedEquityPoint.date`, using `.annotation(position: .top) { pnlTooltip(for: highlightedEquityPoint, dayStart: dayStart) }`.

Attach the same `chartOverlay` interaction, substituting:

```swift
highlightedEquityPoint = nearestEquityPoint(to: date, in: history)
```

Clear the highlight when hover ends. Keep the zero reference rule and existing axes unchanged.

- [ ] **Step 3: Run the app test suite and build**

Run:

```bash
cd app/TradingAgentApp && swift test
cd app && bash build-app.sh
```

Expected: the test suite passes and the app build exits with status `0`.

- [ ] **Step 4: Perform manual pointer verification**

Launch the rebuilt app against the local API. In Charts, select one intraday range and one daily/long-range dataset, move the pointer across several candles, and confirm each tooltip follows the nearest candle and reports the matching O/H/L/C/volume. On Dashboard, move across the P&L line and confirm the time, equity, and P&L agree with the plotted point. Confirm range switching and scroll/zoom still work after a tooltip is dismissed.

- [ ] **Step 5: Commit the isolated chart UI change**

```bash
git add app/TradingAgentApp/ChartsView.swift app/TradingAgentApp/DashboardView.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
git commit -m "feat: add chart hover crosshairs"
```

### Task 5: Full verification and review

**Files:**
- Verify only: all changed files and `docs/specs/ai-agent-analysis-and-chart-crosshair.md`

- [ ] **Step 1: Run the complete engine suite**

Run: `engine/.venv/bin/python -m pytest engine/tests -q`

Expected: every test passes.

- [ ] **Step 2: Inspect the implementation against the approved spec**

Run:

```bash
git diff origin/main...HEAD --check
git diff origin/main...HEAD -- docs/specs/ai-agent-analysis-and-chart-crosshair.md engine/src/autotrader/ipc.py engine/tests/test_ipc.py app/TradingAgentApp/Models.swift app/TradingAgentApp/EngineClient.swift app/TradingAgentApp/AITradeDeskView.swift app/TradingAgentApp/ChartsView.swift app/TradingAgentApp/DashboardView.swift app/TradingAgentApp/Tests/TradingAgentAppTests.swift
```

Expected: no whitespace errors, every done criterion is represented, and no scope item adds chat order execution or personalized advice.

- [ ] **Step 3: Obtain independent code review**

Ask a review-only subagent to compare the diff with `docs/specs/ai-agent-analysis-and-chart-crosshair.md`, specifically checking response compatibility, unsafe-output handling, tooltip coordinate conversion, hover dismissal, and range-switch/reset behavior. Address only confirmed findings with tests before opening a PR.

### Revision: Strict actionable-language output policy

The approved policy replaces open-ended phrase-by-phrase exemptions. The chat
context must identify each historical engine decision with a source and ISO
timestamp. The output validator must process each response sentence: discard a
sentence containing actionable language unless it names `engine decision log`,
contains a date from the supplied decision records, uses historical attribution,
and contains no prospective/actionable framing. If every sentence is discarded,
return the existing safe limitation. This supports factual recorded decisions
without accepting an invented or undated recommendation.

### Task 6: Enforce the strict sentence-level output policy

**Files:**
- Modify: `engine/src/autotrader/models.py`
- Modify: `engine/src/autotrader/state.py`
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/tests/test_models.py`
- Modify: `engine/tests/test_state.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 0: Record and restore a decision timestamp**

Add `timestamp: datetime = field(default_factory=_now)` to `AgentDecision` in
`engine/src/autotrader/models.py`. Extend `_decode_decision` in
`engine/src/autotrader/state.py` to parse a persisted ISO timestamp when
present, using `datetime.fromisoformat(value.replace("Z", "+00:00"))`, and let
the dataclass default supply a timestamp for legacy state that lacks it.

Add a model test that an `AgentDecision` gets a timezone-aware timestamp and a
state round-trip test that a fixed timestamp survives save/load. Run
`PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_models.py engine/tests/test_state.py -q` red before implementation and green after it. Commit this prerequisite as:

```bash
git add engine/src/autotrader/models.py engine/src/autotrader/state.py engine/tests/test_models.py engine/tests/test_state.py
git commit -m "feat: timestamp recorded decisions"
```

- [ ] **Step 1: Write failing boundary tests**

Add a state fixture with an `AgentDecision` timestamp of
`2026-08-31T14:30:00+00:00`. Add a parameterized test proving that these LLM
outputs return the safe limitation rather than pass through:

```python
[
    "You should definitely buy AAPL now.",
    "I recommend that you keep holding AAPL.",
    "For your portfolio, AAPL is a buy.",
    "My advice: sell AAPL now.",
    "Go ahead and buy AAPL.",
    "Trade through the daily stop.",
    "Turn the daily stop off, then keep trading.",
    "AAPL is a buy according to the recorded decision today.",
]
```

Add a test proving that an answer with one factual P&L sentence followed by
`"Go ahead and buy AAPL."` returns only the factual sentence. Add a permitted
historical test for `"The engine decision log recorded BUY AAPL on 2026-08-31."`
and rejection tests for the same wording without the date and without the
source. Assert that `_chat_context` contains exactly
`"source": "engine decision log"` and the decision's ISO `recorded_at` value.

- [ ] **Step 2: Run the focused tests and verify the current implementation fails**

Run: `PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q`

Expected: the new prospective/undated recommendation tests fail because the
current phrase patterns are incomplete and chat context omits decision source
and timestamp.

- [ ] **Step 3: Add sourced decision context and deterministic sentence filtering**

In `_chat_context`, serialize each decision as:

```python
{
    "source": "engine decision log",
    "recorded_at": decision.timestamp.isoformat(),
    "ticker": decision.ticker,
    "decision": decision.decision.value,
    "confidence": decision.confidence,
    "rationale": decision.rationale,
}
```

Replace the short read-only prompt policy with the approved actionable-language
clause, including the per-sentence self-check and the source/date/past-tense
exception. Add a pure helper named `_filter_actionable_sentences(answer,
allowed_decision_dates)` that splits on sentence boundaries, removes a sentence
containing buy/sell/hold/order/risk-control action language unless it includes
all of: `engine decision log`, an ISO date in `allowed_decision_dates`, and
explicit historical attribution (`recorded`, `logged`, `executed`, or `filed`).
It must also remove sentences with advice framing (`should`, `recommend`,
`advice`, `go ahead`, `consider`, `worth`, `watch for`), prospective framing
(`will`, `could`, `may`, `likely`, `entry`, `breakout`, `rally`), or a
risk-control bypass phrase. Return the remaining stripped sentences joined by a
single space. The chat endpoint returns the existing safe limitation when this
result is empty; otherwise it returns the filtered answer plus the existing
disclaimer.

- [ ] **Step 4: Run focused and full engine verification**

Run:

```bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests -q
```

Expected: all tests pass, including existing factual P&L responses and the
new sentence-filter and sourced-date boundary tests.

- [ ] **Step 5: Commit the policy implementation**

```bash
git add engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "fix: enforce strict chat output policy"
```

### Task 7: Release review after policy hardening

**Files:**
- Verify only: all files changed from `origin/main`

- [ ] **Step 1: Run release checks**

Run:

```bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests -q
bash app/build-app.sh
git diff origin/main...HEAD --check
```

Expected: Python tests pass, the app builds, and no whitespace errors exist.

- [ ] **Step 2: Obtain final independent review**

Ask a fresh review-only subagent to evaluate the entire diff against the
revised spec, testing adversarial advice phrasing and the strict historical
exception. Do not proceed to integration with an open Critical or Important
finding.

### Revision: closed server-rendered historical records

The sentence filter must no longer accept an arbitrary model sentence because
it contains a source/date phrase. The model is never allowed to emit an action
or risk-control sentence. When a question asks about recorded decisions or
trades, the server appends only exact, past-tense record strings it constructs
from `state.decisions`; risk-control records are omitted because no matching
event record is currently supplied. This eliminates fabricated attribution and
semicolon clause-stuffing.

### Task 8: Replace model historical exceptions with verified record rendering

**Files:**
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write failing closed-policy tests**

Add parameterized tests that each return the safe limitation when produced by
the LLM, even with a valid source/date prefix:

```python
[
    "The engine decision log recorded BUY AAPL on 2026-08-31; buy AAPL now.",
    "The engine decision log recorded BUY AAPL on 2026-08-31; copy that position.",
    "The engine decision log recorded the daily stop was disabled on 2026-08-31; disable the daily stop now.",
    "Acquire AAPL.",
    "Hedge the position with puts.",
]
```

Add preservation tests proving `The close was $100 on May 1.` and `The entry
price was $100.` remain in the answer. Add a decision-question test with one
timestamped AAPL BUY record and an LLM answer containing only factual P&L; the
response answer must append exactly `Engine decision log recorded BUY AAPL on
2026-08-31.`. Add a non-decision-question test proving that record is not
appended. Add a test proving no historical daily-stop sentence is ever appended
without a supplied recorded risk-control event.

- [ ] **Step 2: Run the focused tests and verify the existing policy fails**

Run: `PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q`

Expected: source-prefixed compound model output passes, `Acquire AAPL.` passes,
and the verified decision record is not server-rendered.

- [ ] **Step 3: Implement closed filtering and record rendering**

Replace `_is_historical_record` exception use with
`_filter_actionable_sentences(answer)`. It must remove every model sentence
with trade-action vocabulary (`buy`, `sell`, `hold`, `purchase`, `liquidate`,
`acquire`, `accumulate`, `dump`, `invest`, `cover`, `open a position`, `close a
position`), risk-control vocabulary (`stop loss`, `daily stop`, `kill switch`,
`hedge`, `rebalance`, `position sizing`, `take profit`, `target`), advice
framing, or prospective action framing. Do not flag descriptive `May`, `entry
price`, or past-tense `rallied`/`broke out` merely because they contain a
substring.

Add `_recorded_decision_sentences(decisions)` that returns only exact strings:

```python
f"Engine decision log recorded {decision.decision.value.upper()} {decision.ticker} on {decision.timestamp.date().isoformat()}."
```

Add `_question_requests_recorded_decisions(question)` matching whole words
`decision`, `decisions`, `trade`, `trades`, or `action`. In `/api/chat`, append
the rendered record strings only when this helper returns true. Never append a
risk-control statement because SharedState has no recorded risk-control event
collection. If filtering and allowed rendered records both yield no content,
return `_SAFE_READ_ONLY_LIMITATION` with the disclosure.

- [ ] **Step 4: Run focused and full engine tests**

Run:

```bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests -q
```

Expected: all tests pass; model action language is never an exception and only
server-created decision records contain BUY/SELL/HOLD wording.

- [ ] **Step 5: Commit the closed policy**

```bash
git add engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "fix: render verified historical decisions"
```

### Revision: deterministic server-rendered chat commentary

Model prose cannot be made safe with a blacklist. The model becomes a bounded
topic selector only: it returns JSON containing zero or more values from
`account`, `pnl`, `positions`, `risk`, and `decisions`. The server validates
that selection and produces every visible sentence from current factual state.
No model-authored content is returned to the client.

### Task 9: Render factual chat responses from validated topics

**Files:**
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write failing deterministic-response tests**

Add a fake LLM that returns `{"topics": ["pnl", "decisions"]}`. With an
equity record, P&L attribution, and one timestamped AAPL BUY decision, assert
the `/api/chat` answer contains only server-rendered daily P&L facts and the
exact server decision record; assert it does not contain arbitrary LLM text.

Add tests showing these model outputs never appear in the response and instead
return either safe selected facts or the safe limitation:

```python
"Short AAPL now."
"Set a trailing stop."
"The engine action was to reduce AAPL exposure."
```

Add validation tests: an unknown selected topic is ignored, a JSON object with
no valid topics yields the safe limitation, malformed non-JSON model output
raises the existing 503 assistant-unavailable error, and a valid `positions`
selection renders only current ticker/quantity/average-entry data. Preserve the
disclaimer on all successful responses.

- [ ] **Step 2: Run the focused tests and verify the free-form path fails**

Run: `PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q`

Expected: tests fail because the endpoint currently exposes LLM prose and does
not parse topic JSON.

- [ ] **Step 3: Implement topic validation and server renderers**

Define `_ALLOWED_CHAT_TOPICS = frozenset({"account", "pnl", "positions",
"risk", "decisions"})`. Add `_selected_chat_topics(raw)` that calls
`json.loads`, accepts only a mapping with a list-valued `topics`, and returns
the ordered de-duplicated intersection with `_ALLOWED_CHAT_TOPICS`; invalid JSON
raises `ValueError`.

Add `_render_chat_topics(state, topics)` that returns only template-generated
sentences from `_chat_context(state)`: currency equity/day-start facts for
`account`, daily/realized/unrealized P&L only when values exist for `pnl`, open
position ticker/quantity/average-entry facts for `positions`, factual
kill-switch/daily-stop state for `risk`, and `_recorded_decision_sentences` for
`decisions`. It must not render a risk-control action record because there is
no recorded risk-control-event source.

Replace the free-form output use in `/api/chat`: prompt the model to return
only `{"topics":[...]}` and treat all other output as unavailable. Render the
selected topics, use `_SAFE_READ_ONLY_LIMITATION` when rendering is empty, and
return the same structured answer/disclaimer contract.

- [ ] **Step 4: Run focused and full engine tests**

Run:

```bash
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py -q
PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests -q
```

Expected: the complete suite passes and unsafe LLM prose is never visible.

- [ ] **Step 5: Commit deterministic rendering**

```bash
git add engine/src/autotrader/ipc.py engine/tests/test_ipc.py
git commit -m "fix: render chat commentary from factual topics"
```

### Task 10: Final release verification

**Files:**
- Verify only: all feature files from `origin/main...HEAD`

- [ ] **Step 1: Run release checks**

Run the full engine suite, `bash app/build-app.sh`, and `git diff origin/main...HEAD --check`.

- [ ] **Step 2: Obtain a fresh independent release review**

Ask a review-only agent to verify that no LLM-provided prose reaches the API
response, all server text is sourced from SharedState, the legacy Swift response
decoder remains compatible, and chart behavior remains within the approved
spec. Do not declare success with open Critical or Important findings.

### Task 11: Close selector, legacy-record, and factual market-data gaps

**Files:**
- Modify: `engine/src/autotrader/models.py`
- Modify: `engine/src/autotrader/state.py`
- Modify: `engine/src/autotrader/ipc.py`
- Modify: `engine/tests/test_models.py`
- Modify: `engine/tests/test_state.py`
- Modify: `engine/tests/test_ipc.py`

- [ ] **Step 1: Write failing boundary tests**

Add tests that a legacy persisted decision without a timestamp restores as
`timestamp is None` and is not present in chat context or a rendered historical
decision. Add a selector test that `{"topics":["positions","unknown"]}`
returns the existing 503 rather than a partial response.

Add market tests with a fake provider: a `market_session` topic renders factual
open/closed engine-schedule state, and a `bars` topic with `AAPL` in the
question calls `provider.bars("AAPL", history_range=HistoryRange.ONE_DAY)` and
renders the latest bar's ticker, timestamp, O/H/L/C, and volume. A missing
ticker, missing provider, empty bars, or provider error must render no bar
sentence and never expose an exception.

- [ ] **Step 2: Run the focused tests and verify the current code fails**

Run: `PYTHONPATH=engine/src /Users/nthnp/Developer/stockmarkethelper/engine/.venv/bin/python -m pytest engine/tests/test_ipc.py engine/tests/test_models.py engine/tests/test_state.py -q`

Expected: legacy decisions receive a fabricated timestamp, unknown topics are
accepted, and market/bar topics are unsupported.

- [ ] **Step 3: Implement fail-closed selectors and factual market templates**

Make `AgentDecision.timestamp` type `datetime | None` while retaining
`default_factory=_now` for new decisions. In `_decode_decision`, pass
`timestamp=None` when legacy serialized data omits the field. In chat context
and `_recorded_decision_sentences`, omit timestamp-less decisions.

Add `market_session` and `bars` to `_ALLOWED_CHAT_TOPICS`; reject the entire
selector when any selected topic is not in that set. Use
`is_market_open(datetime.now(timezone.utc))` to render an engine-schedule
market-session fact. For bars, extract one uppercase ticker from the question,
call only the existing `provider.bars(ticker, history_range=HistoryRange.ONE_DAY)`,
and render the final returned bar using template values. Pass `provider` and
question into `_render_chat_topics`; swallow provider failures by omitting the
bar sentence. Remove unused free-form sentence-filter helpers.

- [ ] **Step 4: Run full verification and commit**

Run the focused command above, the full engine suite, and `git diff --check`.
Commit with:

```bash
git add engine/src/autotrader/models.py engine/src/autotrader/state.py engine/src/autotrader/ipc.py engine/tests/test_models.py engine/tests/test_state.py engine/tests/test_ipc.py
git commit -m "fix: render verified market chat facts"
```
