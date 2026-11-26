"""Layer rules, checked on the AST of every module (never on its text).

`waitarr.core` is pure: it knows nothing of HTTP, qBittorrent, the CLI
or the configuration file. Adapters implement the core's ports and never
reach up into the wiring or the entrypoints.
"""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "src"

# package directory (under src/) -> modules it must never import. A
# forbidden name matches itself and everything below it, nothing else.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "waitarr/adapters": (
        "waitarr.bootstrap",
        "waitarr.cli",
        "waitarr.service",
    ),
}


def imported_modules(source: str, package: str) -> set[str]:
    """Every absolute module name `source` imports, relative ones resolved
    against `package` (the dotted package of the file)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join([*parts, *([base] if base else [])])
            found.add(base)
            # `from waitarr import adapters` imports waitarr.adapters.
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def violations(imports: set[str], forbidden: tuple[str, ...]) -> list[str]:
    return sorted(
        name
        for name in imports
        for rule in forbidden
        if name == rule or name.startswith(rule + ".")
    )


def outsiders(imports: set[str], allowed: tuple[str, ...]) -> list[str]:
    """Every import that is neither the standard library nor `allowed`
    (itself or below it): a package added later is refused by default."""
    return sorted(
        name
        for name in imports
        if name.split(".")[0] not in sys.stdlib_module_names
        and not any(name == a or name.startswith(a + ".") for a in allowed)
    )


def modules(directory: str) -> list[Path]:
    files = sorted((SRC / directory).rglob("*.py"))
    assert files, f"no module found under {directory}"
    return files


@pytest.mark.parametrize(
    ("directory", "path"),
    [(d, p) for d in FORBIDDEN for p in modules(d)],
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_module_respects_its_layer(directory, path):
    package = ".".join(path.relative_to(SRC).with_suffix("").parts[:-1])
    imports = imported_modules(path.read_text(encoding="utf-8"), package)
    assert violations(imports, FORBIDDEN[directory]) == []


# The core imports the standard library and itself, nothing else.
CORE_ALLOWED = ("waitarr.core",)


@pytest.mark.parametrize("path", modules("waitarr/core"), ids=lambda p: p.name)
def test_core_imports_only_the_standard_library_and_itself(path):
    package = ".".join(path.relative_to(SRC).with_suffix("").parts[:-1])
    imports = imported_modules(path.read_text(encoding="utf-8"), package)
    assert outsiders(imports, CORE_ALLOWED) == []


def test_the_allow_list_refuses_any_other_package():
    found = imported_modules(
        "import httpx\nfrom waitarr import adapters\nimport json\n"
        "from waitarr.core import model\nfrom . import policy\n",
        "waitarr.core",
    )
    assert outsiders(found, CORE_ALLOWED) == [
        "httpx",
        "waitarr",
        "waitarr.adapters",
    ]


def test_the_detector_sees_plain_and_from_imports():
    source = "import requests.adapters\nfrom qbit_core.qbit import client\n"
    found = imported_modules(source, "waitarr.core")
    assert violations(found, ("requests", "qbit_core")) == [
        "qbit_core.qbit",
        "qbit_core.qbit.client",
        "requests.adapters",
    ]


def test_the_detector_sees_a_from_import_of_a_forbidden_submodule():
    found = imported_modules("from waitarr import adapters\n", "waitarr.core")
    assert violations(found, ("waitarr.adapters",)) == ["waitarr.adapters"]


def test_the_detector_resolves_relative_imports():
    found = imported_modules("from .. import config\n", "waitarr.core")
    assert violations(found, ("waitarr.config",)) == ["waitarr.config"]


def test_the_detector_does_not_confuse_lookalike_names():
    found = imported_modules(
        "import requests_toolbelt\nimport waitarr.configuration\n",
        "waitarr.core",
    )
    assert violations(found, ("requests", "waitarr.config")) == []
