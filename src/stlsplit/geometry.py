"""Thin wrappers around the geometry libraries: conversions, frames, cylinders, sections, rays.

Used by every geometric stage of the pipeline (PLAN.md §5.1). All solid geometry goes through
manifold3d; trimesh appears here only for conversions (ADR-0001). Every function is pure.

Inputs and outputs are in mm. Unless stated otherwise, solids are in the cutting frame and 2D
data is in plane-local (u, v) coordinates (§4.2, docs/ARCHITECTURE.md "Frames"). The section
helpers (``cut_region`` and friends) arrive in Phase 4.
"""

import math
from collections.abc import Iterable, Sequence

import numpy as np
import trimesh
from manifold3d import CrossSection, FillRule, Manifold, Mesh, OpType
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import Polygon
from shapely.ops import polylabel

from stlsplit.config import POLYLABEL_TOLERANCE
from stlsplit.models import Axis

# Rows of the world -> plane-local rotation per plane axis: local (x, y, z) = world axes
# (§4.2). Each is a cyclic permutation, so det = +1 (ADR-0008).
_LOCAL_AXES: dict[int, tuple[int, int, int]] = {0: (1, 2, 0), 1: (2, 0, 1), 2: (0, 1, 2)}


def to_manifold(mesh: trimesh.Trimesh) -> Manifold:
    """Convert a trimesh mesh to a manifold3d solid.

    Args:
        mesh: Triangle mesh, mm. It should be closed and consistently wound; check the result's
            ``status()``.

    Returns:
        The manifold. ``status()`` is not ``NoError`` when the mesh isn't a valid solid.
    """
    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
    faces = np.ascontiguousarray(mesh.faces, dtype=np.uint32)
    return Manifold(Mesh(vert_properties=vertices, tri_verts=faces))


