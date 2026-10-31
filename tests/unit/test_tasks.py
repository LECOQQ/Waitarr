import pytest

from waitarr.core.model import ScheduledTask, TaskRun, TaskState
from waitarr.core.tasks import (
    TaskAction,
    TaskOwnership,
    TaskRecord,
    TaskWrite,
    restore_task,
    step_task,
)

# Identities are the host's own StartTimeUtc, opaque to the machine.
BEFORE = "2026-10-30T04:00:00.0000000Z"
CANCELLED_RUN = "2026-10-30T21:25:06.0000000Z"
LATER = "2026-10-31T04:00:00.0000000Z"


def task(state=TaskState.IDLE, last: str | None = BEFORE, status="Completed"):
    return ScheduledTask(
        key="RefreshLibrary",
        id="abc",
        name="Scan media library",
        state=state,
        progress=42.0 if state is TaskState.RUNNING else None,
        last=TaskRun(last, status) if last else None,
    )


def running(last=BEFORE):
    return task(TaskState.RUNNING, last)


def stopped(cancelled: str | None = CANCELLED_RUN, **extra):
    return TaskRecord(TaskOwnership.STOPPED, cancelled_start=cancelled, **extra)


def stopping(origin: str | None = BEFORE):
    return TaskRecord(
        TaskOwnership.STOPPED,
        pending=TaskWrite.STOP,
        pending_from=origin,
    )


def starting(cancelled=CANCELLED_RUN):
    return stopped(cancelled, pending=TaskWrite.START, pending_from=cancelled)


YIELDED = TaskRecord(TaskOwnership.YIELDED)


def step(record, observed, *, hold=True, suspend=True, simulate=False):
    return step_task(
        record, observed, hold=hold, suspend=suspend, simulate=simulate
    )


# -- nothing owned ---------------------------------------------------------


def test_a_running_task_is_stopped_when_the_hold_starts():
    result = step(TaskRecord(), running())
    assert result.action is TaskAction.STOP
    assert result.write is TaskWrite.STOP
    assert result.record == stopping(BEFORE)


def test_a_task_that_never_ran_is_stopped_with_the_identity_none():
    result = step(TaskRecord(), task(TaskState.RUNNING, last=None))
    assert result.record == stopping(None)


@pytest.mark.parametrize(
    "kwargs",
    [{"hold": False}, {"suspend": False}],
    ids=["no hold", "option off or key not listed"],
)
def test_nothing_is_stopped_without_a_hold_or_without_the_option(kwargs):
    result = step(TaskRecord(), running(), **kwargs)
    assert result.action is TaskAction.NONE
    assert result.write is None
    assert result.record == TaskRecord()


@pytest.mark.parametrize("state", [TaskState.IDLE, TaskState.CANCELLING])
def test_a_task_that_is_not_running_is_left_alone(state):
    assert step(TaskRecord(), task(state)).action is TaskAction.NONE


def test_a_task_the_host_does_not_list_is_left_alone():
    assert step(TaskRecord(), None).action is TaskAction.NONE


# -- a stop that may not have landed ---------------------------------------


def test_a_stop_that_did_not_land_is_retried_while_the_hold_lasts():
    result = step(stopping(), running(BEFORE))
    assert result.action is TaskAction.RETRY
    assert result.write is TaskWrite.STOP
    assert result.record == stopping()


@pytest.mark.parametrize(
    "kwargs",
    [{"hold": False}, {"suspend": False}],
    ids=["hold over", "option off or key retired"],
)
def test_a_stop_that_did_not_land_is_forgotten_when_it_is_no_longer_wanted(
    kwargs,
):
    result = step(stopping(), running(BEFORE), **kwargs)
    assert result.action is TaskAction.FORGET
    assert result.write is None
    assert result.record == TaskRecord()


