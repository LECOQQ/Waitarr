# 0006. Throttle with alternative limits that Waitarr sets and restores

- Status: accepted (2026-10-27)

## Context

The v1 mechanism is qBittorrent's alternative speed limits mode. On the
production instances those limits are `0`, which qBittorrent reads as
"unlimited": switching the mode alone would change nothing.

## Decision

- While throttling, Waitarr sets the alternative limits to configured
  values (`[throttle]`, per-target override), then turns the mode on.
  Releasing restores both the limits and the mode found before.
- Limits are written through `app/setPreferences`
  (`alt_dl_limit`/`alt_up_limit`), never `transfer/setDownloadLimit`,
  which writes the limit of whichever mode is active.
- `0` is refused in the configuration, with an explanation.
- Without `[throttle]`, the instance's own alternative limits are used,
  and a startup warning says when they are unlimited.

## Consequences

- Torrents stay connected and seeding, at a trickle; nothing is paused.
- A human who changes the limits during a throttle is detected like one
  who toggles the switch.
