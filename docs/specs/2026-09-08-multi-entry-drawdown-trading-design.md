# Design: Multi-Entry Drawdown Trading Profile (`multi-entry`)

Date: 2026-09-08
Status: Approved design — awaiting implementation plan

## Problem

The engine's single approved paper profile (`initial`) is fail-closed by design:
one entry per session, one concurrent position, a 5% daily-loss halt, and a 10%
kill-switch. The user wants the engine to trade throughout the whole trading day,
entering multiple positions, keeping trading through drawdowns, and letting a
position that is dipping — but likely to recover — be held rather than dumped.
This requires a risk-profile change plus new exit and sizing logic.

This spec introduces a second approved profile (`multi-entry`) alongside the
existing `initial` profile, which remains byte-for-byte intact.

## Goals / "Done"

- A second hardcoded‑approved risk profile, `multi-entry`, passes `_validate_paper_profile`.
- Up to 5 concurrent positions; unlimited entries per session before the daily‑risk gate engages.
- Position size is computed risk‑first: `qty = floor(equity × risk_per_position_pct / (price × stop_loss_pct))`.
- The engine keeps trading through drawdowns until market close, bounded by two session-level limits (realized-loss entry gate and −25% equity floor).
- Exits are two independent checks per tick: (1) an unconditional hard stop-loss and (2) a dynamic hold/exit/take-profit model that never sees the stop.
- The existing `initial` profile behaves exactly as it does today.
- Full test suite passes.

## Requirements

### R1 — Risk profile and configuration

- Add approved profile `multi-entry` to `_validate_paper_profile` with exact values:
  - `max_positions: 5`
  - `max_entries_per_session: unlimited` (no cap; session gating is via the realized-loss gate instead). **Decision: sentinel `sys.maxsize`** via a named constant (e.g. `UNLIMITED_ENTRIES = sys.maxsize`). The field stays `int`, and the only two consumers (`risk.py:107` and `risk.py:246`) are strict comparisons — neither does arithmetic on the value — so no call site changes and no `None`-handling spread. A `None`/`Optional[int]` representation was rejected: it would force every future consumer to handle `None` explicitly.
  - `risk_per_position_pct: 0.01` (1%)
  - `max_daily_risk_pct: 0.05` (5%)
  - `stop_loss_pct: 0.05` (5%, shared stop distance)
  - `kill_switch_pct: 0.25` (−25% equity floor)
  - `max_position_pct` / `max_gross_exposure_pct` removed from the direct profile assertions — exposure is derived from the risk math, not imposed. The ceiling is 5 × 20% = 100% gross.
  - `max_snapshot_age_seconds: 120` (unchanged)
- `daily_loss_pct` no longer halts trading for `multi-entry`. It remains informational in the status API.
- The `initial` profile validation remains unchanged.
- Validation asserts internal consistency, e.g. `max_daily_risk_pct == risk_per_position_pct × max_positions`, and **stop_loss_pct is the single source of truth shared by both sizing and the hard stop check** — sizing cannot reference a different distance than exits enforce.

### R2 — Risk-based position sizing

- `qty = floor(equity × risk_per_position_pct / (price × stop_loss_pct))`, floored at integers (no partial shares). Per-position notional ≈ 20% at the default budget.
- Quantity is computed from the quote at sizing time. The stop is enforced against the actual fill (`position.avg_entry_price`). If fill differs from quote, realized risk drifts slightly from exactly 1% — accepted and documented; not worth staging positions around fill uncertainty.
- Position sizing, reservation, and risk bookkeeping reuse the existing `reserve_entry` + `apply_order_delta` flow.

### R3 — Exit model: two independent checks

Per tick, per open position, in this exact order:

1. **Hard stop-loss — unconditional, checked first, cannot be vetoed.** If `current_price ≤ avg_entry_price × (1 − stop_loss_pct)` → close, reason `stop_loss`. The dynamic model is never invoked for this check. Structurally separate:
   - the dynamic evaluator does not receive the stop price or stop config, and cannot veto or modify check (1).
2. **Dynamic hold/exit — only when the stop has not been hit.** Uses trend (SMA short vs long), RSI, regime (`RegimeFilter`), and sentiment (`SentimentSignal`, reusing the existing Ollama agent path) to decide:
   - `hold` — keep the position open; a dip with intact trend/regime is held.
   - `exit_early` — trend/regime/sentiment actually broke down (reason recorded, e.g. `trend_break`, `sentiment_turn`).
   - `take_profit` — bank gains when the model judges the move done. The static `take_profit_pct` acts as a decision-space floor, not an auto-sell.
- Dynamic evaluator failures fall back to **no-op hold**: the position stays open; the hard stop still covers downside.

### R4 — Concurrency and lifecycle

- Up to 5 concurrent positions. New entries allowed while others are open, gated only by: composite ≥ threshold, risk state `ACTIVE`, not at cutoff, free slot, and the realized-loss gate (below).
- `can_scan` unchanged: restored, account valid, broker-clean, `ACTIVE`, no cutoff latch.
- `daily_stop_triggered` is dropped from `tick()` under `multi-entry`. Only `hard_stop_triggered` (−25%) remains.
- Flatten at 15:55 + cutoff latch end the day as today; next-session re-arm clears the counters.
- A `stop_loss` exit frees its slot for a new entry (this is what makes "trade through drawdowns" work).

