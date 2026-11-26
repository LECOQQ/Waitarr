# 0011. The image is built by CI, published only from a release

- Status: accepted (2026-10-27)

## Context

The image (`ghcr.io/lecoqq/waitarr`, amd64 and arm64) is the main
distribution channel. Publishing any version, `latest` included, is a
manual decision.

## Decision

- CI builds both architectures on every pull request and push, without
  pushing.
- `publish-container.yml` (from qbit-ops) pushes version tags, and moves
  `latest` only for the newest release; release-please dispatches it
  when a release pull request is merged.
- A machine that builds the image locally runs it as `waitarr:local`.

## Consequences

- Nothing is public until the release pull request is merged.
- Deploying on a host needs either a release or a locally built image on
  that host.

## Amendment (2026-11-26)

Pull requests build amd64 only (arm64 needs emulation and is slow);
`main` and the release build both architectures.