def test_a_task_running_a_new_execution_after_a_stop_is_a_human_decision():
    # The stop landed (last execution changed), then someone started it.
    result = step(stopping(), running(CANCELLED_RUN))
    assert result.action is TaskAction.YIELD
    assert result.write is None
    assert result.record == YIELDED


def test_a_cancelled_execution_makes_the_task_waitarrs_to_start_again():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(stopping(), idle)
    assert result.action is TaskAction.CONFIRM
    assert result.write is None
    assert result.record == stopped(CANCELLED_RUN)


@pytest.mark.parametrize("status", ["Completed", "Failed", "Aborted"])
def test_a_task_that_ended_by_itself_is_forgotten(status):
    result = step(stopping(), task(last=LATER, status=status))
    assert result.action is TaskAction.FORGET
    assert result.record == TaskRecord()


def test_an_execution_that_vanished_without_a_result_is_started_again_later():
    # Same last execution, idle: the host restarted while it was running.
    result = step(stopping(BEFORE), task(last=BEFORE), hold=True)
    assert result.action is TaskAction.CONFIRM
    assert result.record == stopped(BEFORE)


def test_an_execution_that_vanished_is_started_again_once_the_hold_is_over():
    result = step(stopping(BEFORE), task(last=BEFORE), hold=False)
    assert result.action is TaskAction.START
    assert result.write is TaskWrite.START
    assert result.record == stopped(
        BEFORE, pending=TaskWrite.START, pending_from=BEFORE
    )


def test_a_task_that_never_ran_and_vanished_is_owned_with_identity_none():
    result = step(stopping(None), task(last=None))
    assert result.action is TaskAction.CONFIRM
    assert result.record == stopped(None)


@pytest.mark.parametrize("hold", [True, False])
def test_a_task_being_cancelled_is_never_written_to(hold):
    result = step(stopping(), task(TaskState.CANCELLING), hold=hold)
    assert result.action is TaskAction.WAIT
    assert result.write is None
    assert result.record == stopping()


def test_a_cancel_seen_at_the_first_idle_is_confirmed_and_started_if_due():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(stopping(), idle, hold=False)
    assert result.action is TaskAction.START
    assert result.write is TaskWrite.START


# -- a stopped task --------------------------------------------------------


def test_a_stopped_task_stays_stopped_while_the_hold_lasts():
    result = step(stopped(), task(last=CANCELLED_RUN, status="Cancelled"))
    assert result.action is TaskAction.NONE
    assert result.write is None
    assert result.record == stopped()


def test_a_stopped_task_is_started_when_the_hold_is_over():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(stopped(), idle, hold=False)
    assert result.action is TaskAction.START
    assert result.write is TaskWrite.START
    assert result.record == starting()


def test_a_stopped_task_started_again_by_a_human_is_not_stopped_again():
    result = step(stopped(), running(CANCELLED_RUN))
    assert result.action is TaskAction.YIELD
    assert result.write is None
    assert result.record == YIELDED


def test_a_yielded_task_is_left_alone_until_the_hold_is_over():
    assert step(YIELDED, running(CANCELLED_RUN)).action is TaskAction.NONE
    result = step(YIELDED, running(CANCELLED_RUN), hold=False)
    assert result.action is TaskAction.FORGET
    assert result.record == TaskRecord()


@pytest.mark.parametrize("hold", [True, False])
def test_a_task_that_ran_since_is_forgotten_without_a_start(hold):
    ran = task(last=LATER, status="Completed")
    result = step(stopped(), ran, hold=hold)
    assert result.action is TaskAction.FORGET
    assert result.write is None
    assert result.record == TaskRecord()


def test_a_task_started_by_a_human_after_the_hold_is_forgotten():
    result = step(stopped(), running(CANCELLED_RUN), hold=False)
    assert result.action is TaskAction.FORGET


def test_an_owned_task_is_still_started_when_the_option_is_turned_off():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(stopped(), idle, hold=False, suspend=False)
    assert result.write is TaskWrite.START
    assert step(stopped(), idle, hold=True, suspend=False).write is None


