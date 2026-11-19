"""Orientation, cutting frame and even grid.

Third stage of the pipeline (PLAN.md §5.1), after ``repair.prepare``. ``orient`` picks the
proper rotation that needs the fewest cells (auto-orient, ADR-0008) and moves the model into
the cutting frame, its bounding-box minimum at the origin (§4.2). ``even_grid`` then splits
each axis into the fewest equal cells that fit the usable volume U (ADR-0003). Plane nudging
arrives in Phase 6.

Pure: geometry and numbers in, geometry and numbers out. U comes from ``config.derived``
(bed − 2·margin, minus L_max/2 in peg mode; ADR-0005); it is never recomputed here.

Guarantees:
- Every rotation is a signed permutation with det = +1: the model is never mirrored.
- The oriented body's bounding box starts exactly at (0, 0, 0).
- Every cell fits U: its size along axis a is at most ``U_a · (1 + GRID_TOLERANCE)``.
- Each axis has the fewest cells that fit: n − 1 even cells would each be larger than U.
"""

import itertools
import math
from typing import NamedTuple

import numpy as np
from manifold3d import Manifold

from stlsplit import config
from stlsplit.config import GRID_TOLERANCE, Config
from stlsplit.errors import diagnostic
from stlsplit.models import Axis, Diagnostic, Grid, Orientation, Plane

Vec3 = tuple[float, float, float]
"""A value per cutting-frame axis (X, Y, Z), mm."""

_AXES: tuple[Axis, Axis, Axis] = (0, 1, 2)


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
    return max(1, math.ceil(extent / usable - GRID_TOLERANCE))


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
    for axis in _AXES:  # task 5: every cell fits U
        bounds = axis_bounds(layout, axis)
        largest = max(high - low for low, high in itertools.pairwise(bounds))
        if largest > usable[axis] * (1 + GRID_TOLERANCE):
            raise AssertionError(f"a cell is {largest} mm along axis {axis}, over U = {usable}")
    if layout.counts != (1, 1, 1):
        return layout, ()
    size = " x ".join(f"{value:g}" for value in usable)
    return layout, (
        diagnostic("W012", f"the model already fits the usable volume ({size} mm): nothing to cut"),
    )


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
