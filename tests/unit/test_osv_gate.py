import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[2] / "scripts" / "osv_gate.py"


def _report(tmp_path, ecosystem):
    report = {
        "results": [
            {
                "packages": [
                    {
                        "package": {
                            "name": "pip",
                            "version": "25.0.1",
                            "ecosystem": ecosystem,
                        },
                        "vulnerabilities": [{"id": "GHSA-test"}],
                    }
                ]
            }
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _run(path):
    return subprocess.run(
        [sys.executable, str(GATE), str(path)], capture_output=True, text=True
    )


def test_a_python_vulnerability_fails_the_gate(tmp_path):
    result = _run(_report(tmp_path, "PyPI"))
    assert result.returncode == 1
    assert "GHSA-test" in result.stdout


def test_a_base_image_os_vulnerability_is_listed_without_failing(tmp_path):
    result = _run(_report(tmp_path, "Debian:13"))
    assert result.returncode == 0
    assert "Debian:13: 1" in result.stdout


def test_an_unreadable_report_fails(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("", encoding="utf-8")
    assert _run(path).returncode == 2
