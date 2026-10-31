"""The startup block: what Waitarr was configured with and what it found.

Pure functions, so the text is testable without a service. They read
settings and versions only, never a secret: a URL loses its userinfo,
query and fragment, and the key, password and token fields are not read.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from waitarr import __version__
from waitarr.compatibility import Verdict, assess
from waitarr.config import AppConfig, SourceConfig, TargetConfig
from waitarr.core.model import ServiceVersion
from waitarr.core.policy import PlaybackFilter
from waitarr.core.units import format_duration, format_rate

__all__ = ["compatibility_warnings", "plain_url", "startup_block"]

# The playback filter lists, in the order the configuration documents them.
_FILTER_LISTS = (
    "users",
    "ignore_users",
    "ignore_devices",
    "ignore_clients",
    "media_types",
    "libraries",
    "ignore_libraries",
)


def plain_url(url: str) -> str:
    """The URL without userinfo, query and fragment."""
    parts = urlsplit(url)
    host = parts.netloc.rpartition("@")[2]
    return f"{parts.scheme}://{host}{parts.path}".rstrip("/")


def startup_block(
    config: AppConfig,
    versions: Mapping[str, ServiceVersion | None],
    *,
    simulate: bool,
    http_port: int | None = None,
) -> list[str]:
    """The lines logged once at start, in reading order."""
    mode = (
        "OBSERVATION mode: decisions are logged, nothing is ever written"
        if simulate
        else "ACTIVE mode: targets are throttled during playback"
    )
    lines = [
        f"Waitarr {__version__} starting in {mode}",
        f"Polling every {format_duration(config.poll_interval)}, releasing "
        f"{format_duration(config.policy.release_after)} after the last "
        "playback",
    ]
    if http_port is not None:
        webhook = ", webhook on /hooks/jellyfin" if config.http.webhook else ""
        lines.append(
            f"Health endpoint on http://{config.http.host}:{http_port}"
            f"/healthz{webhook}"
        )
    lines.append(_filters(config.policy.playback_filter))
    lines.extend(_source(s, versions.get(s.name)) for s in config.sources)
    lines.extend(_target(t, versions.get(t.name)) for t in config.targets)
    return lines


def compatibility_warnings(
    config: AppConfig, versions: Mapping[str, ServiceVersion | None]
) -> list[str]:
    """One line per service whose version is not a tested one."""
    kinds = {s.name: s.type for s in config.sources} | {
        t.name: t.type for t in config.targets
    }
    warnings = []
    for name, version in versions.items():
        assessment = assess(kinds[name], version)
        if assessment.verdict is not Verdict.TESTED:
            warnings.append(f"{name}: {assessment.message}.")
    return warnings


def _filters(playback_filter: PlaybackFilter) -> str:
    parts = [
        f"{name}={','.join(sorted(values))}"
        for name in _FILTER_LISTS
        if (values := getattr(playback_filter, name))
    ]
    if playback_filter.count_paused:
        parts.append("count_paused")
    if not parts:
        return "Playback filters: none, every playback counts"
    return "Playback filters: " + "; ".join(parts)


def _source(source: SourceConfig, version: ServiceVersion | None) -> str:
    tasks = (
        "tasks held while something plays: " + ", ".join(source.tasks)
        if source.suspend_tasks
        else "task suspension off"
    )
    return (
        f"Source {source.name} ({source.type}) at {plain_url(source.url)}; "
        f"{assess(source.type, version).message}; {tasks}"
    )


def _target(target: TargetConfig, version: ServiceVersion | None) -> str:
    limits = (
        "throttle to "
        f"{format_rate(target.throttle.download)} down / "
        f"{format_rate(target.throttle.upload)} up"
        if target.throttle is not None
        else "throttle to its own alternative limits"
    )
    return (
        f"Target {target.name} ({target.type}) at {plain_url(target.url)}; "
        f"{assess(target.type, version).message}; {limits}"
    )
