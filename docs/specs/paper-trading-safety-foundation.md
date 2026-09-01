# Paper-Trading Safety Foundation

## Goal

Make the engine safe to evaluate in Alpaca paper trading before any strategy
scaling. The engine must use a small, fixed exposure profile, enforce every
entry limit atomically, stop and remain stopped on a safety event, and never
claim that an order or exit occurred before the broker confirms it.

This is operational-risk work, not a change intended to predict returns or
provide investment advice.

## What done looks like

- The engine refuses to start unless `alpaca.paper` is `true`. No change in
  this feature can enable live trading.
- Before submitting a buy, one atomic admission operation reserves its symbol,
  position slot, and notional exposure. Limits apply to broker positions plus
  locally pending orders, so one scan cannot exceed them.
- The initial profile is intentionally small: at most one open-or-pending
  position, one entry per session, and 0.25% of current paper equity in gross
  exposure and per position. It remains fixed for the whole session.
- A rejected, cancelled, or expired buy releases its reservation. A filled buy
  becomes an open position using the broker's filled quantity and average fill
  price. A partial fill retains only its unfilled reservation.
- The risk state is durable and explicit: `ACTIVE`, `HALTING`, or `HALTED`.
  A daily-loss or hard-stop breach latches the state, blocks entries, cancels
  pending entry orders, and submits exits for open positions. It does not
  return to `ACTIVE` without an explicit operator re-arm after reconciliation.
- At or after the configured flatten time, the engine blocks new entries for
  the rest of the session and follows the same exit/reconciliation path. It
  cannot repurchase a symbol after flattening it.
- Missing, invalid, or stale-enough-to-be-unsafe account, order, position, or
  quote data blocks new entries. A nonterminal or unknown sell continues to be
  tracked; it is not recorded as a closed trade or removed from local state.
- All of the above are verified with deterministic fakes before production
  code is added. The existing test suite and app build remain green.

## Locked decisions

| Topic | Decision |
| --- | --- |
| Trading venue | Alpaca paper only; startup fails closed otherwise. |
| Initial exposure | One open-or-pending position; one entry per session; 0.25% per position and 0.25% gross exposure. |
| Scaling | Never automatic. A human changes the named paper profile only after the evidence gate below. |
| Limit accounting | Open broker positions plus submitted-but-not-terminal orders and in-process reservations. |
| Circuit breaker | Durable, latching `ACTIVE → HALTING → HALTED`; manual re-arm only after a successful broker reconciliation. |
| Cutoff | No new entries at or after `flatten_time`; positions are exited and pending entries cancelled. |
| Order truth | Submission is acknowledgement, not a fill. Broker terminal state and fill fields determine local state and P&L. |
| Failure posture | Fail closed for entries; preserve/continue reconciling uncertain exits. |
| Strategy policy | Unchanged in this feature. No entry-score, model-prompt, news, recommendation, or profit-target changes. |

## Scope

### 1. Paper-mode and exposure profile validation

`Config` gains an explicit paper-only validation path and named risk-profile
values for gross exposure and maximum session entries. Validation rejects
nonpositive percentages, an invalid profile, or a configuration where the
gross cap cannot contain a position cap. `AlpacaExecutor` continues to receive
the validated paper flag and exposes enough broker metadata to make that
boundary testable.

The initial values above are defaults for the `initial` paper profile. They are
configuration, not an adaptive sizing algorithm.

### 2. Atomic admission and reservation ledger

`RiskManager` becomes the single admission authority. Its operation accepts a
symbol, price, and current equity and either returns a reservation token or a
machine-readable rejection reason. It checks, in one operation:

- paper profile is active and risk state is `ACTIVE`;
- valid, positive, fresh-enough inputs are available;
- no duplicate symbol exists in an open, pending, or reserved state;
- the position, gross-exposure, and session-entry caps will still hold.

The runner creates a reservation before it requests a buy. It attaches the
broker order ID after acknowledgement, then reconciles that order on later
cycles. Reservation release and fill conversion are idempotent, so retries or
restarts cannot create an extra slot or exposure.

### 3. Durable safety state and session cutoff

State persistence includes the risk state, current-session entry count,
pending-order/reservation records, and the session cutoff marker. Existing
legacy state files load into the safest compatible defaults: no unknown pending
entry is accepted as filled, and unknown risk state is `HALTED` until broker
reconciliation succeeds.

