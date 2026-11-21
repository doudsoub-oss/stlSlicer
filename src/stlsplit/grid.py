"""Orientation, cutting frame, even grid and plane nudging.

Third stage of the pipeline (PLAN.md §5.1), after ``repair.prepare`` and before
``cutting.cut``. ``orient`` picks the proper rotation that needs the fewest cells
(auto-orient, ADR-0008) and moves the model into the cutting frame, its bounding-box minimum
at the origin (§4.2). ``even_grid`` then splits each axis into the fewest equal cells that fit
the usable volume U, and ``nudge`` moves each plane within a small window to a position whose
cut regions have room for connectors and no tiny islands (ADR-0003).

Pure: geometry and numbers in, geometry and numbers out. U comes from ``config.derived``
(bed − 2·margin, minus L_max/2 in peg mode; ADR-0005); it is never recomputed here.

Guarantees:
- Every rotation is a signed permutation with det = +1: the model is never mirrored.
- The oriented body's bounding box starts exactly at (0, 0, 0).
- Every cell fits U: its size along axis a is at most ``U_a · (1 + GRID_TOLERANCE)``, checked
  by ``fits`` in the same arithmetic as ``cell_count``, before and after nudging.
- Each axis has the fewest cells that fit: n − 1 even cells would each be larger than U.
- Nudging moves a plane by a whole number of steps within the window, keeps it strictly
  between its neighbours, and leaves it where it is unless moving gains something.
"""

import itertools
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import NamedTuple

import numpy as np
from manifold3d import Manifold
from shapely.geometry import Polygon

from stlsplit import config, connectors, geometry
from stlsplit.config import GRID_TOLERANCE, MAX_GRID_CELLS, Config
from stlsplit.errors import InputError, diagnostic
from stlsplit.models import Axis, Diagnostic, Grid, Orientation, Plane

LOGGER = logging.getLogger(__name__)

Vec3 = tuple[float, float, float]
"""A value per cutting-frame axis (X, Y, Z), mm."""

CellIndex = tuple[int, int, int]
"""A cell (i, j, k), 0-based along X, Y, Z (§4.3)."""

_AXES: tuple[Axis, Axis, Axis] = (0, 1, 2)
_AXIS_NAMES = "XYZ"


class Rotation(NamedTuple):
    """One candidate rotation of auto-orient.

    Attributes:
        name: Short ASCII name, used in logs, the dry run and ``Orientation.name``.
        matrix: R, rows = cutting axes, columns = input axes: ``x_cut = R · x_in``. A signed
            permutation with det = +1.
    """

    name: str
    matrix: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]


ROTATIONS: tuple[Rotation, ...] = (
    Rotation("identity", ((1, 0, 0), (0, 1, 0), (0, 0, 1))),
    Rotation("90 deg about Z", ((0, -1, 0), (1, 0, 0), (0, 0, 1))),
    Rotation("90 deg about X", ((1, 0, 0), (0, 0, -1), (0, 1, 0))),
    Rotation("90 deg about Y", ((0, 0, 1), (0, 1, 0), (-1, 0, 0))),
    Rotation("120 deg about (1,1,1)", ((0, 0, 1), (1, 0, 0), (0, 1, 0))),
    Rotation("240 deg about (1,1,1)", ((0, 1, 0), (0, 0, 1), (1, 0, 0))),
)
"""The six axis orders as proper rotations, in tie-break order (PLAN.md Phase 3, ADR-0008).

Keeping the model as it is comes first, then the quarter turn that keeps its Z up, then the
other quarter turns, then the two turns about the diagonal. An odd axis order swaps two axes;
it is the +90° turn about the third axis, which negates one of the swapped ones so that
det = +1. The even orders are the identity and the two cyclic permutations.
"""


def cell_count(extent: float, usable: float) -> int:
    """Return the fewest equal cells along one axis that fit U.

    ``n = max(1, ceil(extent / U − GRID_TOLERANCE))``: the slack keeps float noise in an
    extent that is an exact multiple of U from adding a cell (PLAN.md Phase 3, task 4).

    Args:
        extent: Model size along the axis, mm.
        usable: U along the axis, mm (> 0).

    Returns:
        The number of cells, at least 1.
    """
    return max(1, math.ceil(_ratio(extent, usable)))