@pytest.mark.parametrize("record", [stopped(), stopping(), starting(), YIELDED])
def test_an_owned_task_the_host_no_longer_lists_is_forgotten(record):
    result = step(record, None, hold=False)
    assert result.action is TaskAction.FORGET
    assert result.record == TaskRecord()


# -- a start that may not have landed --------------------------------------


@pytest.mark.parametrize(
    "observed",
    [running(CANCELLED_RUN), task(last=LATER, status="Completed")],
    ids=["running", "ran since"],
)
@pytest.mark.parametrize("hold", [True, False])
def test_a_start_that_landed_is_forgotten(observed, hold):
    result = step(starting(), observed, hold=hold)
    assert result.action is TaskAction.FORGET
    assert result.write is None
    assert result.record == TaskRecord()


def test_a_start_that_did_not_land_is_retried_once_the_hold_is_over():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(starting(), idle, hold=False)
    assert result.action is TaskAction.RETRY
    assert result.write is TaskWrite.START
    assert result.record == starting()


def test_a_start_that_did_not_land_is_not_retried_when_the_hold_is_back():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = step(starting(), idle, hold=True)
    assert result.action is TaskAction.CONFIRM
    assert result.write is None
    assert result.record == stopped()


# -- observation -----------------------------------------------------------


def test_a_simulated_stop_writes_no_pending_and_is_reported_once():
    first = step(TaskRecord(), running(), simulate=True)
    assert first.action is TaskAction.STOP
    assert first.record == stopped(BEFORE)
    again = step(first.record, running(BEFORE), simulate=True)
    assert again.action is TaskAction.NONE
    assert again.record == first.record


def test_a_simulated_start_is_reported_once_when_the_hold_is_over():
    record = stopped(BEFORE)
    first = step(record, running(BEFORE), hold=False, simulate=True)
    assert first.action is TaskAction.START
    assert first.record == TaskRecord()
    again = step(first.record, running(BEFORE), hold=False, simulate=True)
    assert again.action is TaskAction.NONE


def test_a_simulated_stop_is_forgotten_when_the_task_ends_by_itself():
    ended = task(last=LATER, status="Completed")
    result = step(stopped(BEFORE), ended, hold=True, simulate=True)
    assert result.action is TaskAction.FORGET
    assert result.write is None


def test_each_execution_is_reported_in_observation():
    record = step(TaskRecord(), running(BEFORE), simulate=True).record
    ended = step(record, task(last=LATER), simulate=True)
    assert ended.record == TaskRecord()
    second = step(ended.record, running(LATER), simulate=True)
    assert second.action is TaskAction.STOP


# -- shutdown --------------------------------------------------------------


def test_restore_starts_a_stopped_task_again():
    idle = task(last=CANCELLED_RUN, status="Cancelled")
    result = restore_task(stopped(), idle)
    assert result.action is TaskAction.START
    assert result.write is TaskWrite.START


def test_restore_never_retries_a_stop():
    result = restore_task(stopping(), running(BEFORE))
    assert result.action is TaskAction.FORGET
    assert result.write is None


def test_restore_forgets_a_yielded_task_and_waits_for_a_cancel():
    assert restore_task(YIELDED, running()).action is TaskAction.FORGET
    waiting = restore_task(stopping(), task(TaskState.CANCELLING))
    assert waiting.action is TaskAction.WAIT
    assert waiting.record == stopping()


@pytest.mark.parametrize("hold", [True, False])
def test_a_yielded_task_being_cancelled_by_someone_else_is_not_waited_for(
    hold,
):
    result = step(YIELDED, task(TaskState.CANCELLING), hold=hold)
    assert result.action is not TaskAction.WAIT
    assert result.write is None


def test_restore_forgets_a_yielded_task_even_while_it_is_cancelling():
    result = restore_task(YIELDED, task(TaskState.CANCELLING))
    assert result.action is TaskAction.FORGET
    assert result.record == TaskRecord()
