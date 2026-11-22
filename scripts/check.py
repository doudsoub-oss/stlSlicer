"""Run every check: lint, format check, type check, then the tests (PLAN.md §9.6).

    python scripts/check.py           # everything except the slow tests
    python scripts/check.py --fast    # also skip the end-to-end tests

Prints each command and stops at the first failure with its exit code. Pure Python, so it
works the same on Linux, macOS and Windows.
"""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COVERAGE_MINIMUM = 85
"""Percent (PLAN.md §9.4). Enforced here, not in the pytest configuration, where it would fail
every run of a single test."""


def commands(fast: bool) -> list[list[str]]:
    marker = "not slow and not e2e" if fast else "not slow"
    python = sys.executable
    return [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "mypy", "src"],
        [python, "-m", "pytest", "-m", marker, f"--cov-fail-under={COVERAGE_MINIMUM}"],
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run lint, format, type and test checks.")
    parser.add_argument("--fast", action="store_true", help="skip the end-to-end tests")
    args = parser.parse_args(argv)
    for command in commands(args.fast):
        print("$ " + " ".join(command[2:] if command[1] == "-m" else command), flush=True)
        code = subprocess.run(command, cwd=ROOT, check=False).returncode
        if code != 0:
            print(f"FAILED (exit {code})", flush=True)
            return code
    print("all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
