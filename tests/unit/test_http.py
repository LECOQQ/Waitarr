from datetime import timedelta

import pytest
import requests

from tests.fakes import (
    THROTTLE,
    FakeClock,
    FakeSource,
    FakeTarget,
    MemoryStore,
    RecordingHeartbeat,
    RecordingNotifier,
    playback,
)
from waitarr.adapters.http import HttpSurface, status_document
from waitarr.core.engine import Engine, TargetBinding
from waitarr.core.policy import GlobalHysteresisPolicy

STALE_AFTER = timedelta(seconds=45)


class Rig:
    def __init__(self, *, webhook=False, token=None):
        self.clock = FakeClock()
        self.source = FakeSource()
        self.target = FakeTarget("main")
        self.woken = 0
        self.engine = Engine(
            sources=[self.source],
            targets=[TargetBinding(self.target, THROTTLE)],
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

    def health(self):
        return requests.get(self.base + "/healthz", timeout=3)


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


def test_health_lists_the_sessions_being_watched(make_rig):
    rig = make_rig()
    rig.source.sessions = [playback("alice", title="Dune")]
    rig.tick()
    (session,) = rig.health().json()["sessions"]
    assert (session["user"], session["title"]) == ("alice", "Dune")


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
