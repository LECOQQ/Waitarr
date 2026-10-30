import logging

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
