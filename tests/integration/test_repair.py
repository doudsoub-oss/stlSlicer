"""Phase 2: load, repair and shell normalization on the Appendix D fixtures (PLAN.md Phase 2)."""

import dataclasses
import math
from collections.abc import Callable
from pathlib import Path

import pytest
import trimesh
from manifold3d import Error, Manifold

from stlsplit import geometry, io, repair
from stlsplit.config import Config, ModelConfig, RepairConfig
from stlsplit.errors import ConfigError, ExitCode, RepairError
from tests.conftest import (
    SPHERE_SEGMENTS,
    ball_in_hollow_sphere,
    capless_sphere,
    cube,
    dense_sphere,
    duplicated_cube,
    edge_touching_cubes,
    embedded_cube,
    finned_cube,
    flat_sheet,
    hollow_sphere,
    hollow_sphere_with_a_flipped_triangle,
    inside_out_cube,
    inside_out_hollow_sphere,
    inverted_body,
    missing_face_cube,
    open_edge_count,
    overlapping_hollow_spheres,
    overlapping_shells,
    soup_cube,
    two_bodies,
    void_across_two_cubes,
    void_in_ball_in_hollow_sphere,
)

WriteStl = Callable[[Manifold | trimesh.Trimesh, str], Path]


def prepare(
    write_stl: WriteStl,
    model: Manifold | trimesh.Trimesh,
    *,
    deep: bool = False,
    simplify: float = 0.0,
) -> tuple[Manifold, repair.RepairReport]:
    """Write the model to STL, load it the way the CLI does, and run ``repair.prepare``."""
    mesh, _ = io.load_stl(write_stl(model, "model"), 1.0)
    cfg = dataclasses.replace(
        Config(), repair=RepairConfig(deep=deep), model=ModelConfig(simplify=simplify)
    )
    return repair.prepare(mesh, cfg)


def codes(report: repair.RepairReport) -> list[str]:
    return [d.code for d in report.diagnostics]


def assert_valid(body: Manifold, report: repair.RepairReport) -> None:
    assert body.status() == Error.NoError
    assert body.volume() > 0
    assert report.reference_volume == body.volume()


# --- No repair needed ----------------------------------------------------------------------------


def test_clean_cube_passes_through_without_repair(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, cube())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert report.steps == ()
    assert report.diagnostics == ()
    assert (report.bodies, report.voids, report.inverted) == (1, 0, 0)


def test_soup_cube_loads_watertight(write_stl: WriteStl) -> None:
    # Documents trimesh's merge on load (docs/LIBRARY_NOTES.md): the soup needs no repair.
    soup = soup_cube()
    assert len(soup.vertices) == 36
    mesh, _ = io.load_stl(write_stl(soup, "soup"), 1.0)
    assert len(mesh.vertices) == 8
    assert mesh.is_watertight
    body, report = repair.prepare(mesh, Config())
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert report.steps == ()


def test_edge_touching_cubes_are_accepted_as_is(write_stl: WriteStl) -> None:
    # manifold3d pairs the four half-edges of the shared edge (docs/LIBRARY_NOTES.md), so the
    # PLAN.md r2 expectation "exit 2 without --deep-repair" can't hold (Appendix E, r5).
    body, report = prepare(write_stl, edge_touching_cubes())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(2000.0, rel=1e-6)
    assert report.steps == ()
    assert report.bodies == 2
    assert report.diagnostics == ()


# --- Basic and deep repair -----------------------------------------------------------------------


def test_cube_missing_a_face_is_repaired_with_w007(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, missing_face_cube())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert any("hole" in step for step in report.steps)
    assert codes(report) == ["W007"]
    assert all(step in report.diagnostics[0].message for step in report.steps)


def test_capless_sphere_exits_2_with_the_open_edge_count(write_stl: WriteStl) -> None:
    sphere = capless_sphere()
    expected = open_edge_count(sphere)
    assert expected > 4  # a large hole, not one fill_holes can close
    with pytest.raises(RepairError) as caught:
        prepare(write_stl, sphere)
    assert caught.value.exit_code == ExitCode.UNREPAIRABLE
    message = str(caught.value)
    assert f"{expected} open edges" in message
    assert "--deep-repair" in message


def test_finned_cube_exits_2_without_deep_repair(write_stl: WriteStl) -> None:
    with pytest.raises(RepairError) as caught:
        prepare(write_stl, finned_cube())
    assert caught.value.exit_code == ExitCode.UNREPAIRABLE
    message = str(caught.value)
    assert "2 open edges" in message
    assert "1 non-manifold edge" in message
    assert "1 body" in message
    assert "--deep-repair" in message


