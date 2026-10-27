# 🐢 Waitarr

<p align="center">
  <a href="https://github.com/LECOQQ/Waitarr/actions/workflows/ci.yml"><img src="https://github.com/LECOQQ/Waitarr/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12">
  <img src="https://img.shields.io/badge/image-amd64%20%7C%20arm64-2496ED?logo=docker&logoColor=white" alt="amd64 and arm64">
</p>

🐢 **While something plays on Jellyfin, Waitarr slows qBittorrent down to
a trickle -- without pausing a single torrent -- and gives the speed back
a few minutes after the playback ends.**

Your torrents stay connected and seeding, with no re-announce and no
lost peers. Your film stops freezing because a torrent was reading the
same slow disk.

## 🤔 Why

Small NAS boxes share one disk between everything. On a Raspberry Pi
with a USB drive, two simultaneous reads can drop throughput to a few
megabytes per second: enough for a torrent, not for a film. Existing
tools (speedrr, AutoThrottle, limitrr) throttle to protect *upload
bandwidth*, and usually ignore playback on the local network. Waitarr
throttles to protect *the disk*: a LAN playback counts. The longer story
is in [PHILOSOPHY.md](PHILOSOPHY.md).

## 🚀 Install in three minutes

### 🐳 Docker Compose (recommended)

```bash
mkdir waitarr && cd waitarr
curl -fsSLO https://raw.githubusercontent.com/LECOQQ/Waitarr/main/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/LECOQQ/Waitarr/main/.env.example
curl -fsSL -o waitarr.toml https://raw.githubusercontent.com/LECOQQ/Waitarr/main/config/waitarr.example.toml
chmod 600 .env
```

1. In `waitarr.toml`, set the `url` of your Jellyfin and of each
   qBittorrent, and the qBittorrent `username`.
2. In `.env`, set `WAITARR_JELLYFIN_API_KEY` (Jellyfin: *Dashboard >
   API Keys*) and `WAITARR_MAIN_PASSWORD` (the qBittorrent WebUI
   password).
3. Start it, and check what it sees:

```bash
docker compose up -d
docker compose exec waitarr waitarr check
docker compose logs -f waitarr
```

The image runs on amd64 and arm64 (Raspberry Pi 4 and 5): `ghcr.io/lecoqq/waitarr:0.0.0` <!-- x-release-please-version -->.

### 🐍 As a Python tool

```bash
uv tool install waitarr      # or: pipx install waitarr
waitarr check --config waitarr.toml
waitarr run --config waitarr.toml
```

## 🔭 Observe first, then act

Waitarr starts in **observation mode**: it computes every decision and
logs it, and writes nothing, anywhere.

```text
INFO    Sessions now: alice playing "Dune" (Living Room on Jellyfin Web).
INFO    main: [observe] would throttle (alternative limits on: 1 KiB/s down, 1 KiB/s up) -- alice playing "Dune" (Living Room on Jellyfin Web).
INFO    No session is playing anything.
INFO    main: [observe] would release, restoring the state found before (alternative mode off, limits unlimited down, unlimited up).
```

When the log says what you expect, set `mode = "active"` and restart.

## ⚙️ Configuration

One TOML file, plus secrets from the environment. The commented example
is [config/waitarr.example.toml](config/waitarr.example.toml); every key
and variable is in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

```toml
mode = "observe"          # then "active"
poll_interval = "15s"

[policy]
release_after = "3m"      # how long after the last playback the speed comes back

[throttle]
download = "1KiB"         # never 0: to qBittorrent, 0 means unlimited
upload = "1KiB"

[[sources]]
name = "jellyfin"
type = "jellyfin"
url = "http://jellyfin:8096"

[[targets]]
name = "main"
type = "qbittorrent"
url = "http://qbittorrent:8080"
username = "admin"
```

## 🧠 How it works

Every `poll_interval`, Waitarr reads Jellyfin's sessions and each
qBittorrent's speed settings.

- 🎬 **A playback starts**: Waitarr writes down the state it finds,
  sets the alternative speed limits to your `[throttle]` values, and
  turns qBittorrent's alternative mode (the turtle) on.
- ⏸️ **Pause, seek, next episode**: nothing changes while the gap is
  shorter than `release_after`.
- ⏹️ **Playback over for `release_after`**: Waitarr restores exactly the
  state it found: mode and limits.
- 🙋 **You decide**: if the turtle was already on, or you change it
  while Waitarr holds it, Waitarr leaves it alone until playback stops,
  and never undoes your change.
- 💥 **Crash or restart**: what Waitarr owns is in a state file, written
  before every change; the next start gives it back.
- 📵 **A service is unreachable**: Waitarr changes nothing that depends
  on it, logs it, and notifies you if you configured ntfy or a webhook.

Health: `GET /healthz` on port 8778 (`waitarr status` reads it; the
image's `HEALTHCHECK` uses it). Optional Healthchecks.io ping, ntfy or
webhook alerts on failure, and a Jellyfin webhook endpoint to react
instantly.

## 🚧 Limits

- v1 throttles **every** torrent of each configured instance. Throttling
  only the torrents on the disk being read is the plan for v2.
- Sources: Jellyfin only. Targets: qBittorrent only. The architecture
  takes more (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- qBittorrent's speed **scheduler** flips the same switch; Waitarr
  reads each flip as a human decision and steps aside (it warns at
  startup).
- Tested versions are listed in
  [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md); Waitarr warns at
  startup outside them.

## ❓ FAQ

**Why not pause the torrents?** Pausing drops every peer and re-announces
on resume; some private trackers count that against you. A throttle at
1 KiB/s keeps the torrent connected and seeding.

**My playback is on the local network. Does it count?** Yes, by default.
That is the point: the disk does not care where the viewer is.

**Can I exclude someone, or a music speaker?** Yes: `users`,
`ignore_users`, `ignore_devices`, `ignore_clients`, `media_types` in
`[policy]`.

**I already use the turtle on a schedule.** Then Waitarr will step
aside whenever the turtle is on. Disable the scheduler, or let Waitarr
handle playback times only.

**What if Waitarr dies while throttling?** Restart it: it reads its
state file and gives the speed back. `waitarr restore --yes` does it
without starting the service.

**Does it need admin access to Jellyfin?** It needs an API key created
in the dashboard, which can see every session.

## 🛠️ Development

```bash
make install
make check          # lint, types, tests, docs, AI hygiene
make test-docker    # against a disposable qBittorrent container
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## 📄 License

MIT. Waitarr builds on [qbit-ops](https://github.com/LECOQQ/qbit-ops)'s
`qbit_core`.
