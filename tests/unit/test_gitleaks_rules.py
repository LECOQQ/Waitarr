"""The gitleaks rules catch the destinations ADR 0005 treats as secrets."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
GITLEAKS = shutil.which("gitleaks")

pytestmark = pytest.mark.skipif(not GITLEAKS, reason="needs gitleaks on PATH")

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
    subprocess.run(
        [
            str(GITLEAKS),
            "detect",
            "--no-git",
            "--source",
            str(source),
            "-c",
            str(ROOT / ".gitleaks.toml"),
            "--no-banner",
            "--redact",
            "-f",
            "json",
            "-r",
            str(report),
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
