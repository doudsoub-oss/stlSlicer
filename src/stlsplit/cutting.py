"""Splitting into pieces, piece IDs, cut faces and the small-piece merge.

Fourth stage of the pipeline (PLAN.md §5.1), after the grid (``grid.even_grid``, then
``grid.nudge``). ``cut`` runs ``split_cells`` → ``cut_faces`` → ``merge_small_pieces`` →
``check_pieces`` on the normalized body (cutting frame, mm) and returns the pieces, their cut
faces and the diagnostics: W004 and W005 from the merge, W008 for pieces without a cut face.

Pure: geometry in, geometry out. Every cut face's region is computed from the normalized
body, never from the pieces, so both sides agree (ADR-0002). Solids are cut by difference
(``geometry.split_at``, ``geometry.clip``): an intersection leaves a zero-thickness flap where a
model face lies on a plane. A merged piece is cut from the normalized body too, never glued
from its two parts: a union of two split halves keeps a face inside when the plane passes
through mesh vertices (ADR-0012, docs/LIBRARY_NOTES.md).

Guarantees:
- Pieces come in piece order: cell (i, j, k), then suffix; IDs follow §4.3.
- A body keeps its voids: it is an outer shell minus the voids it holds (``geometry.bodies``).
- Every piece is valid with a positive volume (I1), and the volumes add up to the reference
  volume within 0.1 % (I3); otherwise ``AssertionError`` (a bug, exit 4).
- Every cut face has one piece on each side, and its region lies in both pieces' sections
  (I4).
"""

import logging
import math
import string
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import NamedTuple

from manifold3d import Error, Manifold
from shapely.geometry import MultiPolygon, Point

from stlsplit import geometry, grid
from stlsplit.config import (
    AREA_TOLERANCE,
    CUTTER_PAD,
    MERGE_MARGIN,
    MERGE_VOLUME_TOLERANCE,
    MIN_BODY_VOLUME,
    PIECE_PROBE_DEPTH,
    PIECE_PROBE_DEPTH_RETRY,
    VOLUME_TOLERANCE,
    Config,
)
from stlsplit.errors import diagnostic
from stlsplit.models import Axis, CutFace, Diagnostic, Grid, Piece, Plane

LOGGER = logging.getLogger(__name__)

CellIndex = tuple[int, int, int]
"""A cell (i, j, k), 0-based along X, Y, Z (§4.3)."""

_AXES: tuple[Axis, Axis, Axis] = (0, 1, 2)
_AXIS_NAMES = "XYZ"


class Cut(NamedTuple):
    """What the cutting stage returns.

    Attributes:
        pieces: The pieces, in piece order (cell, then suffix), merged pieces removed.
        faces: The cut faces, in face order (``cut_faces``), faces between merged pieces
            removed.
        diagnostics: W004 and W005 in piece order, then W008 in piece order.
    """

    pieces: list[Piece]
    faces: list[CutFace]
    diagnostics: tuple[Diagnostic, ...]


def cut(body: Manifold, layout: Grid, cfg: Config, reference_volume: float) -> Cut:
    """Cut the body into pieces and cut faces, merge small pieces, and check the result.

    Args:
        body: The normalized body, mm, cutting frame (from ``grid.orient``).
        layout: The grid.
        cfg: The configuration (``advanced.section_epsilon``, ``advanced.small_piece_volume``).
        reference_volume: ``RepairReport.reference_volume``, mm³ (I3).

    Returns:
        The pieces, faces and diagnostics.

    Raises:
        AssertionError: I1 or I3 doesn't hold (a bug).
    """
    pieces = split_cells(body, layout)
    pieces, faces = cut_faces(body, layout, pieces, cfg.advanced.section_epsilon)
    pieces, faces, merged = merge_small_pieces(
        body, layout, pieces, faces, cfg.advanced.small_piece_volume
    )
    check_pieces(pieces, reference_volume)
    return Cut(pieces=pieces, faces=faces, diagnostics=merged + separate_bodies(pieces, layout))