def test_finned_cube_is_repaired_with_deep_repair(write_stl: WriteStl) -> None:
    pytest.importorskip("pymeshlab")
    body, report = prepare(write_stl, finned_cube(), deep=True)
    assert_valid(body, report)
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert any("pymeshlab" in step for step in report.steps)
    assert codes(report) == ["W007"]


def test_deep_repair_without_pymeshlab_exits_2_with_the_install_hint(
    write_stl: WriteStl, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(geometry, "deep_repair_available", lambda: False)
    with pytest.raises(RepairError) as caught:
        prepare(write_stl, finned_cube(), deep=True)
    assert "stlsplit[deep-repair]" in str(caught.value)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        pytest.param("refused", "pymeshlab refused", id="pymeshlab-refuses"),
        pytest.param("unchanged", "after deep repair", id="still-not-closed"),
    ],
)
def test_failed_deep_repair_exits_2_with_the_counts(
    write_stl: WriteStl, monkeypatch: pytest.MonkeyPatch, outcome: str, expected: str
) -> None:
    def fake_deep_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
        return None if outcome == "refused" else mesh

    monkeypatch.setattr(geometry, "deep_repair_available", lambda: True)
    monkeypatch.setattr(geometry, "deep_repair", fake_deep_repair)
    with pytest.raises(RepairError) as caught:
        prepare(write_stl, finned_cube(), deep=True)
    message = str(caught.value)
    assert expected in message
    assert "1 non-manifold edge" in message
    assert "--deep-repair" not in message  # it was already used


def test_mesh_that_encloses_no_volume_exits_2(write_stl: WriteStl) -> None:
    with pytest.raises(RepairError) as caught:
        prepare(write_stl, flat_sheet())
    assert "no volume" in str(caught.value)


# --- Shell normalization -------------------------------------------------------------------------


def test_overlapping_shells_are_unioned_with_w010(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, overlapping_shells())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(12_000.0, rel=1e-6)
    assert report.bodies == 1
    assert codes(report) == ["W010"]


def test_hollow_sphere_keeps_its_void(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, hollow_sphere())
    assert_valid(body, report)
    expected = 4.0 / 3.0 * math.pi * (150.0**3 - 148.0**3)
    assert body.volume() == pytest.approx(expected, rel=0.01)
    assert (report.bodies, report.voids, report.inverted) == (1, 1, 0)
    assert report.diagnostics == ()


def test_ball_inside_a_hollow_sphere_is_kept(write_stl: WriteStl) -> None:
    # One level of nesting (PLAN.md Appendix E, r5): subtracting the void must not delete the
    # ball inside it, and the ball must not count as an overlapping shell.
    model = ball_in_hollow_sphere()
    body, report = prepare(write_stl, model)
    assert_valid(body, report)
    assert body.volume() == pytest.approx(model.volume(), rel=1e-6)
    assert (report.bodies, report.voids) == (2, 1)
    assert report.diagnostics == ()


def test_inverted_body_next_to_a_cube_is_flipped_with_w011(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, inverted_body())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(2000.0, rel=1e-6)
    assert (report.bodies, report.inverted) == (2, 1)
    assert codes(report) == ["W011"]


def test_single_inside_out_cube_is_flipped_with_w011(write_stl: WriteStl) -> None:
    # One component with negative volume also needs normalization (PLAN.md Appendix E, r5).
    body, report = prepare(write_stl, inside_out_cube())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert codes(report) == ["W011"]


def test_inside_out_hollow_sphere_keeps_its_void(write_stl: WriteStl) -> None:
    # Found by the Phase 2 review: the reversed outer shell used to become a solid of its own
    # and swallow the void (14.06M mm³ instead of 554 829).
    body, report = prepare(write_stl, inside_out_hollow_sphere())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(hollow_sphere().volume(), rel=1e-6)
    assert (report.bodies, report.voids, report.inverted) == (1, 1, 2)
    assert codes(report) == ["W011"]


@pytest.mark.parametrize("shell", [pytest.param(0, id="outer"), pytest.param(1, id="void")])
def test_one_flipped_triangle_in_a_hollow_sphere_keeps_its_void(shell: int) -> None:
    # Basic repair must keep each shell's majority orientation: fix_winding alone follows one
    # reference triangle, here the reversed one, and reversed the 2047 good ones instead
    # (docs/LIBRARY_NOTES.md). The mesh goes to repair directly, without an STL round trip:
    # loading renumbers the vertices, which changes the triangle trimesh takes as reference.
    body, report = repair.prepare(hollow_sphere_with_a_flipped_triangle(shell), Config())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(hollow_sphere().volume(), rel=1e-6)
    assert report.voids == 1
    assert codes(report) == ["W007"]
    assert "faces re-oriented: 1" in report.steps


