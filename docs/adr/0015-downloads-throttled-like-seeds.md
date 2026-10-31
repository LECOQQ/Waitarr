# 0015. Downloading torrents are throttled like seeding ones, not stopped

- Status: accepted (2026-10-31)

## Context

A seeding torrent must stay in the swarm; a downloading one does not
need to, and could be stopped during a playback, or throttled harder.
Before adding per-torrent ownership for that, the disk cost of each
case was measured: qBittorrent 5.1.4, a seeder and a leecher in
disposable containers on one ext4 disk, peers on a Docker network with
*Apply rate limit to peers on LAN* on, bytes read and written per
container from its cgroup `io.stat`, 60 s windows.

| Case | Seeder reads | Leecher writes |
| --- | --- | --- |
| Free (disk-bound) | 6.5 MiB/s | 6.0 MiB/s |
| Alternative limits at 1 KiB/s, first minute | 12 MiB | 6 MiB (requests in flight) |
| Alternative limits at 1 KiB/s, steady | ~0.06 MiB/min | ~0.06 MiB/min |
| Download stopped | 0 | 0 |
| Download started again, 60 s | 0 | 0.1 MiB, no recheck |

Also measured: the end of a download reads nothing back; with
*Pre-allocate disk space for all files*, a file is created and
allocated whole at its first write (`fallocate`, almost free on ext4),
not when the torrent is added.

## Decision

No separate treatment for downloads. Once the throttle is on, a
download costs the disk about as much as a seed: a few kilobytes a
second. Stopping it would save almost nothing more, and would make
Waitarr own the state of each torrent (and tell its stop from a
human's) for that.

## Consequences

- Nothing changes for users; Waitarr still only changes speed limits.
- What the limits do not cover stays outside Waitarr: the first
  minute after the throttle starts, a recheck, and a file moved when a
  download completes. Where downloads in progress should live:
  [ADR 0016](0016-downloads-off-the-media-disk.md).
- Pre-allocation is not among them where `fallocate` works: on a real
  NFS 4.2 share, allocating 2 GB took 0.56 s and reserved the blocks
  without writing them. On a share without it (NFS before 4.2),
  pre-allocation may still write a file's whole size; not measured.
