"""Decide what to do with one target, given what Waitarr owns and what
it observes. Pure: no I/O, no clock.

Ownership is the safety model. Waitarr only ever undoes its own change:

- `IDLE`: Waitarr owns nothing on this target.
- `ENGAGED`: Waitarr throttled the target and remembers the state it
  found (`before`), to give it back.
- `YIELDED`: a human decided (the target was already throttled, or its
  state changed under Waitarr). Waitarr touches nothing until no
  playback asks for a throttle any more; it then forgets, and the next
  playback starts from a clean slate. If the human switched the throttle
  off but left Waitarr's limits in place, those limits are put back as
  found, and the switch is left as the human set it.

`pending` is a write that may not have landed (a crash or an error
between "decided" and "confirmed"), and `pending_from` the state it was
decided from. It is retried only while the target is still in that
state, or half-way (limits written, switch not yet): any other state is
a human's, and Waitarr yields.
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
    pending_from: TargetState | None = None


@dataclass(frozen=True)
class Step:
    """The next record, and the write (if any) that leads to it."""

    record: TargetRecord
    action: Action
    write: TargetState | None = None


def _writing(
    record: TargetRecord,
    write: TargetState,
    observed: TargetState,
    *,
    simulate: bool,
) -> TargetRecord:
    if simulate:
        return record
    return replace(record, pending=write, pending_from=observed)


def _in_flight(record: TargetRecord, observed: TargetState) -> bool:
    origin, pending = record.pending_from, record.pending
    if origin is None or pending is None:
        return True
    # Adapters write the limits first, then the switch.
    halfway = TargetState(origin.throttled, pending.limits)
    return observed in (origin, halfway)


def _resolve_pending(
    record: TargetRecord, observed: TargetState, *, throttle: bool
) -> Step | None:
    """Settle a write that may not have landed; `None` once it has."""
    assert record.pending is not None
    if observed == record.pending:
        return None
    if not _in_flight(record, observed):
        return Step(
            TargetRecord(
                Ownership.YIELDED, before=record.before, applied=record.applied
            ),
            Action.YIELD_CHANGED_OUTSIDE,
        )
    if record.ownership is Ownership.ENGAGED and not throttle:
        # An engage nobody needs any more: undo it rather than finish it.
        assert record.before is not None
        if observed == record.before:
            return Step(TargetRecord(), Action.CONFIRM)
        return Step(
            _writing(
                TargetRecord(
                    Ownership.IDLE,
                    before=record.before,
                    applied=record.applied,
                ),
                record.before,
                observed,
                simulate=False,
            ),
            Action.RELEASE,
            write=record.before,
        )
    return Step(record, Action.RETRY, write=record.pending)


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
        settled = _resolve_pending(record, observed, throttle=throttle)
        if settled is not None:
            return settled
        record = replace(record, pending=None, pending_from=None)
        if record.ownership is Ownership.IDLE:
            return Step(TargetRecord(), Action.CONFIRM)

    if record.ownership is Ownership.IDLE:
        if not throttle:
            return Step(TargetRecord(), Action.NONE)
        if observed.throttled:
            return Step(
                TargetRecord(Ownership.YIELDED),
                Action.YIELD_ALREADY_THROTTLED,
            )
        wanted = TargetState(
            throttled=True, limits=throttle_limits or observed.limits
        )
        expected = observed if simulate else wanted
        engaged = TargetRecord(
            Ownership.ENGAGED, before=observed, applied=expected
        )
        return Step(
            _writing(engaged, wanted, observed, simulate=simulate),
            Action.ENGAGE,
            write=wanted,
        )

    if record.ownership is Ownership.ENGAGED:
        if observed != record.applied:
            return Step(
                TargetRecord(
                    Ownership.YIELDED,
                    before=record.before,
                    applied=record.applied,
                ),
                Action.YIELD_CHANGED_OUTSIDE,
            )
        if throttle:
            return Step(record, Action.NONE)
        assert record.before is not None
        released = TargetRecord(
            Ownership.IDLE, before=record.before, applied=record.applied
        )
        return Step(
            _writing(released, record.before, observed, simulate=simulate),
            Action.RELEASE,
            write=record.before,
        )

    if throttle:
        return Step(record, Action.NONE)
    before, applied = record.before, record.applied
    if (
        before is not None
        and applied is not None
        and not observed.throttled
        and observed.limits == applied.limits
        and applied.limits != before.limits
    ):
        # The human switched the throttle off; Waitarr's limits are still
        # there. Put the limits back, leave the switch as the human set it.
        wanted = TargetState(False, before.limits)
        return Step(
            _writing(TargetRecord(), wanted, observed, simulate=simulate),
            Action.RESUME,
            write=wanted,
        )
    return Step(TargetRecord(), Action.RESUME)


def restore(record: TargetRecord, observed: TargetState) -> Step:
    """Give back what Waitarr owns, regardless of demand (shutdown).

    Same guards as a release: a target changed outside Waitarr is left
    alone, and an engage that may not have landed is undone, never
    retried.
    """
    return reconcile(
        record,
        observed,
        throttle=False,
        throttle_limits=None,
        simulate=False,
    )
