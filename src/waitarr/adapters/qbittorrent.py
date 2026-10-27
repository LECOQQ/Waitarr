"""qBittorrent as a throttle target: its alternative speed limits mode
(the turtle), through `qbit_core` from qbit-ops."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from qbit_core import QbitConfig, QbitCoreError, create_qbit_client
from qbit_core.features.transfer import (
    SpeedLimits,
    read_transfer_settings,
    set_alternative_limits,
    set_alternative_mode,
)
from qbit_core.qbit.client import is_qbit_error

from waitarr.core.model import Diagnostic, Limits, ServiceVersion, TargetState
from waitarr.core.ports import ServiceUnavailable, WriteRefused

__all__ = [
    "READ_METHODS",
    "QbittorrentTarget",
    "diagnose_preferences",
    "ReadOnlyClient",
    "WriteForbidden",
]

# Every qBittorrent client method a read-only Waitarr may call. Anything
# else -- every write included -- is refused by `ReadOnlyClient`.
READ_METHODS = frozenset(
    {
        "app_preferences",
        "app_version",
        "app_web_api_version",
        "transfer_info",
        "transfer_speed_limits_mode",
    }
)


class WriteForbidden(WriteRefused):
    """Observation mode tried to reach a qBittorrent method that is not
    a known read."""


class ReadOnlyClient:
    """Wraps a qBittorrent client, exposing only `READ_METHODS`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name not in READ_METHODS:
            raise WriteForbidden(
                f"observation mode refused qBittorrent method {name!r}"
            )
        return getattr(self._client, name)


class QbittorrentTarget:
    def __init__(
        self,
        name: str,
        config: QbitConfig,
        *,
        read_only: bool,
        timeout: float = 10.0,
        connect: Callable[[QbitConfig, float], Any] | None = None,
    ) -> None:
        self._name = name
        self._config = config
        self._read_only = read_only
        self._timeout = timeout
        self._connect = connect or _connect
        self._client: Any = None

    @property
    def name(self) -> str:
        return self._name

    def version(self) -> ServiceVersion:
        client = self._session()
        version, api = self._call(
            lambda: (client.app_version(), client.app_web_api_version())
        )
        return ServiceVersion("qBittorrent", str(version), str(api))

    def diagnose(self) -> list[Diagnostic]:
        client = self._session()
        preferences = self._call(lambda: client.app_preferences())
        return diagnose_preferences(self._name, preferences)

    def read(self) -> TargetState:
        client = self._session()
        settings = self._call(lambda: read_transfer_settings(client))
        alternative = settings.alternative_limits
        return TargetState(
            throttled=settings.alternative_mode,
            limits=Limits(alternative.download, alternative.upload),
        )

    def apply(self, state: TargetState) -> None:
        if self._read_only:
            raise WriteForbidden(
                f"{self._name}: observation mode refused a write"
            )
        client = self._session()
        current = self.read()
        if current.limits != state.limits:
            limits = SpeedLimits(state.limits.download, state.limits.upload)
            self._call(lambda: set_alternative_limits(client, limits))
        self._call(lambda: set_alternative_mode(client, state.throttled))

    def _session(self) -> Any:
        if self._client is None:
            try:
                client = self._connect(self._config, self._timeout)
            except QbitCoreError as error:
                raise ServiceUnavailable(str(error)) from error
            self._client = ReadOnlyClient(client) if self._read_only else client
        return self._client

    def _call[T](self, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except WriteForbidden:
            raise
        except QbitCoreError as error:
            raise ServiceUnavailable(str(error)) from error
        except Exception as error:
            if not is_qbit_error(error):
                raise
            # A failed call may mean an expired session: reconnect next time.
            self._client = None
            raise ServiceUnavailable(
                f"qBittorrent at {self._config.host}: "
                f"{type(error).__name__}: {error}"
            ) from error


# bittorrent_protocol: 0 = TCP and µTP, 1 = TCP only, 2 = µTP only.
_UTP_PROTOCOLS = frozenset({0, 2})
_RATE_LIMITS = "Options > Speed > Rate Limits Settings"


def diagnose_preferences(
    name: str, preferences: Mapping[str, Any]
) -> list[Diagnostic]:
    """Settings that let traffic escape the limits Waitarr switches on."""
    found: list[Diagnostic] = []
    if preferences.get("scheduler_enabled"):
        found.append(
            Diagnostic(
                name,
                "warning",
                f"{name}: qBittorrent's speed scheduler is enabled. It flips "
                "the same alternative limits switch, and Waitarr reads each "
                "flip as a human decision that it must leave alone.",
            )
        )
    if (
        preferences.get("bittorrent_protocol") in _UTP_PROTOCOLS
        and preferences.get("limit_utp_rate") is False
    ):
        found.append(
            Diagnostic(
                name,
                "warning",
                f"{name}: µTP traffic is not rate-limited: throttling will "
                f'leak. In qBittorrent, check {_RATE_LIMITS} > "Apply rate '
                'limit to µTP protocol".',
            )
        )
    if preferences.get("limit_lan_peers") is False:
        found.append(
            Diagnostic(
                name,
                "notice",
                f"{name}: peers on the local network are not rate-limited, "
                "so one of them can still read the disk at full speed. If "
                f'that matters, check {_RATE_LIMITS} > "Apply rate limit to '
                'peers on LAN".',
            )
        )
    return found


def _connect(config: QbitConfig, timeout: float) -> Any:
    return create_qbit_client(config, request_timeout=timeout)
