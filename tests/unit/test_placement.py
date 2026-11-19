"""Phase 5: safe regions, candidates, the connector count and the trial order (PLAN.md Phase 5,
tasks 1 to 4).

2D only, in plane-local (u, v), mm. With the defaults (d = 5): inset = 2 + 2.7 + 0.4 = 5.1,
g = 1.25, s_min = 15 and A = 900 mm² (§6.1). ``connectors.select`` takes the 3D checks as a
callback, so the order can be tested without solids.
"""

import itertools
import math
from typing import Any

import numpy as np
import pytest
import shapely
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Point, box

from stlsplit import config, connectors, geometry
from stlsplit.config import MAX_CANDIDATE_TRIALS, Config

CFG = Config()
DERIVED = config.derived(CFG)


def make(overrides: dict[str, Any]) -> Config:
    cfg = config.with_overrides(Config(), overrides, "test")
    config.validate(cfg)
    return cfg


def safe_of(region: Any, cfg: Config = CFG) -> MultiPolygon:
    return connectors.safe_region(region, cfg)


def positions(points: NDArray[np.float64], indices: list[int]) -> list[tuple[float, float]]:
    return [(float(points[i][0]), float(points[i][1])) for i in indices]


# --- safe region (task 1) ---------------------------------------------------------------------


def test_safe_region_is_the_region_inset_by_wall_hole_radius_and_chamfer() -> None:
    assert DERIVED.inset == pytest.approx(5.1)
    safe = safe_of(box(0.0, 0.0, 40.0, 40.0))
    assert safe.bounds == pytest.approx((5.1, 5.1, 34.9, 34.9))
    assert safe.area == pytest.approx(29.8**2)  # 888.04 mm², under A = 900


def test_thin_ring_has_an_empty_safe_region_and_no_candidates() -> None:
    outer, inner = Point(150.0, 150.0).buffer(150.0, 64), Point(150.0, 150.0).buffer(148.0, 64)
    safe = safe_of(outer.difference(inner))
    assert safe.is_empty
    points = connectors.candidates(safe, CFG)
    assert points.shape == (0, 2)
    assert connectors.connector_count(safe, points, CFG) == 0


def test_safe_region_keeps_each_part_that_has_room() -> None:
    # Two squares joined by a 4 mm bar: the bar has no room, so two parts remain.
    region = box(0, 0, 20, 20).union(box(20, 8, 40, 12)).union(box(40, 0, 64, 24))
    safe = safe_of(region)
    assert len(safe.geoms) == 2
    # Each part is its square inset by 5.1, plus a small bulge towards the bar: the concave
    # corners where the bar meets the square are inset along an arc (round joins).
    cores = [box(5.1, 5.1, 14.9, 14.9), box(45.1, 5.1, 58.9, 18.9)]
    parts = sorted(safe.geoms, key=lambda part: part.bounds)
    for part, core in zip(parts, cores, strict=True):
        assert part.covers(core.buffer(-1e-9))
        assert 0.0 < part.area - core.area < 1.0


# --- candidates (task 2) ----------------------------------------------------------------------


def test_candidates_are_the_grid_points_inside_plus_each_parts_polylabel_sorted_by_u_v() -> None:
    safe = safe_of(box(0.0, 0.0, 40.0, 41.0))  # u in [5.1, 34.9], v in [5.1, 35.9]
    points = connectors.candidates(safe, CFG)
    step = DERIVED.candidate_step
    grid_points = {(i * step, j * step) for i in range(5, 28) for j in range(5, 29)}
    label = geometry.polylabel_point(safe.geoms[0])
    expected = sorted(grid_points | {label})
    assert positions(points, list(range(len(points)))) == expected


def test_candidates_have_no_duplicates() -> None:
    safe = safe_of(box(0.0, 0.0, 100.0, 100.0))
    points = connectors.candidates(safe, CFG)
    label = geometry.polylabel_point(safe.geoms[0])  # within 1e-3 of (50, 50), a grid point
    grid_points = {(i * 1.25, j * 1.25) for i in range(5, 76) for j in range(5, 76)}
    assert len(points) == len(grid_points | {label})
    assert len({tuple(point) for point in points.tolist()}) == len(points)


# --- connector count (task 3) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("region", "overrides", "count"),
    [
        pytest.param(box(0, 0, 100, 100), {}, 4, id="100x100-clamped-to-k-max"),
        pytest.param(box(0, 0, 40, 40), {}, 2, id="40x40-two-although-area-under-a"),
        pytest.param(box(0, 0, 200, 12), {}, 2, id="long-strip-two-although-area-under-a"),
        pytest.param(box(0, 0, 20, 20), {}, 1, id="no-two-candidates-15-mm-apart"),
        pytest.param(box(0, 0, 100, 100), {"connectors.max_per_face": 1}, 1, id="k-max-1"),
        pytest.param(box(0, 0, 210, 210), {"connectors.max_per_face": 50}, 44, id="area-rule"),
    ],
)
def test_connector_count(region: Any, overrides: dict[str, Any], count: int) -> None:
    cfg = make(overrides)
    safe = safe_of(region, cfg)
    assert connectors.connector_count(safe, connectors.candidates(safe, cfg), cfg) == count


# --- trial order (task 4) ---------------------------------------------------------------------


def square_candidates() -> tuple[MultiPolygon, NDArray[np.float64]]:
    safe = safe_of(box(0.0, 0.0, 100.0, 100.0))
    return safe, connectors.candidates(safe, CFG)


