"""In-memory doubles for every core port."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from waitarr.core.model import Limits, Playback, ServiceVersion, TargetState
from waitarr.core.ports import Notification, ServiceUnavailable

UNTHROTTLED = TargetState(False, Limits(0, 0))
THROTTLE = Limits(1024, 1024)


def playback(
    user: str = "alice",
    *,
    paused: bool = False,
    session_id: str = "s1",
    device: str | None = "Living Room",
    client: str | None = "Jellyfin Web",
    media_type: str | None = "Movie",
    title: str | None = "Dune",
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

    def version(self) -> ServiceVersion:
        return ServiceVersion("qBittorrent", "v5.1.0", "2.11.4")

    def diagnose(self) -> list[str]:
        return []

    def read(self) -> TargetState:
        if self.down:
            raise ServiceUnavailable("connection refused")
        return self.state

    def apply(self, state: TargetState) -> None:
        if self.down or self.fail_writes:
            raise ServiceUnavailable("write refused")
        self.writes.append(state)
        self.state = state


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
