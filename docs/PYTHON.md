# 🐍 Installing with Python

The container is the recommended way ([README](../README.md)). Waitarr is
also a Python 3.12+ package.

```bash
uv tool install waitarr   # or: pipx install waitarr
```

Configure it with environment variables, as in the Compose example, or
with a TOML file started from
[config/waitarr.example.toml](../config/waitarr.example.toml):

```bash
export WAITARR_JELLYFIN_URL=http://jellyfin:8096
export WAITARR_JELLYFIN_API_KEY=...
export WAITARR_QBIT_INSTANCES=main
export WAITARR_MAIN_URL=http://qbittorrent:8080
export WAITARR_MAIN_PASSWORD=...
waitarr check
waitarr run
```

or, with a file:

```bash
waitarr run --config waitarr.toml
```

Every key and variable is listed in [CONFIGURATION.md](CONFIGURATION.md).
The state file defaults to `waitarr-state.json` in the working directory;
set `WAITARR_STATE_FILE` to keep it elsewhere. To run it as a service,
wrap `waitarr run` in a systemd unit with `KillSignal=SIGTERM` and a
`TimeoutStopSec` of 30 seconds, so stopping gives the speed back.
