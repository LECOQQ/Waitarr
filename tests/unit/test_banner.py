import dataclasses
import logging

import pytest

from tests.unit.test_config import MINIMAL, load
from waitarr import __version__
from waitarr.banner import compatibility_warnings, plain_url, startup_block
from waitarr.config import load_config
from waitarr.core.model import ServiceVersion
from waitarr.service import Service

JELLYFIN = ServiceVersion("Jellyfin", "12.2.0")
QBIT = ServiceVersion("qBittorrent", "5.1.4", "2.11.4")
VERSIONS = {"jellyfin": JELLYFIN, "main": QBIT}

FILTERED = """
poll_interval = "30s"

[policy]
release_after = "5m"
ignore_users = ["Kid", "Guest"]
count_paused = true

[throttle]
download = "1MiB"
upload = "512KiB"

[http]
listen = "0.0.0.0:8778"
webhook = true
"""


def block(tmp_path, text=MINIMAL, versions=VERSIONS, **kwargs):
    config = load(tmp_path, text)
    return startup_block(config, versions, simulate=False, **kwargs)


def test_first_line_names_version_and_mode(tmp_path):
    config = load(tmp_path)
    active = startup_block(config, VERSIONS, simulate=False)[0]
    observing = startup_block(config, VERSIONS, simulate=True)[0]
    assert active == (
        f"Waitarr {__version__} starting in ACTIVE mode: targets are "
        "throttled during playback"
    )
    assert "OBSERVATION mode: decisions are logged" in observing


def test_durations_and_endpoint_are_shown(tmp_path):
    lines = block(tmp_path, FILTERED + MINIMAL, http_port=8778)
    assert lines[1] == (
        "Polling every 30s, releasing 5m after the last playback"
    )
    assert lines[2] == (
        "Health endpoint on http://0.0.0.0:8778/healthz, "
        "webhook on /hooks/jellyfin"
    )


def test_no_endpoint_line_when_it_is_off(tmp_path):
    assert not any("Health endpoint" in line for line in block(tmp_path))


def test_filters_list_only_what_is_set(tmp_path):
    lines = block(tmp_path, FILTERED + MINIMAL)
    assert "Playback filters: ignore_users=guest,kid; count_paused" in lines
    assert "Playback filters: none, every playback counts" in block(tmp_path)


def test_source_line_gives_version_verdict_and_tasks(tmp_path):
    lines = block(tmp_path)
    source = next(line for line in lines if line.startswith("Source"))
    assert source.startswith(
        "Source jellyfin (jellyfin) at http://jellyfin:8096; "
        "Jellyfin 12.2.0: tested; tasks held while something plays: "
        "RefreshLibrary, "
    )
    assert source.endswith("RefreshTrickplayImages")


def test_source_line_says_when_suspension_is_off(tmp_path):
    text = MINIMAL.replace(
        'type = "jellyfin"', 'type = "jellyfin"\nsuspend_tasks = false'
    )
    source = next(line for line in block(tmp_path, text) if "Source" in line)
    assert source.endswith("; task suspension off")
    assert "RefreshLibrary" not in source


def test_target_line_gives_version_and_limits(tmp_path):
    lines = block(tmp_path, FILTERED + MINIMAL)
    assert lines[-1] == (
        "Target main (qbittorrent) at http://qbittorrent:8080; "
        "qBittorrent 5.1.4 (Web API 2.11.4): tested; "
        "throttle to 1 MiB/s down / 512 KiB/s up"
    )
    assert block(tmp_path)[-1].endswith("its own alternative limits")


def test_an_unreadable_version_shows_as_unknown(tmp_path):
    lines = block(tmp_path, versions={"jellyfin": JELLYFIN, "main": None})
    assert lines[-1] == (
        "Target main (qbittorrent) at http://qbittorrent:8080; qBittorrent "
        "version unknown; the compatibility matrix cannot be checked; "
        "throttle to its own alternative limits"
    )


def test_a_tested_matrix_raises_no_warning(tmp_path):
    assert compatibility_warnings(load(tmp_path), VERSIONS) == []


