"""Shared test fixtures (PLAN.md Appendix D).

Fixtures are functions that build a mesh in code; ``write_stl`` turns one into a file in
``tmp_path``. Only the real models in ``tests/fixtures/real/`` are committed. Fixtures from
Appendix D are added in the phase that first uses them.

Valid solids are built as ``Manifold``. Broken or inside-out meshes (open, non-manifold,
reversed winding, unmerged) can't be a valid ``Manifold``, so they are built as
``trimesh.Trimesh`` with ``process=False``, which keeps them exactly as constructed.
"""

import math
import os
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pytest
import trimesh
from hypothesis import settings
from manifold3d import CrossSection, Manifold, OpType

# Hypothesis is derandomized in CI, so a run is reproducible (PLAN.md §4.4, rule 1); local runs
# stay random and explore more. GitHub Actions sets CI=true.
settings.register_profile("ci", derandomize=True)
if os.environ.get("CI"):
    settings.load_profile("ci")

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


def long_box() -> Manifold:
    """A 500 × 100 × 100 box with its minimum corner at the origin (the grid tests)."""
    return Manifold.cube((500.0, 100.0, 100.0))


CHIRAL_L_MARKS: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.0, 0.0),
    (40.0, 0.0, 0.0),
    (0.0, 30.0, 0.0),
    (0.0, 0.0, 20.0),
)
"""Vertices of ``chiral_l``: the corner, then the tips of the X, Y and Z arms. The edge
vectors from the corner to the tips have a positive triple product (40 · 30 · 20)."""


def chiral_l() -> Manifold:
    """A 10 mm corner cube with arms of 3, 2 and 1 more cubes along X, Y and Z.

    Three arms of different lengths make it chiral: its mirror image can't be rotated onto
    it. A flat L would not do, since it is its own mirror image through its mid-plane.
    """
    return Manifold.batch_boolean(
        [
            Manifold.cube((40.0, 10.0, 10.0)),
            Manifold.cube((10.0, 30.0, 10.0)),
            Manifold.cube((10.0, 10.0, 20.0)),
        ],
        OpType.Add,
    )


def two_bodies() -> Manifold:
    """Two 10 mm cubes 10 mm apart along X."""
    return Manifold.compose([cube(), cube().translate((20.0, 0.0, 0.0))])


def dense_sphere() -> Manifold:
    """Sphere r = 20 with 256 segments: 0.5 mm edges, like a scan, that ``--simplify`` can thin.

    Coarser spheres can't be simplified at 0.05 mm: removing a vertex of a 128-segment
    sphere r = 50 would move the surface by about 0.06 mm.
    """
    return Manifold.sphere(20.0, 256)


def cylinder() -> Manifold:
    """A cylinder along Z, r = 60 and 300 mm tall: the default bed cuts it across, a round face."""
    return Manifold.cylinder(300.0, 60.0, circular_segments=SPHERE_SEGMENTS)


TORUS_MAJOR_RADIUS = 60.0
TORUS_MINOR_RADIUS = 15.0


def torus() -> Manifold:
    """Torus around Z, centred on the origin: tube r = 15 at R = 60 (150 × 150 × 30 mm).

    ``revolve`` puts one of its 64 steps at every quarter turn, so the planes x = 0 and
    y = 0 cut the tube through polygon vertices.
    """
    circle = CrossSection.circle(TORUS_MINOR_RADIUS, 32).translate((TORUS_MAJOR_RADIUS, 0.0))
    return Manifold.revolve(circle, 64)


def u_shape() -> Manifold:
    """A U extruded 20 mm along Y: a 60 × 10 base (Z 0 to 10) and two 10 mm arms up to Z = 50.

    Its profile (in the XZ plane) has an area of 600 + 2 × 400 = 1400 mm².
    """
    return Manifold.batch_boolean(
        [
            Manifold.cube((60.0, 20.0, 10.0)),
            Manifold.cube((10.0, 20.0, 50.0)),
            Manifold.cube((10.0, 20.0, 50.0)).translate((50.0, 0.0, 0.0)),
        ],
        OpType.Add,
    )


