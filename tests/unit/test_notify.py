import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from waitarr.adapters import notify as notify_module
from waitarr.adapters.notify import (
    FanOutNotifier,
    HealthchecksHeartbeat,
    NtfyNotifier,
    WebhookNotifier,
)
from waitarr.core.ports import Notification, Severity


class Receiver:
    """A local HTTP server that records every POST it gets."""

    def __init__(self):
        self.received: list[dict] = []
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                receiver.received.append(
                    {
                        "path": self.path,
                        "body": self.rfile.read(length),
                        "headers": dict(self.headers),
                    }
                )
                self.send_response(receiver.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02),
            daemon=True,
        ).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def paths(self):
        return [r["path"] for r in self.received]

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def receiver():
    server = Receiver()
    yield server
    server.stop()


@pytest.fixture
def dead_url():
    server = Receiver()
    url = server.url
    server.stop()
    return url


FAILURE = Notification(Severity.FAILURE, "main is down", "cannot reach it")
RECOVERY = Notification(Severity.RECOVERY, "main is back", "reachable again")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def heartbeat(url, clock, interval=60.0):
    return HealthchecksHeartbeat(url, interval=interval, monotonic=clock)


def test_the_first_healthy_beat_pings_success(receiver):
    beat = heartbeat(receiver.url + "/uuid", Clock())
    beat.beat(healthy=True, message="all good")
    assert receiver.paths() == ["/uuid"]
    assert receiver.received[0]["body"] == b"all good"


def test_success_pings_are_limited_by_the_interval(receiver):
    clock = Clock()
    beat = heartbeat(receiver.url + "/uuid", clock, interval=60)
    beat.beat(healthy=True, message="a")
    clock.now += 15
    beat.beat(healthy=True, message="b")
    clock.now += 30
    beat.beat(healthy=True, message="c")
    assert len(receiver.received) == 1
    clock.now += 15
    beat.beat(healthy=True, message="d")
    assert len(receiver.received) == 2


def test_failure_pings_fail_once_per_episode(receiver):
    beat = heartbeat(receiver.url + "/uuid", Clock())
    beat.beat(healthy=True, message="ok")
    for _ in range(4):
        beat.beat(healthy=False, message="down")
    assert receiver.paths() == ["/uuid", "/uuid/fail"]


def test_the_first_beat_can_be_a_failure(receiver):
    beat = heartbeat(receiver.url + "/uuid", Clock())
    beat.beat(healthy=False, message="down")
    assert receiver.paths() == ["/uuid/fail"]


def test_recovery_pings_success_at_once_even_inside_the_interval(receiver):
    clock = Clock()
    beat = heartbeat(receiver.url + "/uuid", clock)
    beat.beat(healthy=True, message="ok")
    clock.now += 1
    beat.beat(healthy=False, message="down")
    clock.now += 1
    beat.beat(healthy=True, message="back")
    assert receiver.paths() == ["/uuid", "/uuid/fail", "/uuid"]


def test_a_second_failure_episode_pings_fail_again(receiver):
    clock = Clock()
    beat = heartbeat(receiver.url + "/uuid", clock)
    beat.beat(healthy=False, message="down")
    beat.beat(healthy=True, message="back")
    beat.beat(healthy=False, message="down again")
    assert receiver.paths().count("/uuid/fail") == 2


def test_a_trailing_slash_in_the_url_is_tolerated(receiver):
    heartbeat(receiver.url + "/uuid/", Clock()).beat(healthy=False, message="x")
    assert receiver.paths() == ["/uuid/fail"]


def test_the_heartbeat_survives_an_unreachable_server(dead_url):
    beat = heartbeat(dead_url + "/uuid", Clock())
    beat.beat(healthy=True, message="ok")
    beat.beat(healthy=False, message="down")


def test_the_webhook_notifier_posts_a_json_event(receiver):
    WebhookNotifier(receiver.url + "/hook").notify(FAILURE)
    (request,) = receiver.received
    assert request["path"] == "/hook"
    assert json.loads(request["body"]) == {
        "source": "waitarr",
        "event": "failure",
        "title": "main is down",
        "message": "cannot reach it",
    }


def test_the_ntfy_notifier_publishes_the_message_with_priority_headers(
    receiver,
):
    NtfyNotifier(receiver.url + "/topic", token="tk").notify(FAILURE)
    (request,) = receiver.received
    assert request["body"] == b"cannot reach it"
    assert request["headers"]["Title"] == "main is down"
    assert request["headers"]["Priority"] == "high"
    assert request["headers"]["Authorization"] == "Bearer tk"


def test_the_ntfy_notifier_sends_recoveries_at_default_priority(receiver):
    NtfyNotifier(receiver.url + "/topic").notify(RECOVERY)
    (request,) = receiver.received
    assert request["headers"]["Priority"] == "default"
    assert "Authorization" not in request["headers"]


@pytest.mark.parametrize("make", [WebhookNotifier, NtfyNotifier])
def test_notifiers_never_raise_on_a_network_error(make, dead_url):
    make(dead_url + "/x", timeout=1).notify(FAILURE)


@pytest.mark.parametrize("make", [WebhookNotifier, NtfyNotifier])
def test_notifiers_never_raise_on_an_http_error(make, receiver):
    receiver.status = 500
    make(receiver.url + "/x").notify(FAILURE)
    assert len(receiver.received) == 1


@pytest.mark.parametrize("error", [requests.ConnectionError, requests.Timeout])
def test_notifiers_never_raise_when_requests_fails(monkeypatch, error):
    def post(*args, **kwargs):
        raise error("boom")

    monkeypatch.setattr(notify_module.requests, "post", post)
    WebhookNotifier("http://x").notify(FAILURE)
    NtfyNotifier("http://x").notify(FAILURE)
    heartbeat("http://x", Clock()).beat(healthy=True, message="m")


def test_the_fan_out_reaches_every_notifier_even_after_a_dead_one(
    receiver, dead_url
):
    FanOutNotifier(
        [
            WebhookNotifier(dead_url + "/a", timeout=1),
            NtfyNotifier(receiver.url),
        ]
    ).notify(FAILURE)
    assert len(receiver.received) == 1
