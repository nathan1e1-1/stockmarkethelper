# Readable P&L Explanations in the AI Trade Desk

## Goal

Turn a P&L question into a concise, plain-English factual explanation. The
answer must show what the account data can attribute and explicitly identify
any part of the account-level change that the engine cannot attribute. Market
news is not shown in AI responses for this release, and the answer never gives
trading advice.

## Done looks like

- When asked what is driving today's P&L, the assistant returns an organized
  explanation instead of a ledger-like list of P&L fields and decision-log
  entries.
- The explanation begins with the current daily P&L, then separates realized
  P&L, open-position unrealized P&L, and any un-attributed reconciliation
  amount.
- For every open position included in the current account snapshot, the
  explanation has access to ticker, quantity, entry price, latest price,
  unrealized P&L, unrealized P&L percentage, latest one-day open and close,
  and the corresponding one-day price change when those values are available.
  It discusses the largest positive and negative contributors first, while a
  compact details section preserves the remaining available positions.
- For every recorded trade closed on the current trading day, the explanation
  has access to ticker, quantity, entry price, exit price, realized P&L, exit
  reason, and recorded close time. It summarizes the largest gains and losses
  first and retains the remaining records in the details section.
- Market-news context is not shown in AI responses for this release.
- Missing prices, bars, news, or trade records do not fail the chat response.
  The response says what is unavailable and omits that individual detail.
- The existing informational disclosure remains below every response. Chat
  remains read-only and cannot place orders, recommend an action, change risk
  controls, or bypass risk controls.

## Response contract

The model continues to return only a bounded JSON topic selector; no model
prose reaches the UI. A `pnl_explanation` topic causes the server to render
plain English from verified data in this order:

1. **Today at a glance** — daily dollar and percentage P&L, followed by the
   realized and unrealized portions.
2. **What is attributed** — concise contributor sentences for open positions
   and current-day closed trades. A security's price change is described as an
   observed move; it is not predicted or tied causally to a headline.
3. **What remains unexplained** — `daily_pnl - realized_pnl - available
   unrealized_pnl`, reported only when materially non-zero. The text states
   that the current ledger does not attribute this amount, without guessing at
   fees, previous activity, deposits, or other causes.
4. **Price and trade details** — compact factual records for the remaining
   available account positions and recorded current-day trades.

The selector prompt is narrowed so P&L-driver questions choose
`pnl_explanation` rather than the raw `pnl` and `decisions` topics. Existing
non-P&L topics retain their current factual behavior. Friendly Eastern Time
timestamps replace raw ISO timestamps in user-visible P&L explanations.

## Data flow

`main.py` refreshes the account snapshot. It obtains latest prices for open
positions, one-day bars needed to calculate observed day moves, and existing
provider news for account-relevant tickers. A pure P&L-analysis builder creates
a structured snapshot containing contributors, current-day closed trades,
price-data availability, news availability, and the reconciliation amount.
This snapshot is stored in `SharedState`.

The FastAPI chat endpoint serializes this snapshot as untrusted factual data.
The local model may select `pnl_explanation`; the server performs all visible
writing through deterministic renderer functions. The renderer does not
receive an executor, order client, or account mutation capability.

## Constraints

- Use the existing Alpaca account, market-data, and news clients only; do not
  introduce a paid service or a new external market-data provider.
- Treat the account's daily P&L as authoritative for the total. Do not force
  it to equal recorded realized plus available unrealized P&L.
- Do not imply a price move was caused by a news item unless the supplied data
  itself makes that causal relationship explicit; the initial implementation
  does not make causal claims.
- Do not quote or reproduce article bodies. Render a bounded number of
  metadata fields and short supplied summaries only.
- Preserve the strict actionable-language policy: no buy, sell, hold,
  position-sizing, stop-loss, hedge, target, rebalancing, or predictive
  instruction. A historical engine action may be described only as a dated,
  source-attributed record.
- Partial provider failure must produce a truthful partial explanation, not a
  generic assistant-unavailable error.

## Out of scope

- Portfolio-wide news unrelated to a current position or current-day recorded
  trade.
- Unverified causal analysis, sentiment claims outside supplied data, or
  generated investment recommendations.
- Historical tax lots, transaction fees, transfers, dividends, corporate
  actions, benchmark attribution, or reconciliation with Alpaca activity
  history not already captured by the engine.
- Changes to execution, scoring, risk controls, chart behavior, or market-hour
  gating.

## Verification

- Unit tests cover plain-English rendering for a mixed realized/unrealized
  day, a positive and negative contributor, a reconciliation amount, and no
  available contributors.
- Provider tests cover normalization of relevant news metadata and one-day
  price data without live Alpaca or Ollama calls.
- Chat endpoint tests prove P&L-driver questions select the readable path,
  keep model prose out of the response, preserve the disclosure, and return a
  partial answer when individual price, bar, or news lookups fail.
- Existing chat safety tests continue to reject non-JSON selector output and
  actionable model prose.
- The full Python suite and Swift app build pass.
