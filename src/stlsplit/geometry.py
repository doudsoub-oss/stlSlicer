"""Thin wrappers around the geometry libraries: conversions, repair, frames, cylinders, rays.

Used by every geometric stage of the pipeline (PLAN.md §5.1). All solid geometry goes through
manifold3d; trimesh appears here only for conversions and basic mesh repair, and pymeshlab
(optional, GPL-3.0) only for deep repair, imported when it runs (ADR-0001, ADR-0007). Every
function is pure: repair functions work on a copy of their input.

Inputs and outputs are in mm. Unless stated otherwise, solids are in the cutting frame and 2D
data is in plane-local (u, v) coordinates (§4.2, docs/ARCHITECTURE.md "Frames"). The section
helpers (Phase 4) take a plane by its axis and offset: ``section``, ``cut_region`` (ADR-0002),
``clip_to_cells``, ``shadow`` and ``prism``. Solids are cut with ``split_at`` and ``clip``,
which work by difference: an intersection (``split_by_plane``, ``trim_by_plane``, ``^``) leaves
a zero-thickness flap where a model face lies on the cut (docs/LIBRARY_NOTES.md).
"""

import functools
import importlib.util
import math
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import numpy as np
import trimesh
from manifold3d import CrossSection, FillRule, JoinType, Manifold, Mesh, Mesh64, OpType
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel

from stlsplit.config import (
    AREA_TOLERANCE,
    CUTTER_PAD,
    POLYLABEL_CACHE_SIZE,
    POLYLABEL_TOLERANCE,
    VOID_RESIDUAL_FRACTION,
)
from stlsplit.models import Axis, Plane