def wide_u_shape() -> Manifold:
    """A U extruded 60 mm along Y: a 100 × 10 base (Z 0 to 10) and two 20 mm arms up to Z = 60.

    ``u_shape``'s arms are too thin for a connector. Cut at y = 30, this face is the U itself;
    inset by the default safe inset (5.1 mm) the base has no room left, so the safe region is
    one strip in each arm, and both sides of the face are 30 mm deep.
    """
    return Manifold.batch_boolean(
        [
            Manifold.cube((100.0, 60.0, 10.0)),
            Manifold.cube((20.0, 60.0, 60.0)),
            Manifold.cube((20.0, 60.0, 60.0)).translate((80.0, 0.0, 0.0)),
        ],
        OpType.Add,
    )


def crossed_loop() -> Manifold:
    """One closed loop that crosses the plane x = 25 four times (PLAN.md Appendix E, r12).

    Four 8 mm columns run along X at the corners of a 38 mm square. Below the plane, a far plate
    (x 0 to 5) joins two opposite columns, and a near plate (x 10 to 16), notched around those
    two, joins the other two. Above it, two bars (x 40 to 50) join the columns in pairs the
    other way. Each side holds two bodies, and each body touches both bodies across the plane.
    The near plate can only go in before the far plate, which lies in its way along X.
    """

    def block(low: tuple[float, float, float], high: tuple[float, float, float]) -> Manifold:
        size = (high[0] - low[0], high[1] - low[1], high[2] - low[2])
        return Manifold.cube(size).translate(low)

    near_plate = (
        block((10.0, 0.0, 0.0), (16.0, 38.0, 38.0))
        - block((9.0, -1.0, -1.0), (17.0, 11.0, 11.0))
        - block((9.0, 27.0, 27.0), (17.0, 39.0, 39.0))
    )
    return Manifold.batch_boolean(
        [
            block((0.0, 0.0, 0.0), (5.0, 38.0, 38.0)),
            near_plate,
            block((40.0, 0.0, 0.0), (50.0, 38.0, 8.0)),
            block((40.0, 0.0, 30.0), (50.0, 38.0, 38.0)),
            block((0.0, 0.0, 0.0), (50.0, 8.0, 8.0)),
            block((0.0, 30.0, 30.0), (50.0, 38.0, 38.0)),
            block((10.0, 0.0, 30.0), (50.0, 8.0, 38.0)),
            block((10.0, 30.0, 0.0), (50.0, 38.0, 8.0)),
        ],
        OpType.Add,
    )


def _union_of_boxes(*corners: tuple[tuple[float, ...], tuple[float, ...]]) -> Manifold:
    boxes = [
        Manifold.cube((hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])).translate(
            (lo[0], lo[1], lo[2])
        )
        for lo, hi in corners
    ]
    return Manifold.batch_boolean(boxes, OpType.Add)


def hooked_strips() -> Manifold:
    """Three strips on each side of x = 10, woven into one solid (PLAN.md Appendix E, r12).

    A hook of the third strip lies behind the first one on each side, so the first must come
    off before the third. Taking off the first clear candidate in piece order strands it: a
    fully clear order exists, but only a search with backtracking finds it.
    """
    return _union_of_boxes(
        ((5, 12, 0), (10, 50, 10)),
        ((5, 0, 20), (10, 38, 30)),
        ((5, 0, 1), (10, 4, 20)),
        ((5, 0, 40), (10, 50, 50)),
        ((0, 40, 40), (5, 44, 50)),
        ((0, 40, 5), (3, 44, 50)),
        ((10, 0, 0), (15, 10, 56)),
        ((10, 20, 0), (15, 30, 50)),
        ((10, 40, 1), (15, 50, 56)),
        ((15, 40, 52), (20, 50, 56)),
        ((17, 0, 52), (20, 50, 56)),
    )


def interlocked_bodies() -> Manifold:
    """Two bodies below x = 10, each in the other's way along X, held by a block above it (r12).

    No order of straight moves along X can put them together: W013.
    """
    return _union_of_boxes(
        ((0, 0, 0), (4, 10, 10)),
        ((0, 10, 0), (10, 20, 10)),
        ((6, 20, 0), (10, 30, 10)),
        ((6, 0, 0), (10, 9, 20)),
        ((0, 21, 0), (4, 30, 20)),
        ((0, 0, 12), (10, 30, 20)),
        ((10, 0, 0), (20, 30, 20)),
    )


WEDGE_SLOPE = 0.4
"""How fast the top of ``wedge`` falls behind its cut face, mm per mm along X."""