def fits(size: float, usable: float) -> bool:
    """Return whether a cell of this size fits U: ``size / U − GRID_TOLERANCE ≤ 1``.

    That is ``size ≤ U · (1 + GRID_TOLERANCE)``, evaluated with the expression
    :func:`cell_count` uses, so a size it counts as one cell always fits. Written as
    ``size <= U * (1 + tol)``, the two could round differently for one float at the edge
    (230.00000023000004 on U = 230: one cell, yet "over U"; PLAN.md Appendix E, r6).

    Args:
        size: Cell size along one axis, mm.
        usable: U along that axis, mm (> 0).

    Returns:
        True if the cell fits.
    """
    return _ratio(size, usable) <= 1


def _ratio(size: float, usable: float) -> float:
    """``size / U − GRID_TOLERANCE``: the one expression behind both the count and the fit."""
    return size / usable - GRID_TOLERANCE


def rotated_extent(extent: Vec3, rotation: Rotation) -> Vec3:
    """Return the bounding-box size of a model after ``rotation``, without moving any mesh.

    A signed permutation moves each size to another axis unchanged, so this is exact.

    Args:
        extent: Model size per input axis, mm.
        rotation: The rotation.

    Returns:
        The size per cutting-frame axis, mm.
    """
    x, y, z = (extent[_source_axis(row)] for row in rotation.matrix)
    return (x, y, z)


def choose_rotation(extent: Vec3, usable: Vec3, auto_orient: bool) -> Rotation:
    """Pick the rotation that needs the fewest cells (PLAN.md Phase 3, task 2; ADR-0008).

    The cell count of a rotation is Π ``cell_count(extent_i, U_i)`` of its rotated extent.

    Args:
        extent: Model size per input axis, mm.
        usable: U per cutting-frame axis, mm.
        auto_orient: ``model.auto_orient``; False always gives the identity.

    Returns:
        The rotation with the lowest count; on a tie, the first one in ``ROTATIONS``.
    """
    if not auto_orient:
        return ROTATIONS[0]
    # min() keeps the first of equal keys, which is the tie-break order of ROTATIONS.
    return min(
        ROTATIONS, key=lambda rotation: _total_cells(rotated_extent(extent, rotation), usable)
    )


def extent(body: Manifold) -> Vec3:
    """Return the size of a body's bounding box per axis, mm, in the body's frame.

    Args:
        body: Solid, mm.

    Returns:
        (size along X, Y, Z).
    """
    box = body.bounding_box()
    return (box[3] - box[0], box[4] - box[1], box[5] - box[2])


def to_cutting_frame(body: Manifold, rotation: Rotation) -> tuple[Manifold, Orientation]:
    """Rotate a body, then translate its bounding-box minimum to the origin (§4.2).

    The rotation is exact (a signed permutation) and the translation puts the minimum
    exactly at 0 (docs/LIBRARY_NOTES.md), so plane offsets are measured from 0.

    Args:
        body: Solid, mm, input frame.
        rotation: One of ``ROTATIONS``.

    Returns:
        The body in the cutting frame, and the orientation holding the 4×4 input → cutting
        transform ``[[R, t], [0, 0, 0, 1]]``.

    Raises:
        AssertionError: ``rotation`` isn't a proper rotation (det ≠ +1), a bug.
    """
    matrix = np.zeros((3, 4))
    matrix[:, :3] = rotation.matrix
    if round(float(np.linalg.det(matrix[:, :3]))) != 1:
        raise AssertionError(f"rotation {rotation.name} is not proper (det != +1)")
    rotated = body.transform(matrix)
    matrix[:, 3] = [-value for value in rotated.bounding_box()[:3]]
    oriented = rotated.translate(tuple(matrix[:, 3]))
    rows = (*(_row(values) for values in matrix.tolist()), (0.0, 0.0, 0.0, 1.0))
    return oriented, Orientation(name=rotation.name, input_to_cutting=rows)


