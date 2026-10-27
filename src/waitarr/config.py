"""Load the configuration: a TOML file, environment overrides, and
secrets from the environment or from files only.

Every problem is collected and reported at once, with the key or the
variable to fix. A secret written in the file itself is refused: the
file is meant to be shared, copied and committed.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from waitarr.core.model import Limits
from waitarr.core.policy import PlaybackFilter
from waitarr.core.units import parse_duration, parse_rate

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AppConfig",
    "ConfigError",
    "HttpConfig",
    "Mode",
    "NotifyConfig",
    "PolicyConfig",
    "SourceConfig",
    "TargetConfig",
    "load_config",
]

DEFAULT_CONFIG_PATH = Path("waitarr.toml")
DEFAULT_HTTP_PORT = 8778

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_SECRET_KEYS = frozenset({"api_key", "password", "token", "apikey"})


class ConfigError(Exception):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            "invalid configuration:\n" + "\n".join(f"  - {p}" for p in problems)
        )


class Mode(StrEnum):
    OBSERVE = "observe"
    ACTIVE = "active"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    type: str
    url: str
    api_key: str = field(repr=False)
    timeout: float = 10.0


@dataclass(frozen=True)
class TargetConfig:
    name: str
    type: str
    url: str
    username: str
    password: str = field(repr=False)
    throttle: Limits | None = None
    timeout: float = 10.0


@dataclass(frozen=True)
class PolicyConfig:
    strategy: str
    release_after: timedelta
    playback_filter: PlaybackFilter


@dataclass(frozen=True)
class HttpConfig:
    host: str
    port: int | None
    webhook: bool
    webhook_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class NotifyConfig:
    failure_threshold: int = 2
    webhook_url: str | None = field(default=None, repr=False)
    ntfy_url: str | None = field(default=None, repr=False)
    ntfy_token: str | None = field(default=None, repr=False)
    healthchecks_url: str | None = field(default=None, repr=False)
    healthchecks_interval: timedelta = timedelta(seconds=60)


@dataclass(frozen=True)
class AppConfig:
    path: Path
    mode: Mode
    poll_interval: timedelta
    state_file: Path
    restore_on_exit: bool
    log_level: str
    policy: PolicyConfig
    sources: tuple[SourceConfig, ...]
    targets: tuple[TargetConfig, ...]
    http: HttpConfig
    notify: NotifyConfig


def env_name(service: str, field_name: str) -> str:
    """`WAITARR_<SERVICE>_<FIELD>`, e.g. `WAITARR_MAIN_PASSWORD`."""
    return f"WAITARR_{service.upper().replace('-', '_')}_{field_name.upper()}"


class _Reader:
    """Collects problems while reading one config document."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self.environ = environ
        self.problems: list[str] = []

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def table(self, data: Mapping[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key, {})
        if not isinstance(value, dict):
            self.fail(f"[{key}] must be a table")
            return {}
        return value

    def unknown(
        self, where: str, data: Mapping[str, Any], known: set[str]
    ) -> None:
        for key in sorted(set(data) - known):
            if key in _SECRET_KEYS:
                self.fail(
                    f"{where}: '{key}' must not be written in the file; "
                    "pass it through the environment or a secrets file "
                    "(see docs/CONFIGURATION.md)"
                )
            else:
                self.fail(f"{where}: unknown key '{key}'")

    def convert[T](
        self, where: str, raw: Any, parse: Callable[[Any], T], default: T
    ) -> T:
        try:
            return parse(raw)
        except (TypeError, ValueError) as error:
            self.fail(f"{where}: {error}")
            return default

    def string_list(self, where: str, raw: Any) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list) or not all(
            isinstance(v, str) for v in raw
        ):
            self.fail(f"{where}: must be a list of strings")
            return []
        return raw

    def secret(
        self, service: str, field_name: str, entry: Mapping[str, Any]
    ) -> str | None:
        """Resolve a secret: `WAITARR_<SVC>_<FIELD>`, then
        `WAITARR_<SVC>_<FIELD>_FILE`, then `<field>_file` in the file."""
        variable = env_name(service, field_name)
        if self.environ.get(variable):
            return self.environ[variable]
        path = self.environ.get(variable + "_FILE") or entry.get(
            f"{field_name}_file"
        )
        if path:
            return self.read_secret_file(str(path), variable)
        return None

    def env_secret(self, variable: str) -> str | None:
        if self.environ.get(variable):
            return self.environ[variable]
        path = self.environ.get(variable + "_FILE")
        return self.read_secret_file(path, variable) if path else None

    def read_secret_file(self, path: str, variable: str) -> str | None:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as error:
            self.fail(
                f"{variable}: cannot read secrets file {path} "
                f"({error.strerror})"
            )
            return None
        if not value:
            self.fail(f"{variable}: secrets file {path} is empty")
            return None
        return value


