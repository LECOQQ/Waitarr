"""Outbound signals: failure notifications (generic webhook, ntfy) and
the Healthchecks dead-man's switch. None of them may stop a tick: a
delivery failure is logged and dropped."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

import requests

from waitarr.core.ports import Notification, Notifier, Severity

__all__ = [
    "FanOutNotifier",
    "HealthchecksHeartbeat",
    "NoHeartbeat",
    "NtfyNotifier",
    "WebhookNotifier",
]

logger = logging.getLogger("waitarr")


def _deliver(name: str, send: Callable[[], requests.Response]) -> None:
    try:
        response = send()
    except requests.RequestException as error:
        logger.warning("%s: delivery failed (%s).", name, type(error).__name__)
        return
    if response.status_code >= 400:
        logger.warning(
            "%s: delivery refused (HTTP %s).", name, response.status_code
        )


class WebhookNotifier:
    """POSTs `{"event", "title", "message"}` as JSON to any URL."""

    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        self._url = url
        self._timeout = timeout

    def notify(self, notification: Notification) -> None:
        _deliver(
            "webhook notification",
            lambda: requests.post(
                self._url,
                json={
                    "source": "waitarr",
                    "event": notification.severity.value,
                    "title": notification.title,
                    "message": notification.message,
                },
                timeout=self._timeout,
            ),
        )


class NtfyNotifier:
    """Publishes to an ntfy topic URL (e.g. https://ntfy.sh/my-topic)."""

    def __init__(
        self, url: str, *, token: str | None = None, timeout: float = 10.0
    ) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout

    def notify(self, notification: Notification) -> None:
        failure = notification.severity is Severity.FAILURE
        headers = {
            "Title": notification.title,
            "Priority": "high" if failure else "default",
            "Tags": "warning" if failure else "white_check_mark",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        _deliver(
            "ntfy notification",
            lambda: requests.post(
                self._url,
                data=notification.message.encode("utf-8"),
                headers=headers,
                timeout=self._timeout,
            ),
        )


class FanOutNotifier:
    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = tuple(notifiers)

    def notify(self, notification: Notification) -> None:
        log = (
            logger.error
            if notification.severity is Severity.FAILURE
            else (logger.info)
        )
        log("%s", notification.title)
        for notifier in self._notifiers:
            notifier.notify(notification)


class NoHeartbeat:
    def beat(self, *, healthy: bool, message: str) -> None:
        return None


class HealthchecksHeartbeat:
    """Pings a Healthchecks check: success at most every `interval`
    seconds, `/fail` once when health turns bad."""

    def __init__(
        self,
        url: str,
        *,
        interval: float = 60.0,
        timeout: float = 10.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url.rstrip("/")
        self._interval = interval
        self._timeout = timeout
        self._monotonic = monotonic
        self._last_success: float | None = None
        self._failing = False

    def beat(self, *, healthy: bool, message: str) -> None:
        now = self._monotonic()
        if healthy:
            due = (
                self._failing
                or self._last_success is None
                or now - self._last_success >= self._interval
            )
            self._failing = False
            if due:
                self._last_success = now
                self._ping("", message)
            return
        if not self._failing:
            self._failing = True
            self._ping("/fail", message)

    def _ping(self, suffix: str, message: str) -> None:
        _deliver(
            "Healthchecks ping",
            lambda: requests.post(
                self._url + suffix,
                data=message.encode("utf-8"),
                timeout=self._timeout,
            ),
        )
