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
from urllib.parse import parse_qs, urlsplit

from waitarr import __version__
from waitarr.core.engine import EngineStatus
from waitarr.core.model import ServiceVersion

__all__ = ["HttpSurface", "status_document"]

logger = logging.getLogger("waitarr")

_MAX_BODY = 1024 * 1024
_QUERY = re.compile(r"\?\S*")
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


def status_document(
    status: EngineStatus, *, now: datetime, stale_after: timedelta
) -> tuple[bool, dict[str, object]]:
    """Return (healthy, document). Healthy means a recent tick reached
    every service."""
    fresh = (
        status.last_tick_at is not None
        and now - status.last_tick_at <= stale_after
    )
    healthy = fresh and status.healthy
    if status.last_tick_at is None:
        state = "starting"
    else:
        state = "ok" if healthy else "degraded"
    document: dict[str, object] = {
        "status": state,
        "mode": "observe" if status.simulate else "active",
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
                "severity": d.severity,
                "message": d.message,
            }
            for d in status.diagnostics
        ],
        "targets": {
            name: {
                "ownership": target.ownership.value,
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
            server_version = f"Waitarr/{__version__}"

            def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
                if urlsplit(self.path).path != "/healthz":
                    self._reply(404, {"error": "not found"})
                    return
                healthy, document = surface._status()
                self._reply(200 if healthy else 503, document)

            def do_POST(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                self._drain()
                if parts.path != "/hooks/jellyfin" or not surface._webhook:
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

            def _drain(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if 0 < length <= _MAX_BODY:
                    self.rfile.read(length)

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
