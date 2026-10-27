# ⚙️ Configuration

Waitarr reads one TOML file, then environment variables. Secrets come
from the environment or from files, never from the TOML file: Waitarr
refuses a `password`, `api_key` or `token` written there.

The file is found at `--config`, else `$WAITARR_CONFIG`, else
`./waitarr.toml`. The image sets `WAITARR_CONFIG=/config/waitarr.toml`.
`waitarr check` validates it and reads every service once, without
writing anything.

## 🔀 Precedence

For every key that has a variable: **the variable, then the file, then
the default**. A variable set to an empty value counts as absent, so a
Compose file can pass `WAITARR_MODE=${WAITARR_MODE:-}` and leave
`waitarr.toml` in charge while `.env` does not set it. Secrets follow the
same rule: an empty `WAITARR_<NAME>_PASSWORD` falls back to its `_FILE`.

## 🗂️ Top level

| Key | Default | Variable | Meaning |
| --- | --- | --- | --- |
| `mode` | `"observe"` | `WAITARR_MODE` | `observe` logs decisions and writes nothing; `active` throttles. |
| `poll_interval` | `"15s"` | `WAITARR_POLL_INTERVAL` | How often sources and targets are read. At least `1s`. |
| `state_file` | `"waitarr-state.json"` | `WAITARR_STATE_FILE` | What Waitarr owns, for restoration after a restart. Relative to the working directory (`/data` in the image). |
| `restore_on_exit` | `true` | | Give everything back on SIGTERM or Ctrl-C. |
| `log_level` | `"INFO"` | `WAITARR_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

Durations: `"15s"`, `"3m"`, `"1h30m"`, or a number of seconds.
Rates: `"1KiB"`, `"512KiB"`, `"2MiB"` (per second), or a number of bytes
per second.

## 🎯 `[policy]`

| Key | Default | Meaning |
| --- | --- | --- |
| `strategy` | `"global"` | v1's only strategy: throttle every target while anything counted plays. |
| `release_after` | `"3m"` | Delay after the last counted playback before giving the speed back (`WAITARR_RELEASE_AFTER`). |
| `users` | `[]` | Only these Jellyfin users count. Empty: everyone. |
| `ignore_users` | `[]` | These users never count. |
| `ignore_devices` | `[]` | Sessions on these devices never count. |
| `ignore_clients` | `[]` | Sessions from these clients (e.g. `"Jellyfin Web"`) never count. |
| `media_types` | `[]` | Only these item types count (`"Movie"`, `"Episode"`, `"Audio"`, ...). Empty: all. |
| `count_paused` | `false` | Whether a paused session keeps the throttle on. |

Names compare case-insensitively. A session without a user name is
excluded by a `users` list and kept by `ignore_users`. The choice is
explained in [ADR 0007](adr/0007-playback-filter.md).

## 🐢 `[throttle]`

The alternative limits applied while throttling, per second. Both or
neither. Never `0`, which qBittorrent reads as "unlimited". Overridable
per target with `throttle = { download = "...", upload = "..." }`, and
globally with `WAITARR_THROTTLE_DOWNLOAD` and `WAITARR_THROTTLE_UPLOAD`.

Without `[throttle]`, each instance's own alternative limits are used;
Waitarr warns at startup when those are unlimited.

## 🌐 `[http]`

| Key | Default | Meaning |
| --- | --- | --- |
| `listen` | `"0.0.0.0:8778"` | Address of `GET /healthz` (`WAITARR_HTTP_LISTEN`). `""` in the file disables it; an empty variable is ignored. |
| `webhook` | `false` | Accept `POST /hooks/jellyfin` to poll at once. |

`/healthz` answers `200` when the last tick is recent and reached every
service, `503` otherwise, with a JSON body: mode, sessions, each
service's reachability and version, each target's ownership and state.

For the webhook, install Jellyfin's *Webhook* plugin and add a *Generic*
destination to `http://<waitarr>:8778/hooks/jellyfin`, on *Playback
Start* and *Playback Stop*. With `WAITARR_WEBHOOK_TOKEN` set, send it
as the `X-Waitarr-Token` header or `?token=`. The body is ignored: the
webhook only wakes the loop ([ADR 0010](adr/0010-polling-first-webhook-as-nudge.md)).

