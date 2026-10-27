# 0012. Active by default, observation on demand

- Status: accepted (2026-10-27); supersedes the default mode in ADR 0005

## Context

Starting in observation mode protected a first run against production,
but every user then had to edit a file to get what they installed
Waitarr for. Observation stays one setting away: `mode = "observe"` or
`WAITARR_MODE=observe`.

## Decision

- The default mode is `active`.
- The README offers observation as the first step for whoever wants to
  read the log before letting Waitarr act.
- Every key with a variable resolves the variable, then the file, then
  the default; an empty variable counts as absent, so a Compose file can
  expose `WAITARR_MODE=${WAITARR_MODE:-}` without overriding the file.

## Consequences

- A configuration that does not say `mode` now throttles. Deployments that
  must stay in observation write `mode = "observe"` explicitly.
- Observation mode keeps its guarantee (ADR 0004): it cannot write.
