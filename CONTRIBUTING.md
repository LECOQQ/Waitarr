# 🤝 Contributing

```bash
git clone https://github.com/LECOQQ/Waitarr.git
cd Waitarr
make install
make check
```

## 📏 Rules worth preserving

- 🔭 Observation mode never writes: keep it provable
  ([ADR 0004](docs/adr/0004-observation-mode-cannot-write.md)).
- 🙋 Waitarr only undoes its own change
  ([ADR 0003](docs/adr/0003-ownership-state-machine.md)).
- 🧯 An unreadable state means no action.
- 🔒 No secret in a config file, a log line or an error message.
- 🧩 The core knows no service; a new one is a new adapter.

## 📝 Commits

Conventional Commits, body in bullets. Run `make check` before a pull
request; `make test-docker` when touching an adapter or the engine.
