"""A tiny fake Jellyfin: just enough HTTP for `JellyfinSource` and
`JellyfinTasks`.

Serves `GET /System/Info/Public` (no auth), `GET /Sessions`,
`GET /Library/VirtualFolders` and `GET /ScheduledTasks` (all need an
`Authorization` header carrying `Token="<api key>"`, else 401), plus
`DELETE` and `POST /ScheduledTasks/Running/{Id}`. The scheduled tasks
behave as Jellyfin 12.2.0 was probed: a stop on a task at rest is an
HTTP 500, a stopped task is `Cancelling` for a while before it is idle
with a `Cancelled` last execution, and a start on a running task is
ignored. Sessions are programmed by the test, or over HTTP with
`POST /__test__/sessions` when the module runs on its own, e.g. in a
container:

    python tests/fake_jellyfin.py --port 8096 --api-key K
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_TOKEN = re.compile(r'Token="([^"]*)"')
_TASK_ROUTE = re.compile(r"^/ScheduledTasks/Running/([^/]+)$")

DEFAULT_TASK_KEYS = (
    "RefreshLibrary",
    "TaskExtractMediaSegments",
    "RefreshChapterImages",
    "RefreshTrickplayImages",
)


class FakeTask:
    """One scheduled task: `state` is "Idle", "Running" or "Cancelling".

    `last` is the last execution, (start, status), or `None`. A running
    task keeps the previous execution as its last, as Jellyfin does.
    """

    def __init__(self, key: str, task_id: str, name: str, start: str) -> None:
        self.key = key
        self.id = task_id
        self.name = name
        self.state = "Idle"
        self.progress: float | None = None
        self.last: tuple[str, str] | None = (start, "Completed")
        self.current: str | None = None  # start of the execution running
        self.cancel_reads = 0  # reads left before Cancelling becomes Idle

    def as_json(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "Id": self.id,
            "Key": self.key,
            "Name": self.name,
            "State": self.state,
        }
        if self.progress is not None:
            entry["CurrentProgressPercentage"] = self.progress
        if self.last is not None:
            entry["LastExecutionResult"] = {
                "StartTimeUtc": self.last[0],
                "EndTimeUtc": self.last[0],
                "Status": self.last[1],
            }
        return entry


def session(
    session_id: str = "s1",
    *,
    user: str = "alice",
    device: str = "device-1",
    client: str = "Jellyfin Web",
    title: str | None = "A film",
    item_type: str = "Movie",
    paused: bool = False,
    series: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """A /Sessions entry; `title=None` gives an idle session."""
    entry: dict[str, Any] = {
        "Id": session_id,
        "UserName": user,
        "DeviceName": device,
        "Client": client,
        "PlayState": {"IsPaused": paused},
    }
    if title is not None:
        item: dict[str, Any] = {"Name": title, "Type": item_type}
        if series is not None:
            item["SeriesName"] = series
        if season is not None:
            item["ParentIndexNumber"] = season
        if episode is not None:
            item["IndexNumber"] = episode
        if path is not None:
            item["Path"] = path
        entry["NowPlayingItem"] = item
    return entry


class FakeJellyfin:
    def __init__(
        self,
        api_key: str = "test-key",
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        version: str = "12.2.0",
        task_keys: tuple[str, ...] = DEFAULT_TASK_KEYS,
    ) -> None:
        self.api_key = api_key
        self.version = version
        self._runs = 0
        self.tasks: dict[str, FakeTask] = {}
        for key in task_keys:
            self.add_task(key)
        self.cancelling_reads = 1  # reads a stopped task stays Cancelling
        self.stop_fails = False  # a stop answers 500 and does nothing
        self.tasks_forbidden = False  # answer 403, like a non-admin token
        self.raw_tasks: object | None = None  # replaces the task list
        self.writes: list[tuple[str, str]] = []  # (method, path)
        self.sessions: list[dict[str, Any]] = []
        self.libraries: dict[str, list[str]] = {}  # name -> folders
        self.failing = False  # answer HTTP 500 to everything
        self.requests: list[tuple[str, str]] = []  # (path, token seen)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                fake._get(self)

            def do_POST(self) -> None:  # noqa: N802
                fake._post(self)

            def do_DELETE(self) -> None:  # noqa: N802
                fake._delete(self)

            def log_message(self, format: str, *args: object) -> None:
                return None

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02),
            daemon=True,
        )

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> FakeJellyfin:
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop answering and release the port (connection refused)."""
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeJellyfin:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def add_task(self, key: str) -> FakeTask:
        task = FakeTask(
            key,
            uuid.uuid5(uuid.NAMESPACE_URL, key).hex,
            f"Task {key}",
            self._next_start(),
        )
        self.tasks[key] = task
        return task

    def _next_start(self) -> str:
        self._runs += 1
        moment = datetime(2026, 10, 30, tzinfo=UTC) + timedelta(
            minutes=self._runs
        )
        return moment.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

    def run_task(self, key: str, progress: float = 10.0) -> None:
        """Start a task, as the schedule or a human would."""
        task = self.tasks[key]
        if task.state == "Idle":
            task.state = "Running"
            task.progress = progress
            task.current = self._next_start()

    def finish_task(self, key: str, status: str = "Completed") -> None:
        """End the running task by itself (or let it fail)."""
        task = self.tasks[key]
        assert task.current is not None
        task.last = (task.current, status)
        task.state, task.progress, task.current = "Idle", None, None

    def _tick_tasks(self) -> None:
        """One read of the task list: a stopped task moves on."""
        for task in self.tasks.values():
            if task.state != "Cancelling":
                continue
            task.cancel_reads -= 1
            if task.cancel_reads <= 0:
                self.finish_task(task.key, "Cancelled")

    def _authorized(self, handler: BaseHTTPRequestHandler, path: str) -> bool:
        match = _TOKEN.search(handler.headers.get("Authorization") or "")
        self.requests.append((path, match.group(1) if match else ""))
        if self.failing:
            self._reply(handler, 500, {"error": "internal"})
        elif match is None or match.group(1) != self.api_key:
            self._reply(handler, 401, {"error": "unauthorized"})
        elif self.tasks_forbidden and path.startswith("/ScheduledTasks"):
            self._reply(handler, 403, {"error": "forbidden"})
        else:
            return True
        return False

    def _delete(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path.split("?")[0]
        self.writes.append(("DELETE", path))
        if not self._authorized(handler, path):
            return
        task = self._task_of(path)
        if task is None:
            self._reply(handler, 404, {"error": "not found"})
        elif task.state != "Running" or self.stop_fails:
            self._reply(
                handler,
                500,
                {
                    "error": "Cannot cancel a Task unless it is in the "
                    "Running state"
                },
            )
        else:
            task.state = "Cancelling"
            task.cancel_reads = self.cancelling_reads
            self._reply(handler, 204, None)

    def _task_of(self, path: str) -> FakeTask | None:
        match = _TASK_ROUTE.match(path)
        if match is None:
            return None
        return next(
            (t for t in self.tasks.values() if t.id == match.group(1)), None
        )

    def _get(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path.split("?")[0]
        match = _TOKEN.search(handler.headers.get("Authorization") or "")
        self.requests.append((path, match.group(1) if match else ""))
        if self.failing:
            self._reply(handler, 500, {"error": "internal"})
        elif path == "/System/Info/Public":
            self._reply(
                handler,
                200,
                {
                    "ProductName": "Jellyfin Server",
                    "Version": self.version,
                    "ServerName": "fake",
                },
            )
        elif match is None or match.group(1) != self.api_key:
            self._reply(handler, 401, {"error": "unauthorized"})
        elif self.tasks_forbidden and path == "/ScheduledTasks":
            self._reply(handler, 403, {"error": "forbidden"})
        elif path == "/Sessions":
            self._reply(handler, 200, self.sessions)
        elif path == "/ScheduledTasks":
            body = (
                self.raw_tasks
                if self.raw_tasks is not None
                else [t.as_json() for t in self.tasks.values()]
            )
            self._tick_tasks()  # a stopped task moves on after this read
            self._reply(handler, 200, body)
        elif path == "/Library/VirtualFolders":
            self._reply(
                handler,
                200,
                [
                    {"Name": name, "Locations": locations}
                    for name, locations in self.libraries.items()
                ],
            )
        else:
            self._reply(handler, 404, {"error": "not found"})

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        path = handler.path.split("?")[0]
        if _TASK_ROUTE.match(path):
            self._start_task(handler, path)
            return
        if handler.path != "/__test__/sessions":
            self._reply(handler, 404, {"error": "not found"})
            return
        try:
            sessions = json.loads(body or b"[]")
        except ValueError:
            self._reply(handler, 400, {"error": "not JSON"})
            return
        if not isinstance(sessions, list):
            self._reply(handler, 400, {"error": "expected a list"})
            return
        self.sessions = sessions
        self._reply(handler, 204, None)

    def _start_task(self, handler: BaseHTTPRequestHandler, path: str) -> None:
        self.writes.append(("POST", path))
        if not self._authorized(handler, path):
            return
        task = self._task_of(path)
        if task is None:
            self._reply(handler, 404, {"error": "not found"})
            return
        self.run_task(task.key, progress=0.0)  # ignored unless at rest
        self._reply(handler, 204, None)

    @staticmethod
    def _reply(
        handler: BaseHTTPRequestHandler, code: int, body: object
    ) -> None:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8096)
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()
    fake = FakeJellyfin(args.api_key, host=args.host, port=args.port)
    print(f"fake Jellyfin on {fake.url}", flush=True)
    try:
        fake._server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
