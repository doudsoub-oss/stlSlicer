"""Shared test fixtures (PLAN.md Appendix D).

Fixtures are functions that build a mesh in code; ``write_stl`` turns one into a file in
``tmp_path``. Only the real models in ``tests/fixtures/real/`` are committed. Fixtures from
Appendix D are added in the phase that first uses them.

Valid solids are built as ``Manifold``. Broken or inside-out meshes (open, non-manifold,
reversed winding, unmerged) can't be a valid ``Manifold``, so they are built as
``trimesh.Trimesh`` with ``process=False``, which keeps them exactly as constructed.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

SPHERE_SEGMENTS = 64
"""Segments of the fixture spheres: the hollow sphere's volume is then 0.56 % under the
analytic value, inside the 1 % the Phase 2 test allows."""


def cube(size: float = 10.0) -> Manifold:
    """Axis-aligned cube with its minimum corner at the origin, mm."""
    return Manifold.cube((size, size, size))


def manifold_to_trimesh(body: Manifold) -> trimesh.Trimesh:
    """Convert without going through stlsplit, so fixtures don't depend on the code under test."""
    mesh = body.to_mesh()
    return trimesh.Trimesh(
        vertices=np.array(mesh.vert_properties[:, :3], dtype=np.float64),
        faces=np.array(mesh.tri_verts, dtype=np.int64),
        process=False,
    )