def orient(body: Manifold, cfg: Config) -> tuple[Manifold, Orientation]:
    """Choose the rotation with the fewest cells and move the body into the cutting frame.

    Args:
        body: The repaired solid, mm, input frame.
        cfg: The configuration (``model.auto_orient``; U from ``config.derived``).

    Returns:
        The body in the cutting frame (bounding-box minimum at the origin) and its
        orientation.
    """
    usable = config.derived(cfg).usable
    rotation = choose_rotation(extent(body), usable, cfg.model.auto_orient)
    return to_cutting_frame(body, rotation)


def check_cell_limit(extent: Vec3, usable: Vec3) -> None:
    """Refuse a grid of more than ``MAX_GRID_CELLS`` cells, before anything is built (§7.5).

    Args:
        extent: Model size per axis in the cutting frame, mm.
        usable: U per axis, mm (``config.derived(cfg).usable``).

    Raises:
        InputError: The model needs more cells than the limit, usually a wrong ``--scale``.
    """
    counts = [cell_count(e, u) for e, u in zip(extent, usable, strict=True)]
    total = math.prod(counts)
    if total > MAX_GRID_CELLS:
        raise InputError(
            f"the model needs {total} cells ({' x '.join(str(n) for n in counts)}) on this bed, "
            f"over the limit of {MAX_GRID_CELLS}: check --scale (STL has no units and is read "
            "as mm) or use a larger --bed"
        )


def even_grid(extent: Vec3, usable: Vec3) -> tuple[Grid, tuple[Diagnostic, ...]]:
    """Split each axis into the fewest equal cells that fit U (PLAN.md Phase 3, ADR-0003).

    Along axis a, ``n_a = cell_count(extent_a, U_a)`` and the planes sit at
    ``k · extent_a / n_a`` for k = 1 … n_a − 1. Equal cells give pieces of similar size
    instead of one full bed and a sliver.

    Args:
        extent: Model size per axis in the cutting frame, mm (the bounding box starts at 0).
        usable: U per axis, mm (``config.derived(cfg).usable``).

    Returns:
        The grid, and W012 when the model fits in one cell (nothing to cut; the pipeline
        continues with one piece).

    Raises:
        AssertionError: A cell doesn't fit U, a bug.
    """
    nx, ny, nz = (cell_count(e, u) for e, u in zip(extent, usable, strict=True))
    layout = Grid(
        usable=usable,
        counts=(nx, ny, nz),
        planes=(
            _even_planes(0, extent[0], nx),
            _even_planes(1, extent[1], ny),
            _even_planes(2, extent[2], nz),
        ),
        extent=extent,
    )
    # Task 5: every cell fits U. One cell: the count's own expression, so never over. n ≥ 2:
    # the slack leaves a margin of GRID_TOLERANCE · (1 − 1/n) ≥ 5e-10 for the rounding of
    # k · extent / n.
    check_fits(layout)
    if layout.counts != (1, 1, 1):
        return layout, ()
    size = " x ".join(f"{value:g}" for value in usable)
    return layout, (
        diagnostic("W012", f"the model already fits the usable volume ({size} mm): nothing to cut"),
    )


def check_fits(layout: Grid) -> None:
    """Check that every axis' planes increase strictly and every cell fits U (``fits``).

    Args:
        layout: The grid, even or nudged.

    Raises:
        AssertionError: A cell has no size or doesn't fit U, a bug (exit 4).
    """
    for axis in _AXES:
        bounds = axis_bounds(layout, axis)
        sizes = [high - low for low, high in itertools.pairwise(bounds)]
        if min(sizes) <= 0:
            raise AssertionError(f"the cell bounds along axis {axis} don't increase: {bounds}")
        largest = max(sizes)
        if not fits(largest, layout.usable[axis]):
            raise AssertionError(
                f"a cell is {largest} mm along axis {axis}, over U = {layout.usable}"
            )


