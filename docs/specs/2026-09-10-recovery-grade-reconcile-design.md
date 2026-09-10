# Design: Recovery-Grade Reconcile — Retire Fail-Closed Auto-Liquidation

Date: 2026-09-10
Status: Approved design — awaiting implementation plan

## Problem

The engine's fail-closed reconcile architecture has, over five live trading days,
produced a new destructive halt variant every session. Seven targeted fixes were
applied; each revealed another instance of the same three underlying failure modes:

1. **Any transient reconcile mismatch halts the whole session permanently.**
   A stale thin-ticker quote, an in-flight fill not yet reconciled locally, a
   momentary broker snapshot gap, a submission whose outcome is unknown — each calls
   `begin_halt(...)`, so the engine stops trading for the day. ~40 halt codes exist
   and nearly all are treated identically: session-wide, permanent, recoverable only
   by hand-editing `state/state.json`.
2. **The "verified-identical" certainty model is unachievable against a live broker.**
   Fills land between 60s ticks; liquidity gaps make quotes stale; retried client IDs
   collide with prior broker orders. The code answers every uncertainty with a halt,
   which is safe in isolation but operationally fatal in aggregate — it has ended
   every single session this week in a manual recovery.
3. **During a halt, the engine force-sells its own real positions.**
   `_ensure_exits` treats any broker position without an exact local match as an
   orphan and market-sells it. Because a halt is *caused by* a mismatch, the engine
   reliably flips into self-liquidation: NVDA, SNXX, TQQQ, SKHY, DRAM, SOXL, NOK,
   NU, SOXS were all bought then orphan-flushed this week. Local state then holds a
   stale book while the broker is flat.

Plus a lifecycle defect: launchd `KeepAlive` pins one process across midnight, so
the 9:25 `StartCalendarInterval` restart never fires and the session never rolls —
a long-lived process keeps serving yesterday's halted session.

## Goals / "Done"

- Halt semantics are reserved for true integrity threats; transient *uncertainty*
  degrades to per-ticker skip/retry without halting the session.
- When a recoverable mismatch is detected (or at startup), the engine self-reconciles
  against authoritative broker truth: it adopts real positions, releases ghost
  intents, binds or cancels only confirmed orders — and never sells anything.
- The auto-flush / orphan-flush / blanket-cancel machinery is removed: reconciliation
  can no longer liquidate the account.
- A long-lived process correctly rolls into a fresh session.
- No manual `state.json` editing is required to recover from a recoverable failure.
- Existing true-safety halts (`-25%` kill switch, 5% daily-stop, flatten-at-close)
  remain fully enforced.
- Full test suite passes with the new contract.

## Requirements

### R1 — Halt-reason classification

Partition every `begin_halt` / `_fail_closed` call site in `risk.py`, `runner.py`,
`lifecycle.py` into three classes, dispatched through a single classified wrapper:

- **`HALT` — true integrity threat; whole session stays fail-closed.**
  Persistence failure at any safety boundary, confirmed broker-order loss,
  invalid broker/acknowledgement identity, clock errors, kill-switch / daily-stop,
  conflicting or decreasing fills, invalid terminal status/quantity, missing risk
  manager. These mean "we cannot trust our own books / the broker's."
- **`PER_TICKER_SKIP` — transient data quality; skip the ticker, keep session ACTIVE.**
  Stale or invalid entry quote, transient order-lookup no-record, submission-timeout
  uncertainty, stale client-ID collision, unrecognized-but-not-conflicting snapshot.
  These already received partial fixes; this class formalizes them so no ticker-level
  data condition ever halts the session.
- **`RECOVERABLE` — transient reconcile mismatch; retry then recover.**
  `broker_reconciliation_required`, `invalid_order_snapshot` when it reflects a
  resolvable local↔broker mismatch, and similar conditions where broker truth can
  resolve the divergence.