# --- splitting and piece IDs (Phase 4, tasks 3 and 4) ---------------------------------------------


def split_cells(body: Manifold, layout: Grid) -> list[Piece]:
    """Split the body along the grid planes and turn each cell's bodies into pieces.

    The body is split by the X planes, then each slab by the Y planes, then each of those by
    the Z planes (``geometry.split_at``; empty results are dropped). Each cell's material is then
    split into bodies (``geometry.bodies``: voids stay with their body), bodies under
    ``MIN_BODY_VOLUME`` are dropped, and the rest are ordered by (bbox min z, min y, min x,
    larger volume first); remaining ties keep ``decompose()`` order, which is deterministic.

    Args:
        body: The normalized body, mm, cutting frame.
        layout: The grid.

    Returns:
        The pieces in piece order, without faces yet. IDs per §4.3: ``X{i}-Y{j}-Z{k}``, plus
        ``-a``, ``-b``, … (``suffix``) when the cell holds several bodies.
    """
    pieces: list[Piece] = []
    for index, material in _cells(body, layout):
        found = [part for part in geometry.bodies(material) if part.volume() >= MIN_BODY_VOLUME]
        found.sort(key=_body_order)
        for position, part in enumerate(found):
            pieces.append(
                Piece(
                    id=piece_id(index, position, len(found)),
                    grid_index=index,
                    body=part,
                    face_ids=[],
                    merged_from=[],
                )
            )
    return pieces


def piece_id(index: CellIndex, position: int = 0, count: int = 1) -> str:
    """Return a piece's ID (§4.3).

    Args:
        index: The piece's cell.
        position: Its position among the cell's bodies, from 0.
        count: How many bodies the cell holds; with one, there is no suffix.

    Returns:
        ``X{i}-Y{j}-Z{k}``, plus ``-`` and ``suffix(position)`` when ``count`` > 1.
    """
    i, j, k = index
    base = f"X{i}-Y{j}-Z{k}"
    return base if count == 1 else f"{base}-{suffix(position)}"


def suffix(position: int) -> str:
    """Return the letters of a body's position in its cell: a … z, then aa, ab, …, zz, aaa.

    Bijective base 26, so a cell with more than 26 bodies still gets distinct suffixes (PLAN.md
    Appendix E, r7).

    Args:
        position: 0-based position.

    Returns:
        The suffix, lower-case ASCII letters.
    """
    letters = ""
    number = position + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = string.ascii_lowercase[remainder] + letters
    return letters


def _cells(body: Manifold, layout: Grid) -> list[tuple[CellIndex, Manifold]]:
    """The material of each non-empty cell, in cell order (X planes, then Y, then Z)."""
    cells: list[tuple[CellIndex, Manifold]] = []
    for i, slab in enumerate(_slabs(body, 0, layout.planes[0])):
        if slab.is_empty():
            continue
        for j, column in enumerate(_slabs(slab, 1, layout.planes[1])):
            if column.is_empty():
                continue
            for k, cell in enumerate(_slabs(column, 2, layout.planes[2])):
                if not cell.is_empty():
                    cells.append(((i, j, k), cell))
    return cells


def _slabs(body: Manifold, axis: Axis, planes: Sequence[Plane]) -> list[Manifold]:
    """The parts of ``body`` between consecutive planes of one axis, in offset order."""
    slabs: list[Manifold] = []
    rest = body
    for plane in planes:
        below, rest = geometry.split_at(rest, axis, plane.offset)
        slabs.append(below)
    slabs.append(rest)
    return slabs


def _body_order(body: Manifold) -> tuple[float, float, float, float]:
    box = body.bounding_box()
    return (box[2], box[1], box[0], -body.volume())


# --- cut faces (Phase 4, task 5) --------------------------------------------------------------


