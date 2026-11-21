"""Entry point of ``stlsplit`` and ``python -m stlsplit``; delegates to ``stlsplit.cli.main``.

The libraries take most of a second to import, outside ``main``'s error handling, and trimesh
catches ``BaseException`` around some of its imports. So Ctrl-C is only noted during the import,
and reported right after it (PLAN.md Phase 10, task 4).
"""

import signal
from types import FrameType


def run() -> int:
    """Import the CLI with Ctrl-C held, then run it.

    Returns:
        The process exit code (PLAN.md §4.5), 130 if Ctrl-C was pressed during the import.
    """
    pressed: list[int] = []

    def remember(number: int, frame: FrameType | None) -> None:
        pressed.append(number)

    previous = signal.getsignal(signal.SIGINT)
    holding = previous is signal.default_int_handler  # not if the shell made it ignore Ctrl-C
    if holding:
        signal.signal(signal.SIGINT, remember)
    try:
        from stlsplit import cli
    finally:
        if holding:
            signal.signal(signal.SIGINT, previous)
    return cli.interrupted() if pressed else cli.main()


if __name__ == "__main__":
    raise SystemExit(run())
