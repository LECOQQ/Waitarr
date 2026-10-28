"""Jellyfin as an activity source, through its HTTP API (`/Sessions`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import requests

from waitarr import __version__
from waitarr.core.model import Playback, ServiceVersion
from waitarr.core.ports import ServiceUnavailable

__all__ = ["JellyfinSource"]

# How long the library folders (`/Library/VirtualFolders`) are trusted
# before they are read again: libraries change rarely, a tick is 15 s.
LIBRARY_REFRESH_SECONDS = 600.0


class JellyfinSource:
    """Reads the sessions of one Jellyfin server.

    The API key must belong to an administrator (an API key created in
    the dashboard does): a user token only sees its own sessions.
    """

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._base = url.rstrip("/")
        self._timeout = timeout
        self._http = session or requests.Session()
        self._monotonic = monotonic
        self._folders: tuple[tuple[str, tuple[str, ...]], ...] = ()
        self._folders_read_at: float | None = None
        self._http.headers["Authorization"] = (
            'MediaBrowser Client="Waitarr", Device="Waitarr", '
            f'DeviceId="waitarr-{name}", Version="{__version__}", '
            f'Token="{api_key}"'
        )

    @property
    def name(self) -> str:
        return self._name

    def version(self) -> ServiceVersion:
        info = self._get("/System/Info/Public")
        if not isinstance(info, Mapping):
            raise ServiceUnavailable(f"{self._base}: unexpected server info")
        version = info.get("Version")
        return ServiceVersion(
            product=str(info.get("ProductName") or "Jellyfin"),
            version=str(version) if version else None,
        )

    def playbacks(self) -> Sequence[Playback]:
        sessions = self._get("/Sessions")
        if not isinstance(sessions, list):
            raise ServiceUnavailable(
                f"{self._base}/Sessions did not return a list"
            )
        if any(
            isinstance(s, Mapping) and s.get("NowPlayingItem") for s in sessions
        ):
            self._refresh_folders()
        return [
            playback
            for raw in sessions
            if isinstance(raw, Mapping)
            and (playback := self._to_playback(raw)) is not None
        ]

    def _to_playback(self, session: Mapping[str, Any]) -> Playback | None:
        item = session.get("NowPlayingItem")
        if not isinstance(item, Mapping):
            return None
        state = session.get("PlayState")
        paused = isinstance(state, Mapping) and bool(state.get("IsPaused"))
        return Playback(
            source=self._name,
            session_id=str(session.get("Id") or ""),
            user=_text(session.get("UserName")),
            device=_text(session.get("DeviceName")),
            client=_text(session.get("Client")),
            title=_title(item),
            media_type=_text(item.get("Type")),
            media_path=_text(item.get("Path")),
            paused=paused,
            libraries=self._libraries_of(_text(item.get("Path"))),
        )

    def _refresh_folders(self) -> None:
        """Read each library's name and folders, at most every
        `LIBRARY_REFRESH_SECONDS`.

        A failed read keeps the folders known so far and is tried again
        next tick: playbacks still count meanwhile, with what is known.
        """
        now = self._monotonic()
        if (
            self._folders_read_at is not None
            and now - self._folders_read_at < LIBRARY_REFRESH_SECONDS
        ):
            return
        try:
            raw = self._get("/Library/VirtualFolders")
        except ServiceUnavailable:
            return
        if not isinstance(raw, list):
            return
        folders = []
        for library in raw:
            if not isinstance(library, Mapping):
                continue
            name = _text(library.get("Name"))
            locations = library.get("Locations")
            if name and isinstance(locations, list):
                folders.append(
                    (
                        name,
                        tuple(
                            str(loc).rstrip("/")
                            for loc in locations
                            if isinstance(loc, str) and loc.strip("/")
                        ),
                    )
                )
        self._folders = tuple(folders)
        self._folders_read_at = now

    def _libraries_of(self, path: str | None) -> tuple[str, ...]:
        """Every library with a folder holding `path`."""
        if path is None:
            return ()
        return tuple(
            name
            for name, locations in self._folders
            if any(path == d or path.startswith(d + "/") for d in locations)
        )

    def _get(self, path: str) -> object:
        url = self._base + path
        try:
            response = self._http.get(url, timeout=self._timeout)
        except requests.RequestException as error:
            raise ServiceUnavailable(
                f"cannot reach Jellyfin at {self._base} "
                f"({type(error).__name__})"
            ) from error
        if response.status_code in (401, 403):
            raise ServiceUnavailable(
                f"Jellyfin at {self._base} refused the API key "
                f"(HTTP {response.status_code}); use an administrator API key"
            )
        if response.status_code != 200:
            raise ServiceUnavailable(
                f"Jellyfin at {self._base}{path} answered HTTP "
                f"{response.status_code}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise ServiceUnavailable(
                f"Jellyfin at {self._base}{path} did not answer JSON"
            ) from error


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _title(item: Mapping[str, Any]) -> str | None:
    name = _text(item.get("Name"))
    series = _text(item.get("SeriesName"))
    if series and name:
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        if isinstance(season, int) and isinstance(episode, int):
            return f"{series} S{season:02d}E{episode:02d} {name}"
        return f"{series} - {name}"
    return name
