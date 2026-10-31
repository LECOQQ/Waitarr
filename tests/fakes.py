"""In-memory doubles for every core port."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from waitarr.core.model import (
    Diagnostic,
    Limits,
    Playback,
    ScheduledTask,
    ServiceVersion,
    TargetState,
    TaskRun,
    TaskState,
)
from waitarr.core.ports import Notification, ServiceUnavailable

UNTHROTTLED = TargetState(False, Limits(0, 0))
THROTTLE = Limits(1024, 1024)


def playback(
    user: str = "alice",
    *,
    paused: bool = False,
    session_id: str = "s1",
    device: str | None = "device-1",
    client: str | None = "Jellyfin Web",
    media_type: str | None = "Movie",
    title: str | None = "A film",
    libraries: tuple[str, ...] = (),
) -> Playback:
    return Playback(
        source="jellyfin",
        session_id=session_id,
        user=user,
        device=device,
        client=client,
        title=title,
        media_type=media_type,
        media_path=None,
        paused=paused,
        libraries=libraries,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSource:
    def __init__(self, name: str = "jellyfin") -> None:
        self.name = name
        self.sessions: list[Playback] = []
        self.down = False

    def version(self) -> ServiceVersion:
        return ServiceVersion("Jellyfin", "12.2.0")

    def playbacks(self) -> Sequence[Playback]:
        if self.down:
            raise ServiceUnavailable("connection refused")
        return list(self.sessions)


class FakeTarget:
    """A target whose state a test (or a 'human') can change directly."""

    def __init__(
        self, name: str = "main", state: TargetState = UNTHROTTLED
    ) -> None:
        self.name = name
        self.state = state
        self.writes: list[TargetState] = []
        self.down = False
        self.fail_writes = False
        self.diagnostics: list[Diagnostic] = []

    def version(self) -> ServiceVersion:
        return ServiceVersion("qBittorrent", "v5.1.0", "2.11.4")

    def diagnose(self) -> list[Diagnostic]:
        return list(self.diagnostics)

    def read(self) -> TargetState:
        if self.down:
            raise ServiceUnavailable("connection refused")
        return self.state

    def apply(self, state: TargetState) -> None:
        if self.down or self.fail_writes:
            raise ServiceUnavailable("write refused")
        self.writes.append(state)
        self.state = state


class HostCrash(BaseException):
    """Stands for the process dying: nothing in the engine may catch it."""


class FakeTaskHost:
    """A task host that behaves as Jellyfin 12.2.0 was probed.

    A stop leaves the task `Cancelling` for `cancelling_reads` reads, then
    idle with the cancelled execution as its last; a start on a running
    task is ignored; a stop on a task at rest is ignored too (the real
    adapter turns the host's 500 into no effect). `writes` lists the
    (kind, key) of every call, effective or not. A test, or a "human",
    changes a task with `run` and `finish`; `crash` kills the process
    around the next write: ("stop"|"start", "before"|"after").
    """

    def __init__(
        self,
        name: str = "jellyfin",
        keys: tuple[str, ...] = ("RefreshLibrary",),
    ) -> None:
        self.name = name
        self.writes: list[tuple[str, str]] = []
        self.reads = 0
        self.down = False
        self.fail_writes = False
        self.cancelling_reads = 0
        self.crash: tuple[str, str] | None = None
        self._runs = 0
        self._order = list(keys)
        self._state = {k: TaskState.IDLE for k in keys}
        self._current: dict[str, str | None] = {k: None for k in keys}
        self._last = {k: TaskRun(self._next_run(), "Completed") for k in keys}
        self._cancel_left: dict[str, int] = {}

    def _next_run(self) -> str:
        self._runs += 1
        return f"2026-10-30T04:{self._runs:02d}:00.0000000Z"

    def state(self, key: str) -> TaskState:
        return self._state[key]

    def last(self, key: str) -> TaskRun | None:
        return self._last[key]

    def run(self, key: str) -> None:
        """Start the task, as a schedule or a human would."""
        if self._state[key] is TaskState.IDLE:
            self._state[key] = TaskState.RUNNING
            self._current[key] = self._next_run()

    def finish(self, key: str, status: str = "Completed") -> None:
        """End the current execution by itself."""
        current = self._current[key]
        assert current is not None
        self._last[key] = TaskRun(current, status)
        self._state[key] = TaskState.IDLE
        self._current[key] = None

    def vanish(self, key: str) -> None:
        """Lose the current execution without a result (the host restarted)."""
        self._state[key] = TaskState.IDLE
        self._current[key] = None

    def forget(self, key: str) -> None:
        """Make the host stop listing the task (a plugin removed)."""
        self._order.remove(key)

    def tasks(self) -> Sequence[ScheduledTask]:
        if self.down:
            raise ServiceUnavailable("connection refused")
        self.reads += 1
        for key, left in list(self._cancel_left.items()):
            if left == 0:
                del self._cancel_left[key]
                self.finish(key, "Cancelled")
            else:
                self._cancel_left[key] = left - 1
        return [
            ScheduledTask(
                key=key,
                id=f"id-{key}",
                name=f"Task {key}",
                state=self._state[key],
                progress=(
                    42.0 if self._state[key] is TaskState.RUNNING else None
                ),
                last=self._last[key],
            )
            for key in self._order
        ]

    def _crash(self, kind: str, when: str) -> None:
        if self.crash == (kind, when):
            raise HostCrash(f"{kind} {when}")

    def stop(self, task_id: str) -> None:
        key = task_id.removeprefix("id-")
        self.writes.append(("stop", key))
        if self.down or self.fail_writes:
            raise ServiceUnavailable("write refused")
        self._crash("stop", "before")
        if self._state[key] is TaskState.RUNNING:
            self._state[key] = TaskState.CANCELLING
            self._cancel_left[key] = self.cancelling_reads
            if self.cancelling_reads == 0:
                del self._cancel_left[key]
                self.finish(key, "Cancelled")
        self._crash("stop", "after")

    def start(self, task_id: str) -> None:
        key = task_id.removeprefix("id-")
        self.writes.append(("start", key))
        if self.down or self.fail_writes:
            raise ServiceUnavailable("write refused")
        self._crash("start", "before")
        self.run(key)
        self._crash("start", "after")


class MemoryStore:
    def __init__(self, document: dict[str, object] | None = None) -> None:
        self.document: dict[str, object] = document or {}
        self.saves = 0

    def load(self) -> dict[str, object]:
        return dict(self.document)

    def save(self, document: dict[str, object]) -> None:
        self.saves += 1
        self.document = document


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def notify(self, notification: Notification) -> None:
        self.sent.append(notification)


class RecordingHeartbeat:
    def __init__(self) -> None:
        self.beats: list[tuple[bool, str]] = []

    def beat(self, *, healthy: bool, message: str) -> None:
        self.beats.append((healthy, message))
