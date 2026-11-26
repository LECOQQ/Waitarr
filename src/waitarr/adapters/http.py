"""The HTTP surface: `GET /healthz` for supervision, and an optional
`POST /hooks/jellyfin` that wakes the loop early.

The webhook only shortens the wait before the next poll; it never
carries a decision. Polling stays the source of truth.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import parse_qs, urlsplit

from waitarr import __version__
from waitarr.config import WEBHOOK_PATH, Mode
from waitarr.core.engine import EngineStatus
from waitarr.core.model import ServiceVersion

__all__ = ["HttpSurface", "status_document"]

logger = logging.getLogger("waitarr")

_MAX_BODY = 1024 * 1024
_QUERY = re.compile(r"\?\S*")
_URL = re.compile(r"https?://[^\s)]*[^\s).,;]")
# A webhook flood costs at most one extra poll per this many seconds.
_WEBHOOK_MIN_INTERVAL = 5.0


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _version(value: ServiceVersion | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "product": value.product,
        "version": value.version,
        "api_version": value.api_version,
    }


def _without_urls(text: str) -> str:
    return _URL.sub("<url>", text)


def public_view(document: dict[str, object]) -> dict[str, object]:
    """What a caller without the token may read: enough to judge the
    health, but not who watches what, nor where the services are."""
    services = cast("dict[str, dict[str, object]]", document["services"])
    warnings = cast("list[dict[str, object]]", document["warnings"])
    task_errors = cast("dict[str, str]", document["task_errors"])
    sessions = cast("list[dict[str, object]]", document["sessions"])
    return {
        **{k: v for k, v in document.items() if k != "version"},
        "sessions": [
            {key: s[key] for key in ("source", "paused")} for s in sessions
        ],
        "services": {
            name: {
                **{k: v for k, v in service.items() if k != "version"},
                "error": (
                    _without_urls(str(service["error"]))
                    if service["error"]
                    else None
                ),
            }
            for name, service in services.items()
        },
        "warnings": [
            {**w, "message": _without_urls(str(w["message"]))} for w in warnings
        ],
        "task_errors": {
            host: _without_urls(error) for host, error in task_errors.items()
        },
    }


def status_document(
    status: EngineStatus,
    *,
    now: datetime,
    stale_after: timedelta,
) -> tuple[bool, dict[str, object]]:
    """Return (healthy, document). Healthy means a recent tick reached
    every service. `libraries_unreadable` names the sources whose library
    folders could not be read: it marks the document, not the health."""
    fresh = (
        status.last_tick_at is not None
        and now - status.last_tick_at <= stale_after
    )
    healthy = fresh and status.healthy
    if status.last_tick_at is None:
        # "Starting" lasts one staleness window; a first tick that never
        # comes after that is a fault, not a slow start.
        state = (
            "starting" if now - status.started_at <= stale_after else "degraded"
        )
    else:
        state = "ok" if healthy else "degraded"
    document: dict[str, object] = {
        "status": state,
        "mode": (Mode.OBSERVE if status.simulate else Mode.ACTIVE).value,
        "version": __version__,
        "started_at": _iso(status.started_at),
        "last_tick_at": _iso(status.last_tick_at),
        "sessions": [
            {
                "source": p.source,
                "user": p.user,
                "title": p.title,
                "device": p.device,
                "client": p.client,
                "paused": p.paused,
            }
            for p in status.playbacks
        ],
        "services": {
            name: {
                "kind": health.kind,
                "reachable": health.reachable,
                "error": health.error,
                "since": _iso(health.since),
                "version": _version(health.version),
            }
            for name, health in status.services.items()
        },
        "warnings": [
            {
                "target": d.target,
                "severity": d.severity.value,
                "message": d.message,
            }
            for d in status.diagnostics
        ],
        "targets": {
            name: {
                "ownership": target.ownership.value,
                "phase": target.phase.value,
                "throttled": (
                    target.observed.throttled if target.observed else None
                ),
                "download_limit": (
                    target.observed.limits.download if target.observed else None
                ),
                "upload_limit": (
                    target.observed.limits.upload if target.observed else None
                ),
                "last_action": (
                    target.last_action.value if target.last_action else None
                ),
                "last_action_at": _iso(target.last_action_at),
            }
            for name, target in status.targets.items()
        },
        "tasks": {
            host: {
                key: {
                    "ownership": task.ownership.value,
                    "phase": task.phase.value,
                    "state": task.state.value if task.state else None,
                    "progress": task.progress,
                    "last_action": (
                        task.last_action.value if task.last_action else None
                    ),
                    "last_action_at": _iso(task.last_action_at),
                }
                for key, task in owned.items()
            }
            for host, owned in status.tasks.items()
        },
        "task_errors": dict(status.task_errors),
        "libraries_unreadable": list(status.libraries_unreadable),
    }
    return healthy, document


class HttpSurface:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        status: Callable[[], tuple[bool, dict[str, object]]],
        wake: Callable[[], None],
        webhook_enabled: bool,
        webhook_token: str | None,
    ) -> None:
        surface = self

        class Handler(BaseHTTPRequestHandler):
            def version_string(self) -> str:
                # No version of Waitarr or of Python for a passer-by.
                return "Waitarr"

            def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
                if urlsplit(self.path).path != "/healthz":
                    self._reply(404, {"error": "not found"})
                    return
                healthy, document = surface._status()
                if not surface._holds_token(
                    self.headers.get("X-Waitarr-Token")
                ):
                    document = public_view(document)
                self._reply(200 if healthy else 503, document)

            def do_POST(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                if not self._drain():
                    self._reply(400, {"error": "bad Content-Length"})
                    return
                if parts.path != WEBHOOK_PATH or not surface._webhook:
                    self._reply(404, {"error": "not found"})
                    return
                if not surface._authorised(
                    self.headers.get("X-Waitarr-Token"),
                    parse_qs(parts.query).get("token", [None])[0],
                ):
                    self._reply(401, {"error": "bad or missing token"})
                    return
                surface._nudge()
                self._reply(202, {"status": "poll scheduled"})

            def _drain(self) -> bool:
                """Read the body; False when its length is not a size."""
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return False
                if length < 0:
                    return False
                if 0 < length <= _MAX_BODY:
                    self.rfile.read(length)
                return True

            def _reply(self, code: int, body: dict[str, object]) -> None:
                payload = json.dumps(body, indent=2).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_request(
                self, code: int | str = "-", size: int | str = "-"
            ) -> None:
                # Never the query string: it may carry the webhook token.
                logger.debug(
                    "http: %s %s %s",
                    self.command,
                    urlsplit(self.path).path,
                    code,
                )

            def log_message(self, format: str, *args: object) -> None:
                logger.debug("http: %s", _QUERY.sub("?...", format % args))

        self._status = status
        self._wake = wake
        self._webhook = webhook_enabled
        self._token = webhook_token
        self._last_nudge: float | None = None
        self._nudge_lock = threading.Lock()
        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.1),
            name="waitarr-http",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def _nudge(self) -> None:
        now = time.monotonic()
        with self._nudge_lock:
            if (
                self._last_nudge is not None
                and now - self._last_nudge < _WEBHOOK_MIN_INTERVAL
            ):
                return
            self._last_nudge = now
        self._wake()

    def _holds_token(self, header: str | None) -> bool:
        """The token is the key to the detail of `/healthz`: without a
        configured token, nobody holds it."""
        return bool(self._token) and self._authorised(header, None)

    def _authorised(self, header: str | None, query: str | None) -> bool:
        if not self._token:
            return True
        offered = header or query or ""
        return hmac.compare_digest(offered.encode(), self._token.encode())

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
