import re
from pathlib import Path

MAKEFILE = Path(__file__).parents[2] / "Makefile"

TAGS = {"dev", "qa", "use", "diag"}
REQUIRED = {
    "help",
    "doctor",
    "install",
    "format",
    "lint",
    "test",
    "check",
    "check-fast",
    "secrets",
    "check-docs",
    "check-ai",
    "build",
    "check-dist",
    "check-image",
    "ci",
}

# `target: prerequisites ## tag: description`
TARGET_LINE = re.compile(
    r"^(?P<name>[a-zA-Z0-9_-]+):(?P<rest>[^#=]*)(?P<doc>##.*)?$"
)
DOC = re.compile(r"^## (?P<tag>[a-z]+): \S")


def target_lines():
    return [
        m
        for line in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("\t", "#", " "))
        if (m := TARGET_LINE.match(line))
    ]


def documented():
    return {
        m["name"]: DOC.match(m["doc"])
        for m in target_lines()
        if m["doc"] is not None
    }


def test_every_documented_target_has_a_description_and_a_known_tag():
    wrong = {
        name: match and match["tag"]
        for name, match in documented().items()
        if match is None or match["tag"] not in TAGS
    }
    assert wrong == {}


def test_the_required_targets_exist_and_are_documented():
    assert REQUIRED <= set(documented())


def test_the_required_targets_are_declared_phony():
    text = MAKEFILE.read_text(encoding="utf-8")
    phony = " ".join(
        re.sub(r"\\\n", " ", block)
        for block in re.findall(r"^\.PHONY:(?:.*\\\n)*.*$", text, re.M)
    )
    assert REQUIRED <= set(phony.split())


def test_the_help_target_is_the_default_goal():
    assert re.search(
        r"^\.DEFAULT_GOAL\s*:=\s*help\s*$",
        MAKEFILE.read_text(encoding="utf-8"),
        re.M,
    )