# --- plane nudging (PLAN.md Phase 6, ADR-0003) ------------------------------------------------


class PlaneScore(NamedTuple):
    """The score of a plane position: its cut regions, compared as a tuple (lower is better).

    Attributes:
        no_room: How many regions have an empty safe region (``connectors.safe_region``): no
            connector can go there (W001).
        islands: How many regions are tiny islands: area under ``derived(cfg).island_area``
            (4 · π · (d/2)², 78.5 mm² by default).
    """

    no_room: int
    islands: int


_PERFECT = PlaneScore(no_room=0, islands=0)


def nudge(body: Manifold, layout: Grid, cfg: Config) -> Grid:
    """Move each plane within the nudge window to a better position (PLAN.md Phase 6).

    Planes are taken in axis order X, Y, Z, then by increasing offset, one after the other.
    Each is scored on the grid as the planes before it left it, so a move changes the slack of
    the planes after it (task 3). ``candidate_shifts`` gives the moves that keep both
    neighbouring cells within U, ``plane_regions`` and ``score_regions`` score each position,
    and ``choose_shift`` keeps the one with the lowest (no room, tiny islands, |δ|, δ): a plane
    stays where it is unless moving gains something (ADR-0003).

    There is deliberately no rule keeping planes away from mesh vertices or model faces:
    manifold3d splits through vertices, and ``geometry.cut_region`` handles a model face lying
    on the plane (ADR-0002). A "no vertex within 0.01 mm" rule never terminates on a dense mesh
    (task 5).

    Args:
        body: The normalized body, mm, cutting frame (from ``orient``).
        layout: The grid (from ``even_grid``).
        cfg: The configuration: ``advanced.nudge_step`` (δ_n), ``derived(cfg).nudge_steps``
            (W_n / δ_n, at most 100; 0 turns nudging off), ``advanced.section_epsilon`` (ε),
            and what the safe region and the island area derive from.

    Returns:
        The grid with the moved planes, in the same order with the same indices; U, the counts
        and the extent are unchanged. ``layout`` itself when no plane moves.

    Raises:
        AssertionError: A cell doesn't fit U afterwards (``check_fits``), a bug.
    """
    steps = config.derived(cfg).nudge_steps
    if steps == 0:  # nudge_window = 0, or smaller than one step
        return layout
    current = layout
    for axis in _AXES:
        for index in range(len(layout.planes[axis])):
            current = _nudge_plane(body, current, axis, index, steps, cfg)
    check_fits(current)  # task 4
    return current


def candidate_shifts(
    low: float, offset: float, high: float, usable: float, steps: int, step: float
) -> tuple[float, ...]:
    """Return the moves a plane may make: the multiples of the step within the window and its slack.

    A move δ = j · step, for an integer j with |j| ≤ ``steps`` (so the steps don't add up
    rounding errors, and the window is counted in steps: ``derived(cfg).nudge_steps``), is
    kept when:

    - the plane stays strictly between its neighbours (PLAN.md Appendix E, r9);
    - both cells it bounds still fit U (``fits``, the count's own arithmetic).

    Those two are the plane's slack on each side, so this is PLAN.md Phase 6's
    window = min(W_n, slack), side by side.

    Args:
        low: The bound below the plane: the previous plane's offset, or 0, mm.
        offset: The plane's offset, mm.
        high: The bound above: the next plane's offset, or the extent, mm.
        usable: U along the plane's axis, mm.
        steps: How many steps the window holds on each side, ``derived(cfg).nudge_steps``
            (at most ``MAX_NUDGE_STEPS``, 100, so at most 201 moves).
        step: δ_n, ``advanced.nudge_step``, mm (> 0).

    Returns:
        The moves, mm, in increasing order. 0 is among them when the plane's two cells fit.
    """
    shifts: list[float] = []
    for j in range(-steps, steps + 1):
        shift = j * step
        position = offset + shift
        if low < position < high and fits(position - low, usable) and fits(high - position, usable):
            shifts.append(shift)
    return tuple(shifts)


