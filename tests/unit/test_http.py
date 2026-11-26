from dataclasses import replace
from datetime import timedelta

import pytest
import requests

from tests.fakes import (
    THROTTLE,
    FakeClock,
    FakeSource,
    FakeTarget,
    FakeTaskHost,
    MemoryStore,
    RecordingHeartbeat,
    RecordingNotifier,
    playback,
)
from waitarr.adapters.http import HttpSurface, status_document
from waitarr.core.engine import Engine, TargetBinding, TaskBinding
from waitarr.core.policy import GlobalHysteresisPolicy

STALE_AFTER = timedelta(seconds=45)


class Rig:
    def __init__(self, *, webhook=False, token=None):
        self.clock = FakeClock()
        self.source = FakeSource()
        self.target = FakeTarget("main")
        self.tasks = FakeTaskHost("jellyfin", keys=("RefreshLibrary", "Other"))
        self.woken = 0
        self.engine = Engine(
            sources=[self.source],
            targets=[TargetBinding(self.target, THROTTLE)],
            task_hosts=[TaskBinding(self.tasks, ("RefreshLibrary", "Other"))],
            policy=GlobalHysteresisPolicy(release_after=timedelta(minutes=3)),
            store=MemoryStore(),
            notifier=RecordingNotifier(),
            heartbeat=RecordingHeartbeat(),
            simulate=False,
            clock=self.clock,
        )
        self.surface = HttpSurface(
            host="127.0.0.1",
            port=0,
            status=lambda: status_document(
                self.engine.status(),
                now=self.clock(),
                stale_after=STALE_AFTER,
            ),
            wake=self._wake,
            webhook_enabled=webhook,
            webhook_token=token,
        )
        self.surface.start()
        self.base = f"http://127.0.0.1:{self.surface.port}"

    def _wake(self):
        self.woken += 1

    def tick(self, seconds=15):
        self.clock.advance(seconds)
        self.engine.tick()

    def health(self, token=None):
        headers = {"X-Waitarr-Token": token} if token else {}
        return requests.get(self.base + "/healthz", headers=headers, timeout=3)


@pytest.fixture
def make_rig():
    rigs = []

    def make(**kwargs):
        rigs.append(Rig(**kwargs))
        return rigs[-1]

    yield make
    for rig in rigs:
        rig.surface.stop()


def test_health_is_503_and_starting_before_the_first_tick(make_rig):
    response = make_rig().health()
    assert response.status_code == 503
    assert response.json()["status"] == "starting"


def test_stopping_an_idle_surface_does_not_wait_for_its_wakeup():
    import time

    for _ in range(5):
        surface = HttpSurface(
            host="127.0.0.1",
            port=0,
            status=lambda: (True, {}),
            wake=lambda: None,
            webhook_enabled=False,
            webhook_token=None,
        )
        surface.start()
        time.sleep(0.05)  # let the thread settle in its wait
        began = time.monotonic()
        surface.stop()
        assert time.monotonic() - began < 0.3


def test_health_is_still_starting_just_inside_the_staleness_window(make_rig):
    rig = make_rig()
    rig.clock.advance(STALE_AFTER.total_seconds() - 1)
    assert rig.health().json()["status"] == "starting"


def test_health_is_degraded_when_no_tick_came_within_the_window(make_rig):
    rig = make_rig()
    rig.clock.advance(STALE_AFTER.total_seconds() + 1)
    response = rig.health()
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_is_200_when_a_recent_tick_reached_every_service(make_rig):
    rig = make_rig()
    rig.tick()
    response = rig.health()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "active"
    assert body["services"]["jellyfin"]["reachable"] is True
    assert body["targets"]["main"]["ownership"] == "idle"
    assert body["targets"]["main"]["phase"] == "idle"


def test_health_names_the_phase_of_a_throttled_target(make_rig):
    rig = make_rig()
    rig.source.sessions = [playback()]
    rig.tick()
    target = rig.health().json()["targets"]["main"]
    assert target["ownership"] == "engaged"
    assert target["phase"] == "engaged"


def test_health_lists_the_sessions_being_watched_to_the_token_holder(make_rig):
    rig = make_rig(token="hook-token")
    rig.source.sessions = [playback("alice", title="A film")]
    rig.tick()
    (session,) = rig.health(token="hook-token").json()["sessions"]
    assert (session["user"], session["title"]) == ("alice", "A film")
    assert {"device", "client"} <= set(session)


@pytest.mark.parametrize("sent", [None, "wrong"])
def test_health_keeps_who_watches_what_from_a_caller_without_the_token(
    make_rig, sent
):
    rig = make_rig(token="hook-token")
    rig.source.sessions = [playback("alice", title="A film")]
    rig.tick()
    response = rig.health(token=sent)
    assert response.status_code == 200
    (session,) = response.json()["sessions"]
    assert set(session) == {"source", "paused"}
    assert "alice" not in response.text
    assert "A film" not in response.text


