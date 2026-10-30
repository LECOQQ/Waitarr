"""Value types shared by the core, the policies and every adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Diagnostic",
    "Limits",
    "Playback",
    "ScheduledTask",
    "ServiceVersion",
    "TargetState",
    "TaskRun",
    "TaskState",
]


@dataclass(frozen=True)
class Limits:
    """A pair of transfer rate limits, in bytes per second.

    `0` means "unlimited", which is qBittorrent's and Transmission's
    convention: a throttle is a small positive value, never zero.
    """

    download: int
    upload: int


@dataclass(frozen=True)
class TargetState:
    """The part of a target's state Waitarr reads, writes and restores.

    `throttled` is the target's own throttle switch (qBittorrent's
    alternative speed limits mode); `limits` are the limits that switch
    applies.
    """

    throttled: bool
    limits: Limits


@dataclass(frozen=True)
class Playback:
    """One session reported by an activity source.

    `media_path` is the file being read, when the source exposes it. The
    v1 policy ignores it; a disk-aware policy will map it onto a target's
    save paths. `libraries` names every library whose folders hold that
    file (libraries may overlap), empty when the source could not tell.
    """

    source: str
    session_id: str
    user: str | None
    device: str | None
    client: str | None
    title: str | None
    media_type: str | None
    media_path: str | None
    paused: bool
    libraries: tuple[str, ...] = ()

    def describe(self) -> str:
        who = self.user or "someone"
        what = f'"{self.title}"' if self.title else "something"
        where = " on ".join(p for p in (self.device, self.client) if p)
        suffix = f" ({where})" if where else ""
        return f"{who} playing {what}{suffix}"


@dataclass(frozen=True)
class Diagnostic:
    """A setting that defeats or weakens throttling, found at a check.

    `severity` is "warning" (throttling leaks) or "notice" (it may).
    Waitarr reports these; it never changes the setting itself.
    """

    target: str
    severity: str
    message: str


@dataclass(frozen=True)
class ServiceVersion:
    """A service's reported version, as an adapter read it."""

    product: str
    version: str | None
    api_version: str | None = None


class TaskState(StrEnum):
    """Where a scheduled task is, as its host reports it.

    A state the adapter does not know is `ServiceUnavailable`, never a
    guess.
    """

    IDLE = "Idle"
    RUNNING = "Running"
    CANCELLING = "Cancelling"


@dataclass(frozen=True)
class TaskRun:
    """The last execution of a task, as the host reports it.

    `start` is the host's own start time, verbatim: it is the identity
    of an execution, compared by equality and never parsed or compared
    with Waitarr's clock. `status` is the host's word for the outcome
    (`Completed`, `Cancelled`, `Failed`...).
    """

    start: str
    status: str


@dataclass(frozen=True)
class ScheduledTask:
    """One scheduled task of a media server, as observed.

    `key` is the stable name Waitarr identifies it by; `id` is only what
    the host wants back in a call and is never persisted. `progress` is a
    percentage, `None` when the task is not running. `last` is `None`
    when the task never ran.
    """

    key: str
    id: str
    name: str
    state: TaskState
    progress: float | None = None
    last: TaskRun | None = None