def choose_shift(shifts: Iterable[float], score: Callable[[float], PlaneScore]) -> float:
    """Return the move with the lowest (no room, tiny islands, |δ|, δ), compared in that order.

    The last two keys keep a plane where it is when moving gains nothing, and make the choice
    unique, so it doesn't depend on the order of ``shifts`` (task 2). Moves are scored from
    the smallest |δ| outwards (then by δ), and scoring stops at the first one that scores
    (0, 0): no move after it can beat it, so this is the same as scoring every move.

    Args:
        shifts: The candidate moves, mm, in any order (``candidate_shifts``).
        score: The score of the plane moved by a shift.

    Returns:
        The chosen move, mm.

    Raises:
        ValueError: ``shifts`` is empty.
    """
    best: tuple[int, int, float, float] | None = None
    for shift in sorted(shifts, key=lambda value: (abs(value), value)):
        result = score(shift)
        key = (result.no_room, result.islands, abs(shift), shift)
        if best is None or key < best:
            best = key
        if result == _PERFECT:
            break
    if best is None:
        raise ValueError("no candidate shift to choose from")
    return best[3]


def plane_regions(body: Manifold, layout: Grid, plane: Plane, eps: float) -> list[Polygon]:
    """Return a plane's cut regions, clipped to each pair of cells across it, as cutting does.

    ``geometry.cut_region`` of the body (ADR-0002), then ``geometry.clip_to_cells`` for every
    pair from ``cell_pairs``: the polygons Phase 4 turns into cut faces, before it looks for
    their pieces. The rectangles come from the planes of the other two axes, not from the
    plane's own offset, so ``plane`` may be a moved copy of one of ``layout``'s planes.

    The polygons aren't sorted by polylabel point: a score only counts them, and polylabel
    took 97 % of the nudging time on the hollow sphere (4.9 s for 3 planes).

    Args:
        body: The normalized body, mm, cutting frame.
        layout: The grid.
        plane: The plane, possibly at a candidate offset.
        eps: ε, ``advanced.section_epsilon``, mm.

    Returns:
        Polygons in plane-local (u, v), mm, pair by pair in ``cell_pairs`` order; within a
        pair in no particular (but deterministic) order.
    """
    region = geometry.cut_region(body, plane, eps, ordered=False)
    if not region:
        return []
    return [
        polygon
        for neg, pos in cell_pairs(layout, plane)
        for polygon in geometry.clip_to_cells(
            region, plane.axis, cell_bounds(layout, neg), cell_bounds(layout, pos), ordered=False
        )
    ]


def score_regions(regions: Iterable[Polygon], cfg: Config) -> PlaneScore:
    """Score a plane position by its cut regions (PLAN.md Phase 6, task 2).

    Args:
        regions: The position's regions, plane-local (u, v), mm (``plane_regions``).
        cfg: The configuration (the safe-region inset and the island area derive from it).

    Returns:
        How many regions have no room for a connector, and how many are tiny islands.
    """
    island = config.derived(cfg).island_area
    no_room = islands = 0
    for region in regions:
        if connectors.safe_region(region, cfg).is_empty:
            no_room += 1
        if region.area < island:
            islands += 1
    return PlaneScore(no_room=no_room, islands=islands)


