"""Data model shared by every pipeline stage (PLAN.md §5.2).

Dataclasses only, no behaviour. Each dataclass of §5.2 is added by the phase that first uses
it: Phase 1 adds ``Diagnostic``; Phase 3 adds ``Orientation``, ``Plane`` and ``Grid``;
``Piece`` and ``CutFace`` come with the cutting (Phase 4), and so on.
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


@dataclass(frozen=True)
class Orientation:
    """How the input frame maps to the cutting frame: ``x_cut = R · x_in + t`` (PLAN.md §4.2).

    Built by ``grid.orient``. R is one of the six proper rotations of ``grid.ROTATIONS``
    (det = +1, ADR-0008); t moves the rotated model's bounding-box minimum to the origin.

    Attributes:
        name: The rotation, as ``grid.ROTATIONS`` names it, e.g. ``"90 deg about Y"``.
        input_to_cutting: The 4×4 matrix ``[[R, t], [0, 0, 0, 1]]``, row by row, mm. Written to
            ``assembly.json`` as ``frame.input_to_cutting`` (Phase 9).
    """

    name: str
    input_to_cutting: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class Plane:
    """A cut plane, perpendicular to one axis of the cutting frame (ADR-0013).

    Attributes:
        axis: The axis the plane is perpendicular to.
        index: 0-based position among this axis' planes, in increasing offset.
        offset: Position along ``axis``, mm, cutting frame.
    """

    axis: Axis
    index: int
    offset: float


@dataclass(frozen=True)
class Grid:
    """The grid of cells the model is cut into (PLAN.md Phase 3, ADR-0003).

    Cell (i, j, k) spans, along each axis, the interval between two consecutive boundaries
    0, the plane offsets, then ``extent`` (``grid.axis_bounds``).

    Attributes:
        usable: U per axis (X, Y, Z), mm; peg-adjusted in peg mode (§6.1).
        counts: Number of cells per axis.
        planes: Per axis, its planes sorted by offset; ``counts[a] - 1`` of them.
        extent: Model size per axis in the cutting frame, mm (its bounding box starts at 0).
    """

    usable: tuple[float, float, float]
    counts: tuple[int, int, int]
    planes: tuple[tuple[Plane, ...], tuple[Plane, ...], tuple[Plane, ...]]
    extent: tuple[float, float, float]
