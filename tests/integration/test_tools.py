"""Phase 7: tool solids, one batched boolean per piece, pegs and pins (PLAN.md Phase 7).

Most tests use a 200 x 100 x 100 box on a 120 mm bed: the default bed (U = 210) wouldn't cut
it, and a 100 x 100 face would get 4 connectors without ``max_per_face = 2``. With the defaults
(d = 5): r_h = 2.7, ch_h = 0.4, h(20) = 10.5, ch_p = 0.5, f = 0.4. In peg mode U is 100, the
cells are 100 long, and a pegged piece is 110: it fits bed − 2·margin (ADR-0005, PLAN.md I2).
"""

import math
from typing import Any, NamedTuple

import numpy as np
import pytest
from manifold3d import Manifold
from shapely.geometry import MultiPolygon, Polygon

from stlsplit import config, connectors, cutting, geometry, grid, tools
from stlsplit.config import TOOL_OVERLAP, Config
from stlsplit.errors import ConfigError
from stlsplit.models import Connector, Grid
from tests.conftest import torus, wedge
from tests.integration.test_cutting import even, hand_grid, make, oriented

TWO_DOWELS: dict[str, Any] = {
    "printer.bed": (120.0, 120.0, 120.0),
    "connectors.max_per_face": 2,
}
PEGS: dict[str, Any] = {**TWO_DOWELS, "connectors.type": "peg"}
PLANE = 100.0
"""The X plane that cuts the 200 mm box in two."""


class Run(NamedTuple):
    cfg: Config
    cut: cutting.Cut
    placement: connectors.Placement
    applied: tools.Applied


def run(body: Manifold, overrides: dict[str, Any] | None = None, layout: Grid | None = None) -> Run:
    cfg = make({**TWO_DOWELS, **(overrides or {})})
    grid_used = layout or even(body, config.derived(cfg).usable)
    result = cutting.cut(body, grid_used, cfg, body.volume())
    placement = connectors.place(result.pieces, result.faces, cfg)
    applied = tools.apply(result.pieces, result.faces, placement.connectors, cfg)
    return Run(cfg, result, placement, applied)


def box() -> Manifold:
    return oriented(Manifold.cube((200.0, 100.0, 100.0)))


def polygon_factor(segments: int) -> float:
    """Area of a regular polygon of apothem 1: holes have their flats at r_h (§6.2)."""
    return segments * math.tan(math.pi / segments)


def hole_volume(cfg: Config, depth: float) -> float:
    """The bore plus the mouth chamfer, computed from the formulas, not from the tool."""
    r = config.derived(cfg).hole_radius
    ch = cfg.advanced.hole_chamfer
    k = polygon_factor(cfg.advanced.circular_segments)
    return k * (r**2 * (depth - ch) + ch * (r**2 + r * (r + ch) + (r + ch) ** 2) / 3)


def peg_volume(cfg: Config, length: float) -> float:
    """A peg of radius d/2 (vertices on the circle) and height L/2 with its tip chamfer."""
    r = cfg.connectors.diameter / 2
    ch = cfg.advanced.pin_chamfer
    n = cfg.advanced.circular_segments
    k = n * math.sin(2 * math.pi / n) / 2
    return k * (r**2 * (length / 2 - ch) + ch * (r**2 + r * (r - ch) + (r - ch) ** 2) / 3)


def hole_centres(section: MultiPolygon) -> list[tuple[float, float]]:
    """The centroids of the holes of a one-part section, sorted."""
    assert len(section.geoms) == 1
    centres = [Polygon(ring).centroid for ring in section.geoms[0].interiors]
    return sorted((float(centre.x), float(centre.y)) for centre in centres)


def size(body: Manifold) -> tuple[float, float, float]:
    b = body.bounding_box()
    return (b[3] - b[0], b[4] - b[1], b[5] - b[2])


# --- holes (tasks 1 and 3) --------------------------------------------------------------------


def test_each_half_of_a_cut_box_has_two_holes() -> None:
    result = run(box())
    assert len(result.placement.connectors) == 2
    low, high = result.applied.pieces
    assert len(hole_centres(geometry.section(low.body, 0, PLANE - 1.0))) == 2
    assert len(hole_centres(geometry.section(high.body, 0, PLANE + 1.0))) == 2


