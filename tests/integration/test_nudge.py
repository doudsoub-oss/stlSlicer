"""Phase 6: plane nudging on figures that need it (PLAN.md Phase 6).

``tall_figure`` is stacked boxes joined by 6 × 6 necks: a plane through a neck cuts a 36 mm²
region, a tiny island with no room for a connector. Bodies start at the origin, so they are
in the cutting frame as built.
"""

import itertools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from manifold3d import Manifold

from stlsplit import config, grid
from stlsplit.config import Config
from stlsplit.grid import PlaneScore
from stlsplit.models import Grid, Plane
from tests.conftest import tall_figure, two_bodies

EPS = Config().advanced.section_epsilon


def make(overrides: dict[str, Any] | None = None) -> Config:
    cfg = config.with_overrides(Config(), overrides or {}, "test")
    config.validate(cfg)
    return cfg


def planned(body: Manifold, cfg: Config) -> tuple[Manifold, Grid]:
    oriented, _ = grid.orient(body, cfg)
    layout, _ = grid.even_grid(grid.extent(oriented), config.derived(cfg).usable)
    return oriented, layout


def offsets(layout: Grid, axis: int) -> list[float]:
    return [plane.offset for plane in layout.planes[axis]]


def score(body: Manifold, layout: Grid, plane: Plane, cfg: Config) -> PlaneScore:
    return grid.score_regions(grid.plane_regions(body, layout, plane, EPS), cfg)


def test_tall_figure_plane_moves_off_the_neck() -> None:
    cfg = make()
    body, layout = planned(tall_figure(), cfg)
    assert layout.counts == (1, 1, 2)
    assert offsets(layout, 2) == [150.0]
    nudged = grid.nudge(body, layout, cfg)
    # The neck spans 148 to 153: 147.5 (2.5 mm down) is the closest position off it. At 148
    # the contact region is still the neck's (ADR-0002).
    assert nudged.planes[2] == (Plane(axis=2, index=0, offset=147.5),)
    assert (nudged.usable, nudged.counts, nudged.extent) == (
        layout.usable,
        layout.counts,
        layout.extent,
    )
    assert score(body, layout, layout.planes[2][0], cfg) == PlaneScore(no_room=1, islands=1)
    assert score(body, nudged, nudged.planes[2][0], cfg) == PlaneScore(no_room=0, islands=0)


def test_plane_stays_when_no_position_in_the_window_is_better() -> None:
    cfg = make()
    body, layout = planned(tall_figure(necks=((140.0, 160.0),)), cfg)
    # Every position within 5 mm of 150 cuts the neck: no gain, no move.
    assert grid.nudge(body, layout, cfg) == layout


def test_plane_in_a_gap_between_bodies_cuts_nothing_and_stays() -> None:
    cfg = make()
    body = two_bodies()  # two 10 mm cubes, 10 mm apart along X
    layout, _ = grid.even_grid(grid.extent(body), (20.0, 210.0, 210.0))
    assert offsets(layout, 0) == [15.0]
    assert grid.plane_regions(body, layout, layout.planes[0][0], EPS) == []
    assert grid.nudge(body, layout, cfg) == layout


def test_nudge_window_zero_keeps_the_even_grid() -> None:
    cfg = make({"advanced.nudge_window": 0.0})
    body, layout = planned(tall_figure(), cfg)
    assert grid.nudge(body, layout, cfg) is layout


def test_each_move_updates_the_slack_of_the_next_plane() -> None:
    # Three cells of 238 mm on U_z = 240 (task 3): on the even grid each plane may move by
    # 2 mm at most. The first plane leaves its neck (236.4 to 239.2) 1.5 mm up, at 239.5, which
    # shrinks the middle cell to 236.5 mm. The second plane's neck (473.5 to 478.8) needs a
    # 3 mm move up: over the even grid's slack, within the slack the first move left.
    cfg = make()
    figure = tall_figure(height=714.0, necks=((236.4, 239.2), (473.5, 478.8)))
    body, layout = planned(figure, cfg)
    assert layout.usable[2] == 240.0
    assert offsets(layout, 2) == [238.0, 476.0]
    nudged = grid.nudge(body, layout, cfg)
    assert offsets(nudged, 2) == [239.5, 479.0]
    bounds = grid.axis_bounds(nudged, 2)
    assert all(grid.fits(high - low, 240.0) for low, high in itertools.pairwise(bounds))


NECK_END = st.floats(min_value=0.1, max_value=8.0)


@settings(max_examples=25, deadline=None)
@given(
    cells=st.integers(min_value=2, max_value=3),
    usable=st.floats(min_value=100.0, max_value=240.0),
    fill=st.floats(min_value=0.95, max_value=1.0),
    necks=st.lists(st.tuples(NECK_END, NECK_END), min_size=2, max_size=2),
    window=st.floats(min_value=0.0, max_value=10.0),
    step=st.floats(min_value=0.25, max_value=3.0),
)
def test_every_cell_fits_u_after_nudging(
    cells: int,
    usable: float,
    fill: float,
    necks: list[tuple[float, float]],
    window: float,
    step: float,
) -> None:
    # Cells close to U, so the slack is often smaller than the window; a neck around every
    # even plane, so most planes want to move.
    height = cells * usable * fill
    spans = [
        (k * height / cells - below, k * height / cells + above)
        for k, (below, above) in zip(range(1, cells), necks, strict=False)
    ]
    body = tall_figure(height=height, necks=spans)
    cfg = make({"advanced.nudge_window": window, "advanced.nudge_step": step})
    layout, _ = grid.even_grid(grid.extent(body), (210.0, 210.0, usable))
    assert layout.counts[2] == cells
    nudged = grid.nudge(body, layout, cfg)

    bounds = grid.axis_bounds(nudged, 2)
    assert all(low < high for low, high in itertools.pairwise(bounds))
    assert all(grid.fits(high - low, usable) for low, high in itertools.pairwise(bounds))
    for before, after in zip(layout.planes[2], nudged.planes[2], strict=True):
        shift = after.offset - before.offset
        assert after.index == before.index
        assert abs(shift / step - round(shift / step)) < 1e-6
        assert abs(round(shift / step)) <= config.derived(cfg).nudge_steps  # within the window
        assert abs(shift) <= window + step * 1e-6
        # Only Z planes: the cells' (u, v) rectangles don't change, so each plane's score can
        # be compared before and after; a move never makes it worse.
        assert score(body, nudged, after, cfg) <= score(body, layout, before, cfg)
