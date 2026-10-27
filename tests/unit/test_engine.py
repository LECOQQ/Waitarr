from datetime import timedelta

import pytest

from tests.fakes import (
    THROTTLE,
    UNTHROTTLED,
    FakeClock,
    FakeSource,
    FakeTarget,
    MemoryStore,
    RecordingHeartbeat,
    RecordingNotifier,
    playback,
)
from waitarr.core.engine import Engine, TargetBinding
from waitarr.core.model import Limits, TargetState
from waitarr.core.policy import GlobalHysteresisPolicy
from waitarr.core.ports import Severity
from waitarr.core.reconcile import Ownership
from waitarr.core.records import StateDocumentError

HELD = TargetState(True, THROTTLE)


class World:
    def __init__(self, *, simulate=False, store=None, targets=None, clock=None):
        self.clock = clock or FakeClock()
        self.source = FakeSource()
        self.targets = targets or [FakeTarget("main")]
        self.store = store or MemoryStore()
        self.notifier = RecordingNotifier()
        self.heartbeat = RecordingHeartbeat()
        self.engine = Engine(
            sources=[self.source],
            targets=[TargetBinding(t, THROTTLE) for t in self.targets],
            policy=GlobalHysteresisPolicy(release_after=timedelta(minutes=3)),
            store=self.store,
            notifier=self.notifier,
            heartbeat=self.heartbeat,
            simulate=simulate,
            clock=self.clock,
        )
        self.engine.load()

    @property
    def target(self):
        return self.targets[0]

    def tick(self, seconds=15):
        self.clock.advance(seconds)
        self.engine.tick()


def test_playback_throttles_and_stopping_restores_after_the_delay():
    w = World()
    w.tick()
    assert w.target.writes == []
    w.source.sessions = [playback()]
    w.tick()
    assert w.target.state == HELD
    w.source.sessions = []
    w.tick(60)
    assert w.target.state == HELD
    w.tick(121)
    assert w.target.state == UNTHROTTLED
    assert w.target.writes == [HELD, UNTHROTTLED]


def test_a_pause_shorter_than_the_delay_does_not_switch_back_and_forth():
    w = World()
    w.source.sessions = [playback()]
    w.tick()
    w.source.sessions = [playback(paused=True)]
    for _ in range(8):
        w.tick()
    w.source.sessions = [playback()]
    w.tick()
    assert w.target.writes == [HELD]


def test_every_target_is_throttled():
    w = World(targets=[FakeTarget("main"), FakeTarget("second")])
    w.source.sessions = [playback()]
    w.tick()
    assert [t.state for t in w.targets] == [HELD, HELD]


def test_a_throttle_already_on_is_never_touched():
    human = TargetState(True, Limits(50_000, 50_000))
    w = World(targets=[FakeTarget("main", human)])
    w.source.sessions = [playback()]
    w.tick()
    w.source.sessions = []
    w.tick(600)
    assert w.target.writes == []
    assert w.target.state == human


def test_a_human_change_during_playback_is_respected_until_it_ends():
    w = World()
    w.source.sessions = [playback()]
    w.tick()
    w.target.state = UNTHROTTLED  # someone clicks the turtle off
    w.tick()
    w.tick()
    assert w.target.writes == [HELD]
    w.source.sessions = []
    w.tick(600)
    assert w.target.writes == [HELD]
    w.source.sessions = [playback()]
    w.tick()
    assert w.target.writes == [HELD, HELD]


def test_restart_after_a_crash_gives_the_state_back():
    store = MemoryStore()
    clock = FakeClock()
    target = FakeTarget("main")
    first = World(store=store, targets=[target], clock=clock)
    first.source.sessions = [playback()]
    first.tick()
    assert target.state == HELD
    # Crash: no shutdown. A new process starts later, nothing playing.
    clock.advance(600)
    second = World(store=store, targets=[target], clock=clock)
    second.tick()
    assert target.state == UNTHROTTLED


def test_restart_during_playback_keeps_ownership():
    store = MemoryStore()
    clock = FakeClock()
    target = FakeTarget("main")
    first = World(store=store, targets=[target], clock=clock)
    first.source.sessions = [playback()]
    first.tick()
    second = World(store=store, targets=[target], clock=clock)
    second.source.sessions = [playback()]
    second.tick()
    second.source.sessions = []
    second.tick(600)
    assert target.writes == [HELD, UNTHROTTLED]


def test_shutdown_restores_what_waitarr_owns():
    w = World()
    w.source.sessions = [playback()]
    w.tick()
    assert w.engine.restore_all()
    assert w.target.state == UNTHROTTLED


def test_a_crash_mid_write_is_undone_at_the_next_start():
    store = MemoryStore()
    target = FakeTarget("main")
    target.fail_writes = True
    first = World(store=store, targets=[target])
    first.source.sessions = [playback()]
    first.tick()
    assert target.state == UNTHROTTLED
    target.fail_writes = False
    second = World(store=store, targets=[target])
    assert second.engine.restore_all()
    assert target.state == UNTHROTTLED
    assert target.writes == []
    assert second.engine.status().targets["main"].ownership is Ownership.IDLE


def test_limits_a_human_left_after_switching_off_are_given_back():
    w = World()
    w.source.sessions = [playback()]
    w.tick()
    w.target.state = TargetState(False, THROTTLE)  # turtle clicked off
    w.tick()
    w.source.sessions = []
    w.tick(600)
    assert w.target.state == UNTHROTTLED
    assert w.target.writes == [HELD, UNTHROTTLED]


