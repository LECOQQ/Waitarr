# 0004. Observation mode cannot write, by construction

- Status: accepted (2026-10-27)

## Context

Waitarr runs against production in observation mode first. That mode
must never call a write API, and the brief asks for proof.

## Decision

Three independent layers, each sufficient alone:

1. The engine never calls `ThrottleTarget.apply` and never persists
   state when `simulate` is on.
2. In observation mode, the qBittorrent adapter wraps the client in
   `ReadOnlyClient`, which exposes an allow-list of read methods and
   raises `WriteForbidden` for anything else. `apply` raises too.
3. The adapter's own `apply` refuses when built read-only.

`waitarr check` always builds the read-only variant, whatever the mode.

## Consequences

- Tests prove it at the HTTP level against a real qBittorrent: in
  observation mode, only GET requests and the login POST leave the
  process, and the instance's settings are unchanged.
- In observation mode, the reconciliation still runs, with `applied`
  set to the state found, so a human change is reported just as it
  would be in active mode.
