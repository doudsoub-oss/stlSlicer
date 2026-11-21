import itertools
import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from manifold3d import Error, Manifold

from stlsplit import config, grid
from stlsplit.config import GRID_TOLERANCE, MAX_GRID_CELLS, Config
from stlsplit.errors import InputError
from stlsplit.models import Diagnostic, Grid, Orientation
from tests.conftest import CHIRAL_L_MARKS, chiral_l, cube, long_box

# Model sizes from 0.01 mm to 10 m and usable sizes from 1 mm to 1 m: ratios up to 10⁴, where
# float noise stays far below GRID_TOLERANCE.
LENGTHS = st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False)
USABLE = st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)
EXTENTS = st.tuples(LENGTHS, LENGTHS, LENGTHS)
USABLES = st.tuples(USABLE, USABLE, USABLE)


def make(overrides: dict[str, Any]) -> Config:
    cfg = config.with_overrides(Config(), overrides, "test")
    config.validate(cfg)
    return cfg


def plan(body: Manifold, cfg: Config) -> tuple[Manifold, Orientation, Grid, tuple[Diagnostic, ...]]:
    oriented, orientation = grid.orient(body, cfg)
    layout, diagnostics = grid.even_grid(grid.extent(oriented), config.derived(cfg).usable)
    return oriented, orientation, layout, diagnostics


def offsets(layout: Grid, axis: int) -> list[float]:
    return [plane.offset for plane in layout.planes[axis]]


def expected_count(extent: float, usable: float) -> int:
    """The count formula of PLAN.md Phase 3, written out independently of ``grid``."""
    return max(1, math.ceil(extent / usable - GRID_TOLERANCE))


def triple_product(points: np.ndarray) -> float:
    corner, a, b, c = points
    return float(np.dot(np.cross(a - corner, b - corner), c - corner))


# --- Even grid (PLAN.md Phase 3, tasks 4-6) ---------------------------------------------------


def test_long_box_gets_three_cells_along_x_with_even_planes() -> None:
    cfg = make({"printer.bed": (220.0, 220.0, 220.0), "printer.margin": 5.0})
    _, orientation, layout, diagnostics = plan(long_box(), cfg)
    assert orientation.name == "identity"  # every rotation gives 3 cells: the tie keeps it
    assert layout.usable == (210.0, 210.0, 210.0)
    assert layout.extent == (500.0, 100.0, 100.0)
    assert layout.counts == (3, 1, 1)
    assert offsets(layout, 0) == pytest.approx([500 / 3, 1000 / 3], abs=1e-6)
    assert [(plane.axis, plane.index) for plane in layout.planes[0]] == [(0, 0), (0, 1)]
    assert layout.planes[1] == ()
    assert layout.planes[2] == ()
    assert diagnostics == ()


def test_model_that_fits_gets_one_cell_and_w012() -> None:
    _, _, layout, diagnostics = plan(cube(100.0), Config())
    assert layout.counts == (1, 1, 1)
    assert layout.planes == ((), (), ())
    assert [(d.code, d.severity) for d in diagnostics] == [("W012", "info")]
    assert grid.cell_indices(layout) == ((0, 0, 0),)
    assert grid.cell_bounds(layout, (0, 0, 0)) == ((0.0, 0.0, 0.0), (100.0, 100.0, 100.0))


def test_peg_mode_grid_uses_the_reduced_usable_volume() -> None:
    # Auto-orient off, so only U changes: 205 mm fits 210 (dowels) but not 200 (pegs).
    body = Manifold.cube((205.0, 100.0, 100.0))
    _, _, dowel, _ = plan(body, make({"model.auto_orient": False}))
    _, _, peg, _ = plan(body, make({"model.auto_orient": False, "connectors.type": "peg"}))
    assert dowel.usable == (210.0, 210.0, 240.0)
    assert peg.usable == (200.0, 200.0, 230.0)  # bed − 2·margin − L_max/2
    assert dowel.counts == (1, 1, 1)
    assert peg.counts == (2, 1, 1)
    assert offsets(peg, 0) == pytest.approx([102.5])


