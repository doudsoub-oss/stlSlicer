"""Phase 5: connector placement on cut pieces, with the 3D checks (PLAN.md Phase 5).

Bodies are in the cutting frame (``oriented``), and most grids are built by hand to put a
plane exactly where the case needs it (``hand_grid``, as in ``test_cutting.py``). With the
defaults (d = 5): r_h = 2.7, w = 2, r_h + w = 4.7, h(20) = 10.5, h(18) = 9.5, h(16) = 8.5, and
the rays are h(20) + w + 1 = 13.5 mm long.
"""

import itertools
import math
from typing import Any

import pytest
import shapely
from manifold3d import Manifold

from stlsplit import config, connectors, cutting, geometry, grid
from stlsplit.config import RAY_START_OFFSET, Config
from stlsplit.models import Connector, CutFace, Grid
from tests.conftest import SLIT_BLOCK_CUT, cube, hollow_sphere, slit_block, wedge, wide_u_shape
from tests.integration.test_cutting import even, hand_grid, make, oriented

WALL = Config().connectors.min_wall
GAP_TOLERANCE = 1e-9


def split(body: Manifold, layout: Grid, cfg: Config) -> cutting.Cut:
    return cutting.cut(body, layout, cfg, body.volume())


def place(
    body: Manifold, layout: Grid, overrides: dict[str, Any] | None = None
) -> tuple[cutting.Cut, connectors.Placement]:
    cfg = make(overrides)
    result = split(body, layout, cfg)
    return result, connectors.place(result.pieces, result.faces, cfg)


def codes(placement: connectors.Placement) -> list[str]:
    return [item.code for item in placement.diagnostics]


def on_face(placement: connectors.Placement, face: CutFace) -> list[Connector]:
    return [c for c in placement.connectors if c.face_id == face.id]


def assert_inside_safe_regions(result: cutting.Cut, placement: connectors.Placement) -> None:
    """I6: every connector's axis point lies inside its face's safe region."""
    faces = {face.id: face for face in result.faces}
    for connector in placement.connectors:
        safe = connectors.safe_region(faces[connector.face_id].region, Config())
        assert shapely.contains_xy(safe, *connector.position_uv), connector.id


def assert_holes_keep_min_wall(
    result: cutting.Cut, placement: connectors.Placement, cfg: Config
) -> None:
    """I5: no two holes of the same piece are closer than ``min_wall`` (``min_gap``)."""
    faces = {face.id: face for face in result.faces}
    holes: dict[str, list[Manifold]] = {}
    for connector in placement.connectors:
        for piece_id, hole in connectors.hole_solids(connector, faces[connector.face_id], cfg):
            holes.setdefault(piece_id, []).append(hole)
    for piece_holes in holes.values():
        for a, b in itertools.combinations(piece_holes, 2):
            assert a.min_gap(b, WALL + 1.0) >= WALL - GAP_TOLERANCE


def test_100_mm_face_gets_4_connectors_in_the_corners_of_its_safe_region() -> None:
    body = oriented(Manifold.cube((200.0, 100.0, 100.0)))
    layout = even(body, (110.0, 110.0, 110.0))
    assert layout.counts == (2, 1, 1)
    result, placement = place(body, layout)

    face = result.faces[0]
    assert [c.id for c in placement.connectors] == [f"{face.id}/c{n}" for n in range(1, 5)]
    assert [c.position_uv for c in placement.connectors] == [
        (6.25, 6.25),
        (93.75, 93.75),
        (6.25, 93.75),
        (93.75, 6.25),
    ]
    for connector in placement.connectors:
        assert connector.kind == "dowel"
        assert connector.diameter == 5.0
        assert (connector.pin_length, connector.hole_depth_neg, connector.hole_depth_pos) == (
            20.0,
            10.5,
            10.5,
        )
    for a, b in itertools.combinations(placement.connectors, 2):
        assert math.dist(a.position_uv, b.position_uv) >= 15.0
    assert placement.diagnostics == ()
    assert_inside_safe_regions(result, placement)
    assert connectors.place(result.pieces, result.faces, Config()) == placement