def _positive_rate(raw: Any) -> int:
    value = parse_rate(raw)
    if value == 0:
        raise ValueError(
            "0 means 'unlimited' to qBittorrent, which would not throttle "
            "anything; write a small value such as '1KiB'"
        )
    return value


def _limits(
    reader: _Reader, where: str, raw: Mapping[str, Any]
) -> Limits | None:
    reader.unknown(where, raw, {"download", "upload"})
    if not raw:
        return None
    if "download" not in raw or "upload" not in raw:
        reader.fail(f"{where}: set both 'download' and 'upload'")
        return None
    download = reader.convert(
        f"{where}.download", raw["download"], _positive_rate, 1
    )
    upload = reader.convert(f"{where}.upload", raw["upload"], _positive_rate, 1)
    return Limits(download, upload)


def _url(reader: _Reader, where: str, raw: Any) -> str:
    if not isinstance(raw, str) or not re.match(r"^https?://\S+$", raw):
        reader.fail(f"{where}.url: an http:// or https:// URL is required")
        return ""
    parts = urlsplit(raw)
    if parts.username or parts.password:
        # Never echo the URL: it holds the credential being refused.
        reader.fail(
            f"{where}.url: must not carry credentials (user:password@); "
            "use 'username' and the password variable instead"
        )
        return ""
    return raw.rstrip("/")


def _timeout(reader: _Reader, where: str, raw: Any) -> float:
    delta = reader.convert(
        f"{where}.timeout", raw, parse_duration, timedelta(seconds=10)
    )
    return max(delta.total_seconds(), 1.0)


def _jellyfin(reader: _Reader, entry: Mapping[str, Any]) -> SourceConfig:
    name = entry["name"]
    where = f"source '{name}'"
    reader.unknown(
        where, entry, {"name", "type", "url", "api_key_file", "timeout"}
    )
    api_key = reader.secret(name, "api_key", entry)
    if api_key is None:
        reader.fail(
            f"{where}: no API key; set {env_name(name, 'api_key')} "
            f"(or {env_name(name, 'api_key')}_FILE)"
        )
    return SourceConfig(
        name=name,
        type="jellyfin",
        url=_url(reader, where, entry.get("url")),
        api_key=api_key or "",
        timeout=_timeout(reader, where, entry.get("timeout", 10)),
    )


def _qbittorrent(
    reader: _Reader, entry: Mapping[str, Any], default_throttle: Limits | None
) -> TargetConfig:
    name = entry["name"]
    where = f"target '{name}'"
    reader.unknown(
        where,
        entry,
        {
            "name",
            "type",
            "url",
            "username",
            "password_file",
            "throttle",
            "timeout",
        },
    )
    username = reader.environ.get(env_name(name, "username")) or entry.get(
        "username"
    )
    if not isinstance(username, str) or not username:
        reader.fail(
            f"{where}: no username; set 'username' or "
            f"{env_name(name, 'username')}"
        )
        username = ""
    password = reader.secret(name, "password", entry)
    if password is None:
        reader.fail(
            f"{where}: no password; set {env_name(name, 'password')} "
            f"(or {env_name(name, 'password')}_FILE)"
        )
    throttle_raw = entry.get("throttle", {})
    if not isinstance(throttle_raw, dict):
        reader.fail(f"{where}.throttle must be a table")
        throttle_raw = {}
    throttle = _limits(reader, f"{where}.throttle", throttle_raw)
    effective = throttle or default_throttle
    if effective is not None:
        # qBittorrent stores whole KiB/s: any other value reads back
        # different, and Waitarr would take it for a human change.
        for label, value in (
            ("download", effective.download),
            ("upload", effective.upload),
        ):
            if value % 1024:
                reader.fail(
                    f"{where}: throttle {label} must be a whole number of "
                    f"KiB/s for qBittorrent (e.g. '1KiB', '64KiB'), got "
                    f"{value} bytes/s"
                )
    return TargetConfig(
        name=name,
        type="qbittorrent",
        url=_url(reader, where, entry.get("url")),
        username=username,
        password=password or "",
        throttle=effective,
        timeout=_timeout(reader, where, entry.get("timeout", 10)),
    )


