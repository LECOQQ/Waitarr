# 🐢 Waitarr

<p align="center">
  <img src="docs/assets/waitarr-logo.png" alt="Waitarr logo: a cartoon turtle in a cinema armchair with popcorn, in front of a play button" width="200">
</p>

<p align="center">
  <a href="https://github.com/LECOQQ/Waitarr/actions/workflows/ci.yml"><img src="https://github.com/LECOQQ/Waitarr/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/image-amd64%20%7C%20arm64-2496ED?logo=docker&logoColor=white" alt="amd64 and arm64">
</p>

🍿 **Jellyfin and torrents on a Raspberry Pi, without the stutter.**

My NAS is a Raspberry Pi with second-hand USB drives; Waitarr makes sure
nobody notices.

```text
▶ playback  →  🐢 turtle mode on, torrents keep seeding
⏹ stop      →  3 min  →  ⚡ speed restored exactly as it was
```

## 🙋 Is it for you?

- Your media server is a Raspberry Pi or a small NAS.
- Jellyfin and qBittorrent share the same disk.
- Your films stutter while your torrents are seeding.

## 🤔 Why not just pause?

Pausing drops every peer and re-announces on resume. Waitarr throttles
instead, as hard as qBittorrent allows: 1 KiB/s (not 0, which qBittorrent
reads as *unlimited*), so the disk barely works for the torrents. It only
changes speed limits; it never pauses, stops or re-announces a torrent.
They stay in the swarm with their peers, and should keep counting as
seeding on private trackers (seed time, hit-and-run rules), though how
each tracker counts a torrent at a crawl has not been measured yet.

## 🛡️ You stay in charge

- 🔭 **Observation first**: it starts by logging what it *would* do, and
  writes nothing until you switch it to active.
- ↩️ **It only gives back what it took**: the speed limits it found,
  exactly.
- ✋ **Your settings win**: turn the turtle on or off by hand and Waitarr
  steps aside until the movie is over.
- 🔌 **Stops cleanly**: on shutdown, after a crash or a restart, the state
  it found comes back.

## ✅ Before you start

In qBittorrent, *Options > Speed > Rate Limits Settings*: check *Apply rate
limit to µTP protocol*, or µTP peers ignore the throttle (Waitarr warns at
startup).

## 🚀 Install in three minutes

```bash
mkdir waitarr && cd waitarr
curl -fsSLO https://raw.githubusercontent.com/LECOQQ/Waitarr/main/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/LECOQQ/Waitarr/main/.env.example
curl -fsSL -o waitarr.toml https://raw.githubusercontent.com/LECOQQ/Waitarr/main/config/waitarr.example.toml
chmod 600 .env
```

1. In `waitarr.toml`, set the `url` of Jellyfin and of each qBittorrent,
   and the qBittorrent `username`.
2. In `.env`, set `WAITARR_JELLYFIN_API_KEY` (Jellyfin: *Dashboard > API
   Keys*) and `WAITARR_MAIN_PASSWORD` (the qBittorrent WebUI password).
3. Start it and watch what it would do:

```bash
docker compose up -d
docker compose exec waitarr waitarr check
docker compose logs -f waitarr
```

Play something: the log says `would throttle`. Happy with what you read?
Set `mode = "active"` and restart.

Image: `ghcr.io/lecoqq/waitarr:0.0.0` <!-- x-release-please-version -->, amd64 and arm64.
Prefer Python? `uv tool install waitarr` or `pipx install waitarr`, then
`waitarr run --config waitarr.toml`.

## ⚙️ Configuration

Delay before the speed comes back, throttle limits, which users or devices
count, several qBittorrent instances, health endpoint, ntfy, Healthchecks,
Jellyfin webhook: all in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
The commented example is
[config/waitarr.example.toml](config/waitarr.example.toml).

## 🧠 How it works

Every 15 seconds Waitarr asks Jellyfin who is playing, and reads each
qBittorrent's speed settings. A playback turns the alternative speed
limits (the turtle) on, with your limits; a few quiet minutes later, the
state it found is restored. If Jellyfin or qBittorrent cannot be read, it
changes nothing. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
and the reasons behind each choice in [docs/adr/](docs/adr/README.md).

## 🚧 Limits

- Every torrent of an instance is throttled; throttling only the disk
  being read is planned.
- Jellyfin and qBittorrent only, for now. Tested versions:
  [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).
- qBittorrent's speed scheduler flips the same switch: Waitarr treats it
  as a human decision and warns at startup.

## ❓ FAQ

**Does a playback on my local network count?** Yes. The disk does not
care where the viewer is.

**Can I leave out a user or a music speaker?** Yes, in `[policy]`; see
the configuration reference.

**What if Waitarr dies while throttling?** Start it again: it gives the
speed back. `waitarr restore --yes` does it without starting the service.

## 🛠️ Development

`make install`, then `make check`. See [CONTRIBUTING.md](CONTRIBUTING.md)
and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The longer story is in
[PHILOSOPHY.md](PHILOSOPHY.md).

## 📄 License

MIT. Built on [qbit-ops](https://github.com/LECOQQ/qbit-ops)' `qbit_core`.
