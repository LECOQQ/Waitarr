"""Wire a configuration to concrete adapters. The only module that knows
both the core and every adapter: a new source or target type is one
entry in `SOURCE_FACTORIES` or `TARGET_FACTORIES`."""

from __future__ import annotations

from collections.abc import Callable

from qbit_core import QbitConfig

from waitarr.adapters.jellyfin import JellyfinSource
from waitarr.adapters.notify import (
    FanOutNotifier,
    HealthchecksHeartbeat,
    NoHeartbeat,
    NtfyNotifier,
    WebhookNotifier,
)
from waitarr.adapters.qbittorrent import QbittorrentTarget
from waitarr.adapters.state_file import JsonStateFile
from waitarr.config import AppConfig, Mode, SourceConfig, TargetConfig
from waitarr.core.engine import Engine, TargetBinding
from waitarr.core.policy import GlobalHysteresisPolicy, ThrottlePolicy
from waitarr.core.ports import (
    ActivitySource,
    Heartbeat,
    Notifier,
    ThrottleTarget,
)

__all__ = [
    "SOURCE_FACTORIES",
    "TARGET_FACTORIES",
    "build_engine",
]

SOURCE_FACTORIES: dict[str, Callable[[SourceConfig], ActivitySource]] = {
    "jellyfin": lambda c: JellyfinSource(
        c.name, c.url, c.api_key, timeout=c.timeout
    ),
}

TARGET_FACTORIES: dict[str, Callable[[TargetConfig, bool], ThrottleTarget]] = {
    "qbittorrent": lambda c, read_only: QbittorrentTarget(
        c.name,
        QbitConfig(host=c.url, username=c.username, password=c.password),
        read_only=read_only,
        timeout=c.timeout,
    ),
}


def build_policy(config: AppConfig) -> ThrottlePolicy:
    return GlobalHysteresisPolicy(
        release_after=config.policy.release_after,
        playback_filter=config.policy.playback_filter,
    )


def build_notifier(config: AppConfig) -> Notifier:
    notifiers: list[Notifier] = []
    if config.notify.webhook_url:
        notifiers.append(WebhookNotifier(config.notify.webhook_url))
    if config.notify.ntfy_url:
        notifiers.append(
            NtfyNotifier(config.notify.ntfy_url, token=config.notify.ntfy_token)
        )
    return FanOutNotifier(notifiers)


def build_heartbeat(config: AppConfig) -> Heartbeat:
    if not config.notify.healthchecks_url:
        return NoHeartbeat()
    return HealthchecksHeartbeat(
        config.notify.healthchecks_url,
        interval=config.notify.healthchecks_interval.total_seconds(),
    )


def build_engine(config: AppConfig, *, simulate: bool | None = None) -> Engine:
    """Build the engine. In observation mode every target is built
    read-only, so no code path below can reach a qBittorrent write."""
    observe = config.mode is Mode.OBSERVE if simulate is None else simulate
    return Engine(
        sources=[SOURCE_FACTORIES[s.type](s) for s in config.sources],
        targets=[
            TargetBinding(TARGET_FACTORIES[t.type](t, observe), t.throttle)
            for t in config.targets
        ],
        policy=build_policy(config),
        store=JsonStateFile(config.state_file),
        notifier=build_notifier(config),
        heartbeat=build_heartbeat(config),
        simulate=observe,
        failure_threshold=config.notify.failure_threshold,
    )