SOURCE_TYPES: dict[
    str, Callable[[_Reader, Mapping[str, Any]], SourceConfig]
] = {
    "jellyfin": _jellyfin,
}
TARGET_TYPES: dict[
    str,
    Callable[[_Reader, Mapping[str, Any], Limits | None], TargetConfig],
] = {
    "qbittorrent": _qbittorrent,
}


def _entries(
    reader: _Reader,
    data: Mapping[str, Any],
    key: str,
    kinds: Mapping[str, object],
    seen: set[str],
) -> list[dict[str, Any]]:
    raw = data.get(key, [])
    if not isinstance(raw, list) or not raw:
        reader.fail(f"declare at least one [[{key}]] entry")
        return []
    valid: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        where = f"[[{key}]] #{index + 1}"
        if not isinstance(entry, dict):
            reader.fail(f"{where} must be a table")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            reader.fail(
                f"{where}: 'name' is required: lowercase letters, digits, "
                "'-' or '_', at most 32 characters"
            )
            continue
        if name in seen:
            reader.fail(f"{where}: the name '{name}' is already used")
            continue
        seen.add(name)
        kind = entry.get("type")
        if kind not in kinds:
            reader.fail(
                f"{where} '{name}': 'type' must be one of "
                f"{', '.join(sorted(kinds))}"
            )
            continue
        valid.append(entry)
    return valid


def _listen(reader: _Reader, raw: Any) -> tuple[str, int | None]:
    if raw in ("", None, False):
        return "", None
    text = str(raw)
    host, _, port = text.rpartition(":")
    if not port.isdigit() or not 0 <= int(port) <= 65535:
        reader.fail(
            f"http.listen: expected 'host:port' (e.g. '0.0.0.0:8778'), "
            f"or '' to disable, got {text!r}"
        )
        return "", None
    return host or "0.0.0.0", int(port)


