"""Phase 4: splitting, piece IDs, cut faces and the small-piece merge (PLAN.md Phase 4).

Most tests build the grid by hand (``hand_grid``) to put a plane exactly where the case
needs it; nudging (Phase 6) produces such uneven grids too. Bodies are in the cutting frame:
fixtures that don't start at the origin go through ``oriented`` first.
"""

import itertools
import logging
import math
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from manifold3d import Error, Manifold

from stlsplit import config, cutting, geometry, grid
from stlsplit.config import MERGE_MARGIN, Config
from stlsplit.models import Grid, Piece, Plane
from tests.conftest import (
    KNOB_PLANES,
    box_with_bubble,
    cube,
    hollow_sphere,
    knob,
    overhang_step,
    plinth_step,
    torus,
)

EPS = Config().advanced.section_epsilon
KNOB_USABLE = (110.0, 110.0, 210.0)


def make(overrides: dict[str, Any] | None = None) -> Config:
    cfg = config.with_overrides(Config(), overrides or {}, "test")
    config.validate(cfg)
    return cfg


def oriented(body: Manifold) -> Manifold:
    """``body`` moved into the cutting frame without rotating it (bbox minimum at 0)."""
    return grid.to_cutting_frame(body, grid.ROTATIONS[0])[0]


def even(body: Manifold, usable: tuple[float, float, float]) -> Grid:
    return grid.even_grid(grid.extent(body), usable)[0]


def hand_grid(
    body: Manifold,
    usable: tuple[float, float, float],
    offsets: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
) -> Grid:
    """A grid with planes at the given offsets (each cell must fit ``usable``)."""
    x, y, z = (
        tuple(Plane(axis=axis, index=index, offset=o) for index, o in enumerate(values))  # type: ignore[arg-type]
        for axis, values in enumerate(offsets)
    )
    counts = (len(x) + 1, len(y) + 1, len(z) + 1)
    return Grid(usable=usable, counts=counts, planes=(x, y, z), extent=grid.extent(body))


def run(body: Manifold, layout: Grid, **advanced: float) -> cutting.Cut:
    cfg = make({f"advanced.{key}": value for key, value in advanced.items()})
    return cutting.cut(body, layout, cfg, body.volume())


def ids(result: cutting.Cut) -> list[str]:
    return [piece.id for piece in result.pieces]


def codes(result: cutting.Cut) -> list[str]:
    return [item.code for item in result.diagnostics]


def assert_regions_lie_in_both_pieces(result: cutting.Cut) -> None:
    """I4: every face has one piece on each side, and its region is inside both sections."""
    pieces = {piece.id: piece for piece in result.pieces}
    for face in result.faces:
        assert face.piece_neg != face.piece_pos
        for piece_id, side in ((face.piece_neg, -1.0), (face.piece_pos, 1.0)):
            piece = pieces[piece_id]
            assert face.id in piece.face_ids
            plane = face.plane
            section = geometry.section(piece.body, plane.axis, plane.offset + side * EPS)
            assert face.region.difference(section).area <= 1e-6 * face.region.area, face.id


# --- splitting and cut faces ------------------------------------------------------------------


