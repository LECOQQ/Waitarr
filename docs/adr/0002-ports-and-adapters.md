# 0002. Ports and adapters, policies as strategies

- Status: accepted (2026-10-27)

## Context

v1 reads Jellyfin and throttles qBittorrent. Audiobookshelf, Plex or
Emby as sources, Transmission as a target, and a disk-aware policy are
expected next. None of them should require touching the decision logic.

## Decision

- `waitarr.core` knows neither Jellyfin nor qBittorrent. It defines
  the ports (`ActivitySource`, `ThrottleTarget`, `StateStore`,
  `Notifier`, `Heartbeat`), the value types, the pure reconciliation
  and the engine.
- `waitarr.adapters` implements the ports, one module per service.
- `waitarr.bootstrap` is the only module that knows both; a new source
  or target type is one factory entry there and one parser entry in
  `waitarr.config`.
- The decision "which targets to throttle now" is a `ThrottlePolicy`
  strategy. v1 ships `GlobalHysteresisPolicy`. Its memory (last
  activity per target) is handed in and back, so the engine persists it.

The v2 extension point is in place and deliberately unused:
`Playback.media_path` carries the file being read when the source
exposes it, and a policy decides *per target*. A disk-aware policy maps
media paths onto each target's save paths and returns a demand only for
the targets that share the disk. Scoping the throttle to a subset of
torrents will need a richer target port; that is v2's decision.

## Consequences

- `tests/unit/test_architecture.py` holds the dependency rules.
- A target must be able to `read` and idempotently `apply` a
  `TargetState`; anything with a throttle switch and limits fits.
