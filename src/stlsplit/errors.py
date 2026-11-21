"""Exit codes, exception types and the registry of diagnostic codes.

Used by every stage of the pipeline (PLAN.md §5.1) to report failures and diagnostics.
Failures are exceptions carrying their exit code; ``cli.main`` turns them into one line on
stderr. Diagnostics are ``models.Diagnostic`` values that stages return with their results;
``exit_code_for`` turns the collected list into the run's exit code (docs/ARCHITECTURE.md,
"Diagnostics flow").

Exit codes and diagnostic codes are documented in docs/TROUBLESHOOTING.md (a drift test keeps
them in sync). Codes are never reused or renumbered; retired codes stay in the registry marked
as retired (§4.5).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from stlsplit.models import Diagnostic, Severity


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
    INTERRUPTED = 130
    """Stopped with Ctrl-C (128 + SIGINT, the shell convention; PLAN.md Appendix E, r14)."""


class StlsplitError(Exception):
    """Base class for expected failures; carries the exit code the CLI returns."""

    exit_code: ExitCode = ExitCode.INTERNAL


class InputError(StlsplitError):
    """Invalid input file, arguments, configuration or output directory (exit 1)."""

    exit_code = ExitCode.INVALID_INPUT


class ConfigError(InputError):
    """An invalid configuration key or value (exit 1).

    Attributes:
        key: Dotted TOML key, e.g. ``"connectors.clearance"``, or the table name for a bad
            table. The CLI adds the matching flag to the message.
        problem: What is wrong, with the allowed range and the value found.
    """

    def __init__(self, key: str, problem: str) -> None:
        super().__init__(f"{key}: {problem}")
        self.key = key
        self.problem = problem


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
    DiagnosticCode(
        "W013", "partial", "No clear straight path could be shown for an assembly step."
    ),
)
"""Every diagnostic code, sorted by code (PLAN.md §4.5)."""

_REGISTRY: dict[str, DiagnosticCode] = {entry.code: entry for entry in DIAGNOSTIC_CODES}


def diagnostic(code: str, message: str, refs: Iterable[str] = ()) -> Diagnostic:
    """Build a diagnostic whose severity comes from the registry.

    Args:
        code: A registered, non-retired code, e.g. ``"W001"``.
        message: One line for the user.
        refs: IDs of the pieces, faces or connectors concerned; their order is kept.

    Returns:
        The diagnostic.

    Raises:
        ValueError: ``code`` is not registered or is retired. That is a bug, not a user
            error, so the CLI reports it as an internal error (exit 4).
    """
    entry = _REGISTRY.get(code)
    if entry is None or entry.retired:
        raise ValueError(f"diagnostic code {code} is not registered or is retired")
    return Diagnostic(code=code, severity=entry.severity, message=message, refs=tuple(refs))


def exit_code_for(diagnostics: Iterable[Diagnostic]) -> ExitCode:
    """Return the exit code of a run that produced ``diagnostics`` without failing.

    Args:
        diagnostics: Everything the stages reported.

    Returns:
        ``PARTIAL`` (3) if any diagnostic has severity ``partial``, else ``SUCCESS`` (0).
    """
    if any(d.severity == "partial" for d in diagnostics):
        return ExitCode.PARTIAL
    return ExitCode.SUCCESS
