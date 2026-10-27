# 0005. TOML configuration; secrets from the environment or files only

- Status: accepted (2026-10-27)

## Context

The brief allows YAML or TOML, and forbids secrets in the example file.

## Decision

- TOML, read with the standard library's `tomllib`: no dependency, and
  the format Python projects already use.
- Every secret comes from `WAITARR_<NAME>_<FIELD>`, from
  `WAITARR_<NAME>_<FIELD>_FILE`, or from a `<field>_file` key. A literal
  `password`, `api_key` or `token` in the file is refused, with the
  variable to use instead.
- Notification destinations (ntfy topic, webhook, Healthchecks ping
  URL) grant access too: environment or files only.
- Unknown keys are errors, all reported at once.
- The default mode is `observe`.

## Consequences

- The config file can be committed, shared and pasted into an issue.
- A typo cannot silently disable a setting.
