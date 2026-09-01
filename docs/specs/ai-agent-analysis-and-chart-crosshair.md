# AI agent analysis and chart crosshair

## Goal

Make the in-app assistant useful for factual account and market analysis while
retaining its read-only trading safety boundary. Add precise pointer inspection
to every current data chart in the macOS app.

## Done looks like

- The assistant answers factual questions about the supplied account status,
  P&L attribution, positions, decisions, bars, and market-session data.
- Responses clearly disclose: "For informational purposes only — not
  investment advice. Use your own judgment."
- The assistant continues to refuse or safely redirect requests for order
  placement, personalized buy/sell/hold instructions, guaranteed returns, or
  risk-control bypasses.
- Each stock candlestick chart shows a hover crosshair and a tooltip for the
  nearest candle with its timestamp, open, high, low, close, and volume.
- The dashboard P&L chart uses the same crosshair interaction and shows its
  timestamp, account equity, and P&L value.
- The chart controls remain usable without a pointing device; the current
  accessible OHLC/text alternatives remain available.

## Design

### AI analysis mode

The API system prompt will explicitly authorize analysis of the factual context
it receives. It will ask for concise explanation of observed data, P&L drivers,
trends, uncertainty, and non-prescriptive risk context. The prompt will retain
the existing no-order, no-return-guarantee, no-risk-bypass, and no
buy/sell/hold-recommendation requirements.

The response safety filter remains the final enforcement point. It will block
recommendations and unsafe operational guidance but will not reject a factual
explanation merely because it discusses P&L, positions, market movement, or
uncertainty. The API returns the disclosure alongside each response; the app
renders it consistently beneath the answer.

### Actionable-language output policy

The assistant produces factual market commentary only. It must not produce
actionable guidance, including buy, sell, or hold recommendations in any
framing; prospective risk-control instructions such as stops, sizing, hedging,
targets, or rebalancing; predictive framing that implies an action; or
soft-hedged recommendations.

The sole exception is a strictly historical action or risk-control measure that
is explicitly rendered by the server from a named, dated, recorded decision in
the supplied context. Model-produced action or risk-control language is always
removed; the server may append an exact historical decision record derived from
verified data. That record names its source and date, uses past tense, and may
not generalize into forward-looking guidance. Historical risk-control language
is not emitted until a matching recorded risk-control event exists in the
context.

The visible response is server-rendered from supplied facts. The model may
select a bounded set of factual topics, but it does not supply user-visible
prose. Server templates render account, P&L, positions, risk state, and
timestamped engine decisions. It also renders current market-session status and
the latest available one-day bar for a ticker named in the question, using the
existing provider. Timestamp-less legacy decisions are excluded rather than
assigned an invented date. This removes open-ended action language from the
output path entirely.

### Chart interaction

The selected interaction is a pointer-following vertical crosshair (Option A).
Swift Charts resolves the pointer's x position to the nearest chart datum. The
overlay draws a vertical rule and an in-chart tooltip that avoids overflowing
the plot bounds.

For candlesticks, the tooltip displays the time and O/H/L/C/volume values. For
the P&L chart, it displays the time, equity, and P&L from the day-start equity.
The overlay is attached to each existing data chart; it does not alter history
fetching, selected range, panning, or zooming behavior.

## Constraints

- The trading engine remains read-only through the chat API; chat must never
  invoke order placement or alter engine risk controls.
- Do not present personalized investment advice or imply a specific trading
  action.
- Admit a buy/sell/hold or risk-control action only when it is a dated,
  source-attributed historical fact found in the supplied data.
- Use only data already provided by the application/API; no new paid or
  external market-data dependency is introduced.
- Preserve existing chart range, zoom, and accessibility behavior.

## Out of scope

- Automated trade execution from chat.
- Personalized portfolio allocation, price targets, or buy/sell/hold calls.
- New chart types, indicators, or streaming subscriptions.
- Changes to the market-hours trading gate.

## Verification

- Engine unit tests cover a factual P&L explanation that passes the guardrail,
  a disallowed recommendation that is redirected, and the disclosure returned
  to the app.
- Swift tests cover nearest-point lookup and tooltip values where the package
  test target permits it; the app package builds successfully.
- Manual app verification confirms the tooltip appears while hovering an
  intraday and daily candle, and on the dashboard P&L chart.
