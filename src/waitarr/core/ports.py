"""The ports the core drives. Adapters implement them; the core never
imports an adapter.

Every port method may raise `ServiceUnavailable`: the core treats it as
"this service's state is unknown this tick" and changes nothing that
depends on it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from waitarr.core.model import Diagnostic, Playback, ServiceVersion, TargetState

__all__ = [
    "ActivitySource",
    "Heartbeat",
    "Notification",
    "Notifier",
    "ServiceUnavailable",
    "Severity",
    "StateStore",
    "ThrottleTarget",
    "WriteRefused",
]


class ServiceUnavailable(Exception):
    """A service could not be reached, or answered something unusable.

    The message is safe to log: adapters never put a credential in it.
    """


class WriteRefused(RuntimeError):
    """A read-only target was asked to write. Always a bug: the service
    stops rather than carry on in a mode it cannot honour."""


class ActivitySource(Protocol):
    """Answers "who is playing what, right now"."""

    @property
    def name(self) -> str: ...

    def version(self) -> ServiceVersion: ...

    def playbacks(self) -> Sequence[Playback]:
        """Return every session currently playing something, paused or not."""
        ...


class ThrottleTarget(Protocol):
    """Something that can be throttled, released and read back."""

    @property
    def name(self) -> str: ...

    def version(self) -> ServiceVersion: ...

    def read(self) -> TargetState: ...

    def diagnose(self) -> Sequence[Diagnostic]:
        """Return the settings that defeat or weaken throttling (a
        scheduler flipping the switch, traffic outside the limits)."""
        ...

    def apply(self, state: TargetState) -> None:
        """Make the target's state equal to `state`.

        Must be idempotent: the core retries a write it cannot prove
        landed by calling `apply` again with the same state.
        """
        ...


class StateStore(Protocol):
    """Persists what Waitarr owns, so a restart can give it back."""

    def load(self) -> dict[str, object]: ...

    def save(self, document: dict[str, object]) -> None:
        """Replace the stored document atomically."""
        ...


class Severity(StrEnum):
    FAILURE = "failure"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class Notification:
    severity: Severity
    title: str
    message: str


class Notifier(Protocol):
    def notify(self, notification: Notification) -> None:
        """Deliver `notification`; never raises."""
        ...


class Heartbeat(Protocol):
    """Tells an external dead-man's switch that Waitarr is alive."""

    def beat(self, *, healthy: bool, message: str) -> None:
        """Report one completed tick; never raises."""
        ...