def parse_config(
    data: Mapping[str, Any], *, path: Path, environ: Mapping[str, str]
) -> AppConfig:
    reader = _Reader(environ)
    reader.unknown(
        "top level",
        data,
        {
            "mode",
            "poll_interval",
            "state_file",
            "restore_on_exit",
            "log_level",
            "policy",
            "throttle",
            "http",
            "notify",
            "sources",
            "targets",
        },
    )

    def setting(key: str, variable: str, default: Any) -> Any:
        return environ.get(variable) or data.get(key, default)

    mode_raw = setting("mode", "WAITARR_MODE", Mode.OBSERVE.value)
    mode = reader.convert("mode", mode_raw, Mode, Mode.OBSERVE)
    poll = reader.convert(
        "poll_interval",
        setting("poll_interval", "WAITARR_POLL_INTERVAL", "15s"),
        parse_duration,
        timedelta(seconds=15),
    )
    if poll < timedelta(seconds=1):
        reader.fail("poll_interval: must be at least 1s")
    state_file = Path(
        str(setting("state_file", "WAITARR_STATE_FILE", "waitarr-state.json"))
    )
    restore_on_exit = data.get("restore_on_exit", True)
    if not isinstance(restore_on_exit, bool):
        reader.fail("restore_on_exit: must be true or false")
        restore_on_exit = True
    log_level = str(setting("log_level", "WAITARR_LOG_LEVEL", "INFO")).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        reader.fail("log_level: one of DEBUG, INFO, WARNING, ERROR")
        log_level = "INFO"

    policy_raw = reader.table(data, "policy")
    reader.unknown(
        "[policy]",
        policy_raw,
        {
            "strategy",
            "release_after",
            "users",
            "ignore_users",
            "ignore_devices",
            "ignore_clients",
            "media_types",
            "count_paused",
        },
    )
    strategy = policy_raw.get("strategy", "global")
    if strategy != "global":
        reader.fail("[policy] strategy: v1 provides 'global' only")
    release_after = reader.convert(
        "[policy] release_after",
        environ.get("WAITARR_RELEASE_AFTER")
        or policy_raw.get("release_after", "3m"),
        parse_duration,
        timedelta(minutes=3),
    )
    count_paused = policy_raw.get("count_paused", False)
    if not isinstance(count_paused, bool):
        reader.fail("[policy] count_paused: must be true or false")
        count_paused = False
    playback_filter = PlaybackFilter.build(
        users=reader.string_list("[policy] users", policy_raw.get("users")),
        ignore_users=reader.string_list(
            "[policy] ignore_users", policy_raw.get("ignore_users")
        ),
        ignore_devices=reader.string_list(
            "[policy] ignore_devices", policy_raw.get("ignore_devices")
        ),
        ignore_clients=reader.string_list(
            "[policy] ignore_clients", policy_raw.get("ignore_clients")
        ),
        media_types=reader.string_list(
            "[policy] media_types", policy_raw.get("media_types")
        ),
        count_paused=count_paused,
    )

    throttle_raw = dict(reader.table(data, "throttle"))
    for key in ("download", "upload"):
        variable = f"WAITARR_THROTTLE_{key.upper()}"
        if environ.get(variable):
            throttle_raw[key] = environ[variable]
    default_throttle = _limits(reader, "[throttle]", throttle_raw)

    http_raw = reader.table(data, "http")
    reader.unknown("[http]", http_raw, {"listen", "webhook"})
    host, port = _listen(
        reader,
        environ.get(
            "WAITARR_HTTP_LISTEN", http_raw.get("listen", "0.0.0.0:8778")
        ),
    )
    webhook = http_raw.get("webhook", False)
    if not isinstance(webhook, bool):
        reader.fail("[http] webhook: must be true or false")
        webhook = False
    if webhook and port is None:
        reader.fail("[http] webhook needs [http] listen")

    notify_raw = reader.table(data, "notify")
    reader.unknown(
        "[notify]", notify_raw, {"failure_threshold", "healthchecks_interval"}
    )
    threshold = notify_raw.get("failure_threshold", 2)
    if not isinstance(threshold, int) or threshold < 1:
        reader.fail("[notify] failure_threshold: a whole number, at least 1")
        threshold = 2
    notify = NotifyConfig(
        failure_threshold=threshold,
        webhook_url=reader.env_secret("WAITARR_NOTIFY_WEBHOOK_URL"),
        ntfy_url=reader.env_secret("WAITARR_NOTIFY_NTFY_URL"),
        ntfy_token=reader.env_secret("WAITARR_NOTIFY_NTFY_TOKEN"),
        healthchecks_url=reader.env_secret("WAITARR_HEALTHCHECKS_URL"),
        healthchecks_interval=reader.convert(
            "[notify] healthchecks_interval",
            notify_raw.get("healthchecks_interval", "60s"),
            parse_duration,
            timedelta(seconds=60),
        ),
    )

    names: set[str] = set()
    sources = tuple(
        SOURCE_TYPES[e["type"]](reader, e)
        for e in _entries(reader, data, "sources", SOURCE_TYPES, names)
    )
    targets = tuple(
        TARGET_TYPES[e["type"]](reader, e, default_throttle)
        for e in _entries(reader, data, "targets", TARGET_TYPES, names)
    )

    if reader.problems:
        raise ConfigError(reader.problems)
    return AppConfig(
        path=path,
        mode=mode,
        poll_interval=poll,
        state_file=state_file,
        restore_on_exit=restore_on_exit,
        log_level=log_level,
        policy=PolicyConfig(strategy, release_after, playback_filter),
        sources=sources,
        targets=targets,
        http=HttpConfig(
            host=host,
            port=port,
            webhook=webhook,
            webhook_token=reader.env_secret("WAITARR_WEBHOOK_TOKEN"),
        ),
        notify=notify,
    )


def resolve_config_path(
    explicit: Path | None, environ: Mapping[str, str]
) -> Path:
    if explicit is not None:
        return explicit
    if environ.get("WAITARR_CONFIG"):
        return Path(environ["WAITARR_CONFIG"])
    return DEFAULT_CONFIG_PATH


def load_config(
    path: Path | None = None, environ: Mapping[str, str] | None = None
) -> AppConfig:
    env = os.environ if environ is None else environ
    resolved = resolve_config_path(path, env)
    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigError(
            [
                f"{resolved}: no such file; copy config/waitarr.example.toml "
                "there, or point --config / WAITARR_CONFIG at your file"
            ]
        ) from error
    except OSError as error:
        raise ConfigError([f"{resolved}: {error.strerror}"]) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError([f"{resolved}: not valid TOML ({error})"]) from error
    return parse_config(data, path=resolved, environ=env)
