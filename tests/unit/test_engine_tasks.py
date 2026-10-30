from datetime import timedelta

import pytest

from tests.fakes import (
    THROTTLE,
    UNTHROTTLED,
    FakeClock,
    FakeSource,
    FakeTarget,
    FakeTaskHost,
    HostCrash,
    MemoryStore,
    RecordingHeartbeat,
    RecordingNotifier,
    playback,
)
from waitarr.core.engine import (
    UNREACHABLE_REMINDER,
    Engine,
    TargetBinding,
    TaskBinding,
)
from waitarr.core.model import TargetState, TaskState
from waitarr.core.policy import GlobalHysteresisPolicy
from waitarr.core.records import StateDocumentError
from waitarr.core.tasks import TaskAction, TaskOwnership

KEY = "RefreshLibrary"
HELD = TargetState(True, THROTTLE)


class World:
    def __init__(
        self,
        *,
        simulate=False,
        store=None,
        host=None,
        clock=None,
        keys=(KEY,),
        suspend=True,
        with_host=True,
        target=None,
    ):
        self.clock = clock or FakeClock()
        self.source = FakeSource()
        self.target = target or FakeTarget("main")
        self.host = host or FakeTaskHost(keys=(KEY, "Other"))
        self.store = store or MemoryStore()
        self.notifier = RecordingNotifier()
        self.heartbeat = RecordingHeartbeat()
        self.engine = Engine(
            sources=[self.source],
            targets=[TargetBinding(self.target, THROTTLE)],
            policy=GlobalHysteresisPolicy(release_after=timedelta(minutes=3)),
            store=self.store,
            notifier=self.notifier,
            heartbeat=self.heartbeat,
            simulate=simulate,
            clock=self.clock,
            task_hosts=(
                [TaskBinding(self.host, keys, suspend)] if with_host else []
            ),
            sleep=self.clock.advance,
        )
        self.engine.load()

    def tick(self, seconds=15):
        self.clock.advance(seconds)
        self.engine.tick()

    def play(self, *, seconds=15):
        self.source.sessions = [playback()]
        self.tick(seconds)

    def stop_playing(self, *, seconds=15):
        self.source.sessions = []
        self.tick(seconds)

    def record(self):
        tasks = self.store.document.get("tasks", {})
        assert isinstance(tasks, dict)
        return tasks.get("jellyfin", {}).get("records", {}).get(KEY)


def _lines(caplog, marker):
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


# -- the hold ----------------------------------------------------------------


def test_a_running_task_is_stopped_when_playback_starts():
    w = World()
    w.host.run(KEY)
    w.tick()
    assert w.host.writes == []
    w.play()
    assert w.host.writes == [("stop", KEY)]
    assert w.host.state(KEY) is TaskState.IDLE
    assert w.record()["ownership"] == "stopped"
    assert w.engine.status().tasks["jellyfin"][KEY].ownership is (
        TaskOwnership.STOPPED
    )


def test_only_the_listed_tasks_are_stopped():
    w = World()
    w.host.run("Other")
    w.play()
    assert w.host.writes == []
    assert w.host.state("Other") is TaskState.RUNNING


def test_a_task_started_during_playback_is_stopped_too():
    w = World()
    w.play()
    w.host.run(KEY)
    w.tick()
    assert w.host.writes == [("stop", KEY)]


def test_a_stopped_task_is_started_again_after_the_release_delay():
    w = World()
    w.host.run(KEY)
    w.play()
    w.stop_playing(seconds=60)
    assert w.host.writes == [("stop", KEY)]
    w.tick(121)
    assert w.host.writes == [("stop", KEY), ("start", KEY)]
    assert w.host.state(KEY) is TaskState.RUNNING
    assert w.record() is None
    assert w.engine.status().tasks["jellyfin"] == {}


def test_a_task_that_ran_since_is_not_started_again():
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.run(KEY)  # a human starts it...
    w.host.finish(KEY)  # ...and it ends before the next reading
    w.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY)]
    assert w.record() is None


def test_the_hold_of_tasks_does_not_mix_with_a_target_of_the_same_name():
    host = FakeTaskHost("main", keys=(KEY,))
    w = World(host=host)
    w.play()
    document: dict = w.store.document  # type: ignore[type-arg]
    assert set(document["targets"]) == {"main"}
    assert document["targets"]["main"]["last_activity_at"] is not None
    assert document["tasks"]["main"]["last_activity_at"] is not None