def test_volume_removed_from_each_half_is_the_hole_plus_chamfer_volume() -> None:
    result = run(box())
    expected = sum(hole_volume(result.cfg, c.hole_depth_pos) for c in result.placement.connectors)
    for before, after in zip(result.cut.pieces, result.applied.pieces, strict=True):
        removed = before.body.volume() - after.body.volume()
        assert removed == pytest.approx(expected, rel=0.05)
        assert after.body.status().name == "NoError"
        assert len(after.body.decompose()) == 1


def test_holes_of_both_halves_line_up() -> None:
    low, high = run(box()).applied.pieces
    low_centres = hole_centres(geometry.section(low.body, 0, PLANE - 1.0))
    high_centres = hole_centres(geometry.section(high.body, 0, PLANE + 1.0))
    assert np.asarray(low_centres) == pytest.approx(np.asarray(high_centres), abs=0.01)


def test_holes_open_through_the_cut_face_down_to_their_depth() -> None:
    result = run(box())
    connector = result.placement.connectors[0]
    u, v = connector.position_uv
    low, high = result.applied.pieces
    depth = connector.hole_depth_pos
    # From outside the piece, along the axis: the first surface is the hole's floor, so no
    # skin closes the mouth.
    hit = low.body.ray_cast(
        geometry.local_point(0, u, v, PLANE + 5.0), geometry.local_point(0, u, v, 0.0)
    )
    assert hit[0].position[0] == pytest.approx(PLANE - depth)
    hit = high.body.ray_cast(
        geometry.local_point(0, u, v, PLANE - 5.0), geometry.local_point(0, u, v, 200.0)
    )
    assert hit[0].position[0] == pytest.approx(PLANE + depth)


def test_a_piece_keeps_its_id_cell_faces_and_order() -> None:
    result = run(box())
    for before, after in zip(result.cut.pieces, result.applied.pieces, strict=True):
        assert (after.id, after.grid_index, after.face_ids, after.merged_from) == (
            before.id,
            before.grid_index,
            before.face_ids,
            before.merged_from,
        )


def test_tools_do_not_change_the_pieces_they_are_given() -> None:
    result = run(box())
    assert sum(p.body.volume() for p in result.cut.pieces) == pytest.approx(2_000_000.0)


def test_no_connectors_leaves_the_bodies_alone_and_makes_no_pins() -> None:
    result = run(box(), {"connectors.type": "none"})
    assert result.applied.pins == []
    for before, after in zip(result.cut.pieces, result.applied.pieces, strict=True):
        assert after.body.volume() == before.body.volume()


def test_a_face_on_a_sloping_body_stays_valid_after_drilling() -> None:
    body = wedge()
    layout = hand_grid(body, (40.0, 40.0, 40.0), ((40.0,), (), ()))
    result = run(body, {"printer.bed": (220.0, 220.0, 250.0)}, layout)
    assert result.placement.connectors
    for piece in result.applied.pieces:
        assert piece.body.status().name == "NoError"
        assert len(piece.body.decompose()) == 1


# --- pegs (task 2) ----------------------------------------------------------------------------


def test_pegged_piece_gains_the_peg_and_the_other_loses_the_hole() -> None:
    result = run(box(), PEGS)
    assert len(result.placement.connectors) == 2
    pegged_before, holed_before = result.cut.pieces
    pegged, holed = result.applied.pieces
    gained = sum(peg_volume(result.cfg, c.pin_length) for c in result.placement.connectors)
    lost = sum(hole_volume(result.cfg, c.hole_depth_pos) for c in result.placement.connectors)
    assert pegged.body.volume() - pegged_before.body.volume() == pytest.approx(gained, rel=0.02)
    assert holed_before.body.volume() - holed.body.volume() == pytest.approx(lost, rel=0.02)


def test_pegged_piece_fits_the_bed_minus_its_margins() -> None:
    # U is reduced by the protrusion so that a full cell plus its peg still fits (ADR-0005).
    result = run(box(), PEGS)
    d = config.derived(result.cfg)
    assert d.usable == (100.0, 100.0, 100.0)
    assert d.printable == (110.0, 110.0, 110.0)
    pegged, holed = result.applied.pieces
    assert size(pegged.body) == pytest.approx((110.0, 100.0, 100.0))
    assert size(holed.body) == pytest.approx((100.0, 100.0, 100.0))
    for piece in result.applied.pieces:
        assert all(s <= u + 1e-6 for s, u in zip(size(piece.body), d.printable, strict=True))


