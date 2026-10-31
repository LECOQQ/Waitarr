# 0016. Downloads in progress belong on a disk Jellyfin does not read

- Status: proposed (2026-10-31)

## Context

Waitarr only changes qBittorrent's speed limits. That holds the
torrents back once a playback has started, but not while the limits
are released (between two films, during a pause longer than
`release_after`), and not the writes the limits do not govern: a
completed download moved to its final folder, an import by copy, a
recheck.

A film stuttered on a real deployment where qBittorrent downloads to
the disk Jellyfin reads from, over NFS 4.2. Read afterwards, without
changing anything, from the qBittorrent API and log (`added_on`,
`completion_on`) and the Jellyfin and ffmpeg logs:

- The film needed about 5 Mbit/s. ffmpeg stayed under real time for
  ten minutes, down to 0.44x over 30 s windows, while qBittorrent had
  been throttled to 1 KiB/s for more than eight minutes.
- Nine downloads were in progress on that disk. None was added or
  completed during the ten minutes, and the qBittorrent log has no
  entry in them: no pre-allocation, no move, no import, no recheck
  triggered by a completion.
- Pre-allocation would not have cost anything anyway: on that share,
  `fallocate` of 2 GB takes 0.56 s and writes nothing (ADR 0015).
- The next morning, none of the 343 peers of the seven downloads still
  running was on the local network, so peers that escape the throttle
  through *Apply rate limit to peers on LAN* are unlikely; the evening
  itself was not recorded.
- Jellyfin's library scan walked the media folders for 1 min 46 s of
  the ten minutes, and began 36 s after the slowdown.

What wrote to the disk during those ten minutes cannot be told from
what the clients keep. Later that night, the limits released and the
same downloads running at full speed on that disk, the file server's
NFS writes blocked from midnight until the qBittorrent host lost its
network; that the downloads caused it is likely, not proven.

## Decision

Recommend, in the documentation, to keep downloads in progress on a
disk Jellyfin does not read from. Waitarr itself changes nothing: where
files go is qBittorrent's configuration.

With qBittorrent, the least intrusive way is *Options > Downloads >
Keep incomplete torrents in*, set to a folder on another disk. A torrent
downloads there, then qBittorrent moves it to its final folder once
complete: the media disk takes one sequential write per torrent instead
of scattered writes for hours, throttled or not. Seeding and imports by
hard link keep working from the final folder.

Downloading and seeding on the other disk would also take the seeding
reads off the media disk, but every import becomes a copy, and each
file is stored twice while it seeds.

## Consequences

- The move at completion still writes the whole file to the media disk,
  whenever it happens, during a playback too; Waitarr does not hold it
  back, and its effect on a playback has not been measured.
- The other disk needs room for the downloads in progress.
- Whether an *arr application waits for the end of the move before
  importing was not checked here.
- What wrote to the disk during the ten minutes stays open; the file
  server's per-disk statistics over the same window would settle it.
