"""Phase 6: plane nudging, the pure parts (PLAN.md Phase 6).

The candidate moves, the score of a set of regions, and the choice between scored moves are
tested on numbers and polygons; ``tests/integration/test_nudge.py`` runs ``grid.nudge`` on
figures that need it.
"""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from shapely.geometry import Point, box

from stlsplit import config, grid
from stlsplit.config import MAX_NUDGE_STEPS, Config
from stlsplit.grid import PlaneScore
from stlsplit.models import Grid, Plane
from tests.conftest import long_box


def make(overrides: dict[str, Any] | None = None) -> Config:
    cfg = config.with_overrides(Config(), overrides or {}, "test")
    config.validate(cfg)
    return cfg


# --- the 500 mm box (Phase 6 tests, first item) -----------------------------------------------


def test_long_box_keeps_its_planes_at_exactly_500_3_and_1000_3() -> None:
    cfg = make({"printer.bed": (220.0, 220.0, 220.0)})
    body, _ = grid.orient(long_box(), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    nudged = grid.nudge(body, layout, cfg)
    # Every position has the same 100 x 100 face, so moving gains nothing: exact floats.
    assert [plane.offset for plane in nudged.planes[0]] == [500 / 3, 1000 / 3]
    assert nudged == layout


# --- the fit check (task 4) --------------------------------------------------------------------


def grid_with_z_planes(*offsets: float) -> Grid:
    planes = tuple(Plane(axis=2, index=n, offset=value) for n, value in enumerate(offsets))
    return Grid(
        usable=(210.0, 210.0, 240.0),
        counts=(1, 1, len(offsets) + 1),
        planes=((), (), planes),
        extent=(60.0, 60.0, 300.0),
    )


def test_check_fits_accepts_cells_within_u() -> None:
    grid.check_fits(grid_with_z_planes(147.5))


def test_check_fits_rejects_a_cell_over_u() -> None:
    with pytest.raises(AssertionError, match="over U"):
        grid.check_fits(grid_with_z_planes(50.0))  # the cell above is 250 mm


def test_check_fits_rejects_planes_out_of_order() -> None:
    with pytest.raises(AssertionError, match="don't increase"):
        grid.check_fits(grid_with_z_planes(150.0, 150.0))


# --- candidate moves (task 1) ------------------------------------------------------------------


def test_candidate_shifts_are_step_multiples_within_the_window() -> None:
    shifts = grid.candidate_shifts(0.0, 150.0, 300.0, 240.0, steps=10, step=0.5)
    assert shifts == tuple(j * 0.5 for j in range(-10, 11))


def test_candidate_shifts_follow_the_slack_on_each_side() -> None:
    # The cell below is 100 mm and may grow by 31; the cell above is 130 and may grow by 1.
    shifts = grid.candidate_shifts(0.0, 100.0, 230.0, 131.0, steps=10, step=0.5)
    assert shifts == tuple(j * 0.5 for j in range(-2, 11))


def test_a_plane_never_reaches_its_neighbour() -> None:
    # U is no limit here; the plane 1 mm above its neighbour can't move onto it (Appendix E, r9).
    shifts = grid.candidate_shifts(100.0, 101.0, 300.0, 1000.0, steps=10, step=0.5)
    assert shifts == tuple(j * 0.5 for j in range(-1, 11))


def test_no_step_gives_no_move() -> None:
    assert grid.candidate_shifts(0.0, 150.0, 300.0, 240.0, steps=0, step=0.5) == (0.0,)


def nudge_steps(window: float, step: float) -> int:
    overrides = {"advanced.nudge_window": window, "advanced.nudge_step": step}
    return config.derived(make(overrides)).nudge_steps


def test_the_window_is_counted_in_whole_steps() -> None:
    assert nudge_steps(5.0, 0.5) == 10  # the defaults
    assert nudge_steps(0.4, 0.5) == 0  # smaller than one step: the plane stays
    assert nudge_steps(0.0, 0.5) == 0  # nudging off
    assert nudge_steps(0.3, 0.1) == 3  # 0.3 / 0.1 is 2.9999999999999996 in floats


def test_at_most_max_nudge_steps_on_each_side() -> None:
    assert nudge_steps(5.0, 0.05) == MAX_NUDGE_STEPS
    assert nudge_steps(0.9, 0.009) == MAX_NUDGE_STEPS  # 100.00000000000001 in floats
    shifts = grid.candidate_shifts(0.0, 150.0, 300.0, 240.0, steps=MAX_NUDGE_STEPS, step=0.05)
    assert len(shifts) == 2 * MAX_NUDGE_STEPS + 1


USABLE = st.floats(min_value=10.0, max_value=300.0)
FILL = st.floats(min_value=0.001, max_value=1.0)


@given(
    low=st.floats(min_value=0.0, max_value=1000.0),
    usable=USABLE,
    below=FILL,
    above=FILL,
    steps=st.integers(min_value=0, max_value=MAX_NUDGE_STEPS),
    step=st.floats(min_value=0.05, max_value=5.0),
)
def test_every_candidate_shift_keeps_both_cells_within_u(
    low: float, usable: float, below: float, above: float, steps: int, step: float
) -> None:
    offset = low + below * usable
    high = offset + above * usable

    def valid(shift: float) -> bool:
        position = offset + shift
        return (
            abs(round(shift / step)) <= steps
            and low < position < high
            and grid.fits(position - low, usable)
            and grid.fits(high - position, usable)
        )

    shifts = grid.candidate_shifts(low, offset, high, usable, steps, step)
    assert 0.0 in shifts  # the plane may always stay
    assert all(valid(shift) for shift in shifts)
    assert all(shift == round(shift / step) * step for shift in shifts)
    # Nothing is missing: every multiple of the step in the window that fits is offered.
    wider = steps + 2
    assert shifts == tuple(j * step for j in range(-wider, wider + 1) if valid(j * step))


# --- the score (task 2) --------------------------------------------------------------------------


def test_score_counts_regions_without_room_then_tiny_islands() -> None:
    cfg = make()
    neck, fin, face = box(0, 0, 6, 6), box(0, 0, 100, 2), box(0, 0, 60, 60)
    assert grid.score_regions([neck], cfg) == PlaneScore(no_room=1, islands=1)
    assert grid.score_regions([fin], cfg) == PlaneScore(no_room=1, islands=0)  # 200 mm²
    assert grid.score_regions([face], cfg) == PlaneScore(no_room=0, islands=0)
    assert grid.score_regions([face, neck, fin], cfg) == PlaneScore(no_room=2, islands=1)
    assert grid.score_regions([], cfg) == PlaneScore(no_room=0, islands=0)


def test_island_threshold_is_the_derived_island_area() -> None:
    # island = 4 · π · 5² = 314 mm²; the inset is 2 + 5.2 + 0.4 = 7.6 mm.
    cfg = make({"connectors.diameter": 10.0, "connectors.length": 30.0})
    disc = Point(0.0, 0.0).buffer(9.0, quad_segs=64)  # 254 mm², room for an axis
    assert grid.score_regions([disc], cfg) == PlaneScore(no_room=0, islands=1)


# --- the choice (task 2, ties) -----------------------------------------------------------------


def test_equal_scores_go_to_the_smaller_move_then_the_lower_offset() -> None:
    scores = {-1.0: PlaneScore(0, 0), -0.5: PlaneScore(0, 1), 0.0: PlaneScore(1, 1)}
    scores |= {0.5: PlaneScore(0, 1), 1.0: PlaneScore(0, 0)}
    assert grid.choose_shift(scores, scores.__getitem__) == -1.0
    scores[-1.0] = PlaneScore(0, 1)
    assert grid.choose_shift(scores, scores.__getitem__) == 1.0
    scores[1.0] = PlaneScore(0, 1)
    assert grid.choose_shift(scores, scores.__getitem__) == -0.5


def test_a_plane_stays_when_moving_gains_nothing() -> None:
    scores = dict.fromkeys((-1.0, -0.5, 0.0, 0.5, 1.0), PlaneScore(1, 0))
    assert grid.choose_shift(scores, scores.__getitem__) == 0.0


@given(data=st.data())
def test_choice_does_not_depend_on_candidate_order(data: st.DataObject) -> None:
    count = data.draw(st.integers(min_value=0, max_value=12))
    step = data.draw(st.sampled_from([0.1, 0.25, 0.5, 1.0]))
    shifts = [j * step for j in range(-count, count + 1)]
    # Few score values, so ties on the first keys (and between +δ and −δ) are common.
    values = st.builds(PlaneScore, st.integers(0, 2), st.integers(0, 2))
    scores = {shift: data.draw(values) for shift in shifts}
    order = data.draw(st.permutations(shifts))
    expected = min(shifts, key=lambda shift: (*scores[shift], abs(shift), shift))
    assert grid.choose_shift(order, scores.__getitem__) == expected
    assert grid.choose_shift(reversed(order), scores.__getitem__) == expected


def test_choice_without_candidates_is_an_error() -> None:
    with pytest.raises(ValueError, match="no candidate"):
        grid.choose_shift([], lambda shift: PlaneScore(0, 0))