def test_two_or_more_start_with_the_farthest_pair_then_farthest_point_sampling() -> None:
    safe, points = square_candidates()
    selection = connectors.select(safe, points, 4, CFG, lambda index: True)
    # Both diagonals are hull diameters: ties go to (u, v) order. Then the two remaining
    # corners, equally far from the first two, again in (u, v) order.
    assert positions(points, selection.accepted) == [
        (6.25, 6.25),
        (93.75, 93.75),
        (6.25, 93.75),
        (93.75, 6.25),
    ]
    assert selection.tried == selection.accepted


def test_after_a_rejection_the_next_trial_is_the_farthest_from_the_accepted_connectors() -> None:
    safe, points = square_candidates()
    rejected = (93.75, 93.75)
    selection = connectors.select(
        safe, points, 2, CFG, lambda index: tuple(points[index].tolist()) != rejected
    )
    # (92.5, 93.75) and (93.75, 92.5) are equally far from (6.25, 6.25): (u, v) order.
    assert positions(points, selection.tried) == [(6.25, 6.25), rejected, (92.5, 93.75)]
    assert positions(points, selection.accepted) == [(6.25, 6.25), (92.5, 93.75)]


def test_while_none_is_accepted_the_trials_spread_out() -> None:
    safe, points = square_candidates()
    rejected = {(6.25, 6.25), (93.75, 93.75)}
    selection = connectors.select(
        safe, points, 2, CFG, lambda index: tuple(points[index].tolist()) not in rejected
    )
    assert positions(points, selection.tried) == [
        (6.25, 6.25),
        (93.75, 93.75),
        (6.25, 93.75),
        (93.75, 6.25),
    ]
    assert positions(points, selection.accepted) == [(6.25, 93.75), (93.75, 6.25)]


def test_candidates_closer_than_s_min_to_an_accepted_connector_are_never_tried() -> None:
    # A strip about 28 mm long: room for two connectors 15 mm apart, not three.
    safe = safe_of(box(0.0, 0.0, 40.0, 12.0))
    points = connectors.candidates(safe, CFG)
    selection = connectors.select(safe, points, 3, CFG, lambda index: True)
    assert len(selection.accepted) == 2
    first, second = points[selection.accepted].tolist()
    assert math.dist(first, second) >= DERIVED.connector_spacing
    assert selection.tried == selection.accepted
    for point in points.tolist():
        assert min(math.dist(point, first), math.dist(point, second)) < DERIVED.connector_spacing


def test_one_connector_tries_the_largest_parts_polylabel_then_by_distance_to_the_boundary() -> None:
    region = box(0, 0, 20, 20).union(box(20, 8, 40, 12)).union(box(40, 0, 64, 24))
    safe = safe_of(region)
    points = connectors.candidates(safe, CFG)
    selection = connectors.select(safe, points, 1, CFG, lambda index: False)

    assert selection.accepted == []
    assert len(selection.tried) == len(points) < MAX_CANDIDATE_TRIALS
    largest = max(safe.geoms, key=lambda part: part.area)
    assert positions(points, selection.tried[:1]) == [geometry.polylabel_point(largest)]
    rest = points[selection.tried[1:]]
    distances = shapely.distance(safe.boundary, shapely.points(rest))
    keys = [(-dist, u, v) for dist, (u, v) in zip(distances, rest.tolist(), strict=True)]
    assert keys == sorted(keys)


def test_one_connector_stops_at_the_first_accepted_candidate() -> None:
    safe = safe_of(box(0.0, 0.0, 20.0, 20.0))
    points = connectors.candidates(safe, CFG)
    selection = connectors.select(safe, points, 1, CFG, lambda index: True)
    assert positions(points, selection.accepted) == [geometry.polylabel_point(safe.geoms[0])]
    assert selection.tried == selection.accepted


@pytest.mark.parametrize("count", [1, 4])
def test_trials_stop_after_max_candidate_trials(count: int) -> None:
    safe, points = square_candidates()
    selection = connectors.select(safe, points, count, CFG, lambda index: False)
    assert len(selection.tried) == MAX_CANDIDATE_TRIALS < len(points)
    assert len(set(selection.tried)) == len(selection.tried)


def test_accepted_connectors_are_at_least_s_min_apart() -> None:
    cfg = make({"connectors.max_per_face": 50})
    safe = safe_of(box(0.0, 0.0, 210.0, 210.0), cfg)
    points = connectors.candidates(safe, cfg)
    selection = connectors.select(safe, points, 44, cfg, lambda index: True)
    assert len(selection.accepted) == 44
    accepted = points[selection.accepted]
    for a, b in itertools.combinations(accepted.tolist(), 2):
        assert math.dist(a, b) >= DERIVED.connector_spacing


# --- standard lengths (task 5.2) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "lengths"),
    [
        pytest.param(None, (20.0, 18.0, 16.0), id="no-ray-hit"),
        pytest.param(10.5, (20.0, 18.0, 16.0), id="exactly-h-20"),
        pytest.param(10.0, (18.0, 16.0), id="12-mm-behind-the-face"),
        pytest.param(8.5, (16.0,), id="exactly-h-16"),
        pytest.param(8.49, (), id="under-h-16"),
        pytest.param(4.0, (), id="6-mm-behind-the-face"),
    ],
)
def test_lengths_that_fit_are_the_standard_lengths_whose_hole_is_shallow_enough(
    available: float | None, lengths: tuple[float, ...]
) -> None:
    assert connectors.lengths_that_fit(available, CFG) == lengths