## 🔔 `[notify]`

| Key | Default | Meaning |
| --- | --- | --- |
| `failure_threshold` | `2` | Consecutive failed reads of a service before a failure notification. |
| `healthchecks_interval` | `"60s"` | Minimum time between two success pings. |

Destinations, from the environment only (each also accepts `_FILE`):

| Variable | Effect |
| --- | --- |
| `WAITARR_NOTIFY_WEBHOOK_URL` | POST `{"source", "event", "title", "message"}` as JSON on failure and recovery. |
| `WAITARR_NOTIFY_NTFY_URL` | Publish to an ntfy topic URL (`https://ntfy.sh/<topic>`). |
| `WAITARR_NOTIFY_NTFY_TOKEN` | Bearer token for a protected ntfy topic. |
| `WAITARR_HEALTHCHECKS_URL` | Healthchecks ping URL: success after healthy ticks, `/fail` when health turns bad. |

## 🎬 `[[sources]]`

| Key | Meaning |
| --- | --- |
| `name` | Lowercase letters, digits, `-`, `_`; unique across sources and targets. |
| `type` | `"jellyfin"`. |
| `url` | Base URL, e.g. `http://jellyfin:8096`. |
| `timeout` | Request timeout (default `"10s"`). |
| `api_key_file` | Path of a file holding the API key. |

API key: `WAITARR_<NAME>_API_KEY`, or a file named by
`WAITARR_<NAME>_API_KEY_FILE` or `api_key_file`. Create it in Jellyfin's
*Dashboard > API Keys*: a dashboard key sees every session.

## 🧲 `[[targets]]`

| Key | Meaning |
| --- | --- |
| `name` | As for sources. |
| `type` | `"qbittorrent"`. |
| `url` | WebUI base URL, e.g. `http://qbittorrent:8080`. |
| `username` | WebUI user (or `WAITARR_<NAME>_USERNAME`). |
| `password_file` | Path of a file holding the password. |
| `throttle` | Per-target limits, overriding `[throttle]`. |
| `timeout` | Request timeout (default `"10s"`). |

Password: `WAITARR_<NAME>_PASSWORD`, or a file named by
`WAITARR_<NAME>_PASSWORD_FILE` or `password_file`.

`<NAME>` is the entry's `name` in upper case, `-` becoming `_`: a target
named `seedbox-2` reads `WAITARR_SEEDBOX_2_PASSWORD`.

## 🩺 Startup checks

At startup, every hour, and in `waitarr check`, Waitarr reads each
qBittorrent's preferences and reports what lets traffic escape the
throttle. It never changes these settings itself.

| Severity | Setting | Fix in qBittorrent |
| --- | --- | --- |
| warning | µTP enabled (`bittorrent_protocol` TCP and µTP, or µTP) and *Apply rate limit to µTP protocol* unchecked: µTP peers ignore the throttle | *Options > Speed > Rate Limits Settings* > *Apply rate limit to µTP protocol* |
| notice | *Apply rate limit to peers on LAN* unchecked: a peer on the local network still reads the disk at full speed | same place, *Apply rate limit to peers on LAN* |
| warning | The speed scheduler is enabled: it flips the same switch | *Options > Speed > Alternative Rate Limits* > *Schedule the use of alternative rate limits* |

The findings are logged and listed under `warnings` in `GET /healthz`;
they do not change its status code.

## 🧾 Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; for `status`, healthy. |
| `1` | A service failed, the state file cannot be trusted, or (for `run`) something could not be restored on exit. |
| `2` | Invalid configuration; every problem is listed. |
