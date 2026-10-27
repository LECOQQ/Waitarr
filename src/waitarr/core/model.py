"""Value types shared by the core, the policies and every adapter."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Diagnostic",
    "Limits",
    "Playback",
    "ServiceVersion",
    "TargetState",
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
    save paths.
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
