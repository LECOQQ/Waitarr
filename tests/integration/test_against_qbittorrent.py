"""The real adapters against a real, disposable qBittorrent (and the fake
Jellyfin), the engine driven tick by tick on a fake clock."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
import requests

from tests.fake_jellyfin import session
from tests.fakes import FakeClock
from tests.integration.conftest import (
    BASELINE_ALT,
    RELEASE_AFTER,
    THROTTLE,
    Snapshot,
    free_port,
)
from waitarr.adapters.state_file import JsonStateFile
from waitarr.bootstrap import (
    SOURCE_FACTORIES,
    TARGET_FACTORIES,
    build_engine,
    build_notifier,
    build_policy,
)
from waitarr.config import load_config
from waitarr.core.engine import Engine, TargetBinding
from waitarr.core.reconcile import Ownership

pytestmark = pytest.mark.docker

AFTER_DELAY = RELEASE_AFTER.total_seconds() + 30


def test_a_playback_activates_the_alternative_mode_with_the_configured_limits(
    admin, jellyfin, make_rig
):
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    now = Snapshot.take(admin)
    assert now.throttled
    # Raw preferences are bytes per second, as the adapter assumes.
    assert now.preferences["alt_dl_limit"] == THROTTLE.download == 8192
    assert now.preferences["alt_up_limit"] == THROTTLE.upload == 16384


def test_the_end_of_playback_restores_the_mode_and_limits_found_before(
    admin, jellyfin, make_rig
):
    before = Snapshot.take(admin)
    assert not before.throttled and before.alt == BASELINE_ALT
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    jellyfin.sessions = []
    rig.tick(60)
    assert Snapshot.take(admin).throttled  # still inside the delay
    rig.tick(AFTER_DELAY)
    after = Snapshot.take(admin)
    assert not after.throttled
    assert after.alt == BASELINE_ALT
    assert after.preferences["dl_limit"] == before.preferences["dl_limit"]


def test_a_pause_shorter_than_the_delay_writes_nothing(
    admin, jellyfin, make_rig
):
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    engaged = Snapshot.take(admin)
    jellyfin.sessions = [session(paused=True)]
    for _ in range(6):
        rig.tick()
    jellyfin.sessions = [session()]
    rig.tick()
    assert Snapshot.take(admin) == engaged
    jellyfin.sessions = []
    rig.tick(AFTER_DELAY)
    assert not Snapshot.take(admin).throttled


def test_a_mode_already_active_before_playback_is_never_touched(
    admin, jellyfin, make_rig
):
    admin.transfer_set_speed_limits_mode(intended_state=True)
    before = Snapshot.take(admin)
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    assert Snapshot.take(admin) == before
    assert rig.engine.status().targets["main"].ownership is Ownership.YIELDED
    jellyfin.sessions = []
    rig.tick(AFTER_DELAY)
    rig.tick()
    assert Snapshot.take(admin) == before
    assert rig.engine.status().targets["main"].ownership is Ownership.IDLE


def test_a_manual_switch_during_playback_is_respected_then_resumed_after(
    admin, jellyfin, make_rig
):
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    admin.transfer_set_speed_limits_mode(intended_state=False)  # a human
    rig.tick()
    rig.tick()
    assert not Snapshot.take(admin).throttled
    assert rig.engine.status().targets["main"].ownership is Ownership.YIELDED
    jellyfin.sessions = []
    rig.tick(AFTER_DELAY)
    assert not Snapshot.take(admin).throttled
    jellyfin.sessions = [session("next")]
    rig.tick()
    assert Snapshot.take(admin).throttled
    assert rig.engine.status().targets["main"].ownership is Ownership.ENGAGED


def test_a_second_engine_restores_what_a_crashed_one_left(
    admin, jellyfin, make_rig, tmp_path
):
    clock = FakeClock()
    first = make_rig(clock=clock)
    jellyfin.sessions = [session()]
    first.tick()
    assert Snapshot.take(admin).throttled
    del first  # abandoned: no restore_all, no shutdown
    jellyfin.sessions = []
    clock.advance(AFTER_DELAY)
    second = make_rig(clock=clock)
    second.tick()
    after = Snapshot.take(admin)
    assert not after.throttled
    assert after.alt == BASELINE_ALT


def test_shutdown_restore_gives_everything_back(admin, jellyfin, make_rig):
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    assert rig.engine.restore_all()
    after = Snapshot.take(admin)
    assert not after.throttled and after.alt == BASELINE_ALT


def test_a_stopped_jellyfin_changes_nothing(admin, jellyfin, make_rig):
    rig = make_rig()
    jellyfin.sessions = [session()]
    rig.tick()
    engaged = Snapshot.take(admin)
    jellyfin.stop()
    for _ in range(3):
        rig.tick(AFTER_DELAY)
    assert Snapshot.take(admin) == engaged
    assert not rig.engine.status().healthy


def test_a_stopped_jellyfin_before_any_playback_changes_nothing(
    admin, jellyfin, make_rig
):
    before = Snapshot.take(admin)
    rig = make_rig()
    jellyfin.stop()
    rig.tick()
    rig.tick()
    assert Snapshot.take(admin) == before


def test_an_unreachable_qbittorrent_changes_nothing_and_breaks_nothing(
    admin, jellyfin, make_rig
):
    before = Snapshot.take(admin)
    rig = make_rig(qbit_url=f"http://127.0.0.1:{free_port()}")
    jellyfin.sessions = [session()]
    rig.tick()
    rig.tick()
    assert Snapshot.take(admin) == before
    assert not rig.engine.status().healthy
    assert rig.heartbeat.beats[-1][0] is False


class Spy:
    """Records every HTTP request `requests` makes, by method and URL."""

    def __init__(self, monkeypatch):
        self.calls: list[tuple[str, str]] = []
        original = requests.Session.request

        def request(session_, method, url, *args, **kwargs):
            self.calls.append((method.upper(), url))
            return original(session_, method, url, *args, **kwargs)

        monkeypatch.setattr(requests.Session, "request", request)

    def to(self, port: int) -> list[tuple[str, str]]:
        return [c for c in self.calls if urlsplit(c[1]).port == port]


def test_observe_mode_never_writes_to_qbittorrent(
    admin, qbit, jellyfin, tmp_path, monkeypatch
):
    config_file = tmp_path / "waitarr.toml"
    state_file = tmp_path / "state.json"
    config_file.write_text(
        f"""