def test_health_shows_no_session_detail_when_no_token_is_configured(make_rig):
    rig = make_rig()
    rig.source.sessions = [playback("alice", title="A film")]
    rig.tick()
    (session,) = rig.health(token="anything").json()["sessions"]
    assert set(session) == {"source", "paused"}


def test_health_keeps_the_internal_url_of_a_service_from_a_caller(make_rig):
    from waitarr.core.ports import ServiceUnavailable

    def unreachable():
        raise ServiceUnavailable(
            "cannot reach Jellyfin at http://media-host:8096 (ConnectError)"
        )

    rig = make_rig(token="hook-token")
    rig.source.playbacks = unreachable
    rig.tick()
    body = rig.health().json()
    assert body["services"]["jellyfin"]["reachable"] is False
    assert "media-host" not in rig.health().text
    assert "cannot reach Jellyfin" in body["services"]["jellyfin"]["error"]
    assert "media-host" in rig.health(token="hook-token").text


def test_health_keeps_the_versions_from_a_caller_without_the_token(make_rig):
    from waitarr import __version__

    rig = make_rig(token="hook-token")
    rig.engine.check_versions()
    rig.tick()
    known = rig.health(token="hook-token").json()
    assert known["version"] == __version__
    assert known["services"]["jellyfin"]["version"] is not None
    body = rig.health().json()
    assert "version" not in body
    assert all("version" not in s for s in body["services"].values())


def test_the_server_header_names_no_version(make_rig):
    from waitarr import __version__

    server = make_rig().health().headers["Server"]
    assert __version__ not in server
    assert "Python" not in server


@pytest.mark.parametrize("length", ["abc", "-5"])
def test_a_content_length_that_is_not_a_size_is_a_400(make_rig, length):
    import socket

    rig = make_rig(webhook=True)
    with socket.create_connection(("127.0.0.1", rig.surface.port), 3) as s:
        s.sendall(
            b"POST /hooks/jellyfin HTTP/1.0\r\n"
            b"Content-Length: " + length.encode() + b"\r\n\r\n"
        )
        reply = s.makefile("rb").readline()
    assert reply.split()[1] == b"400"
    assert rig.woken == 0


def test_status_with_the_token_shows_the_sessions(make_rig, monkeypatch):
    from typer.testing import CliRunner

    from waitarr import cli

    rig = make_rig(token="hook-token")
    rig.source.sessions = [playback("alice", title="A film")]
    rig.tick()
    runner = CliRunner()
    anonymous = runner.invoke(cli.app, ["status", "--url", rig.base])
    assert "alice" not in anonymous.output
    monkeypatch.setenv("WAITARR_WEBHOOK_TOKEN", "hook-token")
    known = runner.invoke(cli.app, ["status", "--url", rig.base])
    assert "alice" in known.output


def test_health_marks_a_source_whose_library_folders_cannot_be_read(make_rig):
    rig = make_rig()
    rig.tick()
    status = rig.engine.status()
    _, plain = status_document(status, now=rig.clock(), stale_after=STALE_AFTER)
    healthy, marked = status_document(
        replace(status, libraries_unreadable=("jellyfin",)),
        now=rig.clock(),
        stale_after=STALE_AFTER,
    )
    assert plain["libraries_unreadable"] == []
    assert marked["libraries_unreadable"] == ["jellyfin"]
    assert healthy is True


def test_health_is_503_when_the_source_is_unreachable(make_rig):
    rig = make_rig()
    rig.tick()
    rig.source.down = True
    rig.tick()
    response = rig.health()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["jellyfin"]["reachable"] is False


def test_health_is_503_when_the_target_is_unreachable(make_rig):
    rig = make_rig()
    rig.target.down = True
    rig.tick()
    response = rig.health()
    assert response.status_code == 503
    assert response.json()["services"]["main"]["reachable"] is False


def test_health_recovers_when_the_service_comes_back(make_rig):
    rig = make_rig()
    rig.source.down = True
    rig.tick()
    rig.source.down = False
    rig.tick()
    assert rig.health().status_code == 200


def test_health_is_503_when_the_last_tick_is_too_old(make_rig):
    rig = make_rig()
    rig.tick()
    rig.clock.advance(STALE_AFTER.total_seconds() + 1)
    response = rig.health()
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_is_still_200_just_inside_the_staleness_window(make_rig):
    rig = make_rig()
    rig.tick()
    rig.clock.advance(STALE_AFTER.total_seconds() - 1)
    assert rig.health().status_code == 200


def test_the_health_document_never_carries_a_secret_field(make_rig):
    rig = make_rig(token="hook-token")
    rig.tick()
    assert "hook-token" not in rig.health().text


def test_unknown_paths_are_404(make_rig):
    rig = make_rig()
    assert requests.get(rig.base + "/nope", timeout=3).status_code == 404


def test_the_webhook_is_404_when_disabled(make_rig):
    rig = make_rig(webhook=False)
    response = requests.post(rig.base + "/hooks/jellyfin", timeout=3)
    assert response.status_code == 404
    assert rig.woken == 0