def _reversed(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    return trimesh.Trimesh(mesh.vertices, mesh.faces[:, ::-1], process=False)


def _concatenate(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    """Stack meshes without merging anything (the loader merges coincident vertices)."""
    vertices, faces, offset = [], [], 0
    for mesh in meshes:
        vertices.append(mesh.vertices)
        faces.append(mesh.faces + offset)
        offset += len(mesh.vertices)
    return trimesh.Trimesh(np.vstack(vertices), np.vstack(faces), process=False)


# --- Valid solids ------------------------------------------------------------------------------


def hollow_sphere() -> Manifold:
    """Sphere r = 150 with a concentric void r = 148: one positive and one negative shell."""
    return Manifold.sphere(150.0, SPHERE_SEGMENTS) - Manifold.sphere(148.0, SPHERE_SEGMENTS)


def ball_in_hollow_sphere() -> Manifold:
    """A ball r = 100 loose inside the hollow sphere's void (one level of nesting)."""
    return Manifold.compose([hollow_sphere(), Manifold.sphere(100.0, SPHERE_SEGMENTS)])


def void_in_ball_in_hollow_sphere() -> trimesh.Trimesh:
    """``ball_in_hollow_sphere`` with a void r = 50 inside the ball: two levels of nesting."""
    void = _reversed(manifold_to_trimesh(Manifold.sphere(50.0, SPHERE_SEGMENTS)))
    return _concatenate(manifold_to_trimesh(ball_in_hollow_sphere()), void)


def overlapping_hollow_spheres() -> trimesh.Trimesh:
    """Two hollow spheres 200 mm apart: each one's wall crosses the other's void."""
    first = manifold_to_trimesh(hollow_sphere())
    second = manifold_to_trimesh(hollow_sphere().translate((200.0, 0.0, 0.0)))
    return _concatenate(first, second)


def inside_out_hollow_sphere() -> trimesh.Trimesh:
    """The hollow sphere with every triangle reversed: valid, volume −554 829 mm³."""
    return _reversed(manifold_to_trimesh(hollow_sphere()))


def hollow_sphere_with_a_flipped_triangle(shell: int) -> trimesh.Trimesh:
    """The hollow sphere with one triangle reversed in one shell (0 outer, 1 void).

    The reversed triangle is the one trimesh's ``fix_winding`` orients that shell by: the
    shell's first face in ``face_adjacency`` order. ``fix_winding`` alone then reverses the
    shell's 2047 good triangles instead (docs/LIBRARY_NOTES.md).
    """
    mesh = manifold_to_trimesh(hollow_sphere())
    groups = trimesh.graph.connected_components(
        mesh.face_adjacency, nodes=np.arange(len(mesh.faces))
    )
    members = set(sorted(groups, key=lambda group: int(np.min(group)))[shell].tolist())
    order = dict.fromkeys(mesh.face_adjacency.ravel().tolist())
    reference = next(face for face in order if face in members)
    faces = np.array(mesh.faces)
    faces[reference] = faces[reference][::-1]
    return trimesh.Trimesh(mesh.vertices, faces, process=False)


def embedded_cube() -> trimesh.Trimesh:
    """A 5 mm cube entirely inside a 20 mm cube, both facing outwards (an unmerged part)."""
    return _concatenate(
        manifold_to_trimesh(cube(20.0)), manifold_to_trimesh(cube(5.0).translate((5, 5, 5)))
    )


def void_across_two_cubes(body_inside: bool = False) -> trimesh.Trimesh:
    """Overlapping 20 mm cubes (X from 0 to 20 and 10 to 30), a 20 × 4 × 4 void from X 5 to 25.

    The void lies inside their union but inside neither cube alone: volume 12 000 − 320. With
    ``body_inside``, a 2 mm cube floats in the void (+8 mm³).
    """
    void = Manifold.cube((20.0, 4.0, 4.0)).translate((5.0, 8.0, 8.0))
    meshes = [
        manifold_to_trimesh(cube(20.0)),
        manifold_to_trimesh(cube(20.0).translate((10.0, 0.0, 0.0))),
        _reversed(manifold_to_trimesh(void)),
    ]
    if body_inside:
        meshes.append(manifold_to_trimesh(cube(2.0).translate((14.0, 9.0, 9.0))))
    return _concatenate(*meshes)


def duplicated_cube(inside_out: bool = False) -> trimesh.Trimesh:
    """The same 10 mm cube twice (a body pasted onto itself), optionally both inside out."""
    mesh = manifold_to_trimesh(cube())
    if inside_out:
        mesh = _reversed(mesh)
    return _concatenate(mesh, mesh.copy())


def two_bodies() -> Manifold:
    """Two 10 mm cubes 10 mm apart along X."""
    return Manifold.compose([cube(), cube().translate((20.0, 0.0, 0.0))])


def dense_sphere() -> Manifold:
    """Sphere r = 20 with 256 segments: 0.5 mm edges, like a scan, that ``--simplify`` can thin.

    Coarser spheres can't be simplified at 0.05 mm: removing a vertex of a 128-segment
    sphere r = 50 would move the surface by about 0.06 mm.
    """
    return Manifold.sphere(20.0, 256)


# --- Meshes that need normalization or repair ---------------------------------------------------


def overlapping_shells() -> trimesh.Trimesh:
    """Two 20 mm cubes offset by 10 mm along X, concatenated: 12 000 mm³ once unioned."""
    first = manifold_to_trimesh(cube(20.0))
    second = manifold_to_trimesh(cube(20.0).translate((10.0, 0.0, 0.0)))
    return _concatenate(first, second)


def inverted_body() -> trimesh.Trimesh:
    """A 10 mm cube, and 10 mm away along X a 10 mm cube with reversed winding."""
    normal = manifold_to_trimesh(cube())
    flipped = _reversed(manifold_to_trimesh(cube().translate((20.0, 0.0, 0.0))))
    return _concatenate(normal, flipped)


def inside_out_cube() -> trimesh.Trimesh:
    """A single 10 mm cube with reversed winding: one component, volume −1000 mm³."""
    return _reversed(manifold_to_trimesh(cube()))


def soup_cube() -> trimesh.Trimesh:
    """A 10 mm cube as 12 unconnected triangles (36 vertices)."""
    merged = manifold_to_trimesh(cube())
    vertices = merged.vertices[merged.faces].reshape(-1, 3)
    faces = np.arange(len(vertices)).reshape(-1, 3)
    return trimesh.Trimesh(vertices, faces, process=False)


def missing_face_cube() -> trimesh.Trimesh:
    """A 10 mm cube without the two triangles of its x = 10 side: a quad hole."""
    mesh = manifold_to_trimesh(cube())
    on_side = np.isclose(mesh.vertices[mesh.faces][:, :, 0], 10.0).all(axis=1)
    return trimesh.Trimesh(mesh.vertices, mesh.faces[~on_side], process=False)


def capless_sphere() -> trimesh.Trimesh:
    """Sphere r = 20 without its top cap: one large hole that basic repair can't close."""
    mesh = manifold_to_trimesh(Manifold.sphere(20.0, 32))
    keep = mesh.vertices[mesh.faces].mean(axis=1)[:, 2] < 16.0
    capless = trimesh.Trimesh(mesh.vertices, mesh.faces[keep], process=False)
    capless.remove_unreferenced_vertices()
    return capless


def finned_cube() -> trimesh.Trimesh:
    """A 10 mm cube with one stray triangle hanging off its edge x = y = 10.

    The edge then has three faces (non-manifold) and the fin adds two open edges. Basic
    repair can't fix that; pymeshlab removes the fin.
    """
    mesh = manifold_to_trimesh(cube())
    bottom = int(np.argmin(np.linalg.norm(mesh.vertices - (10.0, 10.0, 0.0), axis=1)))
    top = int(np.argmin(np.linalg.norm(mesh.vertices - (10.0, 10.0, 10.0), axis=1)))
    vertices = np.vstack([mesh.vertices, [(15.0, 15.0, 5.0)]])
    faces = np.vstack([mesh.faces, [(bottom, top, len(mesh.vertices))]])
    return trimesh.Trimesh(vertices, faces, process=False)


def edge_touching_cubes() -> trimesh.Trimesh:
    """Two 10 mm cubes sharing the edge x = y = 10 (merged into shared vertices on load)."""
    first = manifold_to_trimesh(cube())
    second = manifold_to_trimesh(cube().translate((10.0, 10.0, 0.0)))
    return _concatenate(first, second)


def flat_sheet() -> trimesh.Trimesh:
    """A 10 mm square made of the same two triangles facing both ways: closed, no volume."""
    vertices = np.array([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], dtype=np.float64)
    faces = np.array([(0, 1, 2), (0, 2, 3), (2, 1, 0), (3, 2, 0)])
    return trimesh.Trimesh(vertices, faces, process=False)


def open_edge_count(mesh: trimesh.Trimesh) -> int:
    """Edges used by exactly one triangle, counted without going through stlsplit."""
    edges = np.sort(mesh.faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int(np.count_nonzero(counts == 1))


@pytest.fixture
def write_stl(tmp_path: Path) -> Callable[[Manifold | trimesh.Trimesh, str], Path]:
    """Return a helper that writes a solid or a mesh to ``tmp_path/<name>.stl`` (binary STL)."""

    def _write(body: Manifold | trimesh.Trimesh, name: str = "model") -> Path:
        path = tmp_path / f"{name}.stl"
        mesh = body if isinstance(body, trimesh.Trimesh) else manifold_to_trimesh(body)
        mesh.export(path, file_type="stl")
        return path

    return _write
