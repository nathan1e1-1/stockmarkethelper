# Stock Market Trading Agent — Design Spec

**Date:** 2026-08-25
**Status:** Approved (awaiting implementation plan)

## Overview

A native macOS application that lets autonomous agents watch the US stock market in
real time and execute trades to generate profit. After market close, the agents write
an in-depth daily summary covering what went well, what didn't, and what to improve.

The system paper-trades for the first two weeks. Moving to real money is a **manual,
gated decision** — only if the paper run shows clear upside/profit and the user approves.
A non-negotiable risk rule halts all trading when equity drops 10% below its peak.

## Goals & success criteria ("done")

- Agents watch the market in real time and place long-only US equity trades (paper first).
- Trades are driven by LLM reasoning over inspectable quant signals, not a black box.
- A SwiftUI macOS app shows live P&L, searchable stock charts, positions, and summaries.
- A post-close daily summary is generated and delivered automatically.
- Risk controls are enforced outside the LLM and cannot be overridden by it.
- A 2-week paper-trading run validates the system before any real money.

## Decisions (locked during brainstorming)

| Topic | Decision |
| --- | --- |
| Decision model | Hybrid — LLM agents reason over quant signals; execution gated by hard rules |
| Instruments | US equities, long-only |
| Broker | Alpaca (paper now, real later) |
| Timeframe | Intraday (positions flattened at close) |
| Strategies (v1) | Momentum + Sentiment catalyst |
| App form | Native macOS (SwiftUI) |
| Universe | Daily screener (top 20 by volume / gainers / movers) |
| Risk — sizing | 2% of equity per trade |
| Risk — concurrency | Max 3 open positions |
| Risk — hard stop | Flatten all + freeze if equity drops 10% from peak |
| Risk — daily stop | Stop trading for the day at −5% from day-start equity |
| LLM runtime | Local model via Ollama |
| Paper capital | $100k |

## Architecture

Two processes, connected by a local WebSocket + REST interface.

### Process 1 — Python Trading Engine (headless daemon)

The "always on" process that owns everything market-hours critical:

- **Data ingestion** — Alpaca WebSocket stream (real-time bars/quotes) + REST snapshots.
- **Universe builder** — daily screener (top 20 by volume / gainers / movers) each pre-market.
- **Signals** — independent, inspectable numbers:
  - momentum score
  - sentiment score (Ollama + news feed)
  - valuation/factor score (reserved, not built in v1)
  - event flag (reserved, not built in v1)
- **Regime filter** — realized volatility + trend strength over the last 20 trading days
  dials signal weights up/down (scales momentum weighting between trending and choppy
  regimes, so the same signal behaves differently in each).
- **Composite scoring** — weighted sum of signals (not an all-or-nothing vote).
- **Decision agent** — local Ollama model reasons over the composite + context and returns
  BUY / HOLD / SELL with rationale. It only emits decisions; it cannot size, order, or halt.
- **Risk layer** — position sizing + circuit breakers (separate from signals).
- **Execution** — Alpaca paper (later real) orders.
- **State & journal** — positions, equity, every decision + rationale, per-signal values.
- **Daily summary** — after close, Ollama writes the recap.
- **IPC server** — serves live state to the app over localhost WebSocket + REST.

### Process 2 — SwiftUI macOS app (thin client)

Renders state; holds no trading logic:

- Dashboard — live P&L, equity curve, agent status, kill-switch state.
- Charts — searchable ticker charts (candles, volume, trades marked).
- Positions & order log.
- Daily summary view.
- macOS notifications for kill-switch / daily-stop events.

The engine keeps trading even if the app is closed; a UI crash can never trigger or
stop a trade.

## Data flow & trading loop

**Pre-market**
1. Engine boots, connects Alpaca stream + Ollama, loads config/state.
2. Universe builder runs the screener → today's candidate list.

**Market hours**
3. Stream bars/quotes for candidates in real time.
4. On a scan cadence (~1 min), compute signals → apply regime filter → composite score.
5. When a composite score crosses the entry threshold, the decision agent returns
   BUY / HOLD / SELL + rationale.
6. BUY → risk layer validates sizing/concurrency/circuit breakers → Alpaca paper order.
7. Positions monitored; risk layer evaluates equity continuously and can flatten all +
   freeze on breach.
8. UI subscribes over WebSocket and renders everything live.

**Post-close**
9. Intraday positions are flattened.
10. Ollama writes the daily recap (well / not well / improve); stored, pushed to app,
    plus a macOS notification.

## Risk controls (non-negotiable)

Enforced in the Python risk layer, re-evaluated on every tick — not just at decision time:

- Position sizing: 2% of current equity per trade.
- Concurrency: max 3 open positions.
- Hard kill-switch: equity drops 10% from peak → flatten everything + stop until the
  user investigates and re-arms manually.
- Daily loss limit: stop trading for the day at −5% from day-start equity.
- Regime filter: signal weights scale with realized volatility + trend strength.
- LLM guardrails: the model can only emit BUY/HOLD/SELL + rationale. Sizing, order
  placement, and halts are the sole authority of the risk layer.

## Error handling

- Alpaca stream/API failure → retry with backoff; stale data pauses new orders.
- Ollama unreachable → block decisions and new entries, but keep risk controls active
  (flattening still works).
- Engine crash → restart reloads state from disk; safe-by-default (no new orders until
  re-initialized).
- Network partition → freeze order placement, log, resume on reconnect.
- Every decision, order, and signal is journaled so any day is reconstructable.

## Testing

- Python: pytest TDD per module — signals, regime filter, composite scoring, risk layer
  (sizing / kill-switch / daily stop), execution (mocked Alpaca), summary generation.
- Alpaca paper trading is the integration testbed (2 weeks before real money).
- SwiftUI: unit tests for view models; charts and manual testing on device.
- Deterministic replay: replay a prior day's data through the engine to validate the
  pipeline end-to-end before live paper.

## Scope & phasing

**v1 (this project, to reach the 2-week paper run)**
- Two-process architecture, Alpaca paper trading, SwiftUI dashboard + charts.
- Momentum + sentiment-catalyst signals, regime filter, composite scoring.
- Local Ollama decision agent + daily summary.
- Full risk layer (2% sizing, 3 concurrent, 10% kill-switch, 5% daily stop).
- Journaling of every decision/signal/order.

**Out of scope for v1 (future)**
- Real-money execution (gated on 2-week paper results).
- Valuation/factor score and event flag signals.
- Short selling, options, multi-asset.
- Full backtesting harness (replay validation only in v1).
- Live self-adjusting signal weights (v1 uses fixed weights; regime filter already
  provides adaptive scaling).

## Reusable existing work

- **AlphaStream (`/Users/nthnp/Documents/stockemailer`)** — provider protocols
  (`FilingProvider` / `NewsProvider` / `MarketDataProvider`), yfinance market snapshots
  (price, 200DMA, RSI), a Finnhub provider + resilient retry provider in the
  `finnhub-market-provider` worktree, VADER news sentiment, weighted scoring, YAML
  config, pytest TDD patterns.
- **pokebot (`/Users/nthnp/Documents/pokebot`)** — Playwright scraping patterns,
  state-diff eventing, Discord notifier, GitHub Actions cron scheduling, TDD plan format.