def test_the_webhook_refuses_a_wrong_token(make_rig):
    rig = make_rig(webhook=True, token="right")
    response = requests.post(
        rig.base + "/hooks/jellyfin",
        headers={"X-Waitarr-Token": "wrong"},
        timeout=3,
    )
    assert response.status_code == 401
    assert rig.woken == 0


def test_the_webhook_refuses_a_missing_token(make_rig):
    rig = make_rig(webhook=True, token="right")
    response = requests.post(rig.base + "/hooks/jellyfin", timeout=3)
    assert response.status_code == 401
    assert rig.woken == 0


def test_the_webhook_refuses_a_wrong_token_in_the_query(make_rig):
    rig = make_rig(webhook=True, token="right")
    response = requests.post(
        rig.base + "/hooks/jellyfin?token=wrong", timeout=3
    )
    assert response.status_code == 401


def test_the_webhook_accepts_the_token_in_the_header(make_rig):
    rig = make_rig(webhook=True, token="right")
    response = requests.post(
        rig.base + "/hooks/jellyfin",
        headers={"X-Waitarr-Token": "right"},
        json={"NotificationType": "PlaybackStart"},
        timeout=3,
    )
    assert response.status_code == 202
    assert rig.woken == 1


def test_the_webhook_accepts_the_token_in_the_query(make_rig):
    rig = make_rig(webhook=True, token="right")
    response = requests.post(
        rig.base + "/hooks/jellyfin?token=right", timeout=3
    )
    assert response.status_code == 202
    assert rig.woken == 1


def test_a_webhook_without_a_configured_token_accepts_anyone(make_rig):
    rig = make_rig(webhook=True, token=None)
    response = requests.post(rig.base + "/hooks/jellyfin", timeout=3)
    assert response.status_code == 202


def test_the_webhook_only_wakes_the_loop_and_changes_nothing(make_rig):
    rig = make_rig(webhook=True, token="t")
    rig.source.sessions = [playback()]
    requests.post(rig.base + "/hooks/jellyfin?token=t", timeout=3)
    assert rig.target.writes == []


def test_get_on_the_webhook_path_is_404(make_rig):
    rig = make_rig(webhook=True, token="t")
    assert (
        requests.get(
            rig.base + "/hooks/jellyfin?token=t", timeout=3
        ).status_code
        == 404
    )


def test_a_webhook_flood_wakes_the_loop_once(make_rig):
    rig = make_rig(webhook=True, token=None)
    for _ in range(5):
        assert (
            requests.post(rig.base + "/hooks/jellyfin", timeout=3).status_code
            == 202
        )
    assert rig.woken == 1


def test_the_webhook_token_never_reaches_the_log(make_rig, caplog):
    caplog.set_level("DEBUG", logger="waitarr")
    rig = make_rig(webhook=True, token="UNMISTAKABLE-TOKEN")
    requests.post(
        rig.base + "/hooks/jellyfin?token=UNMISTAKABLE-TOKEN", timeout=3
    )
    requests.post(rig.base + "/hooks/jellyfin?token=UNMISTAKABLE-X", timeout=3)
    assert caplog.records
    assert not any("UNMISTAKABLE" in r.getMessage() for r in caplog.records)


def test_health_lists_the_warnings_found_at_the_last_check(make_rig):
    from waitarr.core.model import Diagnostic, DiagnosticSeverity

    rig = make_rig()
    rig.target.diagnostics = [
        Diagnostic(
            "main",
            DiagnosticSeverity.WARNING,
            "main: µTP traffic is not rate-limited",
        )
    ]
    rig.engine.diagnose()
    rig.tick()
    body = requests.get(rig.base + "/healthz", timeout=3).json()
    assert body["warnings"] == [
        {
            "target": "main",
            "severity": "warning",
            "message": "main: µTP traffic is not rate-limited",
        }
    ]


def test_health_shows_no_task_when_waitarr_owns_none(make_rig):
    rig = make_rig()
    rig.tick()
    body = rig.health().json()
    assert body["tasks"] == {"jellyfin": {}}
    assert body["task_errors"] == {}


def test_health_lists_the_tasks_waitarr_stopped(make_rig):
    rig = make_rig()
    rig.tasks.run("RefreshLibrary")
    rig.source.sessions = [playback()]
    rig.tick()
    body = rig.health().json()
    assert set(body["tasks"]["jellyfin"]) == {"RefreshLibrary"}
    stopped = body["tasks"]["jellyfin"]["RefreshLibrary"]
    assert stopped["ownership"] == "stopped"
    assert (
        stopped["phase"]
        == rig.engine.status().tasks["jellyfin"]["RefreshLibrary"].phase.value
    )
    assert stopped["last_action"] == "stop"
    assert stopped["last_action_at"].startswith("2026-10-27T")
    assert stopped["state"] in ("Cancelling", "Idle")
    assert "progress" in stopped


def test_health_names_the_task_host_it_cannot_read_and_stays_200(make_rig):
    rig = make_rig()
    rig.source.sessions = [playback()]
    rig.tasks.down = True
    rig.tick()
    response = rig.health()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "connection refused" in body["task_errors"]["jellyfin"]
