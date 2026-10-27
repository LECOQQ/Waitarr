"""The built wheel installs into a clean virtualenv and its entry point
runs: what `uv tool install` and `pipx install` will do. Needs the
network to resolve dependencies; run by `make check-dist` after
`poetry build`."""

from __future__ import annotations

import subprocess
import venv
from pathlib import Path

import pytest

pytestmark = pytest.mark.network

DIST = Path(__file__).resolve().parent.parent / "dist"


def test_the_wheel_installs_and_its_entry_point_runs(tmp_path: Path) -> None:
    wheels = sorted(DIST.glob("waitarr-*.whl"))
    if not wheels:
        pytest.skip("no wheel in dist/: run `make build` first")
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(wheels[-1])],
        check=True,
        timeout=600,
    )
    version = subprocess.run(
        [str(environment / "bin" / "waitarr"), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert version.stdout.startswith("waitarr ")
    imported = subprocess.run(
        [str(python), "-c", "import qbit_core.features.transfer"],
        check=False,
        timeout=60,
    )
    assert imported.returncode == 0