On hard-stop or daily-stop breach, the main loop asks the risk manager to
transition to `HALTING`. The executor first cancels pending entry orders, then
submits exits for reconciled open positions. Once there are no open positions
or nonterminal orders, it becomes `HALTED`; otherwise it remains `HALTING` and
retries reconciliation on later cycles. Re-arm is an explicit local operator
action and cannot bypass paper-mode validation.

At `flatten_time`, the same session cutoff is latched before exit work starts.
The runner refuses all entry admissions after that point, even if flattening or
an order lookup fails.

### 4. Broker-confirmed lifecycle and close accounting

The executor exposes a small order lifecycle interface: submit, fetch status,
and cancel. It maps broker status, filled quantity, and average fill price into
the local `Order` model without inventing values from a quote.

The runner records a `ClosedTrade` only for a confirmed terminal sell fill. It
uses actual filled quantity and average fill price. Rejected, cancelled,
pending, and partially filled sells stay in the pending lifecycle and preserve
the remaining broker position. Quote-based stop and take-profit decisions may
request an exit but may not mark the exit complete.

## Paper-evidence promotion gate

The engine never increases its exposure on its own. A profile may be manually
promoted only after an operator records an evidence review showing all of the
following for the completed paper sample:

- at least 20 completed paper sessions;
- every session reconciles broker equity, positions, and terminal orders with
  no unresolved order or position;
- no exposure-cap, cutoff, paper-mode, or latching-halt invariant failed;
- at least 12 of the 20 sessions finish with a positive net paper result;
- a positive aggregate paper result after the configured transaction-cost and
  slippage assumptions; and
- no manual re-arm while an order or position was unresolved.

This gate authorizes consideration of a configuration review only. It does not
guarantee future profitability, automatically edit configuration, or enable
live trading. Historical replay and richer performance evaluation remain a
later feature.

Re-arm is likewise manual and local: an operator invokes an explicit command
after reconciliation, with no API or UI control that could trigger it. It
unblocks the next paper session only; it never changes the selected profile.

## Data flow

1. Startup validates paper-only configuration, restores persisted safety state,
   and reconciles broker positions and nonterminal orders before scanning.
2. A candidate passes the existing strategy pipeline, then requests atomic
   risk admission. Rejection emits a reason and no order is sent.
3. Admission reservation succeeds → submit paper buy → bind broker order ID →
   reconcile broker status. Only confirmed fills become positions.
4. Each cycle reconciles all pending orders before considering another entry.
   Any unavailable or unsafe data blocks new entries.
5. A threshold breach or close cutoff latches entry blocking, cancels pending
   buys, submits required sells, and keeps reconciling until terminal.
6. State persists after every lifecycle/risk transition so restart recovery
   cannot create new exposure from uncertain local state.

## Error handling and invariants

- Invalid quote, equity, quantity, order ID, order status, or fill data: no
  new entry. The existing exposure is left untouched and reconciliation is
  retried.
- Broker timeout after submit: retain the reservation as unknown-pending; do
  not resubmit or release it until status reconciliation resolves it.
- Partial buy: count filled exposure plus the remaining pending exposure.
- Partial sell: record no closed trade until the remaining position reaches a
  terminal filled state; never report quote-based P&L as realized.
- Repeated cancel/exit calls are idempotent by broker order ID and state.
- A restart with nonterminal orders remains `HALTED` or `HALTING` until the
  broker snapshot resolves them.

## Test-first verification

Each behavior gets a failing test before implementation. The implementation
plan must name exact test files and commands, including:

- paper-only config rejection and initial-profile validation;
- same-scan multi-buy attempts proving reservations enforce every cap;
- duplicate, zero-quantity, invalid-price, and stale/unavailable data
  rejections;
- reservation release, partial fill, rejection, cancellation, timeout, and
  restart recovery;
- hard-stop and daily-stop transitions, pending-buy cancellation, durable halt,
  and re-arm preconditions;
- flatten-time entry lockout, including a failed flatten attempt followed by a
  scan;
- terminal fill, partial fill, rejection, and pending sell handling with
  actual-fill P&L only;
- full engine test suite, application build, and diff whitespace check.

## Out of scope

- Live trading, live-account credentials, automatic profile promotion, or any
  automatic sizing increase.
- Broker-native bracket/OCO protective orders, append-only event ledger,
  historical replay, slippage-model implementation, confidence/strategy
  filters, correlation controls, or market-news changes. Each is a later,
  separately reviewed safety or strategy feature.
- Changing the SwiftUI application, chat API, or readable-chat feature branch.