def to_trimesh(body: Manifold) -> trimesh.Trimesh:
    """Convert a manifold3d solid to a trimesh mesh, for repair and export.

    The arrays returned by ``Manifold.to_mesh()`` are read-only views (docs/LIBRARY_NOTES.md),
    so they are copied.

    Args:
        body: Solid, mm.

    Returns:
        A mesh with float64 vertices, without trimesh's processing (no merge, no reordering).
    """
    mesh = body.to_mesh()
    vertices = np.array(mesh.vert_properties[:, :3], dtype=np.float64)
    faces = np.array(mesh.tri_verts, dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def world_to_local(axis: Axis) -> NDArray[np.float64]:
    """Return the rotation taking cutting-frame coordinates to a plane's local frame.

    After ``body.transform(world_to_local(axis))``, the plane at offset ``o`` is local z = o and
    ``slice(o)`` gives the section in (u, v) (§4.2).

    Args:
        axis: Plane axis, 0 = X, 1 = Y, 2 = Z.

    Returns:
        A 3×4 matrix (no translation) with det(R) = +1, as ``Manifold.transform`` expects.
    """
    matrix = np.zeros((3, 4))
    for local_index, world_index in enumerate(_LOCAL_AXES[axis]):
        matrix[local_index, world_index] = 1.0
    return matrix


def local_to_world(axis: Axis) -> NDArray[np.float64]:
    """Return the rotation taking a plane's local frame back to cutting-frame coordinates.

    The exact inverse of :func:`world_to_local`: the plane at offset ``o`` is local z = o in
    both directions, with z > o on the pos piece's side (§4.2). Tool solids for a plane are
    therefore built around local z = o (e.g. a hole from ``o - h`` to ``o + h``).

    Args:
        axis: Plane axis, 0 = X, 1 = Y, 2 = Z.

    Returns:
        A 3×4 matrix (no translation) whose rotation is the transpose of
        ``world_to_local(axis)``'s, as ``Manifold.transform`` expects.
    """
    matrix = np.zeros((3, 4))
    matrix[:, :3] = world_to_local(axis)[:, :3].T
    return matrix


def cylinder_solid(
    radius: float, z0: float, z1: float, segments: int, *, compensate: bool
) -> Manifold:
    """Return a cylinder along z, centred on the z axis, from ``z0`` to ``z1``.

    Args:
        radius: Requested radius, mm.
        z0: Bottom, mm (local frame of the caller).
        z1: Top, mm; must be greater than ``z0``.
        segments: Number of polygon sides (``advanced.circular_segments``).
        compensate: True to put the polygon *flats* at ``radius`` (vertices at
            ``radius / cos(π / segments)``), as holes need (§6.2, r_model). False puts the
            vertices at ``radius``.

    Returns:
        The cylinder solid.

    Raises:
        ValueError: If ``z1 <= z0``, ``radius <= 0`` or ``segments < 3``.
    """
    if z1 <= z0 or radius <= 0 or segments < 3:
        raise ValueError(f"invalid cylinder: radius={radius}, z0={z0}, z1={z1}, n={segments}")
    vertex_radius = radius / math.cos(math.pi / segments) if compensate else radius
    solid = Manifold.cylinder(z1 - z0, vertex_radius, circular_segments=segments)
    return solid.translate((0.0, 0.0, z0))


def crosssection_from_contours(contours: Iterable[ArrayLike]) -> CrossSection:
    """Build a 2D cross-section from closed contours with the EvenOdd fill rule.

    EvenOdd makes the result independent of the contours' orientation. TrueType glyph outlines
    are clockwise, which the default Positive rule would drop (ADR-0009).

    Args:
        contours: Closed polylines, each an (N, 2) array-like of (u, v) in mm; the closing
            point need not be repeated.

    Returns:
        The cross-section.
    """
    arrays = [np.asarray(contour, dtype=np.float64).reshape(-1, 2) for contour in contours]
    return CrossSection(arrays, FillRule.EvenOdd)


def _signed_area(contour: NDArray[np.float64]) -> float:
    x, y = contour[:, 0], contour[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def crosssection_to_polygons(section: CrossSection) -> list[Polygon]:
    """Convert a cross-section to shapely polygons, one per connected component.

    Args:
        section: 2D cross-section, (u, v) in mm.

    Returns:
        Polygons with holes, sorted by their polylabel point (u, then v), the region order of
        §4.3. Outer contours have positive area in manifold3d, holes negative.
    """
    polygons: list[Polygon] = []
    for component in section.decompose():
        contours = [np.asarray(c, dtype=np.float64) for c in component.to_polygons()]
        shells = [c for c in contours if _signed_area(c) > 0]
        holes = [c for c in contours if _signed_area(c) < 0]
        if len(shells) != 1:  # decompose() yields one outer contour per component
            raise AssertionError(f"component with {len(shells)} outer contours")
        polygons.append(Polygon(shells[0], holes))
    keys = [polylabel(p, tolerance=POLYLABEL_TOLERANCE) for p in polygons]
    order = sorted(range(len(polygons)), key=lambda i: (keys[i].x, keys[i].y))
    return [polygons[i] for i in order]


def ray_depth(
    body: Manifold, origin: Sequence[float], direction: Sequence[float], max_length: float
) -> float | None:
    """Return the distance in mm from ``origin`` to the first surface hit along ``direction``.

    ``RayHit.distance`` is a fraction of the segment, not mm, so the depth is computed from
    ``RayHit.position``. A face the origin lies on is not reported: callers start rays
    ``RAY_START_OFFSET`` inside the piece (§13).

    Args:
        body: Solid, mm.
        origin: Ray start (x, y, z), mm, same frame as ``body``.
        direction: Ray direction; its length doesn't matter.
        max_length: Length of the probed segment, mm.

    Returns:
        The distance to the nearest hit in mm, or ``None`` if nothing is hit within
        ``max_length``.
    """
    start = np.asarray(origin, dtype=np.float64)
    unit = np.asarray(direction, dtype=np.float64)
    unit = unit / np.linalg.norm(unit)
    end = start + unit * max_length
    hits = body.ray_cast(tuple(start), tuple(end))
    if not hits:
        return None
    return float(np.linalg.norm(np.asarray(hits[0].position) - start))


def union_all(solids: Sequence[Manifold]) -> Manifold:
    """Return the union of several solids in one batched boolean.

    Args:
        solids: Solids in the same frame; the order doesn't change the result.

    Returns:
        The union; an empty manifold for an empty input.
    """
    if not solids:
        return Manifold()
    return Manifold.batch_boolean(list(solids), OpType.Add)
