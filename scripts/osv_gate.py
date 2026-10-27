#!/usr/bin/env python3
"""Turn an osv-scanner JSON report into a pass/fail verdict.

A vulnerability in a Python package fails the gate: those are Waitarr's
own dependencies, and a lock update or a Dockerfile change fixes them.
A vulnerability in the base image's operating-system packages is listed
but does not fail: Waitarr cannot patch Debian, and Renovate moves the
base image digest when Debian ships a fix.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

BLOCKING_ECOSYSTEMS = frozenset({"PyPI"})


def _findings(report: dict) -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for result in report.get("results") or []:
        for entry in result.get("packages") or []:
            package = entry.get("package") or {}
            ecosystem = str(package.get("ecosystem") or "unknown")
            for vulnerability in entry.get("vulnerabilities") or []:
                found[ecosystem].append(
                    f"{package.get('name')} {package.get('version')}: "
                    f"{vulnerability.get('id')}"
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate an osv-scanner report.")
    parser.add_argument("report", type=Path, help="osv-scanner --format json")
    parser.add_argument("--label", default="scan")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"{args.label}: unreadable osv-scanner report: {error}")
        return 2
    found = _findings(report)
    blocking = 0
    for ecosystem in sorted(found):
        entries = sorted(set(found[ecosystem]))
        blocks = ecosystem.split(":")[0] in BLOCKING_ECOSYSTEMS
        blocking += len(entries) if blocks else 0
        verdict = "BLOCKING" if blocks else "reported, not blocking"
        print(f"{args.label}: {ecosystem}: {len(entries)} ({verdict})")
        if blocks:
            for line in entries:
                print(f"  {line}")
    if not found:
        print(f"{args.label}: no known vulnerability")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
