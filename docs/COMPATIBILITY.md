# 🧩 Compatibility

Waitarr checks each service's version at startup and says clearly when
it is outside this matrix. It keeps running: an untested version is not
assumed broken, only unverified.

## ✅ Matrix

| Service | Minimum | Tested exactly | How |
| --- | --- | --- | --- |
| Jellyfin | 12.2.0 | 12.2.0 | Read-only, against a real server (production, observation mode) |
| Jellyfin | 12.2.0 | 12.2.0 | Scheduled tasks stopped and started by hand, against a disposable container (2026-10-30) |
| qBittorrent | 5.1.0 | 5.1.0 (Web API 2.11.4) | Read-only, against two real instances (production, observation mode) |
| qBittorrent | 5.1.0 | 5.1.4 (Web API 2.11.4) | Read and write, `make test-docker` (default image), disposable `linuxserver/qbittorrent` container, amd64 |
| qBittorrent | 5.1.0 | 5.1.0 (Web API 2.11.4) | Read and write, `make test-docker` with the 5.1.0 image below, amd64 |
| Python | 3.12 | 3.12, 3.13, 3.14, 3.15 | CI (`make ci`); the image, the integration job and the publish job use 3.15 |
| Image | | amd64, arm64 | CI builds both; runtime tested on amd64 |

- **Tested** means exercised for real, at that exact version.
- **Assumed**: anything newer than the minimum. Waitarr logs a warning.
- **Outside the matrix**: anything older than the minimum. Waitarr logs
  a warning in capitals.

What was probed on Jellyfin 12.2.0 for the tasks: `GET /ScheduledTasks`
gives a `Key`, an `Id` (made up per instance), a `State` (`Idle`,
`Running`, `Cancelling`) and the last execution; stopping a running task
answers 204 and the task is `Cancelling` for a few seconds before it is
`Idle` with a `Cancelled` last execution; stopping an idle task answers
500; starting a running task is ignored; an unknown `Id` answers 404. The
`make test-live` check reads `/ScheduledTasks` and the four default keys
(`GET` only). The stop and the start are exercised by hand and against a
fake server, never against a real library in CI.

Jellyfin's `/Sessions`, `/System/Info/Public`, `/Library/VirtualFolders`
and `/ScheduledTasks` endpoints (read), and `DELETE` and `POST`
`/ScheduledTasks/Running/{Id}` (stop and start a task, active mode only),
and qBittorrent's `transfer/speedLimitsMode`, `transfer/setSpeedLimitsMode`
(Web API 2.8.14 and later) and `app/preferences` are the only APIs used.

## 🔁 Verify it yourself

```bash
waitarr check                       # versions, sessions, current state; never writes
make test-docker                    # write path against a disposable qBittorrent 5.1.4
WAITARR_QBIT_IMAGE=linuxserver/qbittorrent:<tag> make test-docker   # another version
```

The 5.1.0 run used
`linuxserver/qbittorrent:5.1.0@sha256:ca6325989299ff807ab94c9505c138b6cadfe8a77c4ef14c5690094cbbe40d7d`
(2026-10-27); the default is pinned in `tests/integration/qbit_container.py`.

The source of truth for the startup check is
`src/waitarr/compatibility.py`. Add a version there only after it was
exercised for real.
