"""Decide what to do with one target, given what Waitarr owns and what it
observes; pure, and the machine is ADR 0003 (`TargetPhase` names its states)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from waitarr.core.model import Limits, TargetState

__all__ = [
    "Action",
    "Ownership",
    "Step",
    "TargetPhase",
    "TargetRecord",
    "holds_target",
    "normalized",
    "reconcile",
    "restore",
    "target_phase",
]


class Ownership(StrEnum):
    IDLE = "idle"
    ENGAGED = "engaged"
    YIELDED = "yielded"


class TargetPhase(StrEnum):
    """The states of a target, each one shape of `TargetRecord`.

    `pending` is a write that may not have landed, `pending_from` the state
    it was decided from; the two come together, and a write is retried only
    from that state or half-way (limits written, switch not yet).
    """

    IDLE = "idle"  # nothing owned
    ENGAGING = "engaging"  # throttled by Waitarr, write not yet confirmed
    ENGAGED = "engaged"  # throttled by Waitarr; `before` is given back
    WOULD_ENGAGE = "would-engage"  # ENGAGED, in observation mode
    RELEASING = "releasing"  # giving `before` back, write not yet confirmed
    RESUMING = "resuming"  # putting limits back after a human switched off
    YIELDED_BLANK = "yielded-blank"  # a human's throttle: nothing to give back
    YIELDED_HOLDING = "yielded-holding"  # a human's, Waitarr's limits remain


_FIELDS = ("before", "applied", "pending", "pending_from")
_SHAPES = {
    (Ownership.IDLE, False, False, False, False): TargetPhase.IDLE,
    (Ownership.ENGAGED, True, True, True, True): TargetPhase.ENGAGING,
    (Ownership.ENGAGED, True, True, False, False): TargetPhase.ENGAGED,
    (Ownership.IDLE, True, True, True, True): TargetPhase.RELEASING,
    (Ownership.IDLE, False, False, True, True): TargetPhase.RESUMING,
    (Ownership.YIELDED, False, False, False, False): TargetPhase.YIELDED_BLANK,
    (Ownership.YIELDED, True, True, False, False): TargetPhase.YIELDED_HOLDING,
}


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


def normalized(record: TargetRecord) -> TargetRecord:
    """The record without what a settled write leaves behind: an origin
    with no write, and everything an idle target no longer owns."""
    if record.pending is not None:
        return record
    if record.ownership is Ownership.IDLE:
        return TargetRecord()
    return replace(record, pending_from=None)


def target_phase(
    record: TargetRecord, *, simulate: bool = False
) -> TargetPhase:
    """The phase of a record; `ValueError` for a shape the machine never
    produces (a `pending` without its origin, one on a yielded target...)."""
    kept = normalized(record)
    shape = (
        kept.ownership,
        kept.before is not None,
        kept.applied is not None,
        kept.pending is not None,
        kept.pending_from is not None,
    )
    try:
        phase = _SHAPES[shape]
    except KeyError:
        held = [n for n in _FIELDS if getattr(record, n) is not None]
        raise ValueError(
            f"not a state Waitarr produces: {record.ownership.value} "
            f"with {', '.join(held) or 'nothing'}"
        ) from None
    if simulate and phase is TargetPhase.ENGAGED:
        return TargetPhase.WOULD_ENGAGE
    return phase


def holds_target(record: TargetRecord) -> bool:
    """Whether the target is Waitarr's to see out: any phase but IDLE (a
    yielded one included). The one answer, for every reader."""
    return target_phase(record) is not TargetPhase.IDLE


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
