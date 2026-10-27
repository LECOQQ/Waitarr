# 🧩 Compatibility

Waitarr checks each service's version at startup and says clearly when
it is outside this matrix. It keeps running: an untested version is not
assumed broken, only unverified.

## ✅ Matrix

| Service | Minimum | Tested exactly | How |
| --- | --- | --- | --- |
| Jellyfin | 12.2.0 | 12.2.0 | Read-only, against a real server (production, observation mode) |
| qBittorrent | 5.1.0 | 5.1.0 (Web API 2.11.4) | Read-only, against two real instances (production, observation mode) |
| qBittorrent | 5.1.0 | 5.1.4 (Web API 2.11.4) | Read and write, `make test-docker` (default image), disposable `linuxserver/qbittorrent` container, amd64 |
| qBittorrent | 5.1.0 | 5.1.0 (Web API 2.11.4) | Read and write, `make test-docker` with the 5.1.0 image below, amd64 |
| Python | 3.12 | 3.12 | CI |
| Image | | amd64, arm64 | CI builds both; runtime tested on amd64 |

- **Tested** means exercised for real, at that exact version.
- **Assumed**: anything newer than the minimum. Waitarr logs a warning.
- **Outside the matrix**: anything older than the minimum. Waitarr logs
  a warning in capitals.

Jellyfin's `/Sessions` and `/System/Info/Public` endpoints and
qBittorrent's `transfer/speedLimitsMode`, `transfer/setSpeedLimitsMode`
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
