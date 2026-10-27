# 0010. Polling decides; the webhook only wakes the loop

- Status: accepted (2026-10-27)

## Context

Jellyfin's webhook plugin can announce a playback at once; polling
`/Sessions` every 15 s is slower but cannot miss an event.

## Decision

`POST /hooks/jellyfin` (off by default, optional token) ignores its
body and wakes the loop, which then polls as usual. No decision is ever
taken from a webhook payload.

## Consequences

- A lost, duplicated or forged webhook costs one extra poll, nothing
  more.
- Reaction time drops from up to 15 s to about one request when the
  plugin is configured.
