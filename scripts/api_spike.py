"""Executable record of every library behaviour stlsplit relies on (PLAN.md Phase 0, task 6).

Run it after any dependency upgrade:

    python scripts/api_spike.py

It prints the installed versions, then runs one check per behaviour and stops at the first
failure with exit code 1. A check of an optional package (pymeshlab) is reported as skipped
when that package isn't installed. Each check name matches a row of docs/LIBRARY_NOTES.md. If
a check fails after an upgrade, don't work around it: update the code that depends on it (the
LIBRARY_NOTES row says which) and the notes, or pin the dependency.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

import matplotlib
import numpy as np
import trimesh
from manifold3d import CrossSection, Error, FillRule, Manifold, Mesh, OpType
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely.geometry import Point, Polygon
from shapely.ops import polylabel

PACKAGES = ("manifold3d", "trimesh", "numpy", "scipy", "networkx", "shapely", "matplotlib")
OPTIONAL_PACKAGES = ("pymeshlab",)
TOL = 1e-6

Check = Callable[[], None]
CHECKS: list[tuple[str, Check]] = []


def check(name: str) -> Callable[[Check], Check]:
    """Register a check under the name used in docs/LIBRARY_NOTES.md."""

    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


class SkippedError(Exception):
    """Raised by a check whose optional package isn't installed."""


def expect(condition: bool, message: str) -> None:
    """Fail the current check with ``message`` (asserts are stripped by ``python -O``)."""
    if not condition:
        raise AssertionError(message)


