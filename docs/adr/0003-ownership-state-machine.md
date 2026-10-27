# 0003. Ownership: undo only what Waitarr did

- Status: accepted (2026-10-27)

## Context

A human may enable the alternative limits for their own reasons, before
or during a playback. Waitarr must never overwrite that decision, must
give back what it changed, and must do so after a crash too.

## Decision

Each target has a persisted record with an ownership state:

- `idle`: Waitarr owns nothing.
- `engaged`: Waitarr throttled the target. The record holds `before`
  (the state found) and `applied` (the state set).
- `yielded`: the target was already throttled, or was observed in a
  state other than `applied`. Waitarr touches nothing until no playback
  asks for a throttle any more; it then forgets, and the next playback
  starts from a clean slate.

A write is recorded as `pending` *before* it is sent and cleared only
once read back. A pending write is retried, idempotently, until
observed. At shutdown, an engage that may not have landed is undone,
never retried.

Reconciliation is a pure function (`waitarr.core.reconcile`); the
engine does the I/O around it.

## Consequences

- A human's change is detected by comparison with `applied`, which
  includes the limits, not only the switch.
- A crash between "decided" and "written" is repaired at the next start.
- A corrupt state file stops Waitarr instead of guessing what to give
  back.
