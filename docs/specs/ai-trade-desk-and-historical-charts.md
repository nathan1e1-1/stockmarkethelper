# AI Trade Desk and Historical Charts

## Goal

Extend the macOS trading monitor with a read-only AI Trade Desk on the Dashboard and a full-equity search and historical-chart experience in Charts. The monitor must remain available outside market hours and must never gain the ability to place or modify orders.

## What done looks like

- The Dashboard shows an **AI Trade Desk** side panel alongside account metrics. A user can ask natural-language questions about current trades, risk, daily performance, and ways to improve the trading process.
- The assistant answers with the current engine snapshot: account equity, positions, recent decisions, risk-stop state, and the daily summary when available. It uses the configured local Ollama model.
- The assistant is read-only by design: its endpoint has no executor, order client, or trading action. It states uncertainty and does not guarantee returns or recommend bypassing the configured risk controls.
- The Charts tab provides type-ahead search over all active, tradable US equities available through Alpaca. Suggestions include ticker and company name, and can be chosen by keyboard or pointer.
- A selected symbol displays a candlestick chart with `1D`, `5D`, `1M`, `6M`, `1Y`, and `Max` range controls. `Max` shows the complete history available from the provider.
- Users can zoom and pan the displayed history and return to the selected default range. Longer ranges use coarser bars and bounded point counts so the chart stays responsive.
- Clear loading, empty, offline, and retry states are available for chat, suggestions, and chart data.

## User experience

### Dashboard: AI Trade Desk

The current dark dashboard remains the primary surface. On sufficiently wide windows, a fixed-width AI Trade Desk panel appears to its right; on narrower windows, it moves below the main dashboard content rather than compressing metrics or creating horizontal scrolling.

The panel contains a concise conversation history, useful question starters, a visible input label, and a send button. Sending is disabled while a response is loading. The current account data stays visible while the user reads or asks questions. Messages exist only for the current app session; conversation history is not persisted across app or engine restarts in this release.

If the engine or Ollama is unavailable, the panel explains the issue and offers a retry action. It must never present a failed or stale response as current analysis.

### Charts: equity discovery and exploration

The ticker field shows a limited, debounced suggestion list as soon as the user types one or more characters. Each result presents a symbol and company name. Arrow keys and Return select a result, Escape closes the list, and pointer selection has the same effect. A no-results state tells the user that no active, tradable US equity matched the query.

The chart header identifies the selected symbol, latest displayed close, selected range, and bar interval. Range controls use native SwiftUI buttons and clearly expose their selected state. The chart supports normal desktop zoom/pan interaction plus an explicit reset action. Candles use both color and fill/outline treatment so direction is not communicated by color alone. A concise accessible text summary and tabular OHLC fallback accompany the chart interaction.

## Data and API design

The Python engine remains the only process that talks to Alpaca and Ollama. The SwiftUI app continues to communicate only with the local FastAPI server.

| Endpoint | Purpose | Read-only data used |
| --- | --- | --- |
| `GET /api/assets?query=&limit=` | Type-ahead equity discovery | Cached active, tradable US equity symbols and names from Alpaca |
| `GET /api/bars?ticker=&range=` | Historical chart data | Alpaca OHLCV bars at a range-appropriate interval |
| `POST /api/chat` | AI Trade Desk response | Question plus the current `SharedState` snapshot and configured Ollama model |

Asset search results are capped and case-insensitive. The engine caches the Alpaca asset catalogue rather than requesting the complete list on every keystroke. The bar endpoint validates both the ticker and range before querying the provider. The provider chooses a time frame and date window appropriate to the requested range, downsampling or bounding returned bars when necessary; it must preserve the requested period rather than silently returning the existing seven-day, one-minute default.

The chat prompt includes a compact, factual context block derived from `SharedState`. It may interpret that data and suggest questions or risk-aware process improvements, but it cannot initiate execution. The response should be clearly described as informational analysis, not a promise of profit or personalised investment advice.

## Constraints

- Keep Alpaca paper/live configuration and all existing risk controls unchanged.
- Do not add order placement, order modification, account mutations, or autonomous actions to the app or API.
- Use the existing locally configured Ollama model; do not add a cloud LLM service.
- Do not edit lockfiles or vendor code.
- Preserve the existing dark design tokens, native SwiftUI controls, keyboard navigation, dynamic text support, visible focus, and clear loading/error states.
- The dashboard must continue to open and show its offline or initial state at any time of day; market hours only gate scanning and trading.

## Out of scope

- Executing trades through chat, including confirmation flows.
- Persisting or syncing chat history.
- News-driven research, fundamental analysis, options, crypto, or international-equity support.
- Live streaming prices or a new real-time transport; the app continues to use the existing polling model.
- Changing the trading strategy, entry threshold, position limits, exits, or risk policy.

## Verification

- Python tests cover asset-query filtering/capping, range validation and provider time-frame selection, and chat context/error responses. Endpoint tests use fakes and confirm no execution dependency is passed to chat.
- Swift tests cover API decoding and range/query request construction where the current package supports it.
- `cd engine && .venv/bin/pytest -q` passes.
- `cd app/TradingAgentApp && swift build` succeeds.
- Manual QA verifies: one-character symbol discovery, keyboard selection, each time range, zoom/pan/reset, unavailable engine/Ollama, and a market-closed launch.
