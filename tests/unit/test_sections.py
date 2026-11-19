"""Phase 4: plane sections, cut regions, clipping and shadows (PLAN.md Phase 4, tasks 1 and 2).

Everything here is in plane-local (u, v) coordinates (PLAN.md §4.2): for a plane of axis X,
u = world Y and v = world Z; for Y, u = Z and v = X; for Z, u = X and v = Y.
"""

import math

import pytest
from manifold3d import Manifold
from shapely.geometry import Polygon, box

from stlsplit import geometry
from stlsplit.models import Axis, Plane
from tests.conftest import box_with_bubble, cube, overhang_step, plinth_step, two_bodies, u_shape

EPS = 0.01
"""ε, ``advanced.section_epsilon``'s default (ADR-0002)."""

LOCAL_AXES = {0: (1, 2, 0), 1: (2, 0, 1), 2: (0, 1, 2)}


def polygon_area(segments: int, radius: float) -> float:
    """Area of a regular polygon with its vertices on a circle."""
    return 0.5 * segments * radius**2 * math.sin(2 * math.pi / segments)


def test_ring_gives_one_polygon_with_one_hole() -> None:
    tube = Manifold.cylinder(20.0, 20.0, circular_segments=64) - Manifold.cylinder(
        30.0, 10.0, circular_segments=64
    ).translate((0.0, 0.0, -5.0))
    regions = geometry.cut_region(tube, Plane(axis=2, index=0, offset=10.0), EPS)
    assert len(regions) == 1
    assert len(regions[0].interiors) == 1
    expected = polygon_area(64, 20.0) - polygon_area(64, 10.0)
    assert regions[0].area == pytest.approx(expected, rel=1e-9)


def test_u_shape_gives_one_polygon() -> None:
    # A Y plane cuts across the extrusion: the section is the U profile in (u, v) = (Z, X).
    regions = geometry.cut_region(u_shape(), Plane(axis=1, index=0, offset=10.0), EPS)
    assert len(regions) == 1
    assert not regions[0].interiors
    assert regions[0].area == pytest.approx(1400.0, rel=1e-9)
    assert regions[0].bounds == pytest.approx((0.0, 0.0, 50.0, 60.0))


def test_two_separate_squares_give_two_polygons_in_polylabel_order() -> None:
    regions = geometry.cut_region(two_bodies(), Plane(axis=2, index=0, offset=5.0), EPS)
    assert len(regions) == 2
    assert [region.bounds[0] for region in regions] == pytest.approx([0.0, 20.0])
    assert [region.area for region in regions] == pytest.approx([100.0, 100.0])


@pytest.mark.parametrize("fixture", [plinth_step, overhang_step], ids=["plinth", "overhang"])
def test_step_contact_region_is_the_100_mm2_contact(fixture: object) -> None:
    body: Manifold = fixture()  # type: ignore[operator]
    regions = geometry.cut_region(body, Plane(axis=2, index=0, offset=10.0), EPS)
    assert len(regions) == 1
    assert regions[0].area == pytest.approx(100.0, rel=1e-9)
    assert regions[0].bounds == pytest.approx((15.0, 15.0, 25.0, 25.0))


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_cut_region_is_in_the_plane_local_axes(axis: Axis) -> None:
    size = (10.0, 20.0, 30.0)
    body = Manifold.cube(size)
    u_axis, v_axis, n_axis = LOCAL_AXES[axis]
    plane = Plane(axis=axis, index=0, offset=size[n_axis] / 2)
    regions = geometry.cut_region(body, plane, EPS)
    assert len(regions) == 1
    assert regions[0].bounds == pytest.approx((0.0, 0.0, size[u_axis], size[v_axis]))


def test_section_keeps_holes_and_is_empty_off_the_body() -> None:
    hollow = box_with_bubble()
    section = geometry.section(hollow, 0, 50.0)  # through the bubble's centre
    assert len(section.geoms) == 1
    assert len(section.geoms[0].interiors) == 1
    assert section.area == pytest.approx(100.0 * 100.0 - polygon_area(32, 20.0), rel=1e-3)
    assert geometry.section(hollow, 0, 400.0).is_empty