def cut_faces(
    body: Manifold, layout: Grid, pieces: Sequence[Piece], eps: float
) -> tuple[list[Piece], list[CutFace]]:
    """Find the cut faces: one per connected contact region between two pieces.

    For every plane, the region is ``geometry.cut_region`` of the normalized body (ADR-0002),
    clipped to each pair of cells adjacent across the plane. Each connected polygon's polylabel
    point p decides its pieces: the neg piece is the neg cell's piece whose section at
    ``offset − PIECE_PROBE_DEPTH`` contains p, the pos piece likewise at ``+`` (retried at
    ``PIECE_PROBE_DEPTH_RETRY``). A polygon with no piece on a side is too thin for a connector
    anyway: it is skipped and logged at debug level.

    Args:
        body: The normalized body, mm, cutting frame.
        layout: The grid.
        pieces: The pieces from ``split_cells``.
        eps: ε, ``advanced.section_epsilon``, mm.

    Returns:
        The pieces with their ``face_ids``, and the faces in face order: by plane (X planes
        first, by index), then neg cell (cell order), then polylabel point (u, v). IDs per
        §4.3, ``#2``, ``#3``, … in that order for one pair of pieces.
    """
    by_cell: dict[CellIndex, list[Piece]] = {}
    for piece in pieces:
        by_cell.setdefault(piece.grid_index, []).append(piece)
    faces: list[CutFace] = []
    for axis in _AXES:
        for plane in layout.planes[axis]:
            faces.extend(_plane_faces(body, layout, plane, by_cell, eps))
    owned: dict[str, list[str]] = {piece.id: [] for piece in pieces}
    for face in faces:
        owned[face.piece_neg].append(face.id)
        owned[face.piece_pos].append(face.id)
    return [replace(piece, face_ids=owned[piece.id]) for piece in pieces], faces


def _plane_faces(
    body: Manifold,
    layout: Grid,
    plane: Plane,
    by_cell: dict[CellIndex, list[Piece]],
    eps: float,
) -> list[CutFace]:
    region = geometry.cut_region(body, plane, eps)
    if not region:
        return []
    axis = plane.axis
    sections: dict[tuple[str, float], MultiPolygon] = {}  # piece sections, cached per plane
    faces: list[CutFace] = []
    for neg_index, pos_index in grid.cell_pairs(layout, plane):  # as nudging scores them
        polygons = geometry.clip_to_cells(
            region, axis, grid.cell_bounds(layout, neg_index), grid.cell_bounds(layout, pos_index)
        )
        repeats: dict[tuple[str, str], int] = {}
        for polygon in polygons:
            u, v = geometry.polylabel_point(polygon)
            neg = _piece_at(by_cell.get(neg_index, []), plane, Point(u, v), -1.0, sections)
            pos = _piece_at(by_cell.get(pos_index, []), plane, Point(u, v), 1.0, sections)
            if neg is None or pos is None:
                LOGGER.debug(
                    "plane %s = %.6g: a %.6g mm^2 region at (u, v) = (%.6g, %.6g) has no piece "
                    "on its %s side; skipped (too thin for a connector)",
                    _AXIS_NAMES[axis],
                    plane.offset,
                    polygon.area,
                    u,
                    v,
                    "neg" if neg is None else "pos",
                )
                continue
            pair = (neg.id, pos.id)
            repeats[pair] = repeats.get(pair, 0) + 1
            number = repeats[pair]
            faces.append(
                CutFace(
                    id=f"{neg.id}~{pos.id}" + (f"#{number}" if number > 1 else ""),
                    plane=plane,
                    piece_neg=neg.id,
                    piece_pos=pos.id,
                    region=polygon,
                )
            )
    return faces


def _piece_at(
    candidates: Sequence[Piece],
    plane: Plane,
    point: Point,
    side: float,
    sections: dict[tuple[str, float], MultiPolygon],
) -> Piece | None:
    """The candidate whose section just off the plane on ``side`` (−1 or +1) contains point."""
    for depth in (PIECE_PROBE_DEPTH, PIECE_PROBE_DEPTH_RETRY):
        offset = plane.offset + side * depth
        for piece in candidates:
            key = (piece.id, offset)
            if key not in sections:
                sections[key] = geometry.section(piece.body, plane.axis, offset)
            if sections[key].contains(point):
                return piece
    return None


