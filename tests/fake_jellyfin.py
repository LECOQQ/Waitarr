"""A tiny fake Jellyfin: just enough HTTP for `JellyfinSource`.

Serves `GET /System/Info/Public` (no auth) and `GET /Sessions` (needs an
`Authorization` header carrying `Token="<api key>"`, else 401). Sessions
are programmed by the test, or over HTTP with `POST /__test__/sessions`
when the module runs on its own, e.g. in a container:

    python tests/fake_jellyfin.py --port 8096 --api-key K
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_TOKEN = re.compile(r'Token="([^"]*)"')


def session(
    session_id: str = "s1",
    *,
    user: str = "alice",
    device: str = "Living Room",
    client: str = "Jellyfin Web",
    title: str | None = "Dune",
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
    ) -> None:
        self.api_key = api_key
        self.version = version
        self.sessions: list[dict[str, Any]] = []
        self.failing = False  # answer HTTP 500 to everything
        self.requests: list[tuple[str, str]] = []  # (path, token seen)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                fake._get(self)

            def do_POST(self) -> None:  # noqa: N802
                fake._post(self)

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
        elif path == "/Sessions":
            if match is None or match.group(1) != self.api_key:
                self._reply(handler, 401, {"error": "unauthorized"})
            else:
                self._reply(handler, 200, self.sessions)
        else:
            self._reply(handler, 404, {"error": "not found"})

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
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
