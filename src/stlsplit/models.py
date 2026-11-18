"""Data model shared by every pipeline stage (PLAN.md §5.2).

Dataclasses only, no behaviour. Each dataclass of §5.2 is added by the phase that first uses
it: Phase 1 adds ``Diagnostic``; ``Plane`` and ``Grid`` come with the grid (Phase 3), and so
on.
"""

from dataclasses import dataclass
from typing import Literal

Axis = Literal[0, 1, 2]
"""Axis index in the cutting frame: 0 = X, 1 = Y, 2 = Z."""

Severity = Literal["info", "warning", "partial"]
"""Severity of a diagnostic; ``partial`` makes the run exit 3 (PLAN.md §4.5)."""


@dataclass(frozen=True)
class Diagnostic:
    """Something a stage reports without failing (PLAN.md §4.5).

    Build them with ``errors.diagnostic`` so the severity comes from the registry.

    Attributes:
        code: Registry code, e.g. ``"W001"``.
        severity: Copied from the registry entry of ``code``.
        message: One line for the user.
        refs: IDs of the pieces, faces or connectors concerned, in the order the stage found
            them (§4.3).
    """

    code: str
    severity: Severity
    message: str
    refs: tuple[str, ...]
