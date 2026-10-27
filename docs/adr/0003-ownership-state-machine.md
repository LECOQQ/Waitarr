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

If the human switched the throttle off and left Waitarr's limits in
place, those limits are put back as found when the playback ends; the
switch stays as the human set it.

A write is recorded as `pending`, with the state it was decided from,
*before* it is sent, and cleared only once read back. It is retried only
while the target is still in that state or half-way (limits written,
switch not yet); any other state is a human's, and Waitarr yields. An
engage that may not have landed and that no playback needs any more is
undone, never finished, at shutdown as during a run.

A state file that owns a target the configuration no longer declares
stops the start, with the way out: restoring a target nobody watches is
impossible, and forgetting it would leave it throttled.

Reconciliation is a pure function (`waitarr.core.reconcile`); the
engine does the I/O around it.

## Consequences

- A human's change is detected by comparison with `applied`, which
  includes the limits, not only the switch.
- A crash between "decided" and "written" is repaired at the next start.
- A corrupt state file stops Waitarr instead of guessing what to give
  back.
