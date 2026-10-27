"""The shipped image, end to end: a Waitarr container against a real,
disposable qBittorrent and the fake Jellyfin. Run by `make check-image`.

The Waitarr container uses the host network, so it reaches both on
127.0.0.1 exactly as the test does.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.fake_jellyfin import FakeJellyfin, session
from tests.integration import qbit_container
from tests.integration.conftest import API_KEY, BASELINE_ALT, Snapshot

pytestmark = pytest.mark.image

IMAGE = os.environ.get("WAITARR_TEST_IMAGE", "")


def _wait(
    condition: Callable[[], bool], what: str, timeout: float = 30
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}")


class Waitarr:
    def __init__(self, name: str, health_port: int) -> None:
        self.name = name
        self.health_port = health_port

    def healthy(self) -> bool:
        url = f"http://127.0.0.1:{self.health_port}/healthz"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def logs(self) -> str:
        return qbit_container.docker("logs", self.name, check=False).stdout


@pytest.fixture
def start_waitarr(
    qbit, tmp_path: Path
) -> Iterator[Callable[[str, FakeJellyfin], Waitarr]]:
    if not IMAGE:
        pytest.skip("set WAITARR_TEST_IMAGE (make check-image does)")
    names: list[str] = []

    def start(mode: str, jellyfin: FakeJellyfin) -> Waitarr:
        name = f"waitarr-e2e-{uuid.uuid4().hex[:8]}"
        health_port = qbit_container.free_port()
        data = tmp_path / name
        data.mkdir()
        config = data / "waitarr.toml"
        config.write_text(
            f"""
mode = "{mode}"
poll_interval = "1s"
state_file = "/data/state.json"
[policy]
release_after = "3s"
[throttle]
download = "8KiB"
upload = "16KiB"
[http]
listen = "127.0.0.1:{health_port}"
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
        qbit_container.docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{qbit_container.LABEL}=e2e",
            "--network",
            "host",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            f"WAITARR_JELLYFIN_API_KEY={API_KEY}",
            "-e",
            f"WAITARR_MAIN_PASSWORD={qbit.password}",
            "-e",
            f"WAITARR_STATUS_URL=http://127.0.0.1:{health_port}",
            "-v",
            f"{config}:/config/waitarr.toml:ro",
            "-v",
            f"{data}:/data",
            IMAGE,
        )
        names.append(name)
        waitarr = Waitarr(name, health_port)
        _wait(waitarr.healthy, "Waitarr's /healthz to answer 200")
        return waitarr

    yield start
    for name in names:
        qbit_container.docker("rm", "-f", name, check=False)


def test_the_image_throttles_releases_and_restores_on_stop(
    start_waitarr, jellyfin, admin
):
    waitarr = start_waitarr("active", jellyfin)

    def throttled() -> bool:
        snap = Snapshot.take(admin)
        return snap.throttled and snap.alt.download == 8 * 1024

    def restored() -> bool:
        snap = Snapshot.take(admin)
        return not snap.throttled and snap.alt == BASELINE_ALT

    jellyfin.sessions = [session()]
    _wait(throttled, "the throttle")
    jellyfin.sessions = []
    _wait(restored, "the release after release_after")

    jellyfin.sessions = [session()]
    _wait(throttled, "the second throttle")
    stopped = subprocess.run(
        ["docker", "stop", "-t", "30", waitarr.name],
        capture_output=True,
        text=True,
        check=True,
    )
    assert stopped.returncode == 0
    assert restored(), "stopping the container must give the speed back"
    exit_code = qbit_container.docker(
        "inspect", "--format", "{{.State.ExitCode}}", waitarr.name
    ).stdout.strip()
    assert exit_code == "0", waitarr.logs()


def test_the_image_in_observation_mode_changes_nothing(
    start_waitarr, jellyfin, admin
):
    before = Snapshot.take(admin)
    waitarr = start_waitarr("observe", jellyfin)
    jellyfin.sessions = [session()]
    _wait(
        lambda: "main: [observe] would throttle" in waitarr.logs(),
        "the observed decision in the log",
    )
    jellyfin.sessions = []
    _wait(
        lambda: "main: [observe] would release" in waitarr.logs(),
        "the observed release in the log",
    )
    assert Snapshot.take(admin) == before
    data = Path(
        qbit_container.docker(
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Destination "/data"}}'
            "{{.Source}}{{end}}{{end}}",
            waitarr.name,
        ).stdout.strip()
    )
    assert not (data / "state.json").exists()