def wedge() -> Manifold:
    """A block that narrows behind its cut face: the profile below, extruded 40 mm along Z.

    In the XY plane: (0, 0), (80, 0), (80, 24), (40, 40), (0, 40). Cut at x = 40, the face is
    40 × 40 (u = y, v = z). On the +X side the top falls ``WEDGE_SLOPE`` mm per mm, so near the
    top a side wall comes within r_h + w = 4.7 mm of a hole whose axis ray still travels more
    than h(L_max) + w + 1 = 13.5 mm before reaching it (Appendix D).
    """
    top = 40.0 - WEDGE_SLOPE * 40.0
    outline = np.array([(0.0, 0.0), (80.0, 0.0), (80.0, top), (40.0, 40.0), (0.0, 40.0)])
    return Manifold.extrude(CrossSection([outline]), 40.0)


def plinth_step() -> Manifold:
    """A 10 × 10 × 20 box standing on a 40 × 40 × 10 plinth: a step at z = 10, 100 mm² contact."""
    return Manifold.cube((40.0, 40.0, 10.0)) + Manifold.cube((10.0, 10.0, 20.0)).translate(
        (15.0, 15.0, 10.0)
    )


def overhang_step() -> Manifold:
    """A 40 × 40 × 10 plate on a 10 × 10 × 10 column: the other step direction, at z = 10."""
    return Manifold.cube((10.0, 10.0, 10.0)).translate((15.0, 15.0, 0.0)) + Manifold.cube(
        (40.0, 40.0, 10.0)
    ).translate((0.0, 0.0, 10.0))


KNOB_PLANES: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]] = (
    (100.0,),
    (100.0,),
    (),
)
"""Plane offsets per axis that the knob tests cut ``knob`` with: x = 100 crosses the knob,
y = 100 halves the box (so the piece that absorbs the knob tip keeps a cut face)."""


def knob(blocked: bool = False, rounded: bool = False) -> Manifold:
    """A 95 × 200 × 100 box with a small knob on its +X face, centred at y = z = 50.

    The knob is 6 × 6 mm from x = 90 to 105, so x = 100 leaves a 180 mm³ tip on its own
    (``KNOB_PLANES``). ``rounded`` makes it a ball r = 6 centred at x = 100 instead: the plane
    then passes through the ball's equator vertices, and the tip is 450 mm³. ``blocked`` adds a
    10 × 20 × 20 block at x = 110 to 120 on the knob's axis, in the tip's cell, overlapping its
    footprint along X.
    """
    box = Manifold.cube((95.0, 200.0, 100.0))
    if rounded:
        body = box + Manifold.sphere(6.0, SPHERE_SEGMENTS).translate((100.0, 50.0, 50.0))
    else:
        body = box + Manifold.cube((15.0, 6.0, 6.0)).translate((90.0, 47.0, 47.0))
    if blocked:
        body = Manifold.compose([body, Manifold.cube((10.0, 20.0, 20.0)).translate((110, 40, 40))])
    return body


def knob_on_grid(blocked: bool = False, rounded: bool = False) -> Manifold:
    """``knob`` plus a far 10 × 20 × 20 block, so that the CLI's even grid cuts it at x = 100.

    The block makes the model 200 mm long. On a 120 × 120 × 220 bed, without auto-orient and with
    ``nudge_window = 0``, the planes are then ``KNOB_PLANES``: the merge is reachable end to end.
    """
    far = Manifold.cube((10.0, 20.0, 20.0)).translate((190.0, 150.0, 40.0))
    return Manifold.compose([knob(blocked, rounded), far])


def box_with_bubble() -> Manifold:
    """A 300 × 100 × 100 box with a sphere r = 20 void centred at x = 50 (away from x = 150)."""
    bubble = Manifold.sphere(20.0, 32).translate((50.0, 50.0, 50.0))
    return Manifold.cube((300.0, 100.0, 100.0)) - bubble


TALL_FIGURE_WIDTH = 60.0
"""Side of the square boxes of ``tall_figure``, mm."""

TALL_FIGURE_NECK = 6.0
"""Side of the square necks of ``tall_figure``, mm: 36 mm², a tiny island (under 78.5 mm²)
with no room for a connector."""


