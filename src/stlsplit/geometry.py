"""Thin wrappers around the geometry libraries: conversions, repair, frames, cylinders, rays.

Used by every geometric stage of the pipeline (PLAN.md §5.1). All solid geometry goes through
manifold3d; trimesh appears here only for conversions and basic mesh repair, and pymeshlab
(optional, GPL-3.0) only for deep repair, imported when it runs (ADR-0001, ADR-0007). Every
function is pure: repair functions work on a copy of their input.

Inputs and outputs are in mm. Unless stated otherwise, solids are in the cutting frame and 2D
data is in plane-local (u, v) coordinates (§4.2, docs/ARCHITECTURE.md "Frames"). The section
helpers (``cut_region`` and friends) arrive in Phase 4.
"""

import importlib.util
import math
from collections.abc import Iterable, Sequence
from typing import NamedTuple

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


class MeshDefects(NamedTuple):
    """What keeps a mesh from being a closed solid, for the "can't repair" message.

    Attributes:
        open_edges: Edges used by one triangle only (the rims of holes).
        non_manifold_edges: Edges shared by more than two triangles.
        bodies: Connected groups of vertices.
    """

    open_edges: int
    non_manifold_edges: int
    bodies: int


def mesh_defects(mesh: trimesh.Trimesh) -> MeshDefects:
    """Count the defects of a triangle mesh.

    Args:
        mesh: Triangle mesh with merged vertices, any frame.

    Returns:
        The counts.
    """
    edges = np.sort(np.asarray(mesh.edges, dtype=np.int64), axis=1)
    _, uses = np.unique(edges, axis=0, return_counts=True)
    return MeshDefects(
        open_edges=int(np.count_nonzero(uses == 1)),
        non_manifold_edges=int(np.count_nonzero(uses > 2)),
        bodies=int(mesh.body_count),
    )


def basic_repair(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, tuple[str, ...]]:
    """Apply trimesh's basic repair steps to a copy of ``mesh`` (PLAN.md Phase 2, ADR-0007).

    In order: merge duplicate vertices; drop degenerate faces, then duplicate faces; drop
    unreferenced vertices; make the winding consistent (:func:`_orient_faces`); close holes of
    one triangle or one quad with ``fill_holes``.

    Args:
        mesh: Triangle mesh, mm, input frame.

    Returns:
        The repaired copy, and a description of each step that changed something, in the
        order applied (empty if nothing changed).
    """
    fixed = mesh.copy()
    steps: list[str] = []

    def record(count: int, text: str) -> None:
        if count:
            steps.append(f"{text}: {count}")

    before = len(fixed.vertices)
    fixed.merge_vertices()
    record(before - len(fixed.vertices), "duplicate vertices merged")
    before = len(fixed.faces)
    fixed.update_faces(fixed.nondegenerate_faces())
    record(before - len(fixed.faces), "degenerate faces removed")
    before = len(fixed.faces)
    fixed.update_faces(fixed.unique_faces())
    record(before - len(fixed.faces), "duplicate faces removed")
    before = len(fixed.vertices)
    fixed.remove_unreferenced_vertices()
    record(before - len(fixed.vertices), "unreferenced vertices removed")
    record(_orient_faces(fixed), "faces re-oriented")
    before = len(fixed.faces)
    trimesh.repair.fill_holes(fixed)
    record(len(fixed.faces) - before, "triangles added to close holes")
    return fixed, tuple(steps)


def _orient_faces(mesh: trimesh.Trimesh) -> int:
    """Make the winding consistent within each shell, keeping the shell's majority orientation.

    This is ``fix_normals(multibody=False)`` with one change. trimesh's ``fix_winding`` makes
    every face of a connected group agree with one reference face (the group's first face in
    ``face_adjacency`` order), not with the majority, so one reversed triangle could reverse
    the 2047 good ones of a hollow sphere's void and fill it (docs/LIBRARY_NOTES.md). A group
    where more than half the faces changed is therefore reversed back. Then
    ``fix_inversion(multibody=False)`` reverses the whole mesh if its volume is negative.
    Never ``multibody=True``: it turns internal voids outward (ADR-0007).

    Args:
        mesh: Triangle mesh with merged vertices; modified in place.

    Returns:
        The number of faces whose winding changed.
    """
    original = np.array(mesh.faces)
    trimesh.repair.fix_winding(mesh)  # type: ignore[no-untyped-call]  # unannotated in trimesh
    changed = (mesh.faces != original).any(axis=1)
    faces = np.array(mesh.faces)
    for group in trimesh.graph.connected_components(
        mesh.face_adjacency, nodes=np.arange(len(faces))
    ):
        if 2 * np.count_nonzero(changed[group]) > len(group):
            faces[group] = faces[group][:, ::-1]
    mesh.faces = faces
    trimesh.repair.fix_inversion(mesh, multibody=False)
    return int(np.count_nonzero((mesh.faces != original).any(axis=1)))


