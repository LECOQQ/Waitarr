from dataclasses import replace
from datetime import timedelta

import pytest
from typer.testing import CliRunner

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
from waitarr import bootstrap, cli
from waitarr.compatibility import Assessment, Verdict
from waitarr.core.engine import Engine, TargetBinding, TaskBinding
from waitarr.core.model import ServiceVersion
from waitarr.core.policy import GlobalHysteresisPolicy

CONFIG = """
[[sources]]
name = "jellyfin"
type = "jellyfin"
url = "http://jellyfin:8096"

[[targets]]
name = "main"
type = "qbittorrent"
url = "http://qbittorrent:8080"
username = "admin"
"""


class Wiring:
    def __init__(self, tmp_path, monkeypatch, keys=("RefreshLibrary",)):
        self.config = tmp_path / "waitarr.toml"
        self.config.write_text(CONFIG, encoding="utf-8")
        monkeypatch.setenv("WAITARR_JELLYFIN_API_KEY", "k")
        monkeypatch.setenv("WAITARR_MAIN_PASSWORD", "p")
        self.host = FakeTaskHost("jellyfin", keys=("RefreshLibrary", "Other"))
        self.store = MemoryStore()
        self.built: list[bool | None] = []
        self.keys = keys
        monkeypatch.setattr(bootstrap, "build_engine", self.build)

    def build(self, config, *, simulate=None):
        self.built.append(simulate)
        return Engine(
            sources=[FakeSource()],
            targets=[TargetBinding(FakeTarget("main"), THROTTLE)],
            policy=GlobalHysteresisPolicy(
                release_after=config.policy.release_after
            ),
            store=self.store,
            notifier=RecordingNotifier(),
            heartbeat=RecordingHeartbeat(),
            simulate=bool(simulate),
            clock=FakeClock(),
            task_hosts=[TaskBinding(self.host, self.keys)],
        )

    def run(self, *args):
        arguments = [*args, "--config", str(self.config)]
        return CliRunner().invoke(cli.app, arguments)


@pytest.fixture
def wiring(tmp_path, monkeypatch):
    return Wiring(tmp_path, monkeypatch)


def test_check_lists_the_followed_tasks_that_exist(wiring):
    wiring.host.run("RefreshLibrary")
    result = wiring.run("check")
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if "RefreshLibrary" in ln]
    assert any("Running" in ln for ln in lines)
    assert not any("Other" in ln for ln in result.output.splitlines())


def test_check_warns_of_a_configured_key_the_host_does_not_list(
    tmp_path, monkeypatch
):
    wiring = Wiring(tmp_path, monkeypatch, keys=("RefreshLibrary", "Gone"))
    result = wiring.run("check")
    assert result.exit_code == 0  # a warning, never an error
    (warning,) = [ln for ln in result.output.splitlines() if "Gone" in ln]
    assert warning.startswith("[WARN]")


def test_check_survives_an_unreadable_task_host_with_a_warning(wiring):
    wiring.host.down = True
    result = wiring.run("check")
    assert result.exit_code == 0
    assert any(
        ln.startswith("[WARN]") and "jellyfin" in ln
        for ln in result.output.splitlines()
    )


def test_check_fails_on_a_version_it_cannot_read(wiring, monkeypatch):
    monkeypatch.setattr(
        FakeSource, "version", lambda self: ServiceVersion("Jellyfin", "banana")
    )
    result = wiring.run("check")
    assert any(
        ln.startswith("[FAIL]") and "unreadable version" in ln
        for ln in result.output.splitlines()
    )
    assert result.exit_code == 1


def test_check_assesses_each_service_by_its_configured_type(
    wiring, monkeypatch
):
    loaded = cli.load_config(wiring.config)
    config = replace(
        loaded,
        sources=tuple(replace(s, type="plex") for s in loaded.sources),
        targets=tuple(replace(t, type="deluge") for t in loaded.targets),
    )
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    kinds = []

    def record(kind, version):
        kinds.append(kind)
        return Assessment(Verdict.TESTED, "recorded")

    monkeypatch.setattr(cli, "assess", record)
    wiring.run("check")
    assert sorted(kinds) == ["deluge", "plex"]


def test_check_never_writes_to_the_task_host(wiring):
    wiring.host.run("RefreshLibrary")
    wiring.run("check")
    assert wiring.host.writes == []
    assert wiring.built == [True]


def test_restore_without_yes_builds_nothing_and_names_both_services(wiring):
    result = wiring.run("restore")
    assert result.exit_code == 1
    assert wiring.built == []
    assert "qBittorrent" in result.output and "Jellyfin" in result.output


def test_restore_starts_again_the_tasks_a_previous_run_stopped(wiring):
    clock = FakeClock()
    source = FakeSource()
    previous = Engine(
        sources=[source],
        targets=[TargetBinding(FakeTarget("main"), THROTTLE)],
        policy=GlobalHysteresisPolicy(release_after=timedelta(minutes=3)),
        store=wiring.store,
        notifier=RecordingNotifier(),
        heartbeat=RecordingHeartbeat(),
        simulate=False,
        clock=clock,
        task_hosts=[TaskBinding(wiring.host, ("RefreshLibrary",))],
    )
    previous.load()
    wiring.host.run("RefreshLibrary")
    source.sessions = [playback()]
    clock.advance(15)
    previous.tick()  # then it dies, owning the stopped task
    assert wiring.host.writes == [("stop", "RefreshLibrary")]
    result = wiring.run("restore", "--yes")
    assert result.exit_code == 0
    assert wiring.host.writes[-1] == ("start", "RefreshLibrary")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://127.0.0.1/", "127.0.0.1:8080", ""]
)
def test_status_refuses_a_url_that_is_not_http_or_https(monkeypatch, url):
    def never_opened(*args, **kwargs):
        raise AssertionError("the URL must be refused before any request")

    monkeypatch.setattr(cli.urllib.request, "urlopen", never_opened)
    result = CliRunner().invoke(cli.app, ["status", "--url", url])
    assert result.exit_code == 2
    assert "http" in result.output
    assert "https" in result.output


def test_the_health_probe_loads_no_adapter():
    # The container probe starts a process every minute: it must not pay
    # for the HTTP clients of the services it never talks to.
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from typer.testing import CliRunner\n"
        "from waitarr import cli\n"
        "CliRunner().invoke(cli.app, "
        "['status', '--quiet', '--url', 'http://127.0.0.1:1'])\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('requests', 'qbittorrentapi', 'qbit_core') "
        "or m.startswith('waitarr.adapters')))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"