@pytest.mark.parametrize(
    ("extent", "usable", "count"),
    [
        pytest.param(210.0, 210.0, 1, id="exactly-U"),
        pytest.param(210.0 + 1e-7, 210.0, 1, id="float-noise-over-U"),
        pytest.param(210.0 * (1 + 1e-8), 210.0, 2, id="really-over-U"),
        pytest.param(420.0, 210.0, 2, id="exactly-2U"),
        pytest.param(420.00000000000006, 210.0, 2, id="one-ulp-over-2U"),
        pytest.param(420.001, 210.0, 3, id="over-2U"),
        # One cell exactly at the slack's edge. U·(1 + 1e-9) rounds below these extents, so a
        # fit check written as "size <= U·(1 + tol)" disagreed with the count (Phase 3 review;
        # a 100 x 100 x 230 box with float32 noise exited 4 in peg mode).
        pytest.param(230.00000023000004, 230.0, 1, id="slack-edge-U230"),
        pytest.param(220.00000022000003, 220.0, 1, id="slack-edge-U220"),
    ],
)
def test_cell_count_tolerates_float_noise_only(extent: float, usable: float, count: int) -> None:
    assert grid.cell_count(extent, usable) == count
    # The fit check accepts what the count allows (PLAN.md Appendix E, r6): no AssertionError.
    layout, _ = grid.even_grid((extent, 10.0, 10.0), (usable, usable, usable))
    assert layout.counts[0] == count


@given(
    usable=USABLE,
    cells=st.integers(min_value=1, max_value=50),
    ulps=st.integers(min_value=-64, max_value=64),
)
def test_extents_at_the_slack_edge_never_fail_the_fit_check(
    usable: float, cells: int, ulps: int
) -> None:
    # Extents within 64 floats of cells · U · (1 + tol), where float rounding decides.
    edge = cells * usable * (1 + GRID_TOLERANCE)
    extent = edge + ulps * math.ulp(edge)
    layout, _ = grid.even_grid((extent, 1.0, 1.0), (usable, usable, usable))  # no AssertionError
    assert layout.counts[0] in (cells, cells + 1)
    sizes = np.diff(grid.axis_bounds(layout, 0))
    # A cell fits when it would be one cell on its own: the count's own arithmetic.
    assert (sizes / usable - GRID_TOLERANCE <= 1).all()


def test_cells_are_listed_in_index_order_with_their_bounds() -> None:
    layout, diagnostics = grid.even_grid((300.0, 300.0, 100.0), (210.0, 210.0, 240.0))
    assert diagnostics == ()
    assert grid.cell_indices(layout) == ((0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0))
    assert grid.axis_bounds(layout, 0) == (0.0, 150.0, 300.0)
    assert grid.axis_bounds(layout, 2) == (0.0, 100.0)
    assert grid.cell_bounds(layout, (1, 0, 0)) == ((150.0, 0.0, 0.0), (300.0, 150.0, 100.0))


@given(extent=EXTENTS, usable=USABLES)
def test_every_cell_fits_the_usable_volume(
    extent: tuple[float, float, float], usable: tuple[float, float, float]
) -> None:
    layout, _ = grid.even_grid(extent, usable)
    for axis in range(3):
        # Cells are products of one interval per axis, so checking the intervals checks them all.
        bounds = grid.axis_bounds(layout, axis)
        assert len(bounds) == layout.counts[axis] + 1
        assert bounds[0] == 0.0
        assert bounds[-1] == extent[axis]
        sizes = np.diff(bounds)
        assert (sizes > 0).all()
        # size ≤ U · (1 + tol), in grid.fits' arithmetic: written as size <= U * (1 + tol), it
        # rounds differently for one float at the edge (PLAN.md Appendix E, r6).
        assert (sizes / usable[axis] - GRID_TOLERANCE <= 1).all()


@given(extent=EXTENTS, usable=USABLES)
def test_cell_counts_are_minimal(
    extent: tuple[float, float, float], usable: tuple[float, float, float]
) -> None:
    layout, _ = grid.even_grid(extent, usable)
    for axis in range(3):
        n = layout.counts[axis]
        assert n >= 1
        if n > 1:  # n − 1 even cells would each be larger than U
            assert extent[axis] / (n - 1) > usable[axis]


# --- Auto-orient and the cutting frame (PLAN.md Phase 3, tasks 2-3) ---------------------------


def test_auto_orient_puts_the_460_mm_side_along_z() -> None:
    _, orientation, layout, _ = plan(Manifold.cube((460.0, 100.0, 100.0)), Config())
    # "90 deg about Y" and "240 deg about (1,1,1)" both give 2 cells; the first listed wins.
    assert orientation.name == "90 deg about Y"
    assert layout.extent == (100.0, 100.0, 460.0)
    assert layout.counts == (1, 1, 2)
    assert offsets(layout, 2) == pytest.approx([230.0])


def test_without_auto_orient_the_model_keeps_its_axes() -> None:
    cfg = make({"model.auto_orient": False})
    _, orientation, layout, _ = plan(Manifold.cube((460.0, 100.0, 100.0)), cfg)
    assert orientation.name == "identity"
    assert layout.counts == (3, 1, 1)


