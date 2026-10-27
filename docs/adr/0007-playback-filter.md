# 0007. Which playbacks count: allow and ignore lists

- Status: accepted (2026-10-27)

## Context

By default every playback must throttle (a LAN playback reads the same
disk). Some households will want to exclude a user, a device (a music
speaker) or a media type.

## Decision

A `PlaybackFilter` inside the policy, with five lists compared
case-insensitively: `users` (allow-list), `ignore_users`,
`ignore_devices`, `ignore_clients`, `media_types` (allow-list), and
`count_paused` (default off: a paused session does not read the disk).
Empty allow-lists mean "everything". An unknown user never matches an
allow-list and never matches an ignore-list.

Priorities or per-user weights were left out: no v1 need, and the
filter is one field of the policy, so a richer one replaces it without
touching the engine.

## Consequences

- The default throttles on every playback, local or remote.
