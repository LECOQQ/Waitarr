"""Decide what to do with one target, given what Waitarr owns and what
it observes. Pure: no I/O, no clock.

Ownership is the safety model. Waitarr only ever undoes its own change:

- `IDLE`: Waitarr owns nothing on this target.
- `ENGAGED`: Waitarr throttled the target and remembers the state it
  found (`before`), to give it back.
- `YIELDED`: a human decided (the target was already throttled, or its
  state changed under Waitarr). Waitarr touches nothing until no
  playback asks for a throttle any more; it then forgets, and the next
  playback starts from a clean slate.

`pending` is a write that may not have landed (a crash or an error
between "decided" and "confirmed"). It is retried, idempotently, until
the target is observed in that state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from waitarr.core.model import Limits, TargetState

__all__ = [
    "Action",
    "Ownership",
    "Step",
    "TargetRecord",
    "reconcile",
    "restore",
]


class Ownership(StrEnum):
    IDLE = "idle"
    ENGAGED = "engaged"
    YIELDED = "yielded"


class Action(StrEnum):
    """What a step did, for the log and the status endpoint."""

    NONE = "none"
    ENGAGE = "engage"
    RELEASE = "release"
    RETRY = "retry"
    CONFIRM = "confirm"
    YIELD_ALREADY_THROTTLED = "yield-already-throttled"
    YIELD_CHANGED_OUTSIDE = "yield-changed-outside"
    RESUME = "resume"


@dataclass(frozen=True)
class TargetRecord:
    ownership: Ownership = Ownership.IDLE
    before: TargetState | None = None
    applied: TargetState | None = None
    pending: TargetState | None = None


@dataclass(frozen=True)
class Step:
    """The next record, and the write (if any) that leads to it."""

    record: TargetRecord
    action: Action
    write: TargetState | None = None


def reconcile(
    record: TargetRecord,
    observed: TargetState,
    *,
    throttle: bool,
    throttle_limits: Limits | None,
    simulate: bool,
) -> Step:
    """Return the next step for one target.

    `throttle_limits` are the limits to apply while throttling; `None`
    keeps the target's own. With `simulate`, Waitarr writes nothing, so
    it expects to keep observing the state it found: that is what
    `applied` records, and what still lets it notice a human change.
    """
    if record.pending is not None:
        if observed != record.pending:
            return Step(record, Action.RETRY, write=record.pending)
        record = replace(record, pending=None)
        if record.ownership is Ownership.IDLE:
            return Step(record, Action.CONFIRM)

    if record.ownership is Ownership.IDLE:
        if not throttle:
            return Step(record, Action.NONE)
        if observed.throttled:
            return Step(
                TargetRecord(Ownership.YIELDED),
                Action.YIELD_ALREADY_THROTTLED,
            )
        wanted = TargetState(
            throttled=True, limits=throttle_limits or observed.limits
        )
        expected = observed if simulate else wanted
        return Step(
            TargetRecord(
                Ownership.ENGAGED,
                before=observed,
                applied=expected,
                pending=None if simulate else wanted,
            ),
            Action.ENGAGE,
            write=wanted,
        )

    if record.ownership is Ownership.ENGAGED:
        if observed != record.applied:
            return Step(
                TargetRecord(Ownership.YIELDED), Action.YIELD_CHANGED_OUTSIDE
            )
        if throttle:
            return Step(record, Action.NONE)
        assert record.before is not None
        return Step(
            TargetRecord(
                Ownership.IDLE,
                pending=None if simulate else record.before,
            ),
            Action.RELEASE,
            write=record.before,
        )

    if throttle:
        return Step(record, Action.NONE)
    return Step(TargetRecord(Ownership.IDLE), Action.RESUME)


def restore(record: TargetRecord, observed: TargetState) -> Step:
    """Give back what Waitarr owns, regardless of demand (shutdown).

    Same guard as a release: a target changed outside Waitarr is left
    alone. An engage that may not have landed is undone, never retried.
    """
    if (
        record.ownership is Ownership.ENGAGED
        and record.pending is not None
        and observed != record.pending
    ):
        assert record.before is not None
        return Step(
            TargetRecord(Ownership.IDLE, pending=record.before),
            Action.RELEASE,
            write=record.before,
        )
    return reconcile(
        record,
        observed,
        throttle=False,
        throttle_limits=None,
        simulate=False,
    )
