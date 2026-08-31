# P&L Attribution for AI Trade Desk

## Goal

Give the read-only AI Trade Desk enough factual account data to explain what is driving the current day’s P&L without inventing price or trade information.

## Done looks like

- The engine computes and publishes a P&L breakdown for the current account snapshot:
  - total daily P&L and daily P&L percentage;
  - per-open-position current price, unrealized P&L, and unrealized P&L percentage;
  - realized P&L from closed trades for the current day;
  - the current account equity and day-start equity used for the calculation.
- The chat endpoint includes this breakdown in its JSON factual context.
- The assistant prompt directs the model to explain the largest realized and unrealized contributors when asked about P&L, to distinguish them clearly, and to state when a contributor is unavailable.
- The assistant remains read-only: no orders, recommendations, promised returns, or changes to risk controls.
- Existing status, trading, and chart behavior remain unchanged.

## Data flow

`main.py` refreshes account positions and obtains their latest prices from the existing provider. It constructs a pure P&L snapshot from those inputs plus `runner.closed_trades`, then stores it in `SharedState`. The FastAPI chat route serializes that snapshot as untrusted factual JSON alongside the existing account context. No chat path receives an executor or order client.

## Constraints

- Use only existing account, market-data, and closed-trade data; do not add a new external service.
- A latest-price failure for one position must not prevent other contributors or the total account context from being published. That position is marked unavailable.
- Unrealized P&L is calculated as `(current price - average entry price) × quantity`; realized P&L is the sum of current-day `ClosedTrade.realized_pnl` values.
- Totals must identify whether they are realized or unrealized; do not imply that unrealized gains are locked in.
- Tests use fakes and must not call Alpaca or Ollama.

## Out of scope

- Changing position sizing, signals, entries, exits, or risk controls.
- Trade execution, trade recommendations, or automatic actions from chat.
- Historical tax lots, fee attribution, benchmark comparisons, or persistent chat history.

## Verification

- Unit tests cover total, per-position, unavailable-price, and realized-P&L calculations.
- Chat endpoint tests assert that the P&L breakdown is present and the prompt distinguishes realized and unrealized contributors.
- Full Python suite passes.