def test_200_mm_cube_on_a_120_bed_gives_8_pieces_and_12_faces_of_100_by_100() -> None:
    cfg = make({"printer.bed": (120.0, 120.0, 120.0)})
    body, _ = grid.orient(cube(200.0), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    assert layout.counts == (2, 2, 2)
    result = cutting.cut(body, layout, cfg, body.volume())

    assert ids(result) == [f"X{i}-Y{j}-Z{k}" for i, j, k in itertools.product(range(2), repeat=3)]
    assert len(result.faces) == 12
    assert [face.id for face in result.faces[:4]] == [
        "X0-Y0-Z0~X1-Y0-Z0",
        "X0-Y0-Z1~X1-Y0-Z1",
        "X0-Y1-Z0~X1-Y1-Z0",
        "X0-Y1-Z1~X1-Y1-Z1",
    ]
    assert {face.id for face in result.faces} >= {"X0-Y0-Z0~X0-Y1-Z0", "X0-Y0-Z0~X0-Y0-Z1"}
    for face in result.faces:
        assert face.region.area == pytest.approx(10_000.0, rel=1e-6)
        low_u, low_v, high_u, high_v = face.region.bounds
        assert (high_u - low_u, high_v - low_v) == pytest.approx((100.0, 100.0))
    assert all(len(piece.face_ids) == 3 for piece in result.pieces)
    assert all(piece.merged_from == [] for piece in result.pieces)
    assert result.diagnostics == ()
    assert_regions_lie_in_both_pieces(result)


def test_torus_cut_through_its_hole_gives_2_pieces_and_2_faces_on_that_plane() -> None:
    body = oriented(torus())  # 150 x 150 x 30
    layout = even(body, (90.0, 160.0, 40.0))
    assert layout.counts == (2, 1, 1)
    result = run(body, layout)

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0"]
    assert [face.id for face in result.faces] == ["X0-Y0-Z0~X1-Y0-Z0", "X0-Y0-Z0~X1-Y0-Z0#2"]
    assert all(face.plane == layout.planes[0][0] for face in result.faces)
    # Regions in polylabel order: u is world Y, so the tube at y = 15 comes before y = 135.
    assert [face.region.centroid.x for face in result.faces] == pytest.approx(
        [15.0, 135.0], abs=0.1
    )
    for face in result.faces:
        assert not face.region.interiors
        assert face.region.area == pytest.approx(math.pi * 15.0**2, rel=2e-2)
    assert result.diagnostics == ()
    assert_regions_lie_in_both_pieces(result)


def test_hollow_sphere_cut_once_gives_a_ring_face() -> None:
    cfg = make({"printer.bed": (320.0, 320.0, 220.0)})  # U = 310 x 310 x 210
    body, _ = grid.orient(hollow_sphere(), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    assert layout.counts == (1, 1, 2)
    result = cutting.cut(body, layout, cfg, body.volume())

    assert ids(result) == ["X0-Y0-Z0", "X0-Y0-Z1"]
    assert [face.id for face in result.faces] == ["X0-Y0-Z0~X0-Y0-Z1"]
    region = result.faces[0].region
    assert len(region.interiors) == 1
    assert region.area == pytest.approx(math.pi * (150.0**2 - 148.0**2), rel=2e-2)
    assert sum(piece.body.volume() for piece in result.pieces) == pytest.approx(body.volume())
    assert_regions_lie_in_both_pieces(result)


def test_a_void_that_no_plane_crosses_stays_a_void() -> None:
    body = box_with_bubble()  # 300 mm long, bubble at x = 30..70
    layout = even(body, (160.0, 110.0, 110.0))
    assert layout.counts == (2, 1, 1)
    result = run(body, layout)

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0"]
    void = 300.0 * 100.0 * 100.0 - body.volume()
    hollow, solid = result.pieces
    assert hollow.body.volume() == pytest.approx(150.0 * 100.0 * 100.0 - void, rel=1e-9)
    assert solid.body.volume() == pytest.approx(150.0 * 100.0 * 100.0, rel=1e-9)
    assert len(hollow.body.decompose()) == 2  # the outer shell and the void's


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        # (bounding box, surface area) of the piece below, then above, the plane z = 10
        (plinth_step, [((0, 0, 0, 40, 40, 10), 4800.0), ((15, 15, 10, 25, 25, 30), 1000.0)]),
        (overhang_step, [((15, 15, 0, 25, 25, 10), 600.0), ((0, 0, 10, 40, 40, 20), 4800.0)]),
    ],
    ids=["plinth", "overhang"],
)
def test_model_face_on_a_cut_plane_leaves_no_flap(
    fixture: object, expected: list[tuple[tuple[float, ...], float]]
) -> None:
    # split_by_plane would leave the plinth's top face on the column as a zero-thickness
    # 40 x 40 sheet (docs/LIBRARY_NOTES.md): same volume, but 4000 mm^2 of surface.
    body: Manifold = fixture()  # type: ignore[operator]
    result = run(body, hand_grid(body, (210.0, 210.0, 210.0), ((), (), (10.0,))))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y0-Z1"]
    for piece, (box, area) in zip(result.pieces, expected, strict=True):
        assert piece.body.bounding_box() == pytest.approx(box)
        assert piece.body.surface_area() == pytest.approx(area)
    assert [face.region.area for face in result.faces] == pytest.approx([100.0])
    assert_regions_lie_in_both_pieces(result)