def test_an_idle_waitarr_costs_the_host_no_call():
    w = World()
    for _ in range(5):
        w.tick()
    assert w.host.reads == 0


# -- a human starts the task again ------------------------------------------


def test_a_task_started_again_by_a_human_is_not_stopped_again(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.run(KEY)
    for _ in range(4):
        w.tick()
    assert w.host.writes == [("stop", KEY)]
    assert w.record()["ownership"] == "yielded"
    assert len(_lines(caplog, "a human decision")) == 1
    w.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY)]
    assert w.record() is None
    assert w.host.state(KEY) is TaskState.RUNNING


def test_a_task_is_stopped_again_by_the_next_playback_after_a_yield():
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.run(KEY)
    w.tick()
    w.stop_playing(seconds=600)
    w.play()
    assert w.host.writes == [("stop", KEY), ("stop", KEY)]


# -- a task being cancelled --------------------------------------------------


def test_a_task_being_cancelled_is_not_written_to_until_it_is_idle():
    w = World()
    w.host.cancelling_reads = 2
    w.host.run(KEY)
    w.play()
    assert w.host.state(KEY) is TaskState.CANCELLING
    assert w.record()["pending"] == "stop"
    w.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY)]
    w.tick()
    # Idle at last: the cancel is confirmed and the task started again.
    assert w.host.writes == [("stop", KEY), ("start", KEY)]
    assert w.record() is None


# -- the record is written before the call ---------------------------------


@pytest.mark.parametrize("kind", ["stop", "start"])
def test_the_pending_write_is_persisted_before_the_call(kind):
    w = World()
    seen = []
    original = getattr(w.host, kind)

    def spy(task_id):
        seen.append(w.record())
        original(task_id)

    setattr(w.host, kind, spy)
    w.host.run(KEY)
    w.play()
    w.stop_playing(seconds=600)
    assert [r["pending"] for r in seen] == [kind]


def test_a_failed_stop_is_retried_with_the_pending_record_kept():
    w = World()
    w.host.run(KEY)
    w.host.fail_writes = True
    w.play()
    assert w.record()["pending"] == "stop"
    assert w.host.state(KEY) is TaskState.RUNNING
    w.host.fail_writes = False
    w.tick()
    assert w.host.state(KEY) is TaskState.IDLE
    assert w.record()["ownership"] == "stopped"
    assert w.record()["pending"] is None


def test_a_failed_start_is_retried():
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.fail_writes = True
    w.stop_playing(seconds=600)
    assert w.record()["pending"] == "start"
    assert w.host.state(KEY) is TaskState.IDLE
    w.host.fail_writes = False
    w.tick()
    assert w.host.state(KEY) is TaskState.RUNNING
    assert w.record() is None


# -- a crash at each step -----------------------------------------------------


def _crash_and_restart(w, kind, when):
    """Kill the process around the next `kind` write, then start another
    one on the same store and host."""
    w.host.crash = (kind, when)
    with pytest.raises(HostCrash):
        if kind == "stop":
            w.play()
        else:
            w.stop_playing(seconds=600)
    w.host.crash = None
    return World(store=w.store, host=w.host, clock=w.clock, target=w.target)


def test_a_crash_before_the_stop_is_retried_while_playback_lasts():
    w = World()
    w.host.run(KEY)
    second = _crash_and_restart(w, "stop", "before")
    assert w.host.state(KEY) is TaskState.RUNNING
    second.play()
    assert w.host.state(KEY) is TaskState.IDLE
    assert second.record()["ownership"] == "stopped"


def test_a_crash_before_the_stop_is_forgotten_once_playback_is_over():
    w = World()
    w.host.run(KEY)
    second = _crash_and_restart(w, "stop", "before")
    second.stop_playing(seconds=600)
    assert w.host.state(KEY) is TaskState.RUNNING
    assert w.host.writes == [("stop", KEY)]
    assert second.record() is None


def test_a_crash_after_the_stop_is_started_again_once_it_is_idle():
    w = World()
    w.host.cancelling_reads = 1
    w.host.run(KEY)
    second = _crash_and_restart(w, "stop", "after")
    assert w.host.state(KEY) is TaskState.CANCELLING
    second.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY)]  # still being cancelled
    second.tick()
    assert w.host.writes == [("stop", KEY), ("start", KEY)]
    assert w.host.state(KEY) is TaskState.RUNNING
    assert second.record() is None


