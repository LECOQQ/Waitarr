# 🏗️ Architecture

Waitarr is a small hexagon: a core that decides, ports it drives, and
one adapter per service.

```text
            ┌──────────────────── waitarr.core ────────────────────┐
Jellyfin ──▶│ ActivitySource ─▶ ThrottlePolicy ─▶ reconcile ─▶ Engine │──▶ ThrottleTarget ──▶ qBittorrent
            │                                       ▲            │   │
            │                     StateStore ◀──────┴────────────┘   │──▶ Notifier, Heartbeat
            └──────────────────────────────────────────────────────┘
```

## 📦 Layout

```text
src/waitarr/
├── core/            # no I/O library, no service knowledge
│   ├── model.py     # Playback, TargetState, Limits, ServiceVersion
│   ├── ports.py     # ActivitySource, ThrottleTarget, StateStore, Notifier, Heartbeat
│   ├── policy.py    # ThrottlePolicy (strategy), GlobalHysteresisPolicy, PlaybackFilter
│   ├── reconcile.py # the ownership state machine, pure
│   ├── records.py   # the persisted state document
│   ├── engine.py    # one tick: read, decide, reconcile, write
│   └── units.py     # durations and rates
├── adapters/        # jellyfin, qbittorrent (via qbit_core), state_file, notify, http
├── config.py        # TOML + environment -> AppConfig
├── compatibility.py # the version matrix, checked at startup
├── bootstrap.py     # the only module that knows the core and every adapter
├── service.py       # the loop, signals, health endpoint, restore on exit
└── cli.py           # run, check, status, restore
```

## 🔗 Dependency rules

- 🚫 `waitarr.core` imports no adapter, no configuration, and none of
  `requests`, `qbit_core`, `qbittorrentapi` or `typer`.
- 🚫 `waitarr.adapters` imports neither `bootstrap`, `service` nor `cli`.
- ⬇️ `bootstrap` wires configuration to adapters; `service` and `cli`
  use `bootstrap`.

`tests/unit/test_architecture.py` enforces them.

## 🔁 One tick

1. Read every source. If one fails, the demand is unknown: **no target
   changes** this tick.
2. Ask the policy which targets should be throttled, handing it the
   memory of the last activity per target.
3. For each target, read its state (unreadable: left alone), and
   `reconcile` the persisted record with it.
4. Unless observing: record the write as `pending`, persist, write,
   read back, clear `pending`, persist.

The ownership states (`idle`, `engaged`, `yielded`) and why a human
decision is never overwritten: [ADR 0003](adr/0003-ownership-state-machine.md).

## 🧩 Extending

- **A source** (Audiobookshelf, Plex, Emby): an adapter implementing
  `ActivitySource`, a parser in `config.SOURCE_TYPES`, a factory in
  `bootstrap.SOURCE_FACTORIES`, a row in `compatibility.MATRIX`.
- **A target** (Transmission's alt-speed): the same with
  `ThrottleTarget`, `config.TARGET_TYPES`, `bootstrap.TARGET_FACTORIES`.
- **A policy** (disk-aware): a `ThrottlePolicy`. `Playback.media_path`
  already carries the file being played when the source exposes it;
  [ADR 0002](adr/0002-ports-and-adapters.md) describes the v2 path.

## 🛡️ Observation mode

Read-only by construction, three layers deep:
[ADR 0004](adr/0004-observation-mode-cannot-write.md).