def test_void_inside_a_ball_inside_a_hollow_sphere_is_kept(write_stl: WriteStl) -> None:
    # Two levels of nesting: each void is subtracted from the shell that contains it.
    body, report = prepare(write_stl, void_in_ball_in_hollow_sphere())
    assert_valid(body, report)
    ball = Manifold.sphere(100.0, SPHERE_SEGMENTS) - Manifold.sphere(50.0, SPHERE_SEGMENTS)
    assert body.volume() == pytest.approx(hollow_sphere().volume() + ball.volume(), rel=1e-6)
    assert (report.bodies, report.voids) == (2, 2)
    assert report.diagnostics == ()


def test_overlapping_hollow_spheres_keep_their_walls(write_stl: WriteStl) -> None:
    # Found by the Phase 2 review: subtracting every void from the union of every solid cut
    # each sphere's wall where it crosses the other's void (927 978 mm³ instead of 1 106 891).
    body, report = prepare(write_stl, overlapping_hollow_spheres())
    assert_valid(body, report)
    expected = hollow_sphere() + hollow_sphere().translate((200.0, 0.0, 0.0))
    assert body.volume() == pytest.approx(expected.volume(), rel=1e-6)
    assert report.voids == 2
    assert codes(report) == ["W010"]


def test_part_embedded_in_another_is_absorbed_with_w010(write_stl: WriteStl) -> None:
    # A shell facing outwards inside a solid is a redundant part, not a void.
    body, report = prepare(write_stl, embedded_cube())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(8000.0, rel=1e-6)
    assert (report.bodies, report.voids) == (1, 0)
    assert codes(report) == ["W010"]


@pytest.mark.parametrize(
    ("body_inside", "expected", "bodies"),
    [
        pytest.param(False, 12_000.0 - 320.0, 1, id="empty"),
        pytest.param(True, 12_000.0 - 320.0 + 8.0, 2, id="with-a-body-inside"),
    ],
)
def test_void_across_two_overlapping_cubes_is_kept(
    write_stl: WriteStl, body_inside: bool, expected: float, bodies: int
) -> None:
    # Inside the union of the two cubes but inside neither alone; a body floating in it is
    # added back after the void is subtracted.
    body, report = prepare(write_stl, void_across_two_cubes(body_inside))
    assert_valid(body, report)
    assert body.volume() == pytest.approx(expected, rel=1e-6)
    assert (report.bodies, report.voids) == (bodies, 1)
    assert codes(report) == ["W010"]


@pytest.mark.parametrize(
    ("inside_out", "expected_codes"),
    [
        pytest.param(False, ["W010"], id="outwards"),
        pytest.param(True, ["W010", "W011"], id="inside-out"),
    ],
)
def test_duplicated_body_is_merged(
    write_stl: WriteStl, inside_out: bool, expected_codes: list[str]
) -> None:
    # The copies share every vertex once loaded, yet manifold3d keeps them as two shells.
    body, report = prepare(write_stl, duplicated_cube(inside_out))
    assert_valid(body, report)
    assert body.volume() == pytest.approx(1000.0, rel=1e-6)
    assert (report.bodies, report.voids) == (1, 0)
    assert codes(report) == expected_codes


def test_two_separate_bodies_are_both_kept(write_stl: WriteStl) -> None:
    body, report = prepare(write_stl, two_bodies())
    assert_valid(body, report)
    assert body.volume() == pytest.approx(2000.0, rel=1e-6)
    assert report.bodies == 2
    assert report.diagnostics == ()


# --- Simplify ------------------------------------------------------------------------------------


def test_simplify_removes_triangles_and_keeps_the_volume(write_stl: WriteStl) -> None:
    sphere = dense_sphere()
    body, report = prepare(write_stl, sphere, simplify=0.05)
    assert_valid(body, report)
    assert body.num_tri() < sphere.num_tri()
    assert body.volume() == pytest.approx(sphere.volume(), rel=0.005)
    # The reference volume is the simplified body's: that's the one cut (Appendix E, r5).
    assert report.reference_volume == body.volume()


def test_simplify_that_erases_the_model_exits_1_naming_the_option(write_stl: WriteStl) -> None:
    # Found by the Phase 2 review: it used to exit 2 and blame the mesh.
    with pytest.raises(ConfigError) as caught:
        prepare(write_stl, cube(), simplify=1000.0)
    assert caught.value.key == "model.simplify"
    assert caught.value.exit_code == ExitCode.INVALID_INPUT
