"""Fixtures for the Docker tests: one real qBittorrent per session, a
fake Jellyfin per test, and the real adapters wired to both."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
import qbittorrentapi
from qbit_core import QbitConfig

from tests.fake_jellyfin import FakeJellyfin
from tests.fakes import (
    FakeClock,
    RecordingHeartbeat,
    RecordingNotifier,
)
from tests.integration import qbit_container
from waitarr.adapters.jellyfin import JellyfinSource
from waitarr.adapters.qbittorrent import QbittorrentTarget
from waitarr.adapters.state_file import JsonStateFile
from waitarr.core.engine import Engine, TargetBinding
from waitarr.core.model import Limits
from waitarr.core.policy import GlobalHysteresisPolicy

API_KEY = "it-jellyfin-key"
THROTTLE = Limits(8 * 1024, 16 * 1024)
BASELINE_ALT = Limits(500 * 1024, 400 * 1024)
RELEASE_AFTER = timedelta(minutes=3)


@pytest.fixture(scope="session")
def qbit() -> Iterator[qbit_container.Qbit]:
    if not qbit_container.docker_available():
        pytest.skip("docker is not available")
    image = os.environ.get("WAITARR_QBIT_IMAGE", qbit_container.DEFAULT_IMAGE)
    running = qbit_container.start(image)
    print(
        f"\nqBittorrent {running.version} (Web API {running.api_version}) "
        f"image {running.image} id {running.image_id}"
    )
    try:
        yield running
    finally:
        qbit_container.stop(running)


@pytest.fixture
def admin(qbit) -> qbittorrentapi.Client:
    """A raw client, used to set up and to read the truth back. The
    alternative mode starts off and the alternative limits are
    BASELINE_ALT, so a restore is distinguishable from a reset."""
    client = qbittorrentapi.Client(
        host=qbit.host, username=qbit.username, password=qbit.password
    )
    client.auth_log_in()
    reset(client)
    return client


def reset(client: qbittorrentapi.Client) -> None:
    client.app_set_preferences(
        {
            "alt_dl_limit": BASELINE_ALT.download,
            "alt_up_limit": BASELINE_ALT.upload,
            "dl_limit": 0,
            "up_limit": 0,
            "scheduler_enabled": False,
            "bittorrent_protocol": 0,
            "limit_utp_rate": True,
            "limit_lan_peers": True,
        }
    )
    if str(client.transfer_speed_limits_mode()) == "1":
        client.transfer_set_speed_limits_mode(intended_state=False)


@dataclass(frozen=True)
class Snapshot:
    mode: str
    preferences: dict

    @classmethod
    def take(cls, client: qbittorrentapi.Client) -> Snapshot:
        return cls(
            str(client.transfer_speed_limits_mode()),
            dict(client.app_preferences()),
        )

    @property
    def alt(self) -> Limits:
        return Limits(
            self.preferences["alt_dl_limit"], self.preferences["alt_up_limit"]
        )

    @property
    def throttled(self) -> bool:
        return self.mode == "1"


@pytest.fixture
def jellyfin() -> Iterator[FakeJellyfin]:
    with FakeJellyfin(API_KEY) as fake:
        yield fake


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Rig:
    """The engine with the real adapters, driven tick by tick."""

    def __init__(
        self,
        qbit,
        jellyfin: FakeJellyfin,
        state_path: Path,
        *,
        simulate: bool = False,
        clock: FakeClock | None = None,
        qbit_url: str | None = None,
    ) -> None:
        self.clock = clock or FakeClock()
        self.notifier = RecordingNotifier()
        self.heartbeat = RecordingHeartbeat()
        self.state_path = state_path
        self.source = JellyfinSource(
            "jellyfin", jellyfin.url, API_KEY, timeout=2
        )
        self.target = QbittorrentTarget(
            "main",
            QbitConfig(
                host=qbit_url or qbit.host,
                username=qbit.username,
                password=qbit.password,
            ),
            read_only=simulate,
            timeout=3,
        )
        self.engine = Engine(
            sources=[self.source],
            targets=[TargetBinding(self.target, THROTTLE)],
            policy=GlobalHysteresisPolicy(release_after=RELEASE_AFTER),
            store=JsonStateFile(state_path),
            notifier=self.notifier,
            heartbeat=self.heartbeat,
            simulate=simulate,
            clock=self.clock,
        )
        self.engine.load()

    def tick(self, seconds: float = 15) -> None:
        self.clock.advance(seconds)
        self.engine.tick()


@pytest.fixture
def make_rig(qbit, jellyfin, tmp_path):
    def make(**kwargs) -> Rig:
        kwargs.setdefault("state_path", tmp_path / "state.json")
        return Rig(qbit, jellyfin, **kwargs)

    return make