def test_clip_to_cells_keeps_the_rectangle_the_two_cells_share() -> None:
    # Z plane: u = X, v = Y. The cells are stacked along Z and share X 0..100, Y 0..100.
    below = ((0.0, 0.0, 0.0), (100.0, 100.0, 50.0))
    above = ((0.0, 0.0, 50.0), (100.0, 100.0, 120.0))
    clipped = geometry.clip_to_cells([box(-20.0, 30.0, 200.0, 60.0)], 2, below, above)
    assert len(clipped) == 1
    assert clipped[0].bounds == pytest.approx((0.0, 30.0, 100.0, 60.0))


def test_clip_to_cells_splits_a_region_into_connected_polygons_in_polylabel_order() -> None:
    # X plane: u = Y, v = Z. A U-shaped region whose base lies outside the cells' rectangle.
    left = ((0.0, 0.0, 10.0), (50.0, 100.0, 200.0))
    right = ((50.0, 0.0, 10.0), (90.0, 100.0, 200.0))
    region = Polygon([(60, 0), (90, 0), (90, 50), (80, 50), (80, 5), (70, 5), (70, 50), (60, 50)])
    clipped = geometry.clip_to_cells([region], 0, left, right)
    assert [polygon.bounds for polygon in clipped] == [
        pytest.approx((60.0, 10.0, 70.0, 50.0)),
        pytest.approx((80.0, 10.0, 90.0, 50.0)),
    ]


def test_clip_to_cells_drops_what_only_touches_the_rectangle() -> None:
    below = ((0.0, 0.0, 0.0), (100.0, 100.0, 50.0))
    above = ((0.0, 0.0, 50.0), (100.0, 100.0, 100.0))
    touching = box(100.0, 0.0, 150.0, 50.0)  # shares the edge u = 100 only
    assert geometry.clip_to_cells([touching], 2, below, above) == []


def test_shadow_is_the_projection_along_the_axis_in_plane_local_coordinates() -> None:
    block = cube(10.0).translate((5.0, 20.0, 30.0))
    shadow = geometry.shadow(block, 0)  # along X: (u, v) = (Y, Z)
    assert shadow.area() == pytest.approx(100.0)
    assert shadow.bounds() == pytest.approx((20.0, 30.0, 30.0, 40.0))
    beside = geometry.shadow(cube(10.0).translate((50.0, 25.0, 30.0)), 0)
    assert geometry.overlap_area(shadow, beside) == pytest.approx(50.0)
    apart = geometry.shadow(cube(10.0).translate((50.0, 40.0, 30.0)), 0)
    assert geometry.overlap_area(shadow, apart) == pytest.approx(0.0)


def test_bodies_keep_each_void_with_the_body_around_it() -> None:
    hollow = box_with_bubble()
    loose = cube(10.0).translate((400.0, 0.0, 0.0))
    found = geometry.bodies(hollow + loose)
    assert sorted(round(body.volume(), 3) for body in found) == sorted(
        [round(hollow.volume(), 3), 1000.0]
    )
    assert all(body.volume() > 0 for body in found)


def test_reverse_winding_is_exact_for_double_precision_vertices() -> None:
    # Split vertices are doubles; reversing must not round them to float32.
    shell = cube(10.0).translate((0.1, 0.2, 0.3)) - cube(2.0).translate((3.3, 3.3, 3.3))
    half = shell.split_by_plane((1.0, 0.0, 0.0), 1.0 / 3.0)[0]
    back = geometry.reverse_winding(geometry.reverse_winding(half))
    assert back.volume() == pytest.approx(half.volume(), rel=1e-12)
    assert back.bounding_box() == pytest.approx(half.bounding_box(), abs=1e-12)
