"""A disposable qBittorrent container for the Docker tests.

Origin: adapted from qbit-ops' integration harness (`_harness.py` and
`_qbit_conf_template.py`), copied, not imported. The WebUI password format
is PBKDF2-HMAC-SHA512, 100000 iterations, 64-byte digest.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

LABEL = "waitarr.test"
LOOPBACK = "127.0.0.1"
USERNAME = "admin"
DEFAULT_IMAGE = (
    "linuxserver/qbittorrent:5.1.4@sha256:"
    "c9990949e968e99333f47f49da7d16e81ba6e1469c8c46807a65b984c9e8b6ff"
)


class HarnessError(RuntimeError):
    pass


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=180,
    )


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        docker("version", "--format", "{{.Server.Version}}")
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return False
    return True


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha512", password.encode(), salt, 100_000, dklen=64
    )
    return (
        f"@ByteArray({base64.b64encode(salt).decode()}:"
        f"{base64.b64encode(digest).decode()})"
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def hermetic_conf(password: str, port: int) -> str:
    """DHT, PeX, LSD, UPnP and GeoIP updates off from the first boot, a
    known WebUI password, and no localhost authentication bypass.

    The WebUI listens on the same port inside and outside the container:
    qBittorrent rejects a Host header whose port is not its own."""
    return f"""[BitTorrent]
Session\\AnonymousModeEnabled=true
Session\\DHTEnabled=false
Session\\LSDEnabled=false
Session\\PeXEnabled=false
Session\\Port=6881
Session\\QueueingSystemEnabled=false
Session\\AddTorrentStopped=false

[LegalNotice]
Accepted=true

[Preferences]
Connection\\UPnP=false
Connection\\PortRangeMin=6881
Connection\\ResolvePeerCountries=false
WebUI\\Address=*
WebUI\\Port={port}
WebUI\\Username={USERNAME}
WebUI\\Password_PBKDF2="{password_hash(password)}"
WebUI\\ServerDomains=*
WebUI\\HostHeaderValidation=true
WebUI\\CSRFProtection=true
WebUI\\LocalHostAuth=false
"""


@dataclass
class Qbit:
    host: str
    username: str
    password: str = field(repr=False)
    image: str
    image_id: str
    version: str
    api_version: str
    name: str
    root: Path

    @property
    def port(self) -> int:
        return int(self.host.rsplit(":", 1)[1])


def _wait_for_webui(host: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{host}/api/v2/app/webapiVersion", timeout=2
            ) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):  # up, only not logged in
                return
            last = error
        except (urllib.error.URLError, OSError) as error:
            last = error
        time.sleep(1)
    raise HarnessError(f"qBittorrent WebUI at {host} not ready: {last}")


def start(image: str) -> Qbit:
    import qbittorrentapi

    run_id = uuid.uuid4().hex[:10]
    name = f"waitarr-it-{run_id}"
    root = Path(tempfile.mkdtemp(prefix="waitarr-it-"))
    config_dir = root / "qBittorrent"
    downloads = root / "downloads"
    config_dir.mkdir()
    downloads.mkdir()
    port = free_port()
    password = f"Test-{secrets.token_urlsafe(18)}"
    (config_dir / "qBittorrent.conf").write_text(
        hermetic_conf(password, port), encoding="utf-8"
    )
    try:
        # The published port is bound to loopback only.
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{LABEL}={run_id}",
            "-e",
            f"PUID={os.getuid()}",
            "-e",
            f"PGID={os.getgid()}",
            "-e",
            "TZ=Etc/UTC",
            "-e",
            f"WEBUI_PORT={port}",
            "-p",
            f"{LOOPBACK}:{port}:{port}",
            "-v",
            f"{config_dir}:/config/qBittorrent",
            "-v",
            f"{downloads}:/downloads",
            image,
        )
        host = f"http://{LOOPBACK}:{port}"
        _wait_for_webui(host)
        client = qbittorrentapi.Client(
            host=host, username=USERNAME, password=password
        )
        client.auth_log_in()
        image_id = docker(
            "inspect", "--format", "{{.Image}}", name
        ).stdout.strip()
        return Qbit(
            host=host,
            username=USERNAME,
            password=password,
            image=image,
            image_id=image_id,
            version=str(client.app_version()),
            api_version=str(client.app_web_api_version()),
            name=name,
            root=root,
        )
    except BaseException:
        stop_by_name(name, root)
        raise


def stop_by_name(name: str, root: Path) -> None:
    docker("rm", "-f", "-v", name, check=False)
    shutil.rmtree(root, ignore_errors=True)


def stop(qbit: Qbit) -> None:
    stop_by_name(qbit.name, qbit.root)
