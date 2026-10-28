# 🛠️ Development

```bash
make install        # Poetry environment + pre-commit and commit-msg hooks
make help           # every target, by category
```

| Target | What it runs |
| --- | --- |
| `make check-fast` | Lint, types, hermetic tests. |
| `make check` | The push gate: lint, types, tests, version sync, doc links, AI hygiene. |
| `make test-docker` | Integration suite against a disposable qBittorrent container and a fake Jellyfin; fails if a container leaks. |
| `make check-image` | Builds the image and runs it end to end against disposable containers. |
| `make image-multiarch` | Builds amd64 and arm64 locally (buildx + QEMU), never pushes. |
| `make secrets` | gitleaks over the working tree (`GITLEAKS_SCOPE=git` for history). |
| `make check-dist` | Builds the wheel and sdist, `twine check`, and an install smoke test. |
| `make deps-audit` | `pip-audit` over the locked dependencies. |
| `make vulns` | osv-scanner over `poetry.lock` and the built image: a Python vulnerability fails, a base-image OS one is listed (`scripts/osv_gate.py`). CI runs the lockfile scan on every pull request, push to `main` and weekly. |

## 🧪 Test isolation

- `make test` never reaches the network beyond `127.0.0.1` and never
  starts a container.
- Docker tests label everything `waitarr.test=<run>` and remove it.
- No test reads `~/.config/waitarr/` or talks to a real Jellyfin or
  qBittorrent.

## 📝 Commits

Conventional Commits in English, with a body of short bullets (one line
per change). The `commit-msg` hooks refuse an agent co-author trailer and
a prose body. GitHub Flow: a short branch from `main`, a pull request.
