# Rule-Based Exits & Per-Trade P&L — Design Spec

**Date:** 2026-08-26
**Status:** Proposed (awaiting approval)

## Overview

Add deterministic exit logic (stop-loss, take-profit, flatten-at-close) and per-trade
realized/unrealized P&L tracking, then feed real results into the daily summary. Exits are
pure rules in Python — the LLM never controls selling. Its blast radius stays bounded to
"which stock to buy"; everything touching real capital (sizing, circuit breakers, exits)
remains deterministic code outside the model.

## Goals & success criteria ("done")

- Positions exit deterministically via stop-loss, take-profit, and flatten-at-close.
- Every closed position is recorded with its realized P&L and the reason it exited.
- Open positions are marked-to-market (unrealized P&L) at the end of the day.
- The daily summary reports real per-trade results (what went well/wrong) instead of
  invented outcomes.

## Decisions (locked)

| Topic | Decision |
| --- | --- |
| Exit control | Deterministic rules in Python, outside the LLM |
| Stop-loss | Configurable %, default 2% below entry |
| Take-profit | Configurable %, default 3% above entry |
| Flatten | Market-sell all open positions at a configurable time before close (default 15:55 ET) |
| Exit order type | Market |
| P&L | Realized per closed trade; unrealized = mark-to-market via latest price |
| LLM role | Unchanged — entries only; never sells |

## Models (add to `engine/src/autotrader/models.py`)

```python
@dataclass
class ClosedTrade:
    ticker: str
    qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    exit_reason: str          # "stop_loss" | "take_profit" | "flatten"
    opened_at: datetime
    closed_at: datetime
```

`State` gains `closed_trades: list[ClosedTrade]` (persisted alongside `decisions`).

## Config (add to `engine/config/config.yaml`)

```yaml
exits:
  stop_loss_pct: 0.02
  take_profit_pct: 0.03
  flatten_at_close: true
  flatten_time: "15:55"     # Eastern; parsed to time
```

`Config` gains `stop_loss_pct`, `take_profit_pct`, `flatten_at_close`, `flatten_time`.

## Components

- **`exits.py` (new)** — `ExitManager`:
  - `evaluate(position, current_price) -> str | None` returns `"stop_loss"`, `"take_profit"`,
    or `None`, comparing `current_price / entry_price - 1` against the configured thresholds.
    If both would trigger (price gap), stop-loss wins (conservative).
- **`execution.py`** — add `sell(ticker, qty)` (reuse `market_order` with `Side.SELL`).
- **`runner.py`** — `manage_exits()` runs each scan: for every open position, fetch latest
  price, evaluate exit, and on a trigger place a SELL, record a `ClosedTrade`, and remove the
  position from the open set. Also handles time-based flatten.
- **`state.py`** — persist/load `closed_trades` (with type-safe reconstruction like decisions).
- **`summary.py`** — slice 2: include per-trade realized P&L and end-of-day unrealized P&L.

## Data flow

1. Each scan (market open): `manage_exits()` checks open positions against stop/tp.
2. Trigger → market SELL → `ClosedTrade(realized_pnl=(exit-entry)*qty)` recorded.
3. At `flatten_time` (before close): SELL all remaining positions, each recorded as
   `exit_reason="flatten"`; idempotent via a per-day `flattened` flag.
4. After close: summary includes realized per-trade results + unrealized for any position
   still open (only if flatten was disabled or a sell didn't fill).

## Edge cases

- No position to sell / already closed → no-op, log only.
- Stop and TP both breached in one gap → stop-loss wins.
- Flatten triggered after a stop already closed the position → idempotent, skip.
- `flatten_at_close: false` → leave positions overnight; mark-to-market only.
- Market closed → loop is already gated by `is_market_open`, so no after-hours orders.

## Testing (TDD, all in `engine/tests/`)

- `test_exits.py`: stop triggers, tp triggers, no trigger, boundary at exactly ±threshold,
  stop-wins-over-tp on gap.
- `test_runner.py` (extend): `manage_exits` places SELL, records `ClosedTrade` with correct
  P&L, removes the position; flatten records all open positions.
- `test_state.py` (extend): `closed_trades` round-trips.
- `test_summary.py` (extend): prompt includes realized P&L per trade.

## Out of scope

- LLM-driven exits (explicitly rejected).
- Trailing stops, ATR/volatility-based stops, time-based intraday stops.
- Partial-fill-aware P&L (v1 approximates exit price as the latest observed price).
- Deployment/scheduling (e.g., GitHub Actions cron to start the engine) — separate concern.

## Slices

1. **Exits + P&L tracking** — `ClosedTrade` model, config keys, `ExitManager`, `execution.sell`,
   `runner.manage_exits`, `state` persistence. Fully tested.
2. **Summary integration** — feed realized + unrealized P&L into `daily_summary`, replacing
   the "per-trade results are not available" guard with the actual numbers.