def test_peg_is_one_body_with_its_piece_and_leaves_no_internal_face() -> None:
    result = run(box(), PEGS)
    faces = {face.id: face for face in result.cut.faces}
    before = result.cut.pieces[0].body
    pegged = result.applied.pieces[0].body
    assert len(pegged.decompose()) == 1
    r = result.cfg.connectors.diameter / 2
    n = result.cfg.advanced.circular_segments
    base = n * math.sin(2 * math.pi / n) / 2 * r**2
    added = sum(
        tools.peg_solid(c, faces[c.face_id], result.cfg).surface_area() - 2 * base
        for c in result.placement.connectors
    )
    assert pegged.surface_area() - before.surface_area() == pytest.approx(added, abs=1e-6)


def test_assembled_peg_stays_clear_of_the_other_piece() -> None:
    result = run(box(), PEGS)
    pegged, holed = result.applied.pieces
    assert (pegged.body ^ holed.body).volume() == pytest.approx(0.0, abs=1e-6)


def test_pegs_are_fused_to_a_face_whose_vertices_are_off_the_plane_by_float_noise() -> None:
    # On this torus, cut faces have vertices at 29.499999999999993 instead of 29.5: a peg based
    # exactly on the plane misses the face and stays a separate shell.
    cfg = make({"printer.bed": (55.0, 55.0, 55.0), "connectors.type": "peg"})
    body = grid.orient(torus(), cfg)[0]
    layout = grid.nudge(body, even(body, config.derived(cfg).usable), cfg)
    result = run(
        body,
        {"printer.bed": (55.0, 55.0, 55.0), "connectors.type": "peg", "connectors.max_per_face": 4},
        layout,
    )
    assert result.placement.connectors
    for before, after in zip(result.cut.pieces, result.applied.pieces, strict=True):
        assert len(after.body.decompose()) == len(before.body.decompose()), after.id


def test_tools_reach_past_the_face_so_none_is_coplanar_with_it() -> None:
    result = run(box(), PEGS)
    face = result.cut.faces[0]
    connector = result.placement.connectors[0]
    peg = tools.peg_solid(connector, face, result.cfg, overlap=TOOL_OVERLAP)
    assert peg.bounding_box()[0] == pytest.approx(PLANE - TOOL_OVERLAP)
    ((_, hole),) = connectors.hole_solids(connector, face, result.cfg, overlap=TOOL_OVERLAP)
    assert hole.bounding_box()[0] == pytest.approx(PLANE - TOOL_OVERLAP)
    exact = connectors.hole_solids(connector, face, result.cfg)[0][1]
    assert exact.bounding_box()[0] == pytest.approx(PLANE)


def test_pegs_make_no_loose_pins() -> None:
    assert run(box(), PEGS).applied.pins == []


def test_peg_tip_has_its_chamfer() -> None:
    result = run(box(), PEGS)
    face = result.cut.faces[0]
    connector = result.placement.connectors[0]
    peg = tools.peg_solid(connector, face, result.cfg)
    tip = PLANE + connector.pin_length / 2
    assert peg.bounding_box()[3] == pytest.approx(tip)
    r = result.cfg.connectors.diameter / 2
    n = result.cfg.advanced.circular_segments
    k = n * math.sin(2 * math.pi / n) / 2
    ch = result.cfg.advanced.pin_chamfer
    section = geometry.section(peg, 0, tip - ch / 2)
    assert section.area == pytest.approx(k * (r - ch / 2) ** 2, rel=1e-3)


# --- pins (task 4) ----------------------------------------------------------------------------


def bottom_area(solid: Manifold) -> float:
    """Area of the triangles lying on z = 0 with a downward normal."""
    mesh = solid.to_mesh()
    vertices = np.asarray(mesh.vert_properties)[:, :3]
    triangles = vertices[np.asarray(mesh.tri_verts)]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    on_bed = (np.abs(triangles[:, :, 2]) < 1e-6).all(axis=1) & (normals[:, 2] < 0)
    return float(0.5 * np.linalg.norm(normals[on_bed], axis=1).sum())


