# 0008. The repository is bootstrapped on `main`

- Status: accepted (2026-10-27)

## Context

The brief asks for GitHub Flow, forbids merging a pull request without
review, and expects an open release-please pull request, which only
appears from commits on `main`.

## Decision

The initial build is committed directly on `main`, in logical commits.
Every later change follows GitHub Flow: a short branch and a pull
request.

## Consequences

- The release-please pull request exists and stays open; nothing is
  released.
- The friction is recorded in the agent's working notes, which are not
  published.
