# 0001. Python, Poetry, and `qbit_core` from qbit-ops

- Status: accepted (2026-10-27)

## Context

Waitarr talks to qBittorrent. qbit-ops already has a tested library for
that, `qbit_core`, whose rules (no printing, typed protocols, explicit
public surface) suit a long-running service. A rewrite would duplicate
qBittorrent knowledge in two places.

## Decision

Python 3.12 and Poetry, like qbit-ops. Whatever Waitarr needs from
qBittorrent that `qbit_core` lacks (transfer settings, the alternative
mode, a request timeout, named instances) is added to qbit-ops, and
Waitarr depends on it, from PyPI: `qbit-ops = ">=0.7,<0.8"`, locked in
`poetry.lock`.

## Consequences

- One implementation of the qBittorrent transfer API, tested against
  real containers in qbit-ops' matrix.
- The dependency is a release on PyPI, not a Git URL (PyPI refuses direct
  references), so Waitarr can be published there.
- The `<0.8` bound follows qbit-ops' own versioning: before 1.0, a minor
  release may change `qbit_core`'s public surface. Renovate proposes the
  next minor as a pull request.
- `qbit-ops` brings Typer, Rich and qbittorrent-api; Waitarr uses the
  first and the last anyway.