DEEP_REPAIR_INSTALL = 'pip install "stlsplit[deep-repair]"'
"""How to install pymeshlab, for messages."""

PYMESHLAB_FILTERS: tuple[str, ...] = (
    "meshing_repair_non_manifold_edges",
    "meshing_repair_non_manifold_vertices",
    "meshing_close_holes",
    "meshing_re_orient_faces_coherently",
)
"""The ``MeshSet`` filters deep repair applies, in this order."""


def deep_repair_problem() -> str | None:
    """Return why deep repair can't run, or ``None`` if it can.

    pymeshlab is imported only when it is installed, and only from here and
    :func:`deep_repair` (it is GPL-3.0, PLAN.md §2). Its filters are plugins that need system
    libraries: without the OpenGL library ``libOpenGL.so.0``, the plugin holding
    ``meshing_close_holes`` doesn't load and the filter is simply missing
    (docs/LIBRARY_NOTES.md).

    Returns:
        ``None``, or one line saying what is missing and how to fix it.
    """
    if importlib.util.find_spec("pymeshlab") is None:
        return f"pymeshlab is not installed ({DEEP_REPAIR_INSTALL})"
    import pymeshlab  # optional extra, imported only when deep repair is needed

    meshes = pymeshlab.MeshSet()
    missing = [name for name in PYMESHLAB_FILTERS if not hasattr(meshes, name)]
    if not missing:
        return None
    return (
        f"pymeshlab didn't load the filter{'s' if len(missing) > 1 else ''} "
        f"{', '.join(missing)}, usually because the system's OpenGL library libOpenGL.so.0 "
        "is missing (Debian and Ubuntu package: libopengl0)"
    )


def deep_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
    """Repair a copy of ``mesh`` with pymeshlab (``--deep-repair``, PLAN.md Phase 2).

    Removes non-manifold edges, then non-manifold vertices, closes holes and re-orients the
    faces coherently. pymeshlab is GPL-3.0, so it is imported here only (PLAN.md §2).

    Args:
        mesh: Triangle mesh, mm, input frame. :func:`deep_repair_problem` must have
            returned ``None``.

    Returns:
        The repaired mesh, or ``None`` if pymeshlab refused one of the filters.
    """
    import pymeshlab  # optional extra, imported only when deep repair runs

    meshes = pymeshlab.MeshSet()
    meshes.add_mesh(
        pymeshlab.Mesh(
            vertex_matrix=np.asarray(mesh.vertices, dtype=np.float64),
            face_matrix=np.asarray(mesh.faces, dtype=np.int32),
        )
    )
    try:
        for name in PYMESHLAB_FILTERS:
            getattr(meshes, name)()
    except pymeshlab.PyMeshLabException:
        return None
    result = meshes.current_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(result.vertex_matrix(), dtype=np.float64),
        faces=np.asarray(result.face_matrix(), dtype=np.int64),
        process=False,
    )


def reverse_winding(body: Manifold) -> Manifold:
    """Return ``body`` with every triangle's winding reversed: an inside-out shell turns solid.

    Vertices go through ``to_mesh()`` (float32). That is exact for shells straight out of
    ``decompose()`` on a mesh built by :func:`to_manifold`, the only use (``repair``).

    Args:
        body: Solid or inside-out shell, mm.

    Returns:
        The same surface with the opposite orientation, so the opposite signed volume.
    """
    mesh = body.to_mesh()
    # np.array copies: to_mesh() arrays are read-only views, which Mesh() rejects.
    vertices = np.array(mesh.vert_properties[:, :3], dtype=np.float32)
    faces = np.array(mesh.tri_verts[:, ::-1], dtype=np.uint32)
    return Manifold(Mesh(vert_properties=vertices, tri_verts=faces))


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
