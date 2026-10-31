"""Decide what to do with one scheduled task, given what Waitarr owns and
what it observes. Pure: no I/O, no clock.

The same safety model as `reconcile`: Waitarr only ever undoes its own
change.

- `IDLE`: Waitarr owns nothing on this task.
- `STOPPED`: Waitarr stopped a running task and remembers the identity of
  the last execution it saw (`cancelled_start`). It starts the task again
  once the hold is over, and only if no execution has begun or ended
  since: the identity must still be the one it noted.
- `YIELDED`: a human started the task again while Waitarr held it. Waitarr
  stops nothing on it until the hold is over; it then forgets.

An execution is identified by the `StartTimeUtc` the host reports, compared
by equality, never by Waitarr's clock. A task that never ran has the
identity `None`, compared the same way.

`pending` is a write that may not have landed, and `pending_from` the
identity it was decided from. A stop that may not have landed is retried
only while the task is still running that execution and the hold lasts; a
start that may not have landed is retried only while nothing has run since.
A task being cancelled is never written to: the step waits for the first
idle reading, where the identity of the cancelled execution can be read.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from waitarr.core.model import ScheduledTask, TaskState

__all__ = [
    "TaskAction",
    "TaskOwnership",
    "TaskRecord",
    "TaskStep",
    "TaskWrite",
    "restore_task",
    "step_task",
]

CANCELLED = "Cancelled"


class TaskOwnership(StrEnum):
    IDLE = "idle"
    STOPPED = "stopped"
    YIELDED = "yielded"


class TaskWrite(StrEnum):
    STOP = "stop"
    START = "start"


class TaskAction(StrEnum):
    """What a step did, for the log and the status endpoint."""

    NONE = "none"
    STOP = "stop"
    START = "start"
    CONFIRM = "confirm"
    RETRY = "retry"
    YIELD = "yield"
    FORGET = "forget"
    WAIT = "wait"


@dataclass(frozen=True)
class TaskRecord:
    ownership: TaskOwnership = TaskOwnership.IDLE
    cancelled_start: str | None = None
    pending: TaskWrite | None = None
    pending_from: str | None = None


@dataclass(frozen=True)
class TaskStep:
    """The next record, and the write (if any) that leads to it."""

    record: TaskRecord
    action: TaskAction
    write: TaskWrite | None = None


def _identity(task: ScheduledTask) -> str | None:
    return task.last.start if task.last else None


def _forget() -> TaskStep:
    return TaskStep(TaskRecord(), TaskAction.FORGET)


def _yield() -> TaskStep:
    return TaskStep(TaskRecord(TaskOwnership.YIELDED), TaskAction.YIELD)


def _from_idle(
    observed: ScheduledTask | None,
    *,
    hold: bool,
    suspend: bool,
    simulate: bool,
) -> TaskStep:
    if (
        observed is None
        or not (hold and suspend)
        or observed.state is not TaskState.RUNNING
    ):
        return TaskStep(TaskRecord(), TaskAction.NONE)
    identity = _identity(observed)
    if simulate:
        # Nothing is written, so the task keeps running: the record only
        # remembers that this execution was already reported.
        stopped = TaskRecord(TaskOwnership.STOPPED, cancelled_start=identity)
    else:
        stopped = TaskRecord(
            TaskOwnership.STOPPED,
            pending=TaskWrite.STOP,
            pending_from=identity,
        )
    return TaskStep(stopped, TaskAction.STOP, write=TaskWrite.STOP)


def _resolve_stop(
    record: TaskRecord,
    observed: ScheduledTask,
    *,
    hold: bool,
    suspend: bool,
) -> TaskStep:
    """Settle a stop that may not have landed."""
    identity = _identity(observed)
    if observed.state is TaskState.RUNNING:
        if identity != record.pending_from:
            # The stop landed, then a human started the task again.
            return _yield()
        if hold and suspend:
            return TaskStep(record, TaskAction.RETRY, write=TaskWrite.STOP)
        return _forget()
    if identity == record.pending_from:
        # The execution vanished without a result (the host restarted):
        # the state found was "running", so the task is Waitarr's to
        # start again.
        owned = TaskRecord(TaskOwnership.STOPPED, cancelled_start=identity)
        return TaskStep(owned, TaskAction.CONFIRM)
    if observed.last is not None and observed.last.status == CANCELLED:
        owned = TaskRecord(TaskOwnership.STOPPED, cancelled_start=identity)
        return TaskStep(owned, TaskAction.CONFIRM)
    # It ended by itself (completed, failed...) before the stop landed.
    return _forget()


def _resolve_start(
    record: TaskRecord, observed: ScheduledTask, *, hold: bool
) -> TaskStep:
    """Settle a start that may not have landed."""
    if (
        observed.state is TaskState.RUNNING
        or _identity(observed) != record.cancelled_start
    ):
        return _forget()
    if hold:
        # The hold is back before the start landed: do not start now, the
        # task is still Waitarr's to start again later.
        owned = replace(record, pending=None, pending_from=None)
        return TaskStep(owned, TaskAction.CONFIRM)
    return TaskStep(record, TaskAction.RETRY, write=TaskWrite.START)


def _from_owned(
    record: TaskRecord,
    observed: ScheduledTask,
    *,
    hold: bool,
    simulate: bool,
) -> TaskStep:
    """Next step for a stopped or yielded record with nothing pending."""
    if record.ownership is TaskOwnership.YIELDED:
        if hold:
            return TaskStep(record, TaskAction.NONE)
        return _forget()
    identity = _identity(observed)
    running = observed.state is TaskState.RUNNING
    if simulate:
        if identity != record.cancelled_start:
            return _forget()
        if hold:
            return TaskStep(record, TaskAction.NONE)
        return TaskStep(TaskRecord(), TaskAction.START, write=TaskWrite.START)
    if running:
        # Stopped by Waitarr, running again: a human started it.
        return _yield() if hold else _forget()
    if identity != record.cancelled_start:
        # It ran since: there is nothing of Waitarr's left to give back.
        return _forget()
    if hold:
        return TaskStep(record, TaskAction.NONE)
    started = replace(record, pending=TaskWrite.START, pending_from=identity)
    return TaskStep(started, TaskAction.START, write=TaskWrite.START)


def step_task(
    record: TaskRecord,
    observed: ScheduledTask | None,
    *,
    hold: bool,
    suspend: bool,
    simulate: bool,
) -> TaskStep:
    """Return the next step for one task.

    `hold` is the policy's demand (a counted playback, or the delay after
    it); `suspend` whether Waitarr may stop this task now (the option is on
    and the key is listed), which never stops it giving back what it owns.
    `observed` is `None` when the host does not list the task. With
    `simulate`, Waitarr writes nothing and keeps a record in memory only,
    so that each execution is reported once.
    """
    if record.ownership is TaskOwnership.IDLE:
        return _from_idle(
            observed, hold=hold, suspend=suspend, simulate=simulate
        )
    if observed is None:
        return _forget()
    if (
        observed.state is TaskState.CANCELLING
        and record.ownership is TaskOwnership.STOPPED
    ):
        # Only a stop of Waitarr's own is waited for; a yielded task is a
        # person's, whatever it is doing.
        return TaskStep(record, TaskAction.WAIT)
    if record.pending is not None:
        if record.pending is TaskWrite.STOP:
            settled = _resolve_stop(
                record, observed, hold=hold, suspend=suspend
            )
        else:
            settled = _resolve_start(record, observed, hold=hold)
        if settled.action is not TaskAction.CONFIRM:
            return settled
        # The write is settled; go on from what it left.
        follow = _from_owned(
            settled.record, observed, hold=hold, simulate=simulate
        )
        return follow if follow.action is not TaskAction.NONE else settled
    return _from_owned(record, observed, hold=hold, simulate=simulate)


def restore_task(
    record: TaskRecord, observed: ScheduledTask | None
) -> TaskStep:
    """Give back what Waitarr owns, regardless of demand (shutdown).

    A stop that may not have landed is forgotten, never retried.
    """
    return step_task(
        record, observed, hold=False, suspend=False, simulate=False
    )