def test_40_mm_face_gets_2_connectors_although_its_safe_region_is_under_a() -> None:
    body = oriented(Manifold.cube((80.0, 40.0, 40.0)))
    layout = even(body, (40.0, 40.0, 40.0))
    assert layout.counts == (2, 1, 1)
    result, placement = place(body, layout)

    safe = connectors.safe_region(result.faces[0].region, Config())
    assert safe.area == pytest.approx(888.04)  # < A = 900 mm²
    assert [c.position_uv for c in placement.connectors] == [(6.25, 6.25), (33.75, 33.75)]
    assert placement.diagnostics == ()


def test_hollow_sphere_ring_gets_no_connector_and_w001() -> None:
    cfg = make({"printer.bed": (320.0, 320.0, 220.0)})
    body, _ = grid.orient(hollow_sphere(), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    result = split(body, layout, cfg)
    placement = connectors.place(result.pieces, result.faces, cfg)

    assert placement.connectors == []
    assert codes(placement) == ["W001"]
    assert placement.diagnostics[0].refs == (result.faces[0].id,)
    assert "no room" in placement.diagnostics[0].message


def test_u_shaped_face_gets_a_connector_in_each_arm() -> None:
    body = wide_u_shape()
    layout = hand_grid(body, (100.0, 30.0, 60.0), ((), (30.0,), ()))
    result, placement = place(body, layout)

    face = result.faces[0]  # a Y plane: u = world Z, v = world X
    assert len(connectors.safe_region(face.region, Config()).geoms) == 2
    xs = sorted(c.position_uv[1] for c in placement.connectors)
    assert len(xs) == 2
    assert xs[0] < 20.0 < 80.0 < xs[1]
    assert placement.diagnostics == ()
    assert_inside_safe_regions(result, placement)


def test_wedge_narrowing_behind_the_face_shortens_or_rejects_the_connector() -> None:
    body = wedge()
    layout = hand_grid(body, (40.0, 40.0, 40.0), ((40.0,), (), ()))
    cfg = make()
    result = split(body, layout, cfg)
    face = result.faces[0]  # an X plane: u = world Y, v = world Z
    bodies = {piece.id: piece.body for piece in result.pieces}
    narrow = bodies[face.piece_pos]
    ray_length = config.derived(cfg).ray_length

    # At y = 30.5 the axis ray is long (the top is 23.75 mm away), but the ray at
    # r_h + w = 4.7 mm towards the top reaches it at 12 mm: available 10, so L = 18.
    axis_origin = (40.0 + RAY_START_OFFSET, 30.5, 20.0)
    assert geometry.ray_depth(narrow, axis_origin, (1.0, 0.0, 0.0), ray_length) is None
    available = connectors.available_depth(narrow, face.plane, (30.5, 20.0), 1, cfg)
    assert available == pytest.approx(10.0)
    shortened = connectors.check_candidate(face, (30.5, 20.0), bodies, {}, cfg)
    assert shortened is not None
    assert shortened.length == 18.0
    # At y = 31.25 that ray reaches the top at 10.125 mm: under h(16) + w, rejected.
    assert connectors.check_candidate(face, (31.25, 20.0), bodies, {}, cfg) is None
    full = connectors.check_candidate(face, (20.0, 20.0), bodies, {}, cfg)
    assert full is not None
    assert full.length == 20.0

    placement = connectors.place(result.pieces, result.faces, cfg)
    assert placement.connectors
    for connector in placement.connectors:
        for piece_id, side in ((face.piece_neg, -1), (face.piece_pos, 1)):
            assert connectors.fits_inside(
                bodies[piece_id], face.plane, connector.position_uv, side, connector.pin_length, cfg
            )
        assert connector.position_uv[0] <= 30.7  # nothing near the sloping top


def test_containment_catches_a_narrowing_that_the_rays_miss() -> None:
    # A small void in the pos piece, between the rays at 0 and 45 degrees around the axis
    # (24.7, 20) and (23.3, 23.3): no ray hits it, but it is 4.1 mm from the axis, inside the
    # cylinder of radius r_h + w = 4.7.
    pocket = Manifold.cube((7.0, 0.6, 0.6)).translate((103.0, 23.86, 21.42))
    body = Manifold.cube((140.0, 40.0, 40.0)) - pocket
    layout = hand_grid(body, (100.0, 40.0, 40.0), ((100.0,), (), ()))
    cfg = make()
    result = split(body, layout, cfg)
    face = result.faces[0]
    bodies = {piece.id: piece.body for piece in result.pieces}
    pos = bodies[face.piece_pos]

    assert connectors.available_depth(pos, face.plane, (20.0, 20.0), 1, cfg) is None
    assert not connectors.fits_inside(pos, face.plane, (20.0, 20.0), 1, 16.0, cfg)
    assert connectors.check_candidate(face, (20.0, 20.0), bodies, {}, cfg) is None


@pytest.mark.parametrize(
    ("behind", "length", "code"),
    [pytest.param(12.0, 18.0, "W002", id="12-mm"), pytest.param(6.0, None, "W001", id="6-mm")],
)
def test_material_behind_the_face_limits_the_pin_length(
    behind: float, length: float | None, code: str
) -> None:
    body = oriented(Manifold.cube((100.0 + behind, 40.0, 40.0)))
    layout = hand_grid(body, (100.0, 40.0, 40.0), ((100.0,), (), ()))
    cfg = make()
    result, placement = place(body, layout)
    face = result.faces[0]
    pos = next(piece.body for piece in result.pieces if piece.id == face.piece_pos)

    available = connectors.available_depth(pos, face.plane, (20.0, 20.0), 1, cfg)
    assert available == pytest.approx(behind - WALL)
    assert codes(placement) == [code]
    assert placement.diagnostics[0].refs[0] == face.id
    if length is None:
        assert placement.connectors == []
    else:
        assert len(placement.connectors) == 2
        for connector in placement.connectors:
            assert connector.pin_length == length
            assert connector.hole_depth_neg == connector.hole_depth_pos == 9.5
        assert placement.diagnostics[0].refs[1:] == tuple(c.id for c in placement.connectors)


def test_holes_of_every_piece_of_the_2x2x2_cube_keep_min_wall_between_them() -> None:
    cfg = make({"printer.bed": (120.0, 120.0, 120.0)})
    body, _ = grid.orient(cube(200.0), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    result = split(body, layout, cfg)
    placement = connectors.place(result.pieces, result.faces, cfg)

    assert len(result.faces) == 12
    for face in result.faces:
        assert len(on_face(placement, face)) >= 2, face.id
    assert "W001" not in codes(placement)
    assert_holes_keep_min_wall(result, placement, cfg)
    assert_inside_safe_regions(result, placement)


def test_15_mm_pieces_get_no_intersecting_holes_and_w001_where_there_is_no_room() -> None:
    cfg = make({"printer.bed": (30.0, 30.0, 30.0)})  # U = 20: 3 × 3 × 3 cells of 15 mm
    body, _ = grid.orient(cube(45.0), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    assert layout.counts == (3, 3, 3)
    result = split(body, layout, cfg)
    placement = connectors.place(result.pieces, result.faces, cfg)

    assert_holes_keep_min_wall(result, placement, cfg)
    with_connectors = {c.face_id for c in placement.connectors}
    without = {d.refs[0] for d in placement.diagnostics if d.code == "W001"}
    single = {d.refs[0] for d in placement.diagnostics if d.code == "W009"}
    assert without
    assert with_connectors
    assert with_connectors.isdisjoint(without)
    assert with_connectors | without == {face.id for face in result.faces}
    assert single == with_connectors  # 15 mm faces hold one connector at most


def test_pegs_need_a_hole_on_the_pos_side_only() -> None:
    # 6 mm behind the face on the neg side, where the peg stands: no hole there.
    body = oriented(Manifold.cube((106.0, 40.0, 40.0)))
    layout = hand_grid(body, (100.0, 40.0, 40.0), ((6.0,), (), ()))
    result, placement = place(body, layout, {"connectors.type": "peg"})

    assert len(placement.connectors) == 2
    for connector in placement.connectors:
        assert connector.kind == "peg"
        assert (connector.pin_length, connector.hole_depth_neg, connector.hole_depth_pos) == (
            20.0,
            0.0,
            10.5,
        )
    face = result.faces[0]
    holes = connectors.hole_solids(placement.connectors[0], face, make({"connectors.type": "peg"}))
    assert [piece_id for piece_id, _ in holes] == [face.piece_pos]
    assert placement.diagnostics == ()


def test_connector_type_none_places_nothing_and_reports_nothing() -> None:
    body = oriented(Manifold.cube((80.0, 40.0, 40.0)))
    layout = even(body, (40.0, 40.0, 40.0))
    _, placement = place(body, layout, {"connectors.type": "none"})
    assert placement == connectors.Placement(connectors=[], diagnostics=())


# --- the pin-length search (Phase 10) ----------------------------------------------------------

MANY_LENGTHS = {"connectors.length": 60.0, "advanced.pin_length_step": 0.1}
"""451 standard lengths, from 60 down to 15 mm."""


def slit_face() -> tuple[CutFace, dict[str, Manifold], Config]:
    body = slit_block()
    layout = hand_grid(body, (210.0, 210.0, 240.0), ((SLIT_BLOCK_CUT,), (), ()))
    cfg = make(MANY_LENGTHS)
    result = split(body, layout, cfg)
    return result.faces[0], {piece.id: piece.body for piece in result.pieces}, cfg


def test_a_candidate_no_length_fits_is_rejected_without_trying_every_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    face, bodies, cfg = slit_face()
    assert len(config.derived(cfg).standard_lengths) == 451
    calls = 0
    real = connectors.fits_inside

    def counting(*args: Any) -> bool:
        nonlocal calls
        calls += 1
        return real(*args)

    monkeypatch.setattr(connectors, "fits_inside", counting)
    assert connectors.check_candidate(face, (50.0, 50.0), bodies, {}, cfg) is None
    assert calls <= 2  # the longest length, on each side at most


@pytest.mark.parametrize("many_lengths", [False, True], ids=["default-lengths", "451-lengths"])
def test_the_early_rejection_gives_the_same_length_as_trying_all(many_lengths: bool) -> None:
    body = oriented(wedge())
    layout = hand_grid(body, (60.0, 60.0, 60.0), ((40.0,), (), ()))
    cfg = make(MANY_LENGTHS if many_lengths else None)
    result = split(body, layout, cfg)
    face = result.faces[0]
    bodies = {piece.id: piece.body for piece in result.pieces}
    sides = ((face.piece_neg, -1), (face.piece_pos, 1))
    for u, v in itertools.product((10.0, 20.0, 28.0, 30.5, 31.25, 33.0, 34.5), (8.0, 20.0)):
        limits = [
            depth
            for depth in (
                connectors.available_depth(bodies[piece], face.plane, (u, v), side, cfg)
                for piece, side in sides
            )
            if depth is not None
        ]
        lengths = connectors.lengths_that_fit(min(limits) if limits else None, cfg)
        expected = next(
            (
                pin
                for pin in lengths
                if all(
                    connectors.fits_inside(bodies[piece], face.plane, (u, v), side, pin, cfg)
                    for piece, side in sides
                )
            ),
            None,
        )
        found = connectors.check_candidate(face, (u, v), bodies, {}, cfg)
        assert (found.length if found else None) == expected, (u, v)
