# 0009. Harness: starter-kits baseline, qbit-ops gates

- Status: accepted (2026-10-27)

## Context

The brief asks for qbit-ops' harness. starter-kits renders a project
skeleton but lags behind qbit-ops: no Docker, gitleaks, Renovate,
provenance or commit-body hooks, and none of `secrets`, `check-docs`,
`check-ai`, `build`, `check-dist`, `check-image`.

## Decision

- starter-kits (`kit:poc`, `stack:python-cli`, `architecture:python-clean`,
  GitHub CI and release blocks) was rendered to compare and to seed
  the agent rules, `LICENSE` and `.editorconfig`.
- The Makefile, gate scripts (`scripts/check_*.py`, `docker_tags.py`),
  hooks and workflows follow qbit-ops, copied verbatim where generic.
- Improvements over qbit-ops: `deps-audit` (pip-audit, from
  starter-kits), `test-docker` checks for leaked containers like
  qbit-ops' matrix targets, and CI also runs the Docker suite and a
  multi-architecture image build on every pull request.

## Consequences

- Gate scripts exist twice (qbit-ops and here); see the friction about
  moving them into starter-kits.