def close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def signed_area(contour: np.ndarray) -> float:
    x, y = contour[:, 0], contour[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def cube(size: float = 10.0) -> Manifold:
    return Manifold.cube((size, size, size))


# --- manifold3d ---------------------------------------------------------------------------


@check("manifold.mesh_arrays")
def manifold_mesh_arrays() -> None:
    mesh = cube().to_mesh()
    expect(mesh.vert_properties.dtype == np.float32, "vert_properties should be float32")
    expect(mesh.tri_verts.dtype == np.uint32, "tri_verts should be uint32")
    expect(not mesh.vert_properties.flags.writeable, "to_mesh() arrays should be read-only")
    expect(cube().to_mesh64().vert_properties.dtype == np.float64, "to_mesh64() gives float64")
    copied = Manifold(
        Mesh(
            vert_properties=np.array(mesh.vert_properties[:, :3], dtype=np.float32, order="C"),
            tri_verts=np.array(mesh.tri_verts, dtype=np.uint32, order="C"),
        )
    )
    expect(close(copied.volume(), 1000.0), "rebuilt mesh should keep the volume")


@check("manifold.status_volume")
def manifold_status_volume() -> None:
    expect(cube().status() == Error.NoError, "a cube should have status NoError")
    expect(close(cube().volume(), 1000.0), "a 10 mm cube should have volume 1000")
    open_box = trimesh.creation.box((10, 10, 10))
    open_box.update_faces(np.arange(len(open_box.faces)) != 0)
    broken = Manifold(
        Mesh(
            vert_properties=np.ascontiguousarray(open_box.vertices, dtype=np.float32),
            tri_verts=np.ascontiguousarray(open_box.faces, dtype=np.uint32),
        )
    )
    expect(broken.status() != Error.NoError, "an open mesh should not have status NoError")


@check("manifold.split_by_plane")
def manifold_split_by_plane() -> None:
    first, second = cube().split_by_plane((1.0, 0.0, 0.0), 3.0)
    expect(close(first.bounding_box()[0], 3.0), "first result should be on the normal's side")
    expect(close(second.bounding_box()[3], 3.0), "second result should be on the other side")
    expect(close(first.volume() + second.volume(), 1000.0), "split should keep the volume")


@check("manifold.trim_decompose_batch_project")
def manifold_trim_decompose_batch_project() -> None:
    trimmed = cube().trim_by_plane((1.0, 0.0, 0.0), 3.0)
    expect(close(trimmed.bounding_box()[0], 3.0), "trim_by_plane keeps the normal's side")
    two = Manifold.batch_boolean([cube(), cube().translate((20.0, 0.0, 0.0))], OpType.Add)
    expect(close(two.volume(), 2000.0), "batch_boolean Add should union")
    expect(len(two.decompose()) == 2, "decompose should find two bodies")
    expect(close(cube().project().area(), 100.0), "project() should give the XY shadow")


@check("manifold.cylinder_default_segments")
def manifold_cylinder_default_segments() -> None:
    default = Manifold.cylinder(1.0, 2.5)
    expect(default.num_vert() == 32, f"expected 16 segments, got {default.num_vert() // 2}")
    explicit = Manifold.cylinder(1.0, 2.5, circular_segments=64)
    expect(explicit.num_vert() == 128, "circular_segments should set the segment count")


@check("manifold.transform_slice_axes")
def manifold_transform_slice_axes() -> None:
    size = (1.0, 2.0, 3.0)
    local_axes = {0: (1, 2, 0), 1: (2, 0, 1), 2: (0, 1, 2)}
    for axis, (u, v, n) in local_axes.items():
        matrix = np.zeros((3, 4))
        matrix[0, u] = matrix[1, v] = matrix[2, n] = 1.0
        section = Manifold.cube(size).transform(matrix).slice(size[n] / 2)
        bounds = section.bounds()
        expect(
            close(bounds[2], size[u]) and close(bounds[3], size[v]),
            f"axis {axis}: slice bounds {bounds}, expected ({size[u]}, {size[v]})",
        )


@check("manifold.signed_permutation_exact")
def manifold_signed_permutation_exact() -> None:
    # A quarter turn about Y (cutting (X, Y, Z) = input (+Z, +Y, -X)), then the bbox minimum
    # moved to the origin, on a box at awkward float coordinates (scaled by 25.4).
    body = Manifold.cube((460.0, 100.0, 100.0)).translate((-12.345678, 3.3, 0.1)).scale(25.4)
    low, high = np.array(body.bounding_box()[:3]), np.array(body.bounding_box()[3:])
    matrix = np.array([[0.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [-1.0, 0.0, 0.0, 0.0]])
    rotated = body.transform(matrix)
    moved = rotated.translate(tuple(-np.array(rotated.bounding_box()[:3])))
    box = moved.bounding_box()
    expect(box[:3] == (0.0, 0.0, 0.0), f"bounding box should start exactly at 0, got {box[:3]}")
    size = high - low
    expected = (float(size[2]), float(size[1]), float(size[0]))
    expect(box[3:] == expected, f"extents {box[3:]} should be exactly {expected}")
    expect(moved.status() == Error.NoError, "a proper rotation should keep the solid valid")
    expect(moved.volume() == body.volume(), "a signed permutation should keep the volume exactly")


@check("manifold.crosssection_evenodd")
def manifold_crosssection_evenodd() -> None:
    outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    inner = [(2.0, 2.0), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0)]  # same orientation as outer
    section = CrossSection([outer, inner], FillRule.EvenOdd)
    expect(close(section.area(), 64.0), "EvenOdd should make the inner square a hole")
    expect(len(section.decompose()) == 1, "one component expected")
    areas = sorted(signed_area(np.asarray(p)) for p in section.to_polygons())
    expect(close(areas[0], -36.0) and close(areas[1], 100.0), f"signed areas {areas}")


@check("manifold.crosssection_xor_extrude")
def manifold_crosssection_xor_extrude() -> None:
    a = CrossSection.square((10.0, 10.0))
    b = CrossSection.square((5.0, 5.0)).translate((2.5, 2.5))
    expect(close((a ^ b).area(), 25.0), "^ should intersect two cross-sections")
    expect(close(Manifold.extrude(a, 2.0).volume(), 200.0), "extrude should give area x h")


@check("manifold.ray_cast")
def manifold_ray_cast() -> None:
    hits = cube().ray_cast((5.0, 5.0, -10.0), (5.0, 5.0, 30.0))
    expect(len(hits) == 2, f"expected 2 hits, got {len(hits)}")
    expect(close(hits[0].distance, 0.25), "distance should be a fraction of the segment")
    # Three separate bodies, cast both ways: hits must come nearest first, not in face order.
    bodies = Manifold.batch_boolean(
        [cube(), cube().translate((0.0, 0.0, 20.0)), cube().translate((0.0, 0.0, 40.0))],
        OpType.Add,
    )
    for start, end in (
        ((5.0, 5.0, -10.0), (5.0, 5.0, 60.0)),
        ((5.0, 5.0, 60.0), (5.0, 5.0, -10.0)),
    ):
        ordered = bodies.ray_cast(start, end)
        distances = [h.distance for h in ordered]
        expect(len(ordered) == 6, f"expected 6 hits, got {len(ordered)}")
        expect(distances == sorted(distances), f"hits not sorted by distance: {distances}")
        gaps = [abs(h.position[2] - start[2]) for h in ordered]
        expect(gaps == sorted(gaps), "positions should get farther from the origin")
    expect(close(hits[0].position[2], 0.0), "position should be in mm")
    from_face = cube().ray_cast((5.0, 5.0, 0.0), (5.0, 5.0, 30.0))
    expect(
        len(from_face) == 1 and close(from_face[0].position[2], 10.0),
        "a face the origin lies on should not be reported",
    )


@check("manifold.min_gap")
def manifold_min_gap() -> None:
    a = Manifold.cylinder(10.0, 2.7, circular_segments=64)
    expect(close(a.min_gap(a.translate((7.4, 0.0, 0.0)), 10.0), 2.0), "gap should be 2.0")
    expect(a.min_gap(a.translate((1.0, 0.0, 0.0)), 10.0) == 0.0, "crossing solids give 0")


@check("manifold.simplify")
def manifold_simplify() -> None:
    sphere = Manifold.sphere(10.0, 64)
    simple = sphere.simplify(0.1)
    expect(simple.status() == Error.NoError, "simplify should keep the result manifold")
    expect(simple.num_tri() < sphere.num_tri(), "simplify should remove triangles")


@check("manifold.coplanar_booleans")
def manifold_coplanar_booleans() -> None:
    cutter = Manifold.cube((2.0, 2.0, 5.0)).translate((4.0, 4.0, 5.0))  # top face on z = 10
    pocket = cube() - cutter
    expect(close(pocket.volume(), 980.0), "coplanar difference should remove the cutter")
    expect(close(pocket.slice(9.999).area(), 96.0), "the pocket should open through the top")
    # No closing skin: 600 cube faces − 4 opening + 40 pocket walls + 4 pocket floor = 640;
    # a skin would add about 8 mm². A ray from above must reach the pocket floor at z = 5.
    expect(close(pocket.surface_area(), 640.0), f"surface area {pocket.surface_area()}")
    down = pocket.ray_cast((5.0, 5.0, 20.0), (5.0, 5.0, -10.0))
    expect(bool(down) and close(down[0].position[2], 5.0), "the hole should be open at the top")
    union = cube() + cube().translate((10.0, 0.0, 0.0))
    expect(len(union.decompose()) == 1, "coplanar union should give one body")
    expect(close(union.volume(), 2000.0), "coplanar union should have the exact volume")


@check("manifold.slice_at_step")
def manifold_slice_at_step() -> None:
    eps = 0.01
    column = Manifold.cube((10.0, 10.0, 20.0))
    overhang = column + Manifold.cube((40.0, 40.0, 10.0)).translate((-15.0, -15.0, 20.0))
    plinth = Manifold.cube((40.0, 40.0, 10.0)).translate((-15.0, -15.0, 0.0)) + Manifold.cube(
        (10.0, 10.0, 10.0)
    ).translate((0.0, 0.0, 10.0))
    expect(close(overhang.slice(20.0).area(), 1600.0), "slice at the step is one-sided")
    for name, body, z in (("overhang", overhang, 20.0), ("plinth", plinth, 10.0)):
        contact = (body.slice(z - eps) ^ body.slice(z + eps)).area()
        expect(close(contact, 100.0), f"{name}: contact {contact}, expected 100")


def mesh_to_manifold(mesh: trimesh.Trimesh) -> Manifold:
    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
    faces = np.ascontiguousarray(mesh.faces, dtype=np.uint32)
    return Manifold(Mesh(vert_properties=vertices, tri_verts=faces))


def stacked(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    """Concatenate meshes, then merge coincident vertices as ``trimesh.load`` does."""
    mesh = trimesh.util.concatenate(list(meshes))
    mesh.merge_vertices()
    return mesh


@check("manifold.signed_shells")
def manifold_signed_shells() -> None:
    hollow = Manifold.sphere(150.0, 64) - Manifold.sphere(148.0, 64)
    signs = sorted(shell.volume() > 0 for shell in hollow.decompose())
    expect(signs == [False, True], f"hollow sphere shells: positive flags {signs}")
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    inside_out = mesh_to_manifold(trimesh.Trimesh(box.vertices, box.faces[:, ::-1], process=False))
    expect(inside_out.status() == Error.NoError, f"inside-out cube: {inside_out.status()}")
    expect(close(inside_out.volume(), -1000.0), f"inside-out cube volume {inside_out.volume()}")
    expect(len(inside_out.decompose()) == 1, "inside-out cube should be one shell")
    other = box.copy()
    other.apply_translation((5.0, 0.0, 0.0))
    overlapping = mesh_to_manifold(trimesh.util.concatenate([box, other]))
    expect(overlapping.status() == Error.NoError, "overlapping shells are valid by index")
    expect(close(overlapping.volume(), 2000.0), f"overlap volume {overlapping.volume()}")
    reversed_faces = np.array(inside_out.to_mesh().tri_verts[:, ::-1], dtype=np.uint32)
    vertices = np.array(inside_out.to_mesh().vert_properties[:, :3], dtype=np.float32)
    flipped = Manifold(Mesh(vert_properties=vertices, tri_verts=reversed_faces))
    expect(close(flipped.volume(), 1000.0), f"reversed winding volume {flipped.volume()}")


@check("manifold.edge_touching_cubes")
def manifold_edge_touching_cubes() -> None:
    first = trimesh.creation.box((10.0, 10.0, 10.0))
    second = first.copy()
    second.apply_translation((10.0, 10.0, 0.0))
    touching = stacked(first, second)
    expect(len(touching.vertices) == 14, f"shared edge vertices merged: {len(touching.vertices)}")
    body = mesh_to_manifold(touching)
    expect(body.status() == Error.NoError, f"edge-touching cubes: {body.status()}")
    expect(len(body.decompose()) == 2, "edge-touching cubes should be two shells")
    expect(close(body.volume(), 2000.0), f"edge-touching volume {body.volume()}")


def finned_box() -> trimesh.Trimesh:
    """A 10 mm box with one stray triangle on an edge: a non-manifold edge, two open edges."""
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    box.apply_translation((5.0, 5.0, 5.0))
    bottom = int(np.argmin(np.linalg.norm(box.vertices - (10.0, 10.0, 0.0), axis=1)))
    top = int(np.argmin(np.linalg.norm(box.vertices - (10.0, 10.0, 10.0), axis=1)))
    vertices = np.vstack([box.vertices, [(15.0, 15.0, 5.0)]])
    faces = np.vstack([box.faces, [(bottom, top, len(box.vertices))]])
    return trimesh.Trimesh(vertices, faces, process=False)


# --- trimesh ------------------------------------------------------------------------------


def soup_box() -> trimesh.Trimesh:
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    triangles = box.vertices[box.faces].reshape(-1, 3)
    return trimesh.Trimesh(triangles, np.arange(len(triangles)).reshape(-1, 3), process=False)


@check("trimesh.load_merges_vertices")
def trimesh_load_merges_vertices() -> None:
    soup = soup_box()
    expect(len(soup.vertices) == 36, "process=False should keep the soup")
    data = soup.export(file_type="stl")
    loaded = trimesh.load(trimesh.util.wrap_as_stream(data), file_type="stl", force="mesh")
    expect(len(loaded.vertices) == 8, f"load should merge vertices, got {len(loaded.vertices)}")
    expect(loaded.is_watertight, "merged soup should be watertight")


@check("trimesh.load_drops_non_finite")
def trimesh_load_drops_non_finite() -> None:
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    vertices = np.vstack([box.vertices, [(np.nan, 0.0, 0.0)]])
    faces = np.vstack([box.faces, [(0, 1, len(box.vertices))]])
    data = trimesh.Trimesh(vertices, faces, process=False).export(file_type="stl")
    loaded = trimesh.load(trimesh.util.wrap_as_stream(data), file_type="stl", force="mesh")
    expect(len(loaded.faces) == 12, f"the NaN triangle should be dropped: {len(loaded.faces)}")
    expect(bool(np.isfinite(loaded.vertices).all()), "no non-finite vertex should remain")


@check("trimesh.cleanup_methods")
def trimesh_cleanup_methods() -> None:
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    vertices = np.vstack([box.vertices, [[50.0, 50.0, 50.0]]])  # one unreferenced vertex
    faces = np.vstack([box.faces, box.faces[:1], [[0, 0, 1]]])  # one duplicate, one degenerate
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    expect(len(mesh.vertices) == 9 and len(mesh.faces) == 14, "test mesh built as intended")
    mesh.update_faces(mesh.nondegenerate_faces())
    expect(len(mesh.faces) == 13, f"degenerate face not removed: {len(mesh.faces)} faces")
    mesh.update_faces(mesh.unique_faces())
    expect(len(mesh.faces) == 12, f"duplicate face not removed: {len(mesh.faces)} faces")
    mesh.remove_unreferenced_vertices()
    expect(len(mesh.vertices) == 8, f"unreferenced vertex kept: {len(mesh.vertices)} vertices")
    expect(mesh.is_watertight, "the cleaned box should be watertight")


def quad_hole_box() -> trimesh.Trimesh:
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    box.update_faces(np.arange(len(box.faces)) >= 2)  # remove both triangles of one side
    return box


# Child program for run_isolated(). It filters imports *before* importing trimesh, so every
# package from site-packages outside the allowed list behaves as if it weren't installed. It
# runs with ``python -I -c`` so the spike module (and its top-level imports) is never loaded.
ISOLATED_CHILD = """
import importlib.machinery, sys, sysconfig
from pathlib import Path

case, allowed = sys.argv[1], set(sys.argv[2:])
roots = {Path(sysconfig.get_paths()[key]).resolve() for key in ("purelib", "platlib")}
PathFinder = importlib.machinery.PathFinder

class FilteringPathFinder:
    # Like PathFinder, but packages from site-packages outside `allowed` look uninstalled
    # (find_spec returns None), which is what trimesh probes for its optional dependencies.
    @classmethod
    def find_spec(cls, name, path=None, target=None):
        spec = PathFinder.find_spec(name, path, target)
        if spec is None or name.partition(".")[0] in allowed:
            return spec
        places = [spec.origin] if spec.origin else list(spec.submodule_search_locations or [])
        if any(root in Path(place).resolve().parents for place in places for root in roots):
            return None
        return spec

    @classmethod
    def invalidate_caches(cls):
        PathFinder.invalidate_caches()

sys.meta_path[:] = [FilteringPathFinder if f is PathFinder else f for f in sys.meta_path]
import numpy as np
import trimesh

if case == "fill_holes":
    box = trimesh.creation.box((10.0, 10.0, 10.0))
    box.update_faces(np.arange(len(box.faces)) >= 2)
    trimesh.repair.fill_holes(box)
    if not box.is_watertight:
        sys.exit("a quad hole should close")
elif case == "glb":
    data = trimesh.Scene([trimesh.creation.box((10.0, 10.0, 10.0))]).export(file_type="glb")
    if data[:4] != b"glTF":
        sys.exit("GLB export should start with the glTF magic")
else:
    sys.exit(f"unknown case {case}")
"""


def run_isolated(case: str, allowed: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run an ISOLATED_CHILD case where only ``allowed`` third-party packages import."""
    command = [sys.executable, "-I", "-c", ISOLATED_CHILD, case, *allowed]
    return subprocess.run(command, capture_output=True, text=True, check=False)


@check("trimesh.fill_holes")
def trimesh_fill_holes() -> None:
    quad = quad_hole_box()
    expect(not quad.is_watertight, "the box should be open")
    expect(trimesh.repair.fill_holes(quad) and quad.is_watertight, "a quad hole should close")
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    sphere.update_faces(sphere.vertices[sphere.faces].mean(axis=1)[:, 2] < 7.0)
    sphere.remove_unreferenced_vertices()
    expect(not trimesh.repair.fill_holes(sphere), "a large hole should stay open")
    without = run_isolated("fill_holes", ["numpy", "scipy", "trimesh"])
    expect(
        without.returncode != 0 and "networkx" in without.stderr,
        f"fill_holes should need networkx; without it: exit {without.returncode}",
    )
    with_nx = run_isolated("fill_holes", ["numpy", "scipy", "networkx", "trimesh"])
    expect(with_nx.returncode == 0, f"fill_holes with networkx failed:\n{with_nx.stderr}")


@check("trimesh.fix_normals_multibody")
def trimesh_fix_normals_multibody() -> None:
    outer = trimesh.creation.icosphere(subdivisions=3, radius=150.0)
    inner = trimesh.creation.icosphere(subdivisions=3, radius=148.0)
    inner.invert()
    hollow = trimesh.util.concatenate([outer, inner])
    expected = hollow.volume
    single = hollow.copy()
    trimesh.repair.fix_normals(single, multibody=False)
    expect(close(single.volume, expected, 1e-6 * expected), "multibody=False keeps the void")
    multi = hollow.copy()
    trimesh.repair.fix_normals(multi, multibody=True)
    expect(multi.volume > 10 * expected, "multibody=True is expected to fill the void")


@check("trimesh.fix_winding_reference_face")
def trimesh_fix_winding_reference_face() -> None:
    outer = trimesh.creation.icosphere(subdivisions=3, radius=150.0)
    inner = trimesh.creation.icosphere(subdivisions=3, radius=148.0)
    inner.invert()
    hollow = trimesh.util.concatenate([outer, inner])
    # fix_winding starts each shell's traversal at the shell's first face in face_adjacency
    # order (networkx node order) and makes the whole shell agree with it.
    order = dict.fromkeys(hollow.face_adjacency.ravel().tolist())
    reference = next(face for face in order if face >= len(outer.faces))  # void's shell
    faces = np.array(hollow.faces)
    faces[reference] = faces[reference][::-1]
    mesh = trimesh.Trimesh(hollow.vertices, faces, process=False)
    trimesh.repair.fix_winding(mesh)
    changed = int(np.count_nonzero((mesh.faces != faces).any(axis=1)))
    expect(
        changed == len(inner.faces) - 1,
        f"fix_winding should follow the reference face, not the majority: {changed} changed",
    )


@check("trimesh.stl_zero_header")
def trimesh_stl_zero_header() -> None:
    data = trimesh.creation.box((10.0, 10.0, 10.0)).export(file_type="stl")
    expect(data[:80] == b"\0" * 80, "binary STL header should be 80 zero bytes")


@check("trimesh.glb_export")
def trimesh_glb_export() -> None:
    scene = trimesh.Scene([trimesh.creation.box((10.0, 10.0, 10.0))])
    expect(scene.export(file_type="glb")[:4] == b"glTF", "GLB export should start with glTF")
    # Only trimesh's own dependency and the two graph engines may be imported.
    only = run_isolated("glb", ["numpy", "scipy", "networkx", "trimesh"])
    expect(only.returncode == 0, f"GLB export needs more than scipy and networkx:\n{only.stderr}")


# --- shapely ------------------------------------------------------------------------------


@check("shapely.operations")
def shapely_operations() -> None:
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    expect(close(square.buffer(-2.0, join_style="mitre").area, 36.0), "negative buffer insets")
    point = polylabel(square, tolerance=1e-3)
    expect(close(point.x, 5.0, 1e-3) and close(point.y, 5.0, 1e-3), "polylabel at the centre")
    expect(square.contains(Point(5, 5)), "contains")
    triangle = Polygon([(5, 5), (15, 5), (15, 15)])
    expect(close(square.intersection(triangle).area, 12.5), "intersection")


# --- matplotlib ---------------------------------------------------------------------------


@check("matplotlib.font_and_glyph_winding")
def matplotlib_font_and_glyph_winding() -> None:
    font = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
    expect(font.is_file(), f"bundled font missing: {font}")
    contours = TextPath((0, 0), "0", size=10.0, prop=FontProperties(fname=font)).to_polygons()
    areas = [signed_area(np.asarray(c)) for c in contours]
    expect(len(areas) == 2, f"'0' should have 2 contours, got {len(areas)}")
    outer, counter = sorted(areas, key=abs, reverse=True)
    expect(outer < 0, "the glyph's outer contour should be clockwise (EvenOdd required)")
    arrays = [np.asarray(c) for c in contours]
    even_odd = CrossSection(arrays, FillRule.EvenOdd).area()
    positive = CrossSection(arrays, FillRule.Positive).area()
    expect(close(even_odd, abs(outer) - abs(counter)), "EvenOdd should give outer minus counter")
    expect(not close(positive, even_odd, 1e-3), "Positive should not give the glyph")


# --- determinism --------------------------------------------------------------------------


def determinism_pipeline(out_dir: Path) -> None:
    """Split a model and drill holes, then write the pieces as STL (run in a subprocess)."""
    body = Manifold.sphere(30.0, 96) + Manifold.cube((40.0, 20.0, 20.0), center=True)
    pos, neg = body.split_by_plane((1.0, 0.0, 0.0), 3.0)
    hole = Manifold.cylinder(30.0, 2.7, circular_segments=64, center=True).rotate((0, 90, 0))
    for index, piece in enumerate((pos, neg)):
        drilled = piece - hole.translate((3.0, 5.0, 0.0)) - hole.translate((3.0, -5.0, 0.0))
        mesh = drilled.to_mesh()
        tm = trimesh.Trimesh(
            np.array(mesh.vert_properties[:, :3], dtype=np.float64),
            np.array(mesh.tri_verts, dtype=np.int64),
            process=False,
        )
        tm.export(out_dir / f"piece_{index}.stl", file_type="stl")


# --- pymeshlab (optional extra deep-repair) --------------------------------------------------


@check("pymeshlab.repair_filters")
def pymeshlab_repair_filters() -> None:
    try:
        import pymeshlab
    except ModuleNotFoundError as exc:
        raise SkippedError("pymeshlab is not installed (extra deep-repair)") from exc
    fin = finned_box()
    before = mesh_to_manifold(fin)
    expect(before.status() != Error.NoError, "the finned box should not be a valid manifold")
    meshes = pymeshlab.MeshSet()
    meshes.add_mesh(
        pymeshlab.Mesh(
            vertex_matrix=np.asarray(fin.vertices, dtype=np.float64),
            face_matrix=np.asarray(fin.faces, dtype=np.int32),
        )
    )
    meshes.meshing_repair_non_manifold_edges()
    meshes.meshing_repair_non_manifold_vertices()
    meshes.meshing_close_holes()
    meshes.meshing_re_orient_faces_coherently()
    expect(hasattr(pymeshlab, "PyMeshLabException"), "pymeshlab.PyMeshLabException exists")
    result = meshes.current_mesh()
    repaired = mesh_to_manifold(
        trimesh.Trimesh(result.vertex_matrix(), result.face_matrix(), process=False)
    )
    expect(repaired.status() == Error.NoError, f"repaired fin: {repaired.status()}")
    expect(close(repaired.volume(), 1000.0), f"repaired fin volume {repaired.volume()}")


@check("determinism.subprocess_bytes")
def determinism_subprocess_bytes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runs = [Path(tmp, "a"), Path(tmp, "b")]
        for run in runs:
            run.mkdir()
            env = {**os.environ, "PYTHONHASHSEED": "random"}
            subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--determinism-child", str(run)],
                check=True,
                env=env,
            )
        names = sorted(p.name for p in runs[0].iterdir())
        expect(names == sorted(p.name for p in runs[1].iterdir()), "different file sets")
        expect(len(names) == 2, f"expected 2 files, got {names}")
        for name in names:
            same = (runs[0] / name).read_bytes() == (runs[1] / name).read_bytes()
            expect(same, f"{name} differs between runs")


# --- runner -------------------------------------------------------------------------------


def print_versions() -> None:
    print(f"python {sys.version.split()[0]}")
    for package in PACKAGES:
        print(f"{package} {importlib.metadata.version(package)}")
    for package in OPTIONAL_PACKAGES:
        try:
            print(f"{package} {importlib.metadata.version(package)} (optional)")
        except importlib.metadata.PackageNotFoundError:
            print(f"{package} not installed (optional)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--determinism-child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.determinism_child is not None:
        determinism_pipeline(args.determinism_child)
        return 0

    print_versions()
    skipped = 0
    for name, fn in CHECKS:
        try:
            fn()
        except SkippedError as reason:
            print(f"skip {name}: {reason}")
            skipped += 1
            continue
        except Exception as exc:  # report any failure, including library errors
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            return 1
        print(f"ok   {name}")
    passed = len(CHECKS) - skipped
    print(f"all {passed} checks passed" + (f", {skipped} skipped" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
