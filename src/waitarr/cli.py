"""Command line: `run`, `check`, `status`, `restore`."""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated

import typer

from waitarr import __version__
from waitarr.bootstrap import build_engine
from waitarr.compatibility import Verdict, assess
from waitarr.config import AppConfig, ConfigError, Mode, load_config
from waitarr.core.ports import ServiceUnavailable
from waitarr.core.records import StateDocumentError
from waitarr.core.units import format_rate

__all__ = ["app", "main"]

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Throttle qBittorrent while something plays on Jellyfin, without "
        "pausing a single torrent, then give the speed back."
    ),
)

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        help="Config file (default: $WAITARR_CONFIG, then ./waitarr.toml).",
    ),
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"waitarr {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    return None


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Library retry chatter would repeat every tick while a service is down;
    # Waitarr reports outages itself, once, through its own logger.
    for name in ("urllib3", "requests", "qbittorrentapi"):
        logging.getLogger(name).setLevel(logging.ERROR)


def _load(config_path: Path | None) -> AppConfig:
    try:
        return load_config(config_path)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(EXIT_CONFIG) from error


@app.command()
def run(
    config_path: ConfigOption = None,
    mode: Annotated[
        Mode | None,
        typer.Option(help="Override the configured mode for this run."),
    ] = None,
) -> None:
    """Run the service until stopped (SIGTERM or Ctrl-C)."""
    from waitarr.service import Service

    config = _load(config_path)
    _setup_logging(config.log_level)
    chosen = mode or config.mode
    engine = build_engine(config, simulate=chosen is Mode.OBSERVE)
    try:
        code = Service(config, engine).run()
    except StateDocumentError as error:
        logging.getLogger("waitarr").error(
            "Refusing to start: the state file cannot be trusted (%s).", error
        )
        raise typer.Exit(EXIT_FAILURE) from error
    raise typer.Exit(code)


@app.command()
def check(config_path: ConfigOption = None) -> None:
    """Validate the config and read every service once. Never writes."""
    config = _load(config_path)
    _setup_logging("WARNING")
    engine = build_engine(config, simulate=True)
    typer.echo(f"Config: {config.path} (mode: {config.mode.value})")
    ok = True
    versions = engine.check_versions()
    kinds = {s.name: "jellyfin" for s in config.sources} | {
        t.name: "qbittorrent" for t in config.targets
    }
    for name, version in versions.items():
        assessment = assess(kinds[name], version)
        mark = {
            Verdict.TESTED: "OK  ",
            Verdict.ASSUMED: "WARN",
            Verdict.UNSUPPORTED: "WARN",
            Verdict.UNKNOWN: "FAIL",
        }[assessment.verdict]
        ok = ok and version is not None
        typer.echo(f"[{mark}] {name}: {assessment.message}")
    for source in engine.sources:
        try:
            sessions = source.playbacks()
        except ServiceUnavailable as error:
            ok = False
            typer.echo(f"[FAIL] {source.name}: {error}")
            continue
        typer.echo(f"[OK  ] {source.name}: {len(sessions)} session(s) playing")
        for playback in sessions:
            paused = " [paused]" if playback.paused else ""
            typer.echo(f"         {playback.describe()}{paused}")
    for binding in engine.bindings:
        try:
            state = binding.target.read()
        except ServiceUnavailable as error:
            ok = False
            typer.echo(f"[FAIL] {binding.target.name}: {error}")
            continue
        limits = binding.throttle_limits or state.limits
        typer.echo(
            f"[OK  ] {binding.target.name}: alternative mode "
            f"{'on' if state.throttled else 'off'}, own alternative limits "
            f"{format_rate(state.limits.download)} down / "
            f"{format_rate(state.limits.upload)} up; would throttle to "
            f"{format_rate(limits.download)} down / "
            f"{format_rate(limits.upload)} up"
        )
    for diagnostic in engine.diagnose():
        mark = "WARN" if diagnostic.severity == "warning" else "NOTE"
        typer.echo(f"[{mark}] {diagnostic.message}")
    raise typer.Exit(EXIT_OK if ok else EXIT_FAILURE)


@app.command()
def status(
    url: Annotated[
        str,
        typer.Option(
            envvar="WAITARR_STATUS_URL", help="Base URL of a running Waitarr."
        ),
    ] = "http://127.0.0.1:8778",
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Exit code only.")
    ] = False,
) -> None:
    """Query a running Waitarr's /healthz (exit 0 when healthy)."""
    try:
        # `url` is the operator's own --url, a local health probe.
        # nosemgrep: dynamic-urllib-use-detected
        with urllib.request.urlopen(
            f"{url.rstrip('/')}/healthz", timeout=5
        ) as r:
            code, body = r.status, r.read()
    except urllib.error.HTTPError as error:
        code, body = error.code, error.read()
    except (urllib.error.URLError, OSError) as error:
        if not quiet:
            typer.echo(f"Waitarr is not answering at {url}: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error
    if not quiet:
        try:
            typer.echo(json.dumps(json.loads(body), indent=2))
        except ValueError:
            typer.echo(body.decode("utf-8", "replace"))
    raise typer.Exit(EXIT_OK if code == 200 else EXIT_FAILURE)


@app.command()
def restore(
    config_path: ConfigOption = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm: this writes to the targets."),
    ] = False,
) -> None:
    """Give back every target a previous active run still owns."""
    if not yes:
        typer.echo(
            "restore writes to qBittorrent: re-run with --yes to confirm.",
            err=True,
        )
        raise typer.Exit(EXIT_FAILURE)
    config = _load(config_path)
    _setup_logging(config.log_level)
    engine = build_engine(config, simulate=False)
    try:
        engine.load()
    except StateDocumentError as error:
        typer.echo(f"The state file cannot be trusted: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error
    raise typer.Exit(EXIT_OK if engine.restore_all() else EXIT_FAILURE)


def main() -> None:
    app()
