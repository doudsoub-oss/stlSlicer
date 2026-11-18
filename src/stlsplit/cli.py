"""Command-line interface: argument parsing, orchestration, logging and exit codes.

Last stage of the pipeline (PLAN.md §5.1); the only module besides ``io`` that touches the
file system. Phase 0 provides ``--help`` and ``--version`` only; the full CLI (§7) lands in
Phase 1.
"""

import argparse
from collections.abc import Sequence

from stlsplit import __version__
from stlsplit.errors import ExitCode


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The ``stlsplit`` parser. Options are added in Phase 1 (PLAN.md §7.2).
    """
    parser = argparse.ArgumentParser(
        prog="stlsplit",
        description="Split an oversized STL model into printable, connectable parts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        The process exit code (PLAN.md §4.5).
    """
    build_parser().parse_args(argv)
    return int(ExitCode.SUCCESS)