def _nudge_plane(
    body: Manifold, layout: Grid, axis: Axis, index: int, steps: int, cfg: Config
) -> Grid:
    """The grid with one plane nudged; ``layout`` itself when the plane stays."""
    plane = layout.planes[axis][index]
    bounds = axis_bounds(layout, axis)
    shifts = candidate_shifts(
        bounds[index],
        plane.offset,
        bounds[index + 2],
        layout.usable[axis],
        steps,
        cfg.advanced.nudge_step,
    )
    if len(shifts) < 2:  # nowhere to go: the slack is under one step
        return layout
    scores: dict[float, PlaneScore] = {}

    def score(shift: float) -> PlaneScore:
        moved = replace(plane, offset=plane.offset + shift)
        scores[shift] = score_regions(
            plane_regions(body, layout, moved, cfg.advanced.section_epsilon), cfg
        )
        return scores[shift]

    shift = choose_shift(shifts, score)
    name = f"plane {_AXIS_NAMES[axis]}{index} = {plane.offset:.6g}"
    before, after = scores[0.0], scores[shift]
    if shift == 0.0:
        LOGGER.debug(
            "%s stays (no room %d, tiny islands %d; %d of %d positions scored)",
            name,
            before.no_room,
            before.islands,
            len(scores),
            len(shifts),
        )
        return layout
    moved = replace(plane, offset=plane.offset + shift)
    LOGGER.debug(
        "%s moves by %+.6g mm to %.6g (no room %d -> %d, tiny islands %d -> %d)",
        name,
        shift,
        moved.offset,
        before.no_room,
        after.no_room,
        before.islands,
        after.islands,
    )
    row = list(layout.planes[axis])
    row[index] = moved
    x, y, z = (tuple(row) if a == axis else layout.planes[a] for a in _AXES)
    return replace(layout, planes=(x, y, z))


def cell_pairs(layout: Grid, plane: Plane) -> tuple[tuple[CellIndex, CellIndex], ...]:
    """Return the pairs of cells adjacent across a plane.

    Args:
        layout: The grid.
        plane: One of its planes (or a moved copy: only its axis and index count).

    Returns:
        (neg cell, pos cell) pairs, in cell order of the neg cell (``cell_indices``).
    """
    axis = plane.axis
    pairs: list[tuple[CellIndex, CellIndex]] = []
    for index in cell_indices(layout):
        if index[axis] == plane.index:
            i, j, k = (value + 1 if a == axis else value for a, value in enumerate(index))
            pairs.append((index, (i, j, k)))
    return tuple(pairs)


def axis_bounds(grid: Grid, axis: Axis) -> tuple[float, ...]:
    """Return the cell boundaries along one axis: 0, the plane offsets, then the extent.

    Args:
        grid: The grid.
        axis: The axis.

    Returns:
        ``grid.counts[axis] + 1`` increasing values, mm, cutting frame.
    """
    return (0.0, *(plane.offset for plane in grid.planes[axis]), grid.extent[axis])


def cell_indices(grid: Grid) -> tuple[tuple[int, int, int], ...]:
    """Return every cell index (i, j, k), sorted (i first, then j, then k).

    Args:
        grid: The grid.

    Returns:
        ``Π grid.counts`` indices.
    """
    nx, ny, nz = grid.counts
    return tuple(itertools.product(range(nx), range(ny), range(nz)))


def cell_bounds(grid: Grid, index: tuple[int, int, int]) -> tuple[Vec3, Vec3]:
    """Return the box of one cell.

    Args:
        grid: The grid.
        index: The cell (i, j, k), 0-based along X, Y, Z (§4.3).

    Returns:
        (low corner, high corner), mm, cutting frame.
    """
    bounds = [axis_bounds(grid, axis) for axis in _AXES]
    i, j, k = index
    low = (bounds[0][i], bounds[1][j], bounds[2][k])
    high = (bounds[0][i + 1], bounds[1][j + 1], bounds[2][k + 1])
    return low, high


def _even_planes(axis: Axis, size: float, count: int) -> tuple[Plane, ...]:
    return tuple(Plane(axis=axis, index=k - 1, offset=k * size / count) for k in range(1, count))


def _source_axis(row: tuple[int, int, int]) -> int:
    """The input axis a row of a signed permutation takes."""
    return next(index for index, value in enumerate(row) if value != 0)


def _total_cells(extent: Vec3, usable: Vec3) -> int:
    return math.prod(cell_count(e, u) for e, u in zip(extent, usable, strict=True))


def _row(values: list[float]) -> tuple[float, float, float, float]:
    # + 0.0 turns -0.0 into 0.0, so the matrix prints and serializes the same way every time.
    a, b, c, d = (float(value) + 0.0 for value in values)
    return (a, b, c, d)