def test_columns_standing_on_a_cut_plane_are_separate_pieces() -> None:
    plinth = Manifold.cube((40.0, 40.0, 10.0))
    tall = Manifold.cube((10.0, 10.0, 30.0)).translate((5.0, 25.0, 10.0))
    short = Manifold.cube((10.0, 10.0, 20.0)).translate((25.0, 5.0, 10.0))
    body = geometry.union_all([plinth, tall, short])
    result = run(body, hand_grid(body, (210.0, 210.0, 35.0), ((), (), (10.0,))))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y0-Z1-a", "X0-Y0-Z1-b"]
    assert [round(piece.body.volume()) for piece in result.pieces] == [16000, 2000, 3000]
    # Faces in polylabel order (u = X): the tall column at x = 10 before the short one at 30.
    assert [face.id for face in result.faces] == ["X0-Y0-Z0~X0-Y0-Z1-b", "X0-Y0-Z0~X0-Y0-Z1-a"]


def test_nub_on_a_face_lying_on_the_plane_is_merged() -> None:
    # The even grid puts the plane at z = 100, the plate's top face: the 180 mm^3 nub on it
    # merges into the plate. With a flap, its shadow was the plate's and the tower blocked it.
    plate = Manifold.cube((200.0, 200.0, 100.0))
    nub = Manifold.cube((6.0, 6.0, 5.0)).translate((20.0, 20.0, 100.0))
    tower = Manifold.cube((50.0, 50.0, 100.0)).translate((130.0, 130.0, 100.0))
    cfg = make({"printer.bed": (220.0, 220.0, 120.0)})
    body, _ = grid.orient(geometry.union_all([plate, nub, tower]), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    assert layout.planes[2][0].offset == 100.0
    result = cutting.cut(body, layout, cfg, body.volume())

    assert ids(result) == ["X0-Y0-Z0", "X0-Y0-Z1-b"]
    assert codes(result) == ["W005"]
    merged = result.pieces[0]
    assert merged.merged_from == ["X0-Y0-Z1-a"]
    assert merged.body.surface_area() == pytest.approx((plate + nub).surface_area())
    assert result.pieces[1].body.bounding_box() == pytest.approx((130, 130, 100, 180, 180, 200))


def fork() -> Manifold:
    """A 10 mm thick E without its middle bar: a 10 × 30 base and prongs at y = 0 and 20."""
    return geometry.union_all(
        [
            Manifold.cube((10.0, 30.0, 10.0)),
            Manifold.cube((100.0, 10.0, 10.0)),
            Manifold.cube((100.0, 10.0, 10.0)).translate((0.0, 20.0, 0.0)),
        ]
    )


def test_cell_with_two_bodies_gets_suffixes_a_and_b() -> None:
    body = fork()
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((50.0,), (), ())))

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0-a", "X1-Y0-Z0-b"]
    assert [piece.body.bounding_box()[1] for piece in result.pieces[1:]] == [0.0, 20.0]
    assert [face.id for face in result.faces] == ["X0-Y0-Z0~X1-Y0-Z0-a", "X0-Y0-Z0~X1-Y0-Z0-b"]
    assert_regions_lie_in_both_pieces(result)


def test_bodies_of_a_cell_are_ordered_by_min_z_then_y_then_x_then_larger_volume() -> None:
    lifted = cube(10.0).translate((0.0, 0.0, 5.0))  # min z = 5: last
    far = cube(10.0).translate((20.0, 20.0, 0.0))  # min (z, y) = (0, 20)
    first = cube(10.0).translate((40.0, 0.0, 0.0))  # min (z, y, x) = (0, 0, 40)
    big = Manifold.cube((10.0, 30.0, 10.0)).translate((80.0, 0.0, 0.0)) + Manifold.cube(
        (30.0, 10.0, 10.0)
    ).translate((60.0, 20.0, 0.0))  # an L with min (0, 0, 60), 5000 mm^3
    small = cube(10.0).translate((60.0, 0.0, 0.0))  # min (0, 0, 60), 1000 mm^3
    body = geometry.union_all([lifted, far, first, big, small])
    result = run(body, hand_grid(body, (210.0, 210.0, 210.0), ((), (), ())))

    assert ids(result) == [f"X0-Y0-Z0-{letter}" for letter in "abcde"]
    found = [(piece.body.bounding_box()[:3], round(piece.body.volume())) for piece in result.pieces]
    assert found == [
        ((40.0, 0.0, 0.0), 1000),
        ((60.0, 0.0, 0.0), 5000),
        ((60.0, 0.0, 0.0), 1000),
        ((20.0, 20.0, 0.0), 1000),
        ((0.0, 0.0, 5.0), 1000),
    ]
    assert result.faces == []
    assert result.diagnostics == ()  # one cell: nothing was cut, so no W008


