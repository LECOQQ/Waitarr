"""Jellyfin through its HTTP API: an activity source (`/Sessions`) and a
host of scheduled tasks (`/ScheduledTasks`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import requests

from waitarr import __version__
from waitarr.core.model import (
    Playback,
    ScheduledTask,
    ServiceVersion,
    TaskRun,
    TaskState,
)
from waitarr.core.ports import ServiceUnavailable, WriteRefused

__all__ = ["JellyfinSource", "JellyfinTasks"]

# How long the library folders (`/Library/VirtualFolders`) are trusted
# before they are read again: libraries change rarely, a tick is 15 s.
LIBRARY_REFRESH_SECONDS = 600.0


class _JellyfinClient:
    """The HTTP side shared by the source and the task host: the
    authorization header, every request, and the way a failure is
    reported (never with the API key).

    A client built `read_only` refuses, before anything is sent, every
    method but GET: the last of the three layers that keep observation
    mode from writing (see ADR 0004).
    """

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        *,
        read_only: bool,
        timeout: float,
        session: requests.Session | None,
    ) -> None:
        self._name = name
        self._base = url.rstrip("/")
        self._read_only = read_only
        self._timeout = timeout
        self._http = session or requests.Session()
        self._http.headers["Authorization"] = (
            'MediaBrowser Client="Waitarr", Device="Waitarr", '
            f'DeviceId="waitarr-{name}", Version="{__version__}", '
            f'Token="{api_key}"'
        )

    @property
    def name(self) -> str:
        return self._name

    def _request(self, method: str, path: str) -> requests.Response:
        """Send one request; a refused key or an unreachable server is
        `ServiceUnavailable`, any other status is the caller's to judge."""
        if self._read_only and method != "GET":
            raise WriteRefused(
                f"{self._name}: observation mode refused Jellyfin "
                f"{method} {path}"
            )
        try:
            response = self._http.request(
                method, self._base + path, timeout=self._timeout
            )
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
        return response

    def _expect(
        self,
        response: requests.Response,
        method: str,
        path: str,
        *statuses: int,
    ) -> None:
        if response.status_code not in statuses:
            raise ServiceUnavailable(
                f"Jellyfin at {self._base}: {method} {path} answered HTTP "
                f"{response.status_code}"
            )

    def _get(self, path: str) -> object:
        response = self._request("GET", path)
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


class JellyfinSource(_JellyfinClient):
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
        super().__init__(
            name,
            url,
            api_key,
            read_only=True,  # a source only ever reads
            timeout=timeout,
            session=session,
        )
        self._monotonic = monotonic
        self._folders: tuple[tuple[str, tuple[str, ...]], ...] = ()
        self._folders_read_at: float | None = None

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


class JellyfinTasks(_JellyfinClient):
    """Reads, stops and starts the scheduled tasks of one Jellyfin server.

    The API key must belong to an administrator: every task route answers
    403 to a user token. A task is identified by its `Key`; its `Id` is
    only what a call wants back, and Jellyfin makes it up per instance.

    Built `read_only` (observation mode), it reads and nothing else:
    `stop` and `start` raise `WriteRefused` before any request, and the
    request itself refuses every method but GET.
    """

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        *,
        read_only: bool,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(
            name,
            url,
            api_key,
            read_only=read_only,
            timeout=timeout,
            session=session,
        )

    def tasks(self) -> Sequence[ScheduledTask]:
        raw = self._get("/ScheduledTasks")
        if not isinstance(raw, list):
            raise ServiceUnavailable(
                f"{self._base}/ScheduledTasks did not return a list"
            )
        return [self._to_task(entry) for entry in raw]

    def stop(self, task_id: str) -> None:
        """Cancel a running task. Jellyfin answers 500 to a task that is
        not running, also when it has just finished: the task is read
        again, and a task no longer running is not an error."""
        self._refuse_write("stop")
        path = _task_route(task_id)
        response = self._request("DELETE", path)
        if response.status_code == 500 and not self._is_running(task_id):
            return
        self._expect(response, "DELETE", path, 200, 204)

    def _is_running(self, task_id: str) -> bool:
        return any(
            task.id == task_id and task.state is TaskState.RUNNING
            for task in self.tasks()
        )

    def start(self, task_id: str) -> None:
        """Start a task from zero; Jellyfin ignores a task already
        running."""
        self._refuse_write("start")
        path = _task_route(task_id)
        response = self._request("POST", path)
        self._expect(response, "POST", path, 200, 204)

    def _refuse_write(self, what: str) -> None:
        if self._read_only:
            raise WriteRefused(
                f"{self._name}: observation mode refused to {what} a task"
            )

    def _to_task(self, entry: object) -> ScheduledTask:
        if not isinstance(entry, Mapping):
            raise ServiceUnavailable(
                f"{self._base}/ScheduledTasks returned an unexpected entry"
            )
        key, task_id = _text(entry.get("Key")), _text(entry.get("Id"))
        if key is None or task_id is None:
            raise ServiceUnavailable(
                f"{self._base}/ScheduledTasks returned a task without a "
                "Key or an Id"
            )
        try:
            state = TaskState(entry.get("State"))
        except ValueError as error:
            raise ServiceUnavailable(
                f"{self._base}/ScheduledTasks: task {key} is in the "
                f"unknown state {entry.get('State')!r}"
            ) from error
        progress = entry.get("CurrentProgressPercentage")
        return ScheduledTask(
            key=key,
            id=task_id,
            name=_text(entry.get("Name")) or key,
            state=state,
            progress=(
                float(progress)
                if isinstance(progress, int | float)
                and not isinstance(progress, bool)
                else None
            ),
            last=self._to_run(key, entry.get("LastExecutionResult")),
        )

    def _to_run(self, key: str, raw: object) -> TaskRun | None:
        if raw is None:
            return None
        start = raw.get("StartTimeUtc") if isinstance(raw, Mapping) else None
        status = raw.get("Status") if isinstance(raw, Mapping) else None
        if not isinstance(start, str) or not isinstance(status, str):
            raise ServiceUnavailable(
                f"{self._base}/ScheduledTasks: task {key} has an unreadable "
                "last execution"
            )
        return TaskRun(start=start, status=status)


def _task_route(task_id: str) -> str:
    return f"/ScheduledTasks/Running/{quote(task_id, safe='')}"


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
