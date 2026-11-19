"""Data model shared by every pipeline stage (PLAN.md §5.2).

Dataclasses only, no behaviour. Each dataclass of §5.2 is added by the phase that first uses
it: Phase 1 adds ``Diagnostic``; Phase 3 adds ``Orientation``, ``Plane`` and ``Grid``; Phase 4
adds ``Piece`` and ``CutFace``; Phase 5 adds ``Connector``. ``Label`` (and ``Piece.label``)
come in Phase 8, ``AssemblyStep`` in Phase 9.
"""

from dataclasses import dataclass
from typing import Literal

from manifold3d import Manifold
from shapely.geometry import Polygon

Axis = Literal[0, 1, 2]
"""Axis index in the cutting frame: 0 = X, 1 = Y, 2 = Z."""

Severity = Literal["info", "warning", "partial"]
"""Severity of a diagnostic; ``partial`` makes the run exit 3 (PLAN.md §4.5)."""

ConnectorKind = Literal["dowel", "peg"]
"""A placed connector: a loose dowel in two holes, or a peg on the neg piece in a hole of the
pos piece (ADR-0005)."""


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


@dataclass
class Piece:
    """One output part: a body of one grid cell, possibly with small pieces merged into it.

    Built by ``cutting.split_cells``; ``cutting.cut_faces`` fills ``face_ids`` and
    ``cutting.merge_small_pieces`` ``merged_from``. Stages return new pieces rather than
    changing these lists in place.

    Attributes:
        id: ``X{i}-Y{j}-Z{k}``, plus ``-a``, ``-b``, … when the cell holds several bodies
            (PLAN.md §4.3).
        grid_index: The cell (i, j, k) the piece was cut from; a merged piece keeps its own.
        body: The solid, mm, cutting frame; valid, with a positive volume (I1).
        face_ids: IDs of its cut faces, in face order (``cutting.cut_faces``).
        merged_from: IDs of the small pieces merged into it, in merge order (ADR-0012).
    """

    id: str
    grid_index: tuple[int, int, int]
    body: Manifold
    face_ids: list[str]
    merged_from: list[str]


@dataclass(frozen=True)
class CutFace:
    """The contact between two pieces on one cut plane: one connected region (ADR-0002).

    Attributes:
        id: ``{piece_neg}~{piece_pos}``, plus ``#2``, ``#3``, … when the same two pieces
            share several regions, in polylabel order (PLAN.md §4.3).
        plane: The cut plane.
        piece_neg: ID of the piece on the local z < offset side.
        piece_pos: ID of the piece on the local z > offset side.
        region: The contact, plane-local (u, v), mm; may have holes (I4: inside both
            pieces' sections).
    """

    id: str
    plane: Plane
    piece_neg: str
    piece_pos: str
    region: Polygon


@dataclass(frozen=True)
class Connector:
    """One connector on a cut face (PLAN.md Phase 5): its axis position and its pin.

    Built by ``connectors.place``. The holes run along the plane's normal from the face, into
    the neg piece (local z < offset) and the pos piece (z > offset).

    Attributes:
        id: ``{face}/c{n}``, n from 1 in acceptance order (PLAN.md §4.3).
        face_id: The cut face.
        kind: ``dowel`` (holes on both sides) or ``peg`` (the peg stands on the neg piece).
        position_uv: The axis point, plane-local (u, v), mm; inside the face's safe region (I6).
        diameter: d, mm.
        pin_length: L, one of the standard lengths, mm (§6.2); for a peg, twice its
            protrusion.
        hole_depth_neg: h(L) in the neg piece, mm; 0 on a peg's side.
        hole_depth_pos: h(L) in the pos piece, mm.
    """

    id: str
    face_id: str
    kind: ConnectorKind
    position_uv: tuple[float, float]
    diameter: float
    pin_length: float
    hole_depth_neg: float
    hole_depth_pos: float
