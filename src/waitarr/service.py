"""The long-running service: poll, tick, serve health, restore on exit."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Mapping
from types import FrameType

from waitarr import __version__
from waitarr.adapters.http import HttpSurface, status_document
from waitarr.banner import compatibility_warnings, startup_block
from waitarr.config import AppConfig
from waitarr.core.engine import Engine, utc_now
from waitarr.core.model import Diagnostic, ServiceVersion
from waitarr.core.ports import WriteRefused

__all__ = ["Service"]

logger = logging.getLogger("waitarr")

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
        try:
            self._engine.load()
        except Exception:
            # Without the block, a bug report would not say which version.
            logger.error(
                "Waitarr %s could not start (%s mode).",
                __version__,
                "OBSERVATION" if self._engine.simulate else "ACTIVE",
            )
            raise
        versions = self._engine.check_versions()
        if self._http is not None:
            self._http.start()
        self._announce(versions)
        self._diagnose()
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

    def _announce(self, versions: Mapping[str, ServiceVersion | None]) -> None:
        """Log the startup block, then a warning per untested version."""
        port = self._http.port if self._http is not None else None
        for line in startup_block(
            self._config,
            versions,
            simulate=self._engine.simulate,
            http_port=port,
        ):
            logger.info("%s", line)
        for line in compatibility_warnings(self._config, versions):
            logger.warning("%s", line)

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