def test_suffixes_continue_after_z() -> None:
    assert [cutting.suffix(n) for n in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == [
        "a", "b", "z", "aa", "ab", "az", "ba", "zz", "aaa",
    ]  # fmt: skip


# --- small-piece merge --------------------------------------------------------------------


def test_knob_tip_is_merged_into_its_neighbour() -> None:
    body = knob()
    result = run(body, hand_grid(body, KNOB_USABLE, KNOB_PLANES))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y1-Z0"]
    merged = result.pieces[0]
    assert merged.merged_from == ["X1-Y0-Z0"]
    # The merged piece is cut from the model in one go: the box half and the whole knob,
    # one body, no face left inside it.
    reference = body.trim_by_plane((0.0, -1.0, 0.0), -100.0)
    assert merged.body.volume() == pytest.approx(reference.volume(), rel=1e-9)
    assert merged.body.surface_area() == pytest.approx(reference.surface_area(), rel=1e-9)
    assert len(merged.body.decompose()) == 1
    assert [face.id for face in result.faces] == ["X0-Y0-Z0~X0-Y1-Z0"]
    assert merged.face_ids == ["X0-Y0-Z0~X0-Y1-Z0"]
    assert codes(result) == ["W005"]
    assert result.diagnostics[0].refs == ("X1-Y0-Z0", "X0-Y0-Z0")
    assert_regions_lie_in_both_pieces(result)


def test_rounded_knob_cut_through_its_vertices_merges_without_an_internal_face() -> None:
    # Gluing the two halves back with a union would leave a face at x = 100 here: the plane
    # passes through the ball's equator vertices (docs/LIBRARY_NOTES.md).
    body = knob(rounded=True)
    result = run(body, hand_grid(body, KNOB_USABLE, KNOB_PLANES))

    assert codes(result) == ["W005"]
    merged = result.pieces[0]
    reference = body.trim_by_plane((0.0, -1.0, 0.0), -100.0)
    assert merged.body.volume() == pytest.approx(reference.volume(), rel=1e-9)
    assert merged.body.surface_area() == pytest.approx(reference.surface_area(), rel=1e-9)
    assert merged.body.genus() == reference.genus()


def test_knob_with_a_body_over_its_footprint_is_not_merged() -> None:
    body = knob(blocked=True)
    result = run(body, hand_grid(body, KNOB_USABLE, KNOB_PLANES))

    # The block (min z 40) sorts before the tip (min z 47) in their cell.
    assert ids(result) == ["X0-Y0-Z0", "X0-Y1-Z0", "X1-Y0-Z0-a", "X1-Y0-Z0-b"]
    assert codes(result) == ["W004", "W008"]
    left, separate = result.diagnostics
    assert left.refs == ("X1-Y0-Z0-b", "X0-Y0-Z0", "X1-Y0-Z0-a")
    assert "footprint" in left.message
    assert separate.refs == ("X1-Y0-Z0-a",)


def test_small_piece_between_two_pieces_is_not_merged() -> None:
    rod = Manifold.cube((30.0, 6.0, 6.0)).translate((90.0, 47.0, 47.0))  # x 90..120
    body = geometry.union_all(
        [cube(100.0).scale((0.95, 1.0, 1.0)), rod, cube(100.0).translate((115.0, 0.0, 0.0))]
    )
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((100.0, 110.0), (), ())))

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0", "X2-Y0-Z0"]
    assert codes(result) == ["W004"]
    assert result.diagnostics[0].refs == ("X1-Y0-Z0", "X0-Y0-Z0", "X2-Y0-Z0")
    assert "2 pieces" in result.diagnostics[0].message


def test_small_piece_whose_merged_piece_would_not_fit_is_not_merged() -> None:
    body = knob()  # merged, the box half and the knob would be 105 mm along X
    result = run(body, hand_grid(body, (102.0, 110.0, 210.0), KNOB_PLANES))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y1-Z0", "X1-Y0-Z0"]
    assert codes(result) == ["W004"]
    assert "over U" in result.diagnostics[0].message


def test_zero_small_piece_volume_disables_merging() -> None:
    body = knob()
    result = run(body, hand_grid(body, KNOB_USABLE, KNOB_PLANES), small_piece_volume=0.0)

    assert ids(result) == ["X0-Y0-Z0", "X0-Y1-Z0", "X1-Y0-Z0"]
    assert result.diagnostics == ()


def test_piece_that_absorbed_another_is_not_merged_itself() -> None:
    # A 4 x 4 rod from x = 0 into a box from x = 30: planes at 5 and 25 leave an 80 mm^3 end
    # (X0) and a 320 mm^3 middle (X1). The end merges into the middle, which is then still
    # small but spans two cells: it stays on its own.
    rod = Manifold.cube((32.0, 4.0, 4.0)).translate((0.0, 48.0, 48.0))
    body = rod + Manifold.cube((90.0, 100.0, 100.0)).translate((30.0, 0.0, 0.0))
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((5.0, 25.0), (), ())))

    assert ids(result) == ["X1-Y0-Z0", "X2-Y0-Z0"]
    assert result.pieces[0].merged_from == ["X0-Y0-Z0"]
    assert codes(result) == ["W005", "W004"]
    assert "already absorbed" in result.diagnostics[1].message


def test_body_closer_than_the_margin_to_the_footprint_blocks_the_merge() -> None:
    # A fin beside the knob, outside its shadow but closer than MERGE_MARGIN: the prism the
    # merged piece is cut with would take a sliver of the fin along, so the guard refuses.
    gap = MERGE_MARGIN / 2
    fin = Manifold.cube((15.0, 7.0 - gap, 100.0)).translate((90.0, 53.0 + gap, 0.0))
    body = knob() + fin
    result = run(body, hand_grid(body, KNOB_USABLE, KNOB_PLANES))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y1-Z0", "X1-Y0-Z0-a", "X1-Y0-Z0-b"]
    assert codes(result) == ["W004"]
    assert result.diagnostics[0].refs == ("X1-Y0-Z0-b", "X0-Y0-Z0", "X1-Y0-Z0-a")
    assert "footprint" in result.diagnostics[0].message


def test_merged_piece_is_the_body_that_holds_the_small_piece() -> None:
    # The owner's cell holds a second body of exactly the same volume: the merged piece must
    # be the one the knob tip belongs to, not the first body of the right volume.
    shape = Manifold.cube((95.0, 40.0, 40.0)) + Manifold.cube((15.0, 6.0, 6.0)).translate(
        (90.0, 17.0, 17.0)
    )
    twin = shape.rotate((0.0, 0.0, 90.0)).translate((40.0, 0.0, 0.0))  # all in cell X0
    body = oriented(geometry.union_all([shape.translate((0.0, 150.0, 0.0)), twin]))
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((100.0,), (), ())))

    assert ids(result) == ["X0-Y0-Z0-a", "X0-Y0-Z0-b"]
    merged = result.pieces[1]
    assert merged.merged_from == ["X1-Y0-Z0"]
    assert merged.body.bounding_box() == pytest.approx((0, 150, 0, 105, 190, 40))
    assert result.pieces[0].body.bounding_box() == pytest.approx((0, 0, 0, 40, 105, 40))


def test_pieces_absorbed_across_two_planes_leave_their_neighbours_alone() -> None:
    # The owner absorbs a knob across x = 100 and one across y = 100. The X knob's prism must
    # not reach across y = 100 into the cell of t, a piece just beside it.
    owner = Manifold.cube((99.99, 99.99, 100.0))
    s1 = Manifold.cube((6.0, 5.98, 6.0)).translate((99.0, 94.0, 47.0))
    s2 = Manifold.cube((6.0, 6.0, 6.0)).translate((40.0, 99.0, 47.0))
    t = Manifold.cube((9.99, 50.5, 100.0)).translate((90.0, 99.5, 0.0))
    body = geometry.union_all([owner, s1, s2, t])
    result = run(body, hand_grid(body, (110.0, 110.0, 210.0), ((100.0,), (100.0,), ())))

    assert codes(result) == ["W005", "W005"]
    assert result.pieces[0].merged_from == ["X0-Y1-Z0-b", "X1-Y0-Z0"]
    for first, second in itertools.combinations(result.pieces, 2):
        assert (first.body ^ second.body).volume() == pytest.approx(0.0, abs=1e-9)
    total = sum(piece.body.volume() for piece in result.pieces)
    assert total == pytest.approx(body.volume(), rel=1e-9)


def test_merged_piece_is_refused_when_its_volume_does_not_match() -> None:
    body = knob()
    layout = hand_grid(body, KNOB_USABLE, KNOB_PLANES)
    pieces, _ = cutting.cut_faces(body, layout, cutting.split_cells(body, layout), EPS)
    owner, _, tip = pieces
    assert cutting._cut_merged(body, layout, owner, [tip]) is not None
    wrong = Piece(tip.id, tip.grid_index, tip.body.scale((2.0, 1.0, 1.0)), [], [])
    assert cutting._cut_merged(body, layout, owner, [wrong]) is None


def test_region_with_no_piece_on_a_side_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    # Two thin internal voids just above z = 50, at the two probe depths (0.05 and 0.005):
    # the contact region exists at ±ε, but no piece section contains its polylabel point.
    def slot(bottom: float, top: float) -> Manifold:
        return Manifold.cube((98.0, 98.0, top - bottom)).translate((1.0, 1.0, 50.0 + bottom))

    body = cube(100.0) - slot(0.004, 0.006) - slot(0.04, 0.06)
    with caplog.at_level(logging.DEBUG, logger="stlsplit.cutting"):
        result = run(body, hand_grid(body, (210.0, 210.0, 60.0), ((), (), (50.0,))))

    assert ids(result) == ["X0-Y0-Z0", "X0-Y0-Z1"]
    assert result.faces == []
    assert "has no piece on its pos side; skipped" in caplog.text
    assert codes(result) == ["W008", "W008"]


def test_separate_body_gets_w008() -> None:
    body = cube(100.0) + cube(10.0).translate((150.0, 0.0, 0.0))
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((50.0,), (), ())))

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0-a", "X1-Y0-Z0-b"]
    assert codes(result) == ["W008"]
    assert result.diagnostics[0].refs == ("X1-Y0-Z0-b",)


def test_two_small_halves_of_a_tiny_body_end_as_one_separate_piece() -> None:
    tiny = cube(6.0).translate((147.0, 200.0, 0.0))  # crosses x = 150, away from the big cube
    body = cube(100.0) + tiny
    result = run(body, hand_grid(body, (110.0, 210.0, 210.0), ((50.0, 150.0), (), ())))

    assert ids(result) == ["X0-Y0-Z0", "X1-Y0-Z0-a", "X2-Y0-Z0"]
    whole = result.pieces[2]
    assert whole.merged_from == ["X1-Y0-Z0-b"]
    assert whole.body.volume() == pytest.approx(216.0)
    assert whole.body.bounding_box() == pytest.approx((147.0, 200.0, 0.0, 153.0, 206.0, 6.0))
    assert codes(result) == ["W005", "W008"]
    assert result.diagnostics[1].refs == ("X2-Y0-Z0",)


# --- validation, properties, determinism -------------------------------------------------


def test_check_pieces_rejects_invalid_pieces_and_volumes_that_do_not_add_up() -> None:
    piece = Piece(id="X0-Y0-Z0", grid_index=(0, 0, 0), body=cube(10.0), face_ids=[], merged_from=[])
    cutting.check_pieces([piece], 1000.0)
    cutting.check_pieces([piece], 1000.5)  # within 0.1 %
    with pytest.raises(AssertionError, match="I3"):
        cutting.check_pieces([piece], 2000.0)
    empty = Piece(id="X1-Y0-Z0", grid_index=(1, 0, 0), body=Manifold(), face_ids=[], merged_from=[])
    with pytest.raises(AssertionError, match="I1"):
        cutting.check_pieces([piece, empty], 1000.0)


SIZES = st.floats(min_value=5.0, max_value=80.0)
COORDINATES = st.floats(min_value=0.0, max_value=100.0)
SHAPES = st.lists(
    st.tuples(st.booleans(), COORDINATES, COORDINATES, COORDINATES, SIZES, SIZES, SIZES),
    min_size=1,
    max_size=4,
)
USABLE = st.floats(min_value=40.0, max_value=150.0)


@settings(max_examples=25, deadline=None)
@given(shapes=SHAPES, usable=st.tuples(USABLE, USABLE, USABLE))
def test_piece_volumes_add_up_to_the_reference_volume(
    shapes: list[tuple[bool, float, float, float, float, float, float]],
    usable: tuple[float, float, float],
) -> None:
    solids = [
        Manifold.cube((a, b, c)).translate((x, y, z))
        if is_box
        else Manifold.sphere(a / 2, 16).translate((x, y, z))
        for is_box, x, y, z, a, b, c in shapes
    ]
    body = oriented(geometry.union_all(solids))
    result = run(body, even(body, usable))

    total = sum(piece.body.volume() for piece in result.pieces)
    assert total == pytest.approx(body.volume(), rel=1e-3)
    for piece in result.pieces:
        assert piece.body.status() == Error.NoError
        assert piece.body.volume() > 0
    known = {piece.id for piece in result.pieces}
    for face in result.faces:
        assert {face.piece_neg, face.piece_pos} <= known


LATTICE = st.integers(min_value=0, max_value=12).map(lambda n: 5.0 * n)
BOX_SIZES = st.integers(min_value=1, max_value=8).map(lambda n: 5.0 * n)
LATTICE_BOXES = st.lists(
    st.tuples(LATTICE, LATTICE, LATTICE, BOX_SIZES, BOX_SIZES, BOX_SIZES), min_size=1, max_size=4
)


@settings(max_examples=25, deadline=None)
@given(boxes=LATTICE_BOXES)
def test_cutting_adds_no_surface_but_the_cut_faces(
    boxes: list[tuple[float, float, float, float, float, float]],
) -> None:
    # Boxes on a 5 mm lattice cut at multiples of 10: model faces often lie on the planes.
    # The pieces' surface is then the model's plus both sides of every cut face, exactly; a
    # flap left by a cut (or a face left inside a merged piece) would add to it.
    solids = [Manifold.cube((a, b, c)).translate((x, y, z)) for x, y, z, a, b, c in boxes]
    body = oriented(geometry.union_all(solids))
    extent = grid.extent(body)
    offsets = tuple(
        tuple(10.0 * k for k in range(1, math.ceil(size / 10.0)) if 10.0 * k < size)
        for size in extent
    )
    layout = hand_grid(body, (210.0, 210.0, 210.0), offsets)  # type: ignore[arg-type]
    result = run(body, layout)

    pieces = sum(piece.body.surface_area() for piece in result.pieces)
    faces = sum(face.region.area for face in result.faces)
    assert pieces == pytest.approx(body.surface_area() + 2 * faces, rel=1e-9, abs=1e-6)
    assert sum(p.body.volume() for p in result.pieces) == pytest.approx(body.volume(), rel=1e-9)


def summary(result: cutting.Cut) -> tuple[object, ...]:
    pieces = [
        (p.id, p.grid_index, p.body.volume(), tuple(p.face_ids), tuple(p.merged_from))
        for p in result.pieces
    ]
    faces = [(f.id, f.plane, f.piece_neg, f.piece_pos, f.region.wkb) for f in result.faces]
    return pieces, faces, result.diagnostics


def test_cutting_twice_gives_identical_ids_volumes_and_faces() -> None:
    first = summary(run(knob(), hand_grid(knob(), KNOB_USABLE, KNOB_PLANES)))
    second = summary(run(knob(), hand_grid(knob(), KNOB_USABLE, KNOB_PLANES)))
    assert first == second
    body = oriented(torus())
    assert summary(run(body, even(body, (90.0, 160.0, 40.0)))) == summary(
        run(oriented(torus()), even(body, (90.0, 160.0, 40.0)))
    )
