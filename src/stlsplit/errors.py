"""Exit codes, exception types and the registry of diagnostic codes.

Used by every stage of the pipeline (PLAN.md §5.1) to report failures and diagnostics.
Exit codes and diagnostic codes are documented in docs/TROUBLESHOOTING.md. Codes are never
reused or renumbered; retired codes stay in the registry marked as retired (§4.5).
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

Severity = Literal["info", "warning", "partial"]


class ExitCode(IntEnum):
    """Process exit codes (PLAN.md §4.5)."""

    SUCCESS = 0
    """Success; ``info`` or ``warning`` diagnostics may exist."""
    INVALID_INPUT = 1
    """Invalid input file, arguments, configuration or output directory."""
    UNREPAIRABLE = 2
    """The mesh can't be repaired into a valid solid."""
    PARTIAL = 3
    """Partial success: at least one diagnostic of severity ``partial``."""
    INTERNAL = 4
    """Internal error (a bug)."""


class StlsplitError(Exception):
    """Base class for expected failures; carries the exit code the CLI returns."""

    exit_code: ExitCode = ExitCode.INTERNAL


class InputError(StlsplitError):
    """Invalid input file, arguments, configuration or output directory (exit 1)."""

    exit_code = ExitCode.INVALID_INPUT


class RepairError(StlsplitError):
    """The mesh can't be repaired into a valid solid (exit 2)."""

    exit_code = ExitCode.UNREPAIRABLE


@dataclass(frozen=True)
class DiagnosticCode:
    """One entry of the diagnostic registry.

    Attributes:
        code: Stable identifier, e.g. ``"W001"``.
        severity: ``info``, ``warning`` or ``partial`` (``partial`` makes the run exit 3).
        summary: One-line meaning, as in PLAN.md §4.5.
        retired: True once the code is no longer emitted; it stays listed forever.
    """

    code: str
    severity: Severity
    summary: str
    retired: bool = False


DIAGNOSTIC_CODES: tuple[DiagnosticCode, ...] = (
    DiagnosticCode(
        "W001",
        "partial",
        "A cut face got no connector (no room, or every candidate failed the 3D checks).",
    ),
    DiagnosticCode("W002", "warning", "A pin was shortened to a standard length."),
    DiagnosticCode("W003", "warning", "Label skipped: no room for the minimum text height."),
    DiagnosticCode("W004", "warning", "A small piece was left on its own (merge not allowed)."),
    DiagnosticCode("W005", "info", "A small piece was merged into a neighbour."),
    DiagnosticCode("W006", "warning", "Suspicious scale: model smaller than 1 mm or over 5 m."),
    DiagnosticCode("W007", "info", "The mesh was repaired (lists the steps applied)."),
    DiagnosticCode("W008", "info", "A piece has no cut face (a separate body)."),
    DiagnosticCode("W009", "info", "A face has a single connector: pieces can rotate until glued."),
    DiagnosticCode("W010", "info", "Overlapping shells were merged."),
    DiagnosticCode("W011", "warning", "An inside-out body was flipped."),
    DiagnosticCode("W012", "info", "The model already fits: nothing to cut."),
)
"""Every diagnostic code, sorted by code (PLAN.md §4.5)."""