# --- small-piece merge (Phase 4, task 6; ADR-0012) --------------------------------------------


def merge_small_pieces(
    body: Manifold,
    layout: Grid,
    pieces: Sequence[Piece],
    faces: Sequence[CutFace],
    small_volume: float,
) -> tuple[list[Piece], list[CutFace], tuple[Diagnostic, ...]]:
    """Merge each small piece into its neighbour when that is safe (ADR-0012).

    Pieces with a volume under ``small_volume`` are taken in piece order. A small piece S is
    merged into its neighbour P only if all of these hold, otherwise it gets W004:

    - S shares cut faces with exactly one piece P (with none, it is a separate body: W008
      comes from ``separate_bodies``);
    - S hasn't absorbed a piece itself: it would then span two cells, and the footprint guard
      is defined for one (PLAN.md Appendix E, r7);
    - the bounding box of P and S together fits U (``grid.fits``, peg-adjusted U from the grid);
    - footprint guard: no other piece of S's cell overlaps S's shadow along the axis of the
      shared faces, grown by ``MERGE_MARGIN``, by more than ``AREA_TOLERANCE`` (every assembly
      step stays one straight move; proof sketch in docs/ALGORITHMS.md);
    - the merged piece can be cut cleanly from the normalized body (``_cut_merged``).

    A merge (W005) replaces P's body, drops the faces between P and S, and records S in
    ``P.merged_from``; P keeps its ID.

    Args:
        body: The normalized body, mm, cutting frame.
        layout: The grid (U, cell bounds).
        pieces: Pieces with their faces, in piece order.
        faces: Their cut faces, in face order.
        small_volume: V_small, ``advanced.small_piece_volume``, mm³ (0 disables merging).

    Returns:
        The remaining pieces and faces, in the same orders, and the W004 and W005 diagnostics
        in piece order.
    """
    original = {piece.id: piece for piece in pieces}
    current = dict(original)
    absorbed: dict[str, list[Piece]] = {}  # absorber ID -> the original pieces it took in
    live = list(faces)
    diagnostics: list[Diagnostic] = []
    for piece in pieces:
        small = current.get(piece.id)
        if small is None:
            continue
        volume = small.body.volume()
        if volume >= small_volume:
            continue
        shared = [face for face in live if small.id in (face.piece_neg, face.piece_pos)]
        if not shared:
            continue  # a separate body (W008)
        neighbours = list(
            dict.fromkeys(f.piece_pos if f.piece_neg == small.id else f.piece_neg for f in shared)
        )
        label = f"small piece {small.id} ({volume:.6g} mm^3) left on its own"
        if small.merged_from:
            message = f"{label}: it already absorbed {', '.join(small.merged_from)}"
            diagnostics.append(diagnostic("W004", message + ", so it spans two cells", (small.id,)))
            continue
        if len(neighbours) > 1:
            message = f"{label}: it touches {len(neighbours)} pieces"
            diagnostics.append(diagnostic("W004", message, (small.id, *neighbours)))
            continue
        target = current[neighbours[0]]
        axis = shared[0].plane.axis
        problem = _fit_problem(small, target, layout) or _footprint_problem(
            small, target, axis, original.values()
        )
        if problem is None:
            taken = [*absorbed.get(target.id, []), small]
            merged = _cut_merged(body, layout, original[target.id], taken)
            if merged is not None:
                absorbed[target.id] = taken
                dropped = {face.id for face in shared}
                live = [face for face in live if face.id not in dropped]
                current[target.id] = replace(
                    target,
                    body=merged,
                    face_ids=[face_id for face_id in target.face_ids if face_id not in dropped],
                    merged_from=[*target.merged_from, small.id],
                )
                del current[small.id]
                message = f"small piece {small.id} ({volume:.6g} mm^3) merged into {target.id}"
                diagnostics.append(diagnostic("W005", message, (small.id, target.id)))
                continue
            problem = (
                f"merged with {target.id} it couldn't be cut cleanly from the model",
                (small.id, target.id),
            )
        reason, refs = problem
        diagnostics.append(diagnostic("W004", f"{label}: {reason}", refs))
    return list(current.values()), live, tuple(diagnostics)