def test_pin_lies_on_its_flat() -> None:
    cfg = make()
    d, length, flat, chamfer = 5.0, 20.0, cfg.advanced.pin_flat, cfg.advanced.pin_chamfer
    pin = tools.pin_solid(d, length, cfg)
    r = d / 2
    flat_width = 2 * math.sqrt(r**2 - (r - flat) ** 2)
    assert flat_width == pytest.approx(2.71, abs=0.01)
    assert bottom_area(pin) >= 0.9 * flat_width * (length - 2 * chamfer)


def test_pin_axis_is_along_x_with_the_flat_on_z_zero() -> None:
    cfg = make()
    pin = tools.pin_solid(5.0, 20.0, cfg)
    assert pin.status().name == "NoError"
    low = pin.bounding_box()[:3]
    assert low[0] == pytest.approx(0.0)
    assert low[2] == pytest.approx(0.0, abs=1e-12)
    # A polygon edge faces the bed, so the sides across the flats are at r·cos(π/n).
    r = 2.5
    across = r * math.cos(math.pi / cfg.advanced.circular_segments)
    assert size(pin)[:2] == pytest.approx((20.0, 2 * across), abs=1e-3)
    # The cut is where the polygon is as wide as a round pin's flat. Along x, the gap between
    # polygon and circle is the sagitta / cos(angle), and f < d/4 keeps the angle under 60°.
    height = r - cfg.advanced.pin_flat + across
    assert height - 2 * (r - across) - 1e-9 <= size(pin)[2] <= height + 1e-9


@pytest.mark.parametrize("segments", [16, 17, 64])
@pytest.mark.parametrize("flat", [0.05, 0.1, 0.4, 1.2])
def test_pin_flat_keeps_its_width_at_low_segment_counts(segments: int, flat: float) -> None:
    # With a polygon vertex towards the bed, a shallow flat clipped only a sliver (0.505 x the
    # nominal area at 16 segments and f = 0.05).
    cfg = make({"advanced.circular_segments": segments, "advanced.pin_flat": flat})
    r, length, chamfer = 2.5, 20.0, cfg.advanced.pin_chamfer
    width = 2 * math.sqrt(r**2 - (r - flat) ** 2)
    pin = tools.pin_solid(5.0, length, cfg)
    assert bottom_area(pin) >= 0.9 * width * (length - 2 * chamfer)
    outline = np.asarray(geometry.section(pin, 0, length / 2).geoms[0].exterior.coords)
    on_bed = outline[np.abs(outline[:, 1]) < 1e-9, 0]  # section across X: (u, v) = (Y, Z)
    assert on_bed.max() - on_bed.min() == pytest.approx(width, abs=1e-6)


def test_pin_ends_are_chamfered_on_both_sides() -> None:
    cfg = make({"advanced.pin_flat": 0.0})
    pin = tools.pin_solid(5.0, 20.0, cfg)
    ends = [geometry.section(pin, 0, x).area for x in (0.25, 19.75)]
    middle = geometry.section(pin, 0, 10.0).area
    assert ends[0] == pytest.approx(ends[1], rel=1e-6)
    assert ends[0] < middle


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"advanced.pin_flat": 0.0}, id="round"),
        pytest.param({"advanced.pin_chamfer": 0.0}, id="no-chamfer"),
        pytest.param({"advanced.pin_flat": 0.0, "advanced.pin_chamfer": 0.0}, id="plain"),
        pytest.param({"advanced.pin_flat": 1.2}, id="flat-deeper-than-the-chamfer"),
    ],
)
def test_pin_variants_are_valid_and_rest_on_z_zero(overrides: dict[str, Any]) -> None:
    pin = tools.pin_solid(5.0, 20.0, make(overrides))
    assert pin.status().name == "NoError"
    assert len(pin.decompose()) == 1
    assert pin.bounding_box()[2] == pytest.approx(0.0, abs=1e-12)


def test_shortened_pins_go_to_separate_files_and_the_counts_add_up() -> None:
    # The first piece is 12 mm long, so the pins of the first face are shortened to 18 mm;
    # those of the second face keep the full 20 mm.
    body = oriented(Manifold.cube((80.0, 40.0, 40.0)))
    layout = hand_grid(body, (100.0, 100.0, 100.0), ((12.0, 40.0), (), ()))
    result = run(body, {"printer.bed": (220.0, 220.0, 250.0)}, layout)
    lengths = {c.pin_length for c in result.placement.connectors}
    assert lengths == {18.0, 20.0}

    groups = result.applied.pins
    assert [g.file_name for g in groups] == [
        "dowels/dowel_d5.0_l20.0.stl",
        "dowels/dowel_d5.0_l18.0.stl",
    ]
    assert sum(g.quantity for g in groups) == len(result.placement.connectors)
    for group in groups:
        assert group.quantity == sum(
            c.pin_length == group.length for c in result.placement.connectors
        )
        assert size(group.solid)[0] == pytest.approx(group.length)


