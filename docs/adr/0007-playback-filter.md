# 0007. Which playbacks count: allow and ignore lists

- Status: accepted (2026-10-27)

## Context

By default every playback must throttle (a LAN playback reads the same
disk). Some households will want to exclude a user, a device (a music
speaker) or a media type.

## Decision

A `PlaybackFilter` inside the policy, with seven lists compared
case-insensitively: `users` (allow-list), `ignore_users`,
`ignore_devices`, `ignore_clients`, `media_types` (allow-list),
`libraries` (allow-list), `ignore_libraries`, and
`count_paused` (default off: a paused session does not read the disk).
Empty allow-lists mean "everything". An unknown user never matches an
allow-list and never matches an ignore-list.

Priorities or per-user weights were left out: no v1 need, and the
filter is one field of the policy, so a richer one replaces it without
touching the engine.

Libraries were added later. The Jellyfin source reads every library's
folders from `/Library/VirtualFolders` (cached, refreshed every 10
minutes) and matches the playing file's path against them, so an item
gets every library holding it. `/Items/{id}/Ancestors` was rejected:
without a user id it returns physical folders, never the library, and
with one it returns a single library where folders overlap. An item is
ignored if any of its libraries is ignored, and counted by `libraries`
if any of them is listed.

## Consequences

- The default throttles on every playback, local or remote.