def _fit_problem(small: Piece, target: Piece, layout: Grid) -> tuple[str, tuple[str, ...]] | None:
    """Why P and S together wouldn't fit U, or None."""
    first, second = target.body.bounding_box(), small.body.bounding_box()
    for axis in _AXES:
        size = max(first[axis + 3], second[axis + 3]) - min(first[axis], second[axis])
        usable = layout.usable[axis]
        if not grid.fits(size, usable):
            reason = (
                f"merged with {target.id} it would be {size:.6g} mm along {_AXIS_NAMES[axis]}, "
                f"over U = {usable:g} mm"
            )
            return reason, (small.id, target.id)
    return None


def _footprint_problem(
    small: Piece, target: Piece, axis: Axis, originals: Iterable[Piece]
) -> tuple[str, tuple[str, ...]] | None:
    """The footprint guard: which other pieces of S's cell lie in S's shadow along ``axis``.

    The shadow is grown by ``MERGE_MARGIN``, the footprint ``_cut_merged`` cuts with, so the
    merged piece can't take a sliver of a piece that comes closer than that. The original
    pieces are checked, so a piece of the cell that was merged elsewhere still counts: its
    material is still there.
    """
    footprint = geometry.grow(geometry.shadow(small.body, axis), MERGE_MARGIN)
    blockers = [
        other.id
        for other in originals
        if other.grid_index == small.grid_index
        and other.id != small.id
        and geometry.overlap_area(footprint, geometry.shadow(other.body, axis)) > AREA_TOLERANCE
    ]
    if not blockers:
        return None
    verb = "lies" if len(blockers) == 1 else "lie"
    reason = (
        f"{', '.join(blockers)} of its cell {verb} in its footprint along {_AXIS_NAMES[axis]} "
        f"(or within {MERGE_MARGIN:g} mm of it), so the merged piece couldn't be assembled in "
        "one straight move"
    )
    return reason, (small.id, target.id, *blockers)


def _cut_merged(
    body: Manifold, layout: Grid, owner: Piece, absorbed: Sequence[Piece]
) -> Manifold | None:
    """Cut the owner with its absorbed pieces from the normalized body, in one go.

    The body is clipped (``geometry.clip``) to the owner's cell joined to one prism per
    absorbed piece: its shadow grown by ``MERGE_MARGIN`` and kept within its own cell, from
    ``MERGE_MARGIN`` inside the owner's cell to the far side of the absorbed piece's cell.
    Inside a prism the plane is never cut, so nothing has to be glued back (a union of two
    split halves can keep a face where the plane passes through mesh vertices;
    docs/LIBRARY_NOTES.md). Cells are grown by ``CUTTER_PAD`` where they reach the model's
    bounding box, so the cutter only cuts at the planes. The footprint guard, checked on the
    same grown shadow, keeps the other pieces of each absorbed piece's cell out of its prism,
    and keeping each prism in its own cell keeps every other cell out.

    Returns:
        The body holding the newest absorbed piece, if its volume is the owner's plus the
        absorbed pieces' within ``MERGE_VOLUME_TOLERANCE``; otherwise None (something else
        was caught with them).
    """
    parts = [geometry.box_solid(*_outer_box(layout, owner.grid_index))]
    own_low, own_high = grid.cell_bounds(layout, owner.grid_index)
    for piece in absorbed:
        axis = next(a for a in _AXES if piece.grid_index[a] != owner.grid_index[a])
        cell_low, cell_high = _outer_box(layout, piece.grid_index)
        footprint = geometry.grow(geometry.shadow(piece.body, axis), MERGE_MARGIN)
        footprint = footprint ^ geometry.rectangle(axis, cell_low, cell_high)
        if piece.grid_index[axis] < owner.grid_index[axis]:  # the absorbed piece is below
            start, end = cell_low[axis], own_low[axis] + MERGE_MARGIN
        else:
            start, end = own_high[axis] - MERGE_MARGIN, cell_high[axis]
        parts.append(geometry.prism(footprint, axis, start, end))
    carved = geometry.clip(body, geometry.union_all(parts))
    newest = absorbed[-1].body
    holder = max(geometry.bodies(carved), key=lambda part: _overlap(part, newest), default=None)
    if holder is None or _overlap(holder, newest) <= 0.0:
        return None
    expected = owner.body.volume() + sum(piece.body.volume() for piece in absorbed)
    if abs(holder.volume() - expected) > MERGE_VOLUME_TOLERANCE * expected:
        return None
    return holder