def test_a_state_file_owning_an_unconfigured_target_refuses_to_start():
    store = MemoryStore()
    first = World(store=store, targets=[FakeTarget("main")])
    first.source.sessions = [playback()]
    first.tick()
    with pytest.raises(StateDocumentError, match="main"):
        World(store=store, targets=[FakeTarget("primary")])


def test_unreachable_source_changes_nothing_and_notifies_once():
    w = World()
    w.source.sessions = [playback()]
    w.tick()
    w.source.down = True
    for _ in range(5):
        w.tick(600)
    assert w.target.state == HELD
    assert [n.severity for n in w.notifier.sent] == [Severity.FAILURE]
    assert not w.engine.status().healthy
    w.source.down = False
    w.source.sessions = []
    w.tick()
    assert [n.severity for n in w.notifier.sent] == [
        Severity.FAILURE,
        Severity.RECOVERY,
    ]


def test_unreachable_target_is_left_alone():
    w = World()
    w.target.down = True
    w.source.sessions = [playback()]
    w.tick()
    w.tick()
    assert w.target.writes == []
    assert w.heartbeat.beats[-1][0] is False
    w.target.down = False
    w.tick()
    assert w.target.state == HELD


def test_a_failed_write_is_retried():
    w = World()
    w.target.fail_writes = True
    w.source.sessions = [playback()]
    w.tick()
    assert w.target.state == UNTHROTTLED
    w.target.fail_writes = False
    w.tick()
    assert w.target.state == HELD


def test_observation_mode_never_writes_and_never_persists():
    w = World(simulate=True)
    w.source.sessions = [playback()]
    w.tick()
    w.target.state = HELD  # a human acts meanwhile
    w.tick()
    w.source.sessions = []
    w.tick(600)
    assert w.engine.restore_all()
    assert w.target.writes == []
    assert w.store.saves == 0


def test_observation_mode_reports_what_it_would_do(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.source.sessions = [playback()]
    w.tick()
    w.source.sessions = []
    w.tick(600)
    messages = [r.getMessage() for r in caplog.records]
    assert any("main: [observe] would throttle" in m for m in messages)
    assert any("main: [observe] would release" in m for m in messages)


def test_a_corrupt_state_file_refuses_to_start():
    store = MemoryStore({"schema_version": 99, "targets": {}})
    with pytest.raises(StateDocumentError):
        World(store=store)


def test_engaged_record_is_persisted_before_the_write():
    store = MemoryStore()
    target = FakeTarget("main")
    saved_before_write: list[object] = []

    original_apply = target.apply

    def spying_apply(state):
        targets = store.document["targets"]
        assert isinstance(targets, dict)
        saved_before_write.append(targets["main"]["ownership"])
        original_apply(state)

    target.apply = spying_apply  # type: ignore[method-assign]
    w = World(store=store, targets=[target])
    w.source.sessions = [playback()]
    w.tick()
    assert saved_before_write == [Ownership.ENGAGED.value]


def _messages(caplog):
    return [r.getMessage() for r in caplog.records]


def test_each_session_change_is_logged_just_before_the_decision(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.source.sessions = [playback(paused=True)]
    w.tick()
    w.source.sessions = [playback()]
    w.tick()
    w.source.sessions = [playback(paused=True)]
    w.tick()
    w.source.sessions = []
    w.tick(600)
    lines = _messages(caplog)
    started = lines.index(
        'Session: alice started, paused, "Dune" (Living Room on Jellyfin Web).'
    )
    resumed = lines.index(
        'Session: alice resumed "Dune" (Living Room on Jellyfin Web).'
    )
    throttle = next(
        i for i, m in enumerate(lines) if "[observe] would throttle" in m
    )
    paused = lines.index(
        'Session: alice paused "Dune" (Living Room on Jellyfin Web).'
    )
    stopped = lines.index(
        'Session: alice stopped "Dune" (Living Room on Jellyfin Web).'
    )
    release = next(
        i for i, m in enumerate(lines) if "[observe] would release" in m
    )
    assert started < resumed == throttle - 1
    assert resumed < paused < stopped < release
    assert lines[release - 1] == "No session is playing anything."
    assert lines[release].endswith("-- no counted playback for 10m15s.")


def test_an_unchanged_session_is_not_logged_again(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.source.sessions = [playback()]
    for _ in range(5):
        w.tick()
    assert sum(m.startswith("Session:") for m in _messages(caplog)) == 1


def test_the_next_episode_is_logged(caplog):
    caplog.set_level("INFO", logger="waitarr")
    w = World(simulate=True)
    w.source.sessions = [playback(title="Episode 1")]
    w.tick()
    w.source.sessions = [playback(title="Episode 2")]
    w.tick()
    assert (
        'Session: alice now plays "Episode 2" (Living Room on Jellyfin Web).'
        in _messages(caplog)
    )


def test_diagnostics_are_kept_for_the_status():
    from waitarr.core.model import Diagnostic

    w = World()
    leak = Diagnostic(
        "main", "warning", "main: µTP traffic is not rate-limited"
    )
    w.target.diagnostics = [leak]
    assert w.engine.diagnose() == [leak]
    assert w.engine.status().diagnostics == (leak,)
    w.target.diagnostics = []
    w.engine.diagnose()
    assert w.engine.status().diagnostics == ()
