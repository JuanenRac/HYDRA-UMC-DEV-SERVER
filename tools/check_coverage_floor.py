# =============================================================================
# HYDRA-UMC-DEV-SERVER - tools/check_coverage_floor.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Compare the figure of a `coverage json` report with the floor of tools/coverage_floor.json.

    python tools/check_coverage_floor.py coverage.json [--floors tools/coverage_floor.json]

The coverage job measures line and branch coverage of the package once and calls this script, so the floor lives in one JSON file that the
repository tool (`hydra_project_tool.py coverage`) reads too. It exits 0 when the figure is at or above the floor, 1 when it is below or the
floor file is not a list with a python entry whose floor is a number from 1 to 100, and prints the figure either way. The floor is the figure
measured by the job, rounded down: raise it in the same change that adds the tests, never above what the job measured."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def floor_of(entries: object) -> float:
    """The floor of the python entry of the floors file; a ValueError says what is wrong with the file."""
    if not isinstance(entries, list):
        raise ValueError("the floors file must be a list of entries")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("stack") == "python":
            floor = entry.get("floor")
            if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not 1 <= floor <= 100:
                raise ValueError(f"the floor of the python entry must be a number from 1 to 100, not {floor!r}")
            return float(floor)
    raise ValueError("the floors file has no python entry")


def check(report: object, entries: object) -> tuple[bool, str]:
    """(ok, message) for a `coverage json` document and the content of the floors file."""
    try:
        floor = floor_of(entries)
    except ValueError as error:
        return False, f"COVERAGE_FLOOR=FAIL {error}"
    try:
        value = float(report["totals"]["percent_covered"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return False, "COVERAGE_FLOOR=FAIL the report has no totals.percent_covered"
    if value + 1e-9 < floor:
        return False, f"COVERAGE_FLOOR=FAIL {value:.2f}% is below the floor of {floor:g}%"
    return True, f"COVERAGE_FLOOR=PASS {value:.2f}% (floor {floor:g}%)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", help="the file written by `coverage json`")
    parser.add_argument("--floors", default="tools/coverage_floor.json", help="the file with the floors (default: tools/coverage_floor.json)")
    args = parser.parse_args(argv)
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        entries = json.loads(Path(args.floors).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        print(f"COVERAGE_FLOOR=FAIL cannot read {error.__class__.__name__}: {error}", file=sys.stderr)
        return 1
    ok, message = check(report, entries)
    print(message, file=None if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