Routing: `HALT` keeps today's behavior (enter `HALTING`, persist, stop scanning).
`PER_TICKER_SKIP` records a warning and continues scanning. `RECOVERABLE` triggers the
recovery state (R2) instead of an unrecoverable halt. Automatic recovery engages for
`RECOVERABLE` (on the next tick) and at startup. A `recover` CLI command is the
sanctioned operator path to clear a genuine `HALT`: it runs the same broker-truth
reconcile (R2), and only transitions to ACTIVE when recovery completes cleanly —
replacing the current manual `state.json` editing. `recover` is the documented
recovery-of-last-resort and does not disable any true-safety halt.

The classification is specified as a full mapping of every existing call site; a table
lives in the appendix and is enforced by tests.

### R2 — Recovery: regenerate local books from broker truth

New `RECOVERING` risk state and a `recover()` routine with explicit, write-side rules
that always reconcile **from broker truth into local**:

1. **Adopt real broker positions.** For every position the broker reports, create or
   keep the local `Position` (ticker, qty, avg_entry from the broker). Real holdings
   are never dropped. Fixes the "NU owned at broker but missing locally → orphan →
   force-sold" failure.
2. **Release ghost intents.** For every local reservation/pending order whose
   `client_order_id` has **no record at the broker** (confirmed by lookup), drop the
   pending intent and release the reservation. Fixes the "uncertain reservation held
   forever → slot exhaustion" failure. This is the same information a human applied
   manually; now codified and gated.
3. **Bind or cancel confirmed orders only.** If the broker has an order under our
   client ID, bind it to local (acknowledged) or record it terminal — never both.
   Blanket cancellation is prohibited (R3).
4. **Never sell.** Recovery adopts positions, releases ghosts, cancels only
   confirmed-lost *entry* intents. It never market-sells a position.

Runs: (a) automatically after a `RECOVERABLE` failure, on the next tick; (b) at
process startup, replacing the current mismatch path in `_restore_state`. Produces a
clean, ACTIVE, broker-consistent state with no manual intervention.

**Contract shift (documented):** recovery trades "refuse to continue on any
uncertainty, needs a human" for "continue only on a broker-confirmed view; never
silently create or destroy real positions."

### R3 — Remove auto-flush; conditional cancel only

- **Delete `_ensure_exits`'s sell behavior.** The orphan-flush destruction path is
  removed. Reconciliation machinery never sells positions. The only sell paths are
  the exit manager (`manage_exits`: hard stop, dynamic hold/exit, take-profit) and
  conscious flatten-at-close.
- **`_cancel_open_entries` becomes conditional and recovery-only.** Cancellation of
  open entry orders is allowed only during recovery, and only for orders the broker
  lookup confirms as ours with a matching client ID. No blanket cancel-on-halt.
- During recovery, positions persist as real holdings; the normal `manage_exits`
  pass still runs (hard stop still enforces risk).

### R4 — Session rollover for long-lived processes

A long-running process must start a fresh session on day change:

- The main loop already detects `day != current_day`; extend it so a new day engages
  the lifecycle session rollover (reconcile, adopt broker truth, reset session
  counters, clear realized-loss gate) rather than continuing yesterday's halted
  session.
- Restart scheduling: document the `KeepAlive`/`StartCalendarInterval` interaction
  and make a daily restart safe (recovery on boot already seeds a clean session).

### R5 — Tests

- Halt-classification table: every call site asserted in the correct class (unit).
- `HALT` paths unchanged from today (regression).
- `PER_TICKER_SKIP` does not halt (existing partial fixes asserted).
- Recovery: adopts broker position, releases no-record ghost, binds confirmed order,
  never sells (unit).
- Recovery leaves kill-switch/daily-stop/flatten intact (unit).
- No auto-flush: a `HALTING`/`RECOVERING` mismatch never submits a sell (unit).
- Session rollover: same-process day change produces a fresh session (unit).
- Full suite green.

## Out of scope

- Live (non-paper) trading modes; further strategy changes.
- Re-architecting `rearm` (still requires clean reconcile; may be relaxed to
  recovery-based in a follow-up).
- The `initial` profile's fail-closed behavior is preserved where it does not
  conflict with recovery.

## Appendix — Halt classification table (enforced by tests)

Filled during implementation from the current ~40 call sites. Format:
`reason → class (file)`.