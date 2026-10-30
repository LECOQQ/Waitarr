"""The long-running service: poll, tick, serve health, restore on exit."""

from __future__ import annotations

import logging
import signal
import threading
import time
from types import FrameType

from waitarr.adapters.http import HttpSurface, status_document
from waitarr.compatibility import Verdict, assess
from waitarr.config import AppConfig
from waitarr.core.engine import Engine, utc_now
from waitarr.core.model import Diagnostic
from waitarr.core.ports import WriteRefused
from waitarr.core.units import format_duration

__all__ = ["Service"]

logger = logging.getLogger("waitarr")

_KINDS = {"source": "jellyfin", "target": "qbittorrent"}
# Settings can be fixed while Waitarr runs: look again every hour, and
# log only what changed since the last look.
_DIAGNOSE_EVERY = 3600.0


class Service:
    def __init__(self, config: AppConfig, engine: Engine) -> None:
        self._config = config
        self._engine = engine
        self._stop = threading.Event()
        self._last_diagnosis = 0.0
        self._diagnostics: frozenset[Diagnostic] = frozenset()
        self._wake = threading.Event()
        self._http: HttpSurface | None = None
        if config.http.port is not None:
            stale = config.poll_interval * 3
            self._http = HttpSurface(
                host=config.http.host,
                port=config.http.port,
                # The rule reads the lambda body as a `return` in __init__.
                # nosemgrep: return-in-init
                status=lambda: status_document(
                    engine.status(), now=utc_now(), stale_after=stale
                ),
                wake=self.wake,
                webhook_enabled=config.http.webhook,
                webhook_token=config.http.webhook_token,
            )

    def wake(self) -> None:
        self._wake.set()

    def stop(self, *_: object) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> int:
        self._install_signal_handlers()
        self._announce()
        self._engine.load()
        self._check_compatibility()
        if self._http is not None:
            self._http.start()
            logger.info(
                "Health endpoint on http://%s:%s/healthz%s.",
                self._config.http.host,
                self._http.port,
                (
                    " (webhook on /hooks/jellyfin)"
                    if self._config.http.webhook
                    else ""
                ),
            )
        try:
            while not self._stop.is_set():
                try:
                    self._engine.tick()
                except WriteRefused:
                    logger.critical(
                        "A read-only target was asked to write: stopping."
                    )
                    raise
                except Exception:
                    # A bug must not end the loop silently with a target held.
                    logger.exception("Tick failed; retrying at the next one.")
                if time.monotonic() - self._last_diagnosis >= _DIAGNOSE_EVERY:
                    self._diagnose()
                self._wake.wait(self._config.poll_interval.total_seconds())
                self._wake.clear()
        finally:
            restored = True
            if self._config.restore_on_exit:
                logger.info("Stopping: giving back what Waitarr owns.")
                restored = self._engine.restore_all()
            if self._http is not None:
                self._http.stop()
            logger.info("Stopped.")
        return 0 if restored else 1

    def _announce(self) -> None:
        mode = (
            "OBSERVATION mode: decisions are logged, nothing is ever written"
            if self._engine.simulate
            else "ACTIVE mode: targets are throttled during playback"
        )
        logger.info(
            "Waitarr starting in %s. Polling every %s, releasing %s after "
            "the last playback.",
            mode,
            format_duration(self._config.poll_interval),
            format_duration(self._config.policy.release_after),
        )

    def _check_compatibility(self) -> None:
        versions = self._engine.check_versions()
        status = self._engine.status()
        for name, version in versions.items():
            kind = _KINDS[status.services[name].kind]
            assessment = assess(kind, version)
            log = (
                logger.info
                if assessment.verdict is Verdict.TESTED
                else logger.warning
            )
            log("%s: %s.", name, assessment.message)
        self._diagnose()

    def _diagnose(self) -> None:
        self._last_diagnosis = time.monotonic()
        found = self._engine.diagnose()
        for diagnostic in found:
            if diagnostic in self._diagnostics:
                continue
            log = (
                logger.warning
                if diagnostic.severity == "warning"
                else (logger.info)
            )
            log("%s", diagnostic.message)
        for diagnostic in self._diagnostics - set(found):
            logger.info("No longer the case: %s", diagnostic.message)
        self._diagnostics = frozenset(found)

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def handler(signum: int, _frame: FrameType | None) -> None:
            logger.info("Received %s.", signal.Signals(signum).name)
            self.stop()

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
