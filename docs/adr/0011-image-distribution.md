# 0011. The image is built by CI, published only from a release

- Status: accepted (2026-10-27)

## Context

The image (`ghcr.io/lecoqq/waitarr`, amd64 and arm64) is the main
distribution channel. Publishing any version, `latest` included, needs
the maintainer.

## Decision

- CI builds both architectures on every pull request and push, without
  pushing.
- `publish-container.yml` (from qbit-ops) pushes version tags, and moves
  `latest` only for the newest release; release-please dispatches it
  when a release pull request is merged.
- On the build machine, the observation deployment runs an image built locally
  (`waitarr:local`).

## Consequences

- Nothing is public until the release pull request is merged.
- Deploying on the seedbox needs either a release or a locally built image
  (see `VERIFICATION.md`).