def test_a_crash_after_the_stop_leaves_a_task_a_human_started_alone():
    w = World()
    w.host.run(KEY)
    second = _crash_and_restart(w, "stop", "after")
    w.host.run(KEY)
    second.play()
    assert w.host.writes == [("stop", KEY)]
    assert second.record()["ownership"] == "yielded"


def test_a_crash_after_the_start_does_not_start_twice():
    w = World()
    w.host.run(KEY)
    w.play()
    second = _crash_and_restart(w, "start", "after")
    second.tick()
    assert w.host.writes == [("stop", KEY), ("start", KEY)]
    assert second.record() is None


def test_a_crash_before_the_start_is_retried():
    w = World()
    w.host.run(KEY)
    w.play()
    second = _crash_and_restart(w, "start", "before")
    second.tick()
    assert w.host.state(KEY) is TaskState.RUNNING
    assert second.record() is None


def test_a_host_that_restarted_during_a_stop_gets_its_task_started_again():
    w = World()
    w.host.run(KEY)
    w.host.crash = ("stop", "before")
    with pytest.raises(HostCrash):
        w.play()
    w.host.crash = None
    w.host.vanish(KEY)  # idle, with the same last execution as before
    second = World(store=w.store, host=w.host, clock=w.clock)
    second.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY), ("start", KEY)]


# -- the options and the configuration ----------------------------------------


def test_with_the_option_off_nothing_is_stopped_but_the_run_is_reported(
    caplog,
):
    caplog.set_level("INFO", logger="waitarr")
    w = World(suspend=False)
    w.host.run(KEY)
    w.play()
    for _ in range(4):
        w.tick()
    assert w.host.writes == []
    assert len(_lines(caplog, "seen since")) == 1
    w.host.finish(KEY)
    w.tick()
    w.tick()
    assert len(_lines(caplog, "no longer running")) == 1


def test_a_stopped_task_is_started_again_when_its_key_leaves_the_list():
    w = World()
    w.host.run(KEY)
    w.play()
    second = World(store=w.store, host=w.host, clock=w.clock, keys=())
    second.source.sessions = [playback()]
    second.tick()
    assert w.host.writes == [("stop", KEY)]
    second.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY), ("start", KEY)]


def test_a_stopped_task_is_started_again_when_the_option_is_turned_off():
    w = World()
    w.host.run(KEY)
    w.play()
    second = World(store=w.store, host=w.host, clock=w.clock, suspend=False)
    second.stop_playing(seconds=600)
    assert w.host.writes == [("stop", KEY), ("start", KEY)]


def test_a_task_of_an_unconfigured_source_refuses_to_start():
    w = World()
    w.host.run(KEY)
    w.play()
    with pytest.raises(StateDocumentError, match=KEY):
        World(store=w.store, host=w.host, with_host=False)


def test_the_same_state_file_only_warns_in_observation_mode(caplog):
    w = World()
    w.host.run(KEY)
    w.play()
    caplog.set_level("WARNING", logger="waitarr")
    World(store=w.store, host=w.host, with_host=False, simulate=True)
    assert any(KEY in m for m in _lines(caplog, "still owns"))


