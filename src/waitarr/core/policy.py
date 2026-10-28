"""Throttle policies: given what is playing, which targets should be held.

A policy is a strategy the engine calls once per tick. It is pure: the
memory it needs between ticks (when each target last had a reason to be
throttled) is handed in and handed back, so the engine can persist it
and a restart does not forget a playback that ended a minute ago.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from waitarr.core.model import Playback

__all__ = [
    "Demand",
    "GlobalHysteresisPolicy",
    "PlaybackFilter",
    "PolicyResult",
    "ThrottlePolicy",
]


@dataclass(frozen=True)
class Demand:
    """Whether one target should be throttled, and why."""

    throttle: bool
    playbacks: tuple[Playback, ...] = ()
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class PolicyResult:
    demands: Mapping[str, Demand]
    memory: Mapping[str, datetime]


class ThrottlePolicy(Protocol):
    """Decide, per target, whether it should be throttled now.

    `memory` maps a target name to the last time it had a reason to be
    throttled; the result carries the updated memory.
    """

    def decide(
        self,
        playbacks: Sequence[Playback],
        targets: Sequence[str],
        now: datetime,
        memory: Mapping[str, datetime],
    ) -> PolicyResult: ...


def _folded(values: Sequence[str]) -> frozenset[str]:
    return frozenset(v.casefold() for v in values)


@dataclass(frozen=True)
class PlaybackFilter:
    """Which playbacks count. Empty allow-lists mean "everything".

    Every comparison is case-insensitive. A playback with no user, device,
    client or library never matches a list that names one, so an
    allow-list excludes it and an ignore-list keeps it. An item in several
    libraries is ignored if any of them is ignored, and counted by
    `libraries` if any of them is listed.
    """

    users: frozenset[str] = field(default_factory=frozenset)
    ignore_users: frozenset[str] = field(default_factory=frozenset)
    ignore_devices: frozenset[str] = field(default_factory=frozenset)
    ignore_clients: frozenset[str] = field(default_factory=frozenset)
    media_types: frozenset[str] = field(default_factory=frozenset)
    libraries: frozenset[str] = field(default_factory=frozenset)
    ignore_libraries: frozenset[str] = field(default_factory=frozenset)
    count_paused: bool = False

    @classmethod
    def build(
        cls,
        *,
        users: Sequence[str] = (),
        ignore_users: Sequence[str] = (),
        ignore_devices: Sequence[str] = (),
        ignore_clients: Sequence[str] = (),
        media_types: Sequence[str] = (),
        libraries: Sequence[str] = (),
        ignore_libraries: Sequence[str] = (),
        count_paused: bool = False,
    ) -> PlaybackFilter:
        return cls(
            users=_folded(users),
            ignore_users=_folded(ignore_users),
            ignore_devices=_folded(ignore_devices),
            ignore_clients=_folded(ignore_clients),
            media_types=_folded(media_types),
            libraries=_folded(libraries),
            ignore_libraries=_folded(ignore_libraries),
            count_paused=count_paused,
        )

    def matches(self, playback: Playback) -> bool:
        if playback.paused and not self.count_paused:
            return False
        user = (playback.user or "").casefold()
        if self.users and user not in self.users:
            return False
        if user and user in self.ignore_users:
            return False
        device = (playback.device or "").casefold()
        if device and device in self.ignore_devices:
            return False
        client = (playback.client or "").casefold()
        if client and client in self.ignore_clients:
            return False
        libraries = _folded(playback.libraries)
        if libraries & self.ignore_libraries:
            return False
        if self.libraries and not libraries & self.libraries:
            return False
        media_type = (playback.media_type or "").casefold()
        return not self.media_types or media_type in self.media_types


@dataclass(frozen=True)
class GlobalHysteresisPolicy:
    """Throttle every target while anything counted plays, and for
    `release_after` once it stops.

    The delay absorbs pauses, seeks and the gap between two episodes, so
    a target is not switched back and forth on each of them.
    """

    release_after: timedelta
    playback_filter: PlaybackFilter = field(default_factory=PlaybackFilter)

    def decide(
        self,
        playbacks: Sequence[Playback],
        targets: Sequence[str],
        now: datetime,
        memory: Mapping[str, datetime],
    ) -> PolicyResult:
        counted = tuple(p for p in playbacks if self.playback_filter.matches(p))
        demands: dict[str, Demand] = {}
        updated: dict[str, datetime] = {}
        for target in targets:
            last = now if counted else memory.get(target)
            holding = last is not None and now - last < self.release_after
            if last is not None and holding:
                updated[target] = last
            demands[target] = Demand(
                throttle=bool(counted) or holding,
                playbacks=counted,
                last_activity_at=last,
            )
        return PolicyResult(demands=demands, memory=updated)