mode = "observe"
state_file = "{state_file}"

[throttle]
download = "8KiB"
upload = "16KiB"

[http]
listen = ""

[[sources]]
name = "jellyfin"
type = "jellyfin"
url = "{jellyfin.url}"

[[targets]]
name = "main"
type = "qbittorrent"
url = "{qbit.host}"
username = "{qbit.username}"
""",
        encoding="utf-8",
    )
    config = load_config(
        config_file,
        {
            "WAITARR_JELLYFIN_API_KEY": "it-jellyfin-key",
            "WAITARR_MAIN_PASSWORD": qbit.password,
        },
    )
    assert build_engine(config).simulate  # observe is the default wiring
    clock = FakeClock()
    engine = Engine(
        sources=[SOURCE_FACTORIES[s.type](s) for s in config.sources],
        targets=[
            TargetBinding(TARGET_FACTORIES[t.type](t, True), t.throttle)
            for t in config.targets
        ],
        policy=build_policy(config),
        store=JsonStateFile(config.state_file),
        notifier=build_notifier(config),
        heartbeat=RecordingHeartbeatStub(),
        simulate=True,
        clock=clock,
    )
    before = Snapshot.take(admin)
    spy = Spy(monkeypatch)

    engine.load()
    engine.check_versions()
    engine.diagnose()
    jellyfin.sessions = [session()]
    for _ in range(3):
        clock.advance(15)
        engine.tick()
    jellyfin.sessions = []
    for _ in range(3):
        clock.advance(AFTER_DELAY)
        engine.tick()
    assert engine.restore_all()

    monkeypatch.undo()
    to_qbit = spy.to(qbit.port)
    assert to_qbit, "the spy saw no request: it would prove nothing"
    allowed_post = ("POST", f"{qbit.host}/api/v2/auth/login")
    # qbittorrent-api HEADs the base URL once, to probe the server; that
    # is as read-only as a GET.
    writes = [
        c for c in to_qbit if c[0] not in ("GET", "HEAD") and c != allowed_post
    ]
    assert writes == []
    assert any(
        c[0] == "GET" and "/api/v2/app/preferences" in c[1] for c in to_qbit
    )
    assert Snapshot.take(admin) == before
    assert not state_file.exists()


class RecordingHeartbeatStub:
    def beat(self, *, healthy: bool, message: str) -> None:
        return None


def test_unthrottled_utp_and_lan_traffic_are_reported_never_fixed(
    make_rig, admin
):
    rig = make_rig()
    assert rig.engine.diagnose() == []
    admin.app_set_preferences(
        {"limit_utp_rate": False, "limit_lan_peers": False}
    )
    found = {d.severity: d.message for d in rig.engine.diagnose()}
    assert "µTP traffic is not rate-limited" in found["warning"]
    assert "peers on the local network" in found["notice"]
    preferences = admin.app_preferences()
    assert preferences["limit_utp_rate"] is False
    assert preferences["limit_lan_peers"] is False