def test_pin_groups_are_sorted_longest_first_whatever_the_input_order() -> None:
    cfg = make()
    placed = [
        Connector(f"f/c{i}", "f", "dowel", (0.0, 0.0), 5.0, length, length / 2, length / 2)
        for i, length in enumerate((16.0, 20.0, 16.0, 18.0))
    ]
    groups = tools.pin_groups(placed, cfg)
    assert [(g.length, g.quantity) for g in groups] == [(20.0, 1), (18.0, 1), (16.0, 2)]


# --- validation (task 5) ----------------------------------------------------------------------


def checked(**changes: Any) -> None:
    """``check_piece`` on a 10 mm cube with a 1 mm³ hole, with some arguments replaced."""
    before = Manifold.cube((10.0, 10.0, 10.0))
    drilled = before - Manifold.cube((1.0, 1.0, 1.0)).translate((4.0, 4.0, 9.0))
    arguments: dict[str, Any] = {
        "piece_id": "X0-Y0-Z0",
        "before": before,
        "drilled": drilled,
        "final": drilled,
        "holes_volume": 1.0,
        "pegs_volume": 0.0,
        "cfg": make(),
    }
    tools.check_piece(**{**arguments, **changes})


def test_check_piece_accepts_the_expected_volumes() -> None:
    checked()
    checked(holes_volume=1.04)


def test_check_piece_rejects_a_removed_volume_off_by_more_than_5_percent() -> None:
    with pytest.raises(AssertionError, match="X0-Y0-Z0"):
        checked(holes_volume=1.1)


def test_check_piece_rejects_an_added_volume_off_by_more_than_5_percent() -> None:
    with pytest.raises(AssertionError, match="X0-Y0-Z0"):
        checked(pegs_volume=1.0)


def test_check_piece_rejects_a_piece_that_outgrew_the_printable_volume() -> None:
    big = Manifold.cube((211.0, 10.0, 10.0))
    with pytest.raises(AssertionError, match="I2"):
        checked(before=big, drilled=big, final=big, holes_volume=0.0)


def test_check_piece_rejects_a_peg_left_as_a_separate_shell() -> None:
    before = Manifold.cube((10.0, 10.0, 10.0))
    apart = before + Manifold.cube((1.0, 1.0, 1.0)).translate((20.0, 0.0, 0.0))
    with pytest.raises(AssertionError, match="separate"):
        checked(before=before, drilled=before, final=apart, holes_volume=0.0, pegs_volume=1.0)


def test_a_hole_may_swallow_a_tiny_void_the_containment_check_tolerates() -> None:
    # 0.05 mm of void in the path of a hole: under the 1e-6 of the probe's volume that
    # placement tolerates, so the hole is accepted and the piece loses a (void) shell.
    bubble = Manifold.cube((0.05, 0.05, 0.05)).translate((105.0, 7.25, 7.25))
    result = run(oriented(Manifold.cube((200.0, 100.0, 100.0)) - bubble))
    before, after = result.cut.pieces[1], result.applied.pieces[1]
    assert len(before.body.decompose()) == 2
    assert len(after.body.decompose()) == 1


def test_pins_that_would_share_a_file_name_are_rejected() -> None:
    placed = [
        Connector(f"f/c{i}", "f", "dowel", (0.0, 0.0), 5.0, length, length / 2, length / 2)
        for i, length in enumerate((15.25, 15.15))
    ]
    with pytest.raises(ConfigError, match=r"advanced\.pin_length_step.*dowel_d5\.0_l15\.2"):
        tools.check_pin_names(placed)
    with pytest.raises(ConfigError, match=r"advanced\.pin_length_step"):
        tools.pin_groups(placed, make())


def test_check_piece_rejects_an_invalid_body() -> None:
    with pytest.raises(AssertionError, match="X0-Y0-Z0"):
        checked(final=Manifold())
