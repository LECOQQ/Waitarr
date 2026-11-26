# 0008. The repository is bootstrapped on `main`

- Status: accepted (2026-10-27)

## Context

The requirements are GitHub Flow, no merge of a pull request without
review, and an open release-please pull request, which only appears
from commits on `main`.

## Decision

The initial build is committed directly on `main`, in logical commits.
Every later change follows GitHub Flow: a short branch and a pull
request.

## Consequences

- The release-please pull request exists and stays open; nothing is
  released.