def test_a_task_the_host_no_longer_lists_is_forgotten(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.forget(KEY)
    w.tick()
    assert w.record() is None
    assert len(_lines(caplog, "no longer listed")) == 1
    assert w.engine.restore_all()


def test_a_version_1_state_file_is_loaded():
    store = MemoryStore({"schema_version": 1, "targets": {}})
    w = World(store=store)
    w.host.run(KEY)
    w.play()
    assert w.host.writes == [("stop", KEY)]


# -- an unreadable host or source ---------------------------------------------


def test_an_unreadable_source_changes_no_task():
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.run(KEY)
    w.source.down = True
    for _ in range(5):
        w.tick(600)
    assert w.host.writes == [("stop", KEY)]
    assert w.host.state(KEY) is TaskState.RUNNING


def test_an_unreadable_host_changes_no_task_and_throttling_goes_on(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World()
    w.host.run(KEY)
    w.host.down = True
    w.play()
    w.tick()
    assert w.target.state == HELD
    assert w.host.writes == []
    status = w.engine.status()
    assert status.healthy
    assert "jellyfin" in status.task_errors
    assert w.heartbeat.beats[-1][0] is True
    assert w.notifier.sent == []
    assert len(_lines(caplog, "cannot be read")) == 1
    w.host.down = False
    w.tick()
    assert w.host.writes == [("stop", KEY)]
    assert w.engine.status().task_errors == {}


def test_an_unreadable_host_is_reminded_after_the_delay(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World()
    w.host.down = True
    w.play()
    for _ in range(10):
        w.tick(15)
    assert len(_lines(caplog, "cannot be read")) == 1
    w.source.sessions = [playback()]
    w.tick(int(UNREACHABLE_REMINDER.total_seconds()))
    assert len(_lines(caplog, "cannot be read")) == 2


# -- shutdown -----------------------------------------------------------------


def test_shutdown_starts_the_stopped_tasks_again_after_the_targets():
    w = World()
    events = []
    apply = w.target.apply
    w.target.apply = lambda state: (events.append("target"), apply(state))[1]
    start = w.host.start
    w.host.start = lambda task_id: (events.append("task"), start(task_id))[1]
    w.host.run(KEY)
    w.play()
    events.clear()
    assert w.engine.restore_all()
    assert events == ["target", "task"]
    assert w.target.state == UNTHROTTLED
    assert w.host.state(KEY) is TaskState.RUNNING
    assert w.record() is None


def test_shutdown_waits_for_a_task_being_cancelled():
    w = World()
    w.host.cancelling_reads = 3
    w.host.run(KEY)
    w.play()
    before = w.clock.now
    assert w.engine.restore_all()
    assert w.host.state(KEY) is TaskState.RUNNING
    assert w.clock.now - before <= timedelta(seconds=10)
    assert w.clock.now > before


def test_shutdown_gives_up_on_a_task_cancelled_for_too_long():
    w = World()
    w.host.cancelling_reads = 100
    w.host.run(KEY)
    w.play()
    before = w.clock.now
    assert not w.engine.restore_all()
    assert w.clock.now - before == timedelta(seconds=10)
    assert w.host.writes == [("stop", KEY)]
    assert w.record()["pending"] == "stop"


def test_shutdown_with_an_unreadable_host_keeps_the_record():
    w = World()
    w.host.run(KEY)
    w.play()
    w.host.down = True
    assert not w.engine.restore_all()
    assert w.record()["ownership"] == "stopped"


# -- observation -----------------------------------------------------------


def test_observation_mode_never_writes_a_task_and_never_persists():
    w = World(simulate=True)
    w.host.run(KEY)
    w.play()
    for _ in range(4):
        w.tick()
    w.stop_playing(seconds=600)
    assert w.engine.restore_all()
    assert w.host.writes == []
    assert w.store.saves == 0
    assert w.host.state(KEY) is TaskState.RUNNING


def test_observation_mode_reports_each_execution_once(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.host.run(KEY)
    w.play()
    for _ in range(4):
        w.tick()
    assert len(_lines(caplog, "[observe] would stop task")) == 1
    assert not _lines(caplog, "[observe] would start task")
    w.stop_playing(seconds=60)
    assert not _lines(caplog, "[observe] would start task")
    w.tick(300)
    w.tick()
    assert len(_lines(caplog, "[observe] would start task")) == 1
    assert len(_lines(caplog, "[observe] would stop task")) == 1


def test_observation_mode_reports_the_next_execution_too(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.host.run(KEY)
    w.play()
    w.host.finish(KEY)
    w.tick()
    w.host.run(KEY)
    w.tick()
    assert len(_lines(caplog, "[observe] would stop task")) == 2
    assert not _lines(caplog, "[observe] would start task")


# -- the log ---------------------------------------------------------------


def test_a_task_seen_running_during_the_hold_is_logged_once_and_when_it_ends(
    caplog,
):
    caplog.set_level("INFO", logger="waitarr")
    w = World()
    w.host.run(KEY)
    w.play()
    for _ in range(4):
        w.tick()
    seen = _lines(caplog, "seen since")
    assert len(seen) == 1
    assert KEY in seen[0]
    assert "42%" in seen[0]
    w.stop_playing(seconds=600)  # started again by Waitarr
    w.host.finish(KEY)
    w.tick()
    w.tick()
    assert len(_lines(caplog, "no longer running")) == 1


def test_the_status_lists_the_tasks_owned():
    w = World()
    w.host.run(KEY)
    w.play()
    shown = w.engine.status().tasks["jellyfin"][KEY]
    assert shown.ownership is TaskOwnership.STOPPED
    assert shown.last_action is TaskAction.STOP
    assert shown.last_action_at == w.clock.now