def test_an_untested_version_keeps_a_warning(tmp_path):
    newer = ServiceVersion("qBittorrent", "5.9.0")
    unknown = ServiceVersion("Jellyfin", "not-a-version")
    warnings = compatibility_warnings(
        load(tmp_path), {"jellyfin": unknown, "main": newer}
    )
    assert warnings == [
        "jellyfin: Jellyfin reported an unreadable version 'not-a-version'.",
        "main: qBittorrent 5.9.0: newer than every tested version, assumed "
        "compatible -- see docs/COMPATIBILITY.md.",
    ]


def test_plain_url_drops_userinfo_query_and_fragment():
    assert (
        plain_url("https://user:pw@host:8080/base/?token=x#frag")
        == "https://host:8080/base"
    )
    assert plain_url("http://[::1]:8096") == "http://[::1]:8096"


def test_no_secret_reaches_the_block(tmp_path):
    secrets = {
        "WAITARR_JELLYFIN_API_KEY": "UNMISTAKABLE-API-KEY",
        "WAITARR_MAIN_PASSWORD": "UNMISTAKABLE-PASSWORD",
        "WAITARR_WEBHOOK_TOKEN": "UNMISTAKABLE-HOOK-TOKEN",
        "WAITARR_NOTIFY_WEBHOOK_URL": "https://UNMISTAKABLE-NOTIFY.example/x",
        "WAITARR_NOTIFY_NTFY_URL": "https://UNMISTAKABLE-NTFY.example/topic",
        "WAITARR_NOTIFY_NTFY_TOKEN": "UNMISTAKABLE-NTFY-TOKEN",
        "WAITARR_HEALTHCHECKS_URL": "https://UNMISTAKABLE-HC.example/uuid",
    }
    path = tmp_path / "waitarr.toml"
    path.write_text(FILTERED + MINIMAL, encoding="utf-8")
    config = load_config(path, secrets)
    # The loader refuses credentials in a URL; a config built by hand
    # must still not leak them.
    config = dataclasses.replace(
        config,
        sources=(
            dataclasses.replace(
                config.sources[0],
                url="http://UNMISTAKABLE-USER:UNMISTAKABLE-PW@jellyfin:8096"
                "/?api_key=UNMISTAKABLE-QUERY#UNMISTAKABLE-FRAGMENT",
            ),
        ),
        targets=(
            dataclasses.replace(
                config.targets[0],
                url="http://UNMISTAKABLE-USER:UNMISTAKABLE-PW@qbittorrent:8080"
                "?password=UNMISTAKABLE-QUERY",
            ),
        ),
    )
    text = "\n".join(
        [
            *startup_block(config, VERSIONS, simulate=False, http_port=8778),
            *compatibility_warnings(config, VERSIONS),
        ]
    )
    assert "UNMISTAKABLE" not in text
    assert "jellyfin:8096" in text
    assert "qbittorrent:8080" in text


class FakeEngine:
    simulate = False

    def diagnose(self):
        return []


def test_the_service_logs_the_block_then_the_warnings(tmp_path, caplog):
    config = load(tmp_path, MINIMAL + '\n[http]\nlisten = ""\n')
    service = Service(config, FakeEngine())  # type: ignore[arg-type]
    versions = {"jellyfin": JELLYFIN, "main": ServiceVersion("q", "5.9.0")}
    with caplog.at_level(logging.INFO, logger="waitarr"):
        service._announce(versions)
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.INFO] * 5 + [logging.WARNING]
    assert caplog.records[-1].getMessage().startswith("main: ")


class FailingEngine(FakeEngine):
    simulate = True

    def load(self):
        raise RuntimeError("state file unreadable")


def test_a_failed_load_still_names_the_version(tmp_path, caplog, monkeypatch):
    config = load(tmp_path, MINIMAL + '\n[http]\nlisten = ""\n')
    service = Service(config, FailingEngine())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_install_signal_handlers", lambda: None)
    with caplog.at_level(logging.INFO, logger="waitarr"):
        with pytest.raises(RuntimeError, match="state file unreadable"):
            service.run()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert __version__ in errors[0].getMessage()
    assert "OBSERVATION" in errors[0].getMessage()