def tall_figure(
    height: float = 300.0, necks: Sequence[tuple[float, float]] = ((148.0, 153.0),)
) -> Manifold:
    """Square boxes stacked along Z, joined by thin square necks (the nudging tests).

    The boxes are ``TALL_FIGURE_WIDTH`` wide and the necks ``TALL_FIGURE_NECK``, centred on
    them, with the minimum corner at the origin. Each neck spans the given (bottom, top) along
    Z, and a box fills the space between two necks. By default the figure is 300 mm tall, so the
    default bed (U_z = 240) cuts it once, at z = 150, through the neck from 148 to 153.

    Args:
        height: Total height, mm.
        necks: (bottom, top) of each neck, mm, increasing and inside (0, height).
    """
    side, neck = TALL_FIGURE_WIDTH, TALL_FIGURE_NECK
    tops = [0.0, *(top for _, top in necks)]
    bottoms = [*(bottom for bottom, _ in necks), height]
    parts = [
        Manifold.cube((side, side, high - low)).translate((0.0, 0.0, low))
        for low, high in zip(tops, bottoms, strict=True)
    ]
    # Each neck reaches 1 mm into its boxes, so the union never joins faces that only touch.
    corner = (side - neck) / 2
    parts += [
        Manifold.cube((neck, neck, top - bottom + 2.0)).translate((corner, corner, bottom - 1.0))
        for bottom, top in necks
    ]
    return Manifold.batch_boolean(parts, OpType.Add)


def many_bodies() -> Manifold:
    """125 separate 30 mm cubes on a 70 mm lattice, 310 mm wide (Phase 10).

    The default bed cuts it at 155 mm along each axis, through the middle layer of cubes: 216
    pieces, 27 of them in each cell, so piece suffixes go past ``-z`` to ``-aa``. The eight
    15 mm cubes around the centre have no room for three perpendicular sets of holes: W001.
    """
    return Manifold.compose(
        [
            Manifold.cube((30.0, 30.0, 30.0)).translate((70.0 * i, 70.0 * j, 70.0 * k))
            for i in range(5)
            for j in range(5)
            for k in range(5)
        ]
    )


def thin_plate() -> Manifold:
    """A 400 × 100 × 0.2 mm plate: cut across, its faces are too thin for a connector."""
    return Manifold.cube((400.0, 100.0, 0.2))


def finned_block() -> Manifold:
    """A 300 × 60 × 60 block with a 0.05 mm fin on top that crosses the cut at x = 150."""
    fin = Manifold.cube((200.0, 0.05, 40.0)).translate((50.0, 30.0, 59.0))
    return Manifold.cube((300.0, 60.0, 60.0)) + fin


SLIT_BLOCK_CUT = 200.0
"""Where the default bed cuts ``slit_block`` along X, mm."""


def slit_block() -> Manifold:
    """A 400 × 100 × 100 block with thin internal slits just behind its cut (Phase 10).

    The cut face is whole, and the depth rays mostly pass between the slits (0.02 mm thick,
    7 mm apart), but every 9.4 mm containment cylinder crosses one, so no pin length fits.
    """
    slits = [
        Manifold.cube((140.0, 0.02, 96.0)).translate((SLIT_BLOCK_CUT + 1.0, 3.5 + 7.0 * k, 2.0))
        for k in range(14)
    ]
    return Manifold.cube((400.0, 100.0, 100.0)) - Manifold.batch_boolean(slits, OpType.Add)


SPHERE_UNION_TRIANGLES_PER_SQUARED_SEGMENT = 2.475
"""Triangles of ``refined_sphere_union`` per squared segment count, measured at 636 and 900."""


def refined_sphere_union(triangles: int) -> Manifold:
    """Eight overlapping spheres r = 100 on a 150 mm lattice (Phase 10, performance).

    350 mm wide, so the default bed cuts it into 2 × 2 × 2 pieces.

    Args:
        triangles: About how many triangles the union should have.
    """
    root = math.sqrt(triangles / SPHERE_UNION_TRIANGLES_PER_SQUARED_SEGMENT)
    segments = 4 * math.ceil(root / 4)  # manifold3d rounds sphere segments to a multiple of 4
    spheres = [
        Manifold.sphere(100.0, segments).translate(
            (100.0 + 150.0 * i, 100.0 + 150.0 * j, 100.0 + 150.0 * k)
        )
        for i in range(2)
        for j in range(2)
        for k in range(2)
    ]
    return Manifold.batch_boolean(spheres, OpType.Add)


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