### R5 — Session-level drawdown limits

- **Realized-loss entry gate (`max_daily_risk_pct`).** New `daily_realized_loss_pct` metric in `RiskManager`: incremented by the realized loss each time a *losing exit* closes a position — a `stop_loss` exit **or** a dynamic `exit_early` whose fill is below entry. Realized gains do not offset it (cumulative realized *damage*). Keyed on cumulative loss normalized to equity, not consecutive-stop count — 3 small stops and 1 big stop are treated the same if the realized damage equals.

  **Note (scope addition vs. earlier discussion):** the earlier gate description only counted `stop_loss` exits. This spec deliberately counts dynamic `exit_early` losses too, because a position exited early on a trend break before reaching the full 5% stop is still realized damage — excluding it would understate `daily_realized_loss_pct` relative to what it measures. Intentional, not an oversight.
  - When `daily_realized_loss_pct ≥ max_daily_risk_pct` (5%), no new entries for the rest of the session. Freed slots are not refilled.
  - Existing open positions continue their normal exit logic (hard stop, dynamic hold/exit). The gate only stops refilling, not exiting.
  - Persisted in `_state()` / `restore_persisted_safety_state` so a mid-session restart doesn't reset the counter.
- **−25% equity floor (`kill_switch_pct`).** Unchanged in spirit — true last resort, triggers on total equity, ends the session outright (whole-session halt, then re-arm next session), and takes precedence over everything.
- The two limits measure different things (realized stop-out losses vs. total equity drawdown) and both can engage.

## Interactions

- A session can reach 5% realized loss via repeated stop-outs while still holding open positions. Those ride until their own exits or the −25% floor.
- There is no ceiling on how many entry cycles occur before the realized-loss gate trips — that is the intended "trade through drawdowns" behavior, bounded by the gate.

## Implementation surface

- `engine/src/autotrader/config.py` — `multi-entry` validation branch; new fields (`risk_per_position_pct`, `max_daily_risk_pct`, `UNLIMITED_ENTRIES` sentinel); `initial` untouched.
- `engine/config/config.yaml` — `multi-entry` profile block (or switch profile + stop to 0.05 + risk caps).
- `engine/src/autotrader/risk.py` — risk-based `position_size`; `daily_realized_loss_pct` accumulator; entry-gate check; persist/restore; profile validation.
- `engine/src/autotrader/exits.py` — restructure into two independent checks: hard stop (unconditional) and dynamic evaluator (hold/exit/take-profit); dynamic never receives stop data.
- `engine/src/autotrader/runner.py` — `manage_exits` splits into hard-stop pass then dynamic pass; refill bookkeeping; feed realized loss to risk on `stop_loss` close.
- `engine/src/autotrader/lifecycle.py` — drop `daily_stop_triggered` from `tick()`; keep `hard_stop_triggered`; entry gate still feeds `can_scan`.
- `engine/src/autotrader/main.py` / `ipc.py` — expose `daily_realized_loss_pct`, `entries_blocked_by_daily_risk`, remaining slot count in `/api/status`.
- `engine/tests/` — new/modified tests (see Testing).

## Error handling

- Fail-closed paths unchanged: invalid snapshot, persistence failure, reconciliation mismatch still halt.
- Risk-based sizing adds only deterministic math — no new external failure modes.
- Dynamic exit evaluator failures → no-op hold (see R3).

## Testing

- Unit — sizing: `floor(0.01 × equity / (price × 0.05))`, integer capping near budget edges, zero/insufficient budget → 0 shares; per-position ≈ 20%, ceiling 100%.
- Unit — hard-stop precedence: price ≤ `entry × 0.95` → `stop_loss`, regardless of dynamic output; dynamic must not be called for the stopped position.
- Unit — dynamic decisions: trend-hold beats a dip (stronger regime + rising SMA → `hold` below entry but above stop); `exit_early` only on real breakdown; take-profit held while dynamic says `hold`.
- Unit — dynamic evaluator failure → no-op hold: sentiment/Ollama call raises or times out on an open position → position resolves to `hold` (never `exit_early`/`take_profit`); the hard stop-loss remains active and independent.
- Unit — realized-loss gate: stop-outs accumulate `daily_realized_loss_pct`; at ≥5% new entries return `max_daily_risk_pct`; open positions still exit; damage-keyed not streak-keyed.
- Unit — persistence: `daily_realized_loss_pct` survives `_state()` → restore round-trip; mid-session restart keeps gate intact.
- Unit — floor: −25% equity halts session outright.
- Integration — `tick()` with 5 concurrent positions → 6th signal blocked by slot; freed slot after `stop_loss` refills until gate trips; flatten at 15:55 + cutoff end the day; re-arm clears counters.
- Verify — existing suite passes with `initial` untouched; `multi-entry` validated in config tests.

## Out of scope

- Live (non-paper) trading: `multi-entry` is approved for paper only, same as `initial`.
- Trailing stops, partial fills beyond what reconciliation already supports, and order-type changes.
- Changes to the `initial` profile behavior.