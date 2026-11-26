import logging
from datetime import timedelta

from tests.unit.test_config import MINIMAL, load
from waitarr.core.model import Diagnostic
from waitarr.service import Service

LAN = Diagnostic("main", "notice", "main: LAN peers are not rate-limited")
UTP = Diagnostic("main", "warning", "main: µTP traffic is not rate-limited")


class DiagnosingEngine:
    def __init__(self) -> None:
        self.found: list[Diagnostic] = []

    def diagnose(self) -> list[Diagnostic]:
        return list(self.found)


def _service(tmp_path) -> tuple[Service, DiagnosingEngine]:
    engine = DiagnosingEngine()
    config = load(tmp_path, MINIMAL + '\n[http]\nlisten = ""\n')
    return Service(config, engine), engine  # type: ignore[arg-type]


def test_healthz_marks_the_jellyfin_source_whose_libraries_are_unreadable(
    tmp_path,
):
    import requests

    from tests.fakes import (
        THROTTLE,
        FakeTarget,
        MemoryStore,
        RecordingHeartbeat,
        RecordingNotifier,
    )
    from waitarr.adapters.jellyfin import JellyfinSource
    from waitarr.core.engine import Engine, TargetBinding
    from waitarr.core.policy import GlobalHysteresisPolicy

    reader = JellyfinSource("jellyfin", "http://127.0.0.1:1", "key")
    engine = Engine(
        sources=[reader],
        targets=[TargetBinding(FakeTarget("main"), THROTTLE)],
        task_hosts=[],
        policy=GlobalHysteresisPolicy(release_after=timedelta(minutes=3)),
        store=MemoryStore(),
        notifier=RecordingNotifier(),
        heartbeat=RecordingHeartbeat(),
        simulate=False,
    )
    config = load(tmp_path, MINIMAL + '\n[http]\nlisten = "127.0.0.1:0"\n')
    service = Service(config, engine)
    surface = service._http
    assert surface is not None
    surface.start()
    try:
        url = f"http://127.0.0.1:{surface.port}/healthz"
        assert requests.get(url, timeout=3).json()["libraries_unreadable"] == []
        reader._libraries_unreadable = True
        marked = requests.get(url, timeout=3).json()
        assert marked["libraries_unreadable"] == ["jellyfin"]
    finally:
        surface.stop()


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


def test_a_diagnostic_is_logged_once_not_at_every_check(tmp_path, caplog):
    service, engine = _service(tmp_path)
    engine.found = [LAN]
    with caplog.at_level(logging.INFO, logger="waitarr"):
        service._diagnose()
        service._diagnose()
        service._diagnose()
    assert _messages(caplog).count(LAN.message) == 1


def test_a_new_diagnostic_is_logged_when_it_appears(tmp_path, caplog):
    service, engine = _service(tmp_path)
    engine.found = [LAN]
    service._diagnose()
    engine.found = [LAN, UTP]
    with caplog.at_level(logging.INFO, logger="waitarr"):
        service._diagnose()
    assert _messages(caplog) == [UTP.message]


def test_a_diagnostic_that_disappears_is_logged_as_resolved(tmp_path, caplog):
    service, engine = _service(tmp_path)
    engine.found = [LAN]
    service._diagnose()
    engine.found = []
    with caplog.at_level(logging.INFO, logger="waitarr"):
        service._diagnose()
        service._diagnose()
    assert _messages(caplog) == [f"No longer the case: {LAN.message}"]
