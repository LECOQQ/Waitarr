# 🏗️ Architecture

Waitarr is a small hexagon: a core that decides, ports it drives, and
one adapter per service.

```text
            ┌──────────────────── waitarr.core ────────────────────┐
Jellyfin ──▶│ ActivitySource ─▶ ThrottlePolicy ─▶ reconcile ─▶ Engine │──▶ ThrottleTarget ──▶ qBittorrent
            │                                       ▲            │──▶ TaskHost ──▶ Jellyfin tasks
            │                     StateStore ◀──────┴────────────┘   │──▶ Notifier, Heartbeat
            └──────────────────────────────────────────────────────┘
```

## 📦 Layout

```text
src/waitarr/
├── core/            # no I/O library, no service knowledge
│   ├── model.py     # Playback, TargetState, Limits, ServiceVersion, ScheduledTask
│   ├── ports.py     # ActivitySource, ThrottleTarget, TaskHost, StateStore, Notifier, Heartbeat
│   ├── policy.py    # ThrottlePolicy (strategy), GlobalHysteresisPolicy, PlaybackFilter
│   ├── reconcile.py # the ownership state machine, pure
│   ├── tasks.py     # the same for one scheduled task, pure
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
5. For each task host, after the targets: with the same demand, `step_task`
   stops the listed tasks found running and, when the demand ends, starts
   again those Waitarr stopped. It follows the same steps as 3 and 4,
   with a `pending` of its own. A host that cannot be read changes no task
   and does not change the tick's health.

The ownership states (`idle`, `engaged`, `yielded`) and why a human
decision is never overwritten: [ADR 0003](adr/0003-ownership-state-machine.md).

The task machine identifies an execution by the `StartTimeUtc` Jellyfin
reports, never by Waitarr's clock, and a task by its `Key`; the `Id` is
read again every tick and never persisted. The reasons, and the facts
probed on Jellyfin: [ADR 0013](adr/0013-suspend-jellyfin-tasks.md).

## 🧩 Extending

- **A source** (Audiobookshelf, Plex, Emby): an adapter implementing
  `ActivitySource`, a parser in `config.SOURCE_TYPES`, a factory in
  `bootstrap.SOURCE_FACTORIES`, a row in `compatibility.MATRIX`.
- **A target** (Transmission's alt-speed): the same with
  `ThrottleTarget`, `config.TARGET_TYPES`, `bootstrap.TARGET_FACTORIES`.
- **A task host**: an adapter implementing `TaskHost` (it has no
  `version()`: its source reports it), a factory in
  `bootstrap.TASK_HOST_FACTORIES`.
- **A policy** (disk-aware): a `ThrottlePolicy`. `Playback.media_path`
  already carries the file being played when the source exposes it;
  [ADR 0002](adr/0002-ports-and-adapters.md) describes the v2 path.

## 🛡️ Observation mode

Read-only by construction, three layers deep:
[ADR 0004](adr/0004-observation-mode-cannot-write.md).
