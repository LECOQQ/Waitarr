# 🧭 Architecture decision records

One decision per file, short: context, decision, consequences. A
superseded record stays, marked as such, and names its successor.

| ADR | Decision |
| --- | --- |
| [0001](0001-python-and-qbit-core.md) | Python, Poetry, and `qbit_core` from qbit-ops |
| [0002](0002-ports-and-adapters.md) | Ports and adapters, policies as strategies |
| [0003](0003-ownership-state-machine.md) | Ownership: undo only what Waitarr did |
| [0004](0004-observation-mode-cannot-write.md) | Observation mode cannot write, by construction |
| [0005](0005-configuration-and-secrets.md) | TOML configuration; secrets from the environment or files only |
| [0006](0006-alternative-limits.md) | Throttle with alternative limits that Waitarr sets and restores |
| [0007](0007-playback-filter.md) | Which playbacks count: allow and ignore lists |
| [0008](0008-bootstrap-on-main.md) | The repository is bootstrapped on `main` |
| [0009](0009-harness.md) | Harness: starter-kits baseline, qbit-ops gates |
| [0010](0010-polling-first-webhook-as-nudge.md) | Polling decides; the webhook only wakes the loop |
| [0011](0011-image-distribution.md) | The image is built by CI, published only from a release |
| [0012](0012-active-by-default.md) | Active by default, observation on demand |
| [0013](0013-suspend-jellyfin-tasks.md) | Stop Jellyfin's heavy scheduled tasks during a playback, and start them again |
| [0014](0014-no-anticipation-from-sessions.md) | No throttle ahead of playback from Jellyfin sessions |
| [0015](0015-downloads-throttled-like-seeds.md) | Downloading torrents are throttled like seeding ones, not stopped |
| [0016](0016-downloads-off-the-media-disk.md) | Downloads in progress belong on a disk Jellyfin does not read |