def _outer_box(layout: Grid, index: CellIndex) -> tuple[geometry.Point3, geometry.Point3]:
    """A cell's box, grown by ``CUTTER_PAD`` on the sides that lie on the model's bounding box."""
    low, high = grid.cell_bounds(layout, index)
    grown_low = [value - CUTTER_PAD if value <= 0.0 else value for value in low]
    grown_high = [
        value + CUTTER_PAD if value >= layout.extent[axis] else value
        for axis, value in enumerate(high)
    ]
    return _point(grown_low), _point(grown_high)


def _overlap(first: Manifold, second: Manifold) -> float:
    """The volume two solids share, mm³ (0 when their bounding boxes are apart)."""
    a, b = first.bounding_box(), second.bounding_box()
    if any(a[axis] > b[axis + 3] or b[axis] > a[axis + 3] for axis in _AXES):
        return 0.0
    return float((first ^ second).volume())


def separate_bodies(pieces: Sequence[Piece], layout: Grid) -> tuple[Diagnostic, ...]:
    """W008 for every piece without a cut face, unless the grid is a single cell.

    With a single cell, W012 already says nothing was cut (PLAN.md Appendix E, r7).

    Args:
        pieces: The final pieces, in piece order.
        layout: The grid.

    Returns:
        One W008 per piece without a face, in piece order.
    """
    if math.prod(layout.counts) == 1:
        return ()
    return tuple(
        diagnostic(
            "W008",
            f"piece {piece.id} has no cut face (a separate body): it gets no connector and no "
            "label",
            (piece.id,),
        )
        for piece in pieces
        if not piece.face_ids
    )


# --- validation (Phase 4, task 7) -------------------------------------------------------------


def check_pieces(pieces: Sequence[Piece], reference_volume: float) -> None:
    """Check I1 and I3 (PLAN.md §5.3).

    Args:
        pieces: The pieces, before tools are applied.
        reference_volume: ``RepairReport.reference_volume``, mm³.

    Raises:
        AssertionError: A piece isn't valid or has no volume (I1), or the volumes don't add
            up to the reference within ``VOLUME_TOLERANCE`` (I3). Either is a bug.
    """
    for piece in pieces:
        status, volume = piece.body.status(), piece.body.volume()
        if status != Error.NoError or not volume > 0:
            raise AssertionError(f"I1: piece {piece.id} has status {status}, volume {volume}")
    total = math.fsum(piece.body.volume() for piece in pieces)
    if not abs(total - reference_volume) <= VOLUME_TOLERANCE * reference_volume:
        raise AssertionError(
            f"I3: the pieces add up to {total:.10g} mm^3, not the reference volume "
            f"{reference_volume:.10g} mm^3"
        )


def _point(values: Sequence[float]) -> geometry.Point3:
    x, y, z = values
    return (x, y, z)