Point3 = tuple[float, float, float]
"""A point or a size in the cutting frame, mm."""
Box = tuple[Point3, Point3]
"""An axis-aligned box, (low corner, high corner), mm, cutting frame (``grid.cell_bounds``)."""

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

    Vertices go through ``to_mesh64()`` and ``Mesh64``, so they keep their double precision:
    the result is exact for any shell, including the voids of split pieces, whose new
    vertices are doubles (docs/LIBRARY_NOTES.md).

    Args:
        body: Solid or inside-out shell, mm.

    Returns:
        The same surface with the opposite orientation, so the opposite signed volume.
    """
    mesh = body.to_mesh64()
    # np.array copies: the arrays of to_mesh64() are read-only views, which Mesh64() rejects.
    vertices = np.array(mesh.vert_properties[:, :3], dtype=np.float64)
    faces = np.array(mesh.tri_verts[:, ::-1], dtype=np.uint64)
    return Manifold(Mesh64(vert_properties=vertices, tri_verts=faces))


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
    return sorted_by_polylabel(_polygons(section))


def _polygons(section: CrossSection) -> list[Polygon]:
    """The components of a cross-section as shapely polygons, in ``decompose()`` order."""
    polygons: list[Polygon] = []
    for component in section.decompose():
        contours = [np.asarray(c, dtype=np.float64) for c in component.to_polygons()]
        if not contours:  # an empty cross-section decomposes into one empty component
            continue
        shells = [c for c in contours if _signed_area(c) > 0]
        holes = [c for c in contours if _signed_area(c) < 0]
        if len(shells) != 1:  # decompose() yields one outer contour per component
            raise AssertionError(f"component with {len(shells)} outer contours")
        polygons.append(Polygon(shells[0], holes))
    return polygons


@functools.lru_cache(maxsize=POLYLABEL_CACHE_SIZE)
def polylabel_point(polygon: Polygon) -> tuple[float, float]:
    """Return the polygon's polylabel point: the interior point farthest from its boundary.

    Computed to ``POLYLABEL_TOLERANCE``. It orders regions (§4.3) and tells which piece lies
    on each side of a cut face (Phase 4). It is the slowest step of the cutting on thin
    regions (a 2 mm ring takes about 30 ms), and the same region is sorted and then matched
    to its pieces, so results are cached; shapely geometries hash and compare by value.

    Args:
        polygon: A polygon with a positive area, (u, v) in mm.

    Returns:
        (u, v), mm.
    """
    point = polylabel(polygon, tolerance=POLYLABEL_TOLERANCE)
    return (float(point.x), float(point.y))


def sorted_by_polylabel(polygons: Iterable[Polygon]) -> list[Polygon]:
    """Sort polygons by their polylabel point, u then v: the region order of §4.3.

    Args:
        polygons: Polygons with a positive area, (u, v) in mm.

    Returns:
        The polygons, sorted.
    """
    keyed = [(polylabel_point(polygon), polygon) for polygon in polygons]
    return [polygon for _, polygon in sorted(keyed, key=lambda item: item[0])]


def section(body: Manifold, axis: Axis, offset: float) -> MultiPolygon:
    """Return the section of a solid by a plane, in the plane's (u, v) frame.

    A single slice: when a model face lies exactly on the plane, the section is one-sided
    (ADR-0002), so probe off the plane (``cut_region`` for contacts).

    Args:
        body: Solid, mm, cutting frame.
        axis: Plane axis.
        offset: Plane offset along ``axis``, mm.

    Returns:
        The section's polygons (with holes), in ``decompose()`` order; empty when the plane
        misses the body.
    """
    return MultiPolygon(_polygons(_to_local(body, axis).slice(offset)))


def cut_region(body: Manifold, plane: Plane, eps: float) -> list[Polygon]:
    """Return the contact region between the two sides of a cut plane.

    The region is the intersection of the slices at ``plane.offset - eps`` and
    ``plane.offset + eps``. A single slice is one-sided when a model face lies exactly on the
    plane: a plate on a column sliced at the step gives the plate's 1600 mm² instead of the
    100 mm² contact (ADR-0002).

    Args:
        body: Normalized input body, cutting frame, mm (never a piece: both pieces of a face
            must see the same region).
        plane: The cut plane.
        eps: Half-thickness of the probe, mm (``advanced.section_epsilon``).

    Returns:
        Connected polygons with holes, in plane-local (u, v) coordinates
        (docs/ARCHITECTURE.md, "Frames"), sorted by their polylabel point.
    """
    local = _to_local(body, plane.axis)
    contact = local.slice(plane.offset - eps) ^ local.slice(plane.offset + eps)
    return crosssection_to_polygons(contact)


def clip_to_cells(
    polygons: Iterable[Polygon], axis: Axis, cell_a: Box, cell_b: Box
) -> list[Polygon]:
    """Clip regions to the rectangle two cells adjacent across a plane share in that plane.

    Args:
        polygons: Regions of the plane, (u, v) in mm (``cut_region``).
        axis: Plane axis; the cells are adjacent along it.
        cell_a: One cell's box, cutting frame (``grid.cell_bounds``).
        cell_b: The other cell's box.

    Returns:
        The clipped regions split into connected polygons, without parts of
        ``AREA_TOLERANCE`` or less (float slivers, or a region that only touches the
        rectangle), sorted by their polylabel point.
    """
    u_axis, v_axis, _ = _LOCAL_AXES[axis]
    u0, v0 = max(cell_a[0][u_axis], cell_b[0][u_axis]), max(cell_a[0][v_axis], cell_b[0][v_axis])
    u1, v1 = min(cell_a[1][u_axis], cell_b[1][u_axis]), min(cell_a[1][v_axis], cell_b[1][v_axis])
    if u1 <= u0 or v1 <= v0:
        return []
    rectangle = box(u0, v0, u1, v1)
    parts = [
        part
        for polygon in polygons
        for part in _polygon_parts(polygon.intersection(rectangle))
        if part.area > AREA_TOLERANCE
    ]
    return sorted_by_polylabel(parts)


def _polygon_parts(shape: BaseGeometry) -> list[Polygon]:
    """The polygons in a shapely result, dropping its points and lines."""
    if isinstance(shape, Polygon):
        return [] if shape.is_empty else [shape]
    return [part for item in getattr(shape, "geoms", ()) for part in _polygon_parts(item)]


def shadow(body: Manifold, axis: Axis) -> CrossSection:
    """Return a solid's projection along an axis (its shadow), in that axis' (u, v) frame.

    Args:
        body: Solid, mm, cutting frame.
        axis: The projection axis.

    Returns:
        The shadow, (u, v) in mm (``Manifold.project`` after rotating the axis to local z).
    """
    return _to_local(body, axis).project()


def overlap_area(first: CrossSection, second: CrossSection) -> float:
    """Return the area two cross-sections have in common, mm².

    Args:
        first: Cross-section, (u, v) in mm.
        second: Cross-section in the same frame.

    Returns:
        The area of their intersection.
    """
    return float((first ^ second).area())


def grow(section: CrossSection, delta: float) -> CrossSection:
    """Return a cross-section grown outwards by ``delta`` mm, with round corners.

    Args:
        section: Cross-section, (u, v) in mm.
        delta: Growth, mm (> 0).

    Returns:
        The grown cross-section.
    """
    return section.offset(delta, JoinType.Round)


def prism(footprint: CrossSection, axis: Axis, low: float, high: float) -> Manifold:
    """Extrude a plane-local footprint along the plane's normal, from ``low`` to ``high``.

    Args:
        footprint: Cross-section in the (u, v) frame of ``axis``, mm.
        axis: The extrusion axis (the plane's normal).
        low: Start along ``axis``, mm, cutting frame.
        high: End along ``axis``, mm; greater than ``low``.

    Returns:
        The prism, cutting frame.

    Raises:
        ValueError: If ``high <= low``.
    """
    if high <= low:
        raise ValueError(f"invalid prism: low={low}, high={high}")
    local = Manifold.extrude(footprint, high - low).translate((0.0, 0.0, low))
    return local.transform(local_to_world(axis))


def box_solid(low: Point3, high: Point3) -> Manifold:
    """Return the axis-aligned box from ``low`` to ``high``, mm, cutting frame."""
    size = (high[0] - low[0], high[1] - low[1], high[2] - low[2])
    return Manifold.cube(size).translate(low)


def rectangle(axis: Axis, low: Point3, high: Point3) -> CrossSection:
    """Return a box's cross-section across ``axis``, in that axis' (u, v) frame.

    Args:
        axis: The plane axis.
        low: The box's low corner, mm, cutting frame.
        high: Its high corner.

    Returns:
        The rectangle spanned by the box along u and v.
    """
    u_axis, v_axis, _ = _LOCAL_AXES[axis]
    size = (high[u_axis] - low[u_axis], high[v_axis] - low[v_axis])
    return CrossSection.square(size).translate((low[u_axis], low[v_axis]))


def split_at(body: Manifold, axis: Axis, offset: float) -> tuple[Manifold, Manifold]:
    """Split a solid by a plane into the part below it and the part above it.

    Each part is the body minus a box covering the other side, reaching ``CUTTER_PAD`` past
    the body's bounding box. ``split_by_plane``, ``trim_by_plane`` and an intersection with a
    box all leave a zero-thickness, two-sided flap where a model face lies exactly on the
    plane: a column on a plinth cut at the step keeps the plinth's 40 × 40 top as a sheet. The
    difference doesn't (docs/LIBRARY_NOTES.md, ``manifold.coplanar_cuts``).

    Args:
        body: Solid, mm, cutting frame.
        axis: Plane axis.
        offset: Plane offset along ``axis``, mm.

    Returns:
        (the part where coordinate ``axis`` < ``offset``, the part where it is greater); a part
        is empty when nothing lies on its side.
    """
    if body.is_empty():
        return body, body
    box = body.bounding_box()
    if offset <= box[axis]:
        return Manifold(), body
    if offset >= box[axis + 3]:
        return body, Manifold()
    low = [value - CUTTER_PAD for value in box[:3]]
    high = [value + CUTTER_PAD for value in box[3:]]
    upper_low, lower_high = list(low), list(high)
    upper_low[axis] = offset
    lower_high[axis] = offset
    below = body - box_solid(_point(upper_low), _point(high))
    above = body - box_solid(_point(low), _point(lower_high))
    return below, above


def clip(body: Manifold, region: Manifold) -> Manifold:
    """Return the part of a solid inside a region, computed by difference.

    ``body − (box − region)``, with the box ``2 · CUTTER_PAD`` past the body's bounding box:
    an intersection would leave a flap where a model face lies on the region's surface (see
    :func:`split_at`).

    Args:
        body: Solid, mm.
        region: Solid in the same frame.

    Returns:
        The clipped solid.
    """
    if body.is_empty():
        return body
    box = body.bounding_box()
    low = _point([value - 2 * CUTTER_PAD for value in box[:3]])
    high = _point([value + 2 * CUTTER_PAD for value in box[3:]])
    return body - (box_solid(low, high) - region)


def _point(values: Sequence[float]) -> Point3:
    x, y, z = values
    return (x, y, z)


def lies_inside(solid: Manifold, container: Manifold) -> bool:
    """Whether ``solid`` lies inside ``container``, up to ``VOID_RESIDUAL_FRACTION`` of its volume.

    Args:
        solid: A solid (positive volume), mm.
        container: A solid in the same frame.

    Returns:
        True if ``(solid − container).volume() ≤ VOID_RESIDUAL_FRACTION · solid.volume()``.
    """
    return bool((solid - container).volume() <= VOID_RESIDUAL_FRACTION * solid.volume())


def bodies(solid: Manifold) -> list[Manifold]:
    """Split a valid solid into its bodies: each outward shell with the voids it holds.

    ``decompose()`` returns every closed shell on its own, a void's inside-out shell included
    (docs/LIBRARY_NOTES.md); dropped, or kept as a body of its own, it would fill the void.
    Each void goes to the smallest outward shell it lies inside and is subtracted from it.
    A body loose inside a void is a body of its own.

    Args:
        solid: A valid manifold whose shells don't cross (a normalized body or a part of
            one), mm, any frame.

    Returns:
        The bodies, positive volumes, in ``decompose()`` order of their outer shells.

    Raises:
        AssertionError: A void lies inside no outward shell (the solid isn't normalized; a
            bug).
    """
    shells = solid.decompose()
    outer = [shell for shell in shells if shell.volume() > 0]
    voids = [reverse_winding(shell) for shell in shells if shell.volume() < 0]
    if not voids:
        return outer
    boxes = [shell.bounding_box() for shell in outer]
    volumes = [shell.volume() for shell in outer]
    held: dict[int, list[Manifold]] = {}
    for void in voids:
        low, high = void.bounding_box()[:3], void.bounding_box()[3:]
        containers = [
            index
            for index, shell in enumerate(outer)
            if all(a >= b for a, b in zip(low, boxes[index][:3], strict=True))
            and all(a <= b for a, b in zip(high, boxes[index][3:], strict=True))
            and lies_inside(void, shell)
        ]
        if not containers:
            raise AssertionError(f"a void of {void.volume():.6g} mm^3 lies inside no body")
        owner = min(containers, key=lambda index: (volumes[index], index))
        held.setdefault(owner, []).append(void)
    return [shell - union_all(held[i]) if i in held else shell for i, shell in enumerate(outer)]


def _to_local(body: Manifold, axis: Axis) -> Manifold:
    """``body`` in the plane-local frame of ``axis``: the plane at offset o is local z = o."""
    return body.transform(world_to_local(axis))


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