def test_every_candidate_rotation_is_a_proper_rotation() -> None:
    assert len(grid.ROTATIONS) == 6
    assert grid.ROTATIONS[0].name == "identity"
    np.testing.assert_array_equal(np.array(grid.ROTATIONS[0].matrix), np.eye(3))
    orders = set()
    for rotation in grid.ROTATIONS:
        matrix = np.array(rotation.matrix)
        assert np.linalg.det(matrix) == pytest.approx(1.0)
        # A signed permutation: one ±1 in each row and each column.
        assert set(np.abs(matrix).ravel().tolist()) == {0, 1}
        assert (np.abs(matrix).sum(axis=0) == 1).all()
        assert (np.abs(matrix).sum(axis=1) == 1).all()
        orders.add(tuple(np.abs(matrix).argmax(axis=1).tolist()))
    assert orders == set(itertools.permutations(range(3)))  # each axis order exactly once


@pytest.mark.parametrize("rotation", grid.ROTATIONS, ids=lambda rotation: rotation.name)
def test_chiral_l_keeps_its_handedness(rotation: grid.Rotation) -> None:
    shift = np.array((-7.0, 3.0, 11.0))  # off the origin, so the translation matters
    body = chiral_l().translate(tuple(shift))
    oriented, orientation = grid.to_cutting_frame(body, rotation)
    assert orientation.name == rotation.name
    matrix = np.array(orientation.input_to_cutting)
    assert matrix.shape == (4, 4)
    np.testing.assert_array_equal(matrix[3], (0.0, 0.0, 0.0, 1.0))
    np.testing.assert_array_equal(matrix[:3, :3], np.array(rotation.matrix))

    # The matrix describes what was done to the mesh: the same transform applied here gives
    # the same solid, and the marked vertices land on vertices of the oriented mesh.
    expected = body.transform(matrix[:3])
    assert (oriented - expected).volume() == pytest.approx(0.0, abs=1e-6)
    assert (expected - oriented).volume() == pytest.approx(0.0, abs=1e-6)
    marks = np.array(CHIRAL_L_MARKS) + shift
    mapped = marks @ matrix[:3, :3].T + matrix[:3, 3]
    vertices = np.asarray(oriented.to_mesh64().vert_properties)[:, :3]
    for point in mapped:
        assert np.min(np.linalg.norm(vertices - point, axis=1)) < 1e-9

    assert triple_product(marks) > 0
    assert triple_product(mapped) > 0  # same handedness: not mirrored (ADR-0008)
    assert oriented.status() == Error.NoError
    assert oriented.volume() == pytest.approx(body.volume(), rel=1e-12)
    assert oriented.bounding_box()[:3] == (0.0, 0.0, 0.0)


@given(extent=EXTENTS, usable=USABLES)
def test_auto_orient_picks_the_fewest_cells_and_the_first_on_a_tie(
    extent: tuple[float, float, float], usable: tuple[float, float, float]
) -> None:
    def cells(rotation: grid.Rotation) -> int:
        rotated = grid.rotated_extent(extent, rotation)
        return math.prod(expected_count(e, u) for e, u in zip(rotated, usable, strict=True))

    chosen = grid.choose_rotation(extent, usable, auto_orient=True)
    position = grid.ROTATIONS.index(chosen)
    assert cells(chosen) == min(cells(rotation) for rotation in grid.ROTATIONS)
    assert all(cells(rotation) > cells(chosen) for rotation in grid.ROTATIONS[:position])
    assert grid.choose_rotation(extent, usable, auto_orient=False) == grid.ROTATIONS[0]


def test_rotated_extent_follows_the_matrix() -> None:
    # "90 deg about Y": cutting (X, Y, Z) = input (+Z, +Y, −X).
    rotation = next(r for r in grid.ROTATIONS if r.name == "90 deg about Y")
    assert grid.rotated_extent((1.0, 2.0, 3.0), rotation) == (3.0, 2.0, 1.0)


# --- the cell limit (Phase 10, PLAN.md §7.5) ------------------------------------------------------


def test_cell_limit_accepts_exactly_the_limit() -> None:
    side = round(MAX_GRID_CELLS ** (1 / 3))
    assert side**3 == MAX_GRID_CELLS
    grid.check_cell_limit((side * 10.0, side * 10.0, side * 10.0), (10.0, 10.0, 10.0))


def test_cell_limit_refuses_one_cell_more_and_names_the_count() -> None:
    extent = (float(MAX_GRID_CELLS + 1) * 10.0, 10.0, 10.0)
    with pytest.raises(
        InputError, match=rf"{MAX_GRID_CELLS + 1} cells .*limit of {MAX_GRID_CELLS}"
    ):
        grid.check_cell_limit(extent, (10.0, 10.0, 10.0))


def test_cell_limit_refuses_a_huge_grid_without_building_it() -> None:
    # 10^36 cells: building them, or even their planes, would never finish.
    with pytest.raises(InputError, match="--scale"):
        grid.check_cell_limit((1e13, 1e13, 1e13), (1.0, 1.0, 1.0))
