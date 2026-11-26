"""The gitleaks rules catch the destinations ADR 0005 treats as secrets."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
GITLEAKS = shutil.which("gitleaks")
DOCKER = shutil.which("docker")
# The image `make secrets` falls back to, pinned by digest in the Makefile.
IMAGE = re.search(
    r"^GITLEAKS_IMAGE := (\S+)$", (ROOT / "Makefile").read_text(), re.M
)


@pytest.fixture(scope="module", autouse=True)
def _scanner() -> None:
    """A local gitleaks, else the pinned image; a missing scanner is a skip
    on a workstation and a failure in CI, where a skip would report clean."""
    if GITLEAKS or (DOCKER and IMAGE):
        return
    if os.environ.get("CI"):
        pytest.fail("CI needs gitleaks on PATH or docker for the pinned image")
    pytest.skip("needs gitleaks on PATH or docker")


# Visibly fake destinations: `.invalid` never resolves. They are written
# to a temporary directory; the inline pragma keeps the repository scan
# (`make secrets`) from reporting these lines of the test itself.
DESTINATIONS = [
    "WAITARR_NOTIFY_NTFY_URL=https://ntfy.invalid/fake-topic-not-real",  # noqa: E501 gitleaks:allow
    "WAITARR_NOTIFY_WEBHOOK_URL=https://hooks.invalid/fake-hook-not-real",  # noqa: E501 gitleaks:allow
    "WAITARR_HEALTHCHECKS_URL=https://hc.invalid/ping/fake-uuid-not-real",  # noqa: E501 gitleaks:allow
]


def _scan(source: Path, tmp_path: Path) -> list[dict[str, object]]:
    report = tmp_path / "report.json"
    config = ROOT / ".gitleaks.toml"
    if GITLEAKS:
        command = [GITLEAKS]
        paths = [str(source), str(config), str(report)]
    else:
        assert DOCKER and IMAGE
        # `source` and `report` live under `tmp_path`, mounted as /work.
        command = [
            DOCKER,
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{tmp_path}:/work",
            "-v",
            f"{config}:/config.toml:ro",
            IMAGE.group(1),
        ]
        paths = [
            f"/work/{source.relative_to(tmp_path)}",
            "/config.toml",
            "/work/report.json",
        ]
    subprocess.run(
        [
            *command,
            "detect",
            "--no-git",
            "--source",
            paths[0],
            "-c",
            paths[1],
            "--no-banner",
            "--redact",
            "-f",
            "json",
            "-r",
            paths[2],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(report.read_text())


@pytest.mark.parametrize("line", DESTINATIONS, ids=["ntfy", "webhook", "hc"])
def test_a_destination_url_assigned_a_literal_is_caught(
    tmp_path: Path, line: str
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "sample.env").write_text(line + "\n")

    findings = _scan(source, tmp_path)

    assert [f["RuleID"] for f in findings] == ["waitarr-destination-url"]


def test_an_empty_or_substituted_destination_is_not_a_finding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "sample.env").write_text(
        "WAITARR_HEALTHCHECKS_URL=\n"
        "WAITARR_NOTIFY_NTFY_URL: ${WAITARR_NOTIFY_NTFY_URL:-}\n"
    )

    assert _scan(source, tmp_path) == []
