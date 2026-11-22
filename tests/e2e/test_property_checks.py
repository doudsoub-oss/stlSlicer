"""The end-to-end checks can fail: each one is shown a damaged output (PLAN.md Phase 11).

A property test that can't fail proves nothing, and all of them read files through code written
for this suite, so each check gets a real split with one defect planted in it.
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

from stlsplit import config
from tests.conftest import manifold_to_trimesh
from tests.e2e import properties
from tests.e2e.properties import Split

pytestmark = pytest.mark.e2e

BED = ("--bed", "120", "120", "120")
TIMEOUT_SECONDS = 120.0


def split_of(root: Path, *arguments: str) -> Split:
    root.mkdir(parents=True)
    stl = root / "model.stl"
    manifold_to_trimesh(Manifold.cube((200.0, 100.0, 100.0))).export(stl, file_type="stl")
    out = root / "out"
    done = subprocess.run(
        [sys.executable, "-m", "stlsplit", str(stl), "-o", str(out), *BED, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return Split(out, done.stderr)


@pytest.fixture(scope="module")
def dowels(tmp_path_factory: pytest.TempPathFactory) -> Split:
    return split_of(tmp_path_factory.mktemp("checks") / "dowels")


@pytest.fixture(scope="module")
def pegs(tmp_path_factory: pytest.TempPathFactory) -> Split:
    return split_of(tmp_path_factory.mktemp("checks") / "pegs", "--connector", "peg")


def copy_of(split: Split, tmp_path: Path) -> Split:
    out = tmp_path / "copy"
    shutil.copytree(split.out, out)
    return Split(out, split.stderr)


def edit_document(split: Split, change: Callable[[dict[str, Any]], None]) -> Split:
    path = split.out / "assembly.json"
    document = json.loads(path.read_text("utf-8"))
    change(document)
    path.write_text(json.dumps(document), "utf-8")
    return Split(split.out, split.stderr)


def edit_piece(
    split: Split, name: str, change: Callable[[trimesh.Trimesh], trimesh.Trimesh]
) -> Split:
    path = split.out / "parts" / f"{name}.stl"
    change(trimesh.load(path, force="mesh")).export(path, file_type="stl")
    return Split(split.out, split.stderr)


def stretched_to(size: float) -> Callable[[trimesh.Trimesh], trimesh.Trimesh]:
    def change(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        vertices = np.array(mesh.vertices)
        vertices[:, 0] *= size / mesh.extents[0]
        return trimesh.Trimesh(vertices, mesh.faces, process=False)

    return change


@pytest.mark.parametrize("fixture", ["dowels", "pegs"])
def test_an_undamaged_split_passes_every_check(
    fixture: str, request: pytest.FixtureRequest
) -> None:
    split: Split = request.getfixturevalue(fixture)
    properties.assert_watertight(split)
    properties.assert_fits(split)
    properties.assert_volume_balance(split)
    properties.assert_holes_line_up(split)
    properties.assert_hole_gaps(split)


def test_watertight_check_catches_a_missing_triangle(dowels: Split, tmp_path: Path) -> None:
    def without_a_triangle(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        return trimesh.Trimesh(mesh.vertices, mesh.faces[1:], process=False)

    damaged = edit_piece(copy_of(dowels, tmp_path), "X0-Y0-Z0", without_a_triangle)
    with pytest.raises(AssertionError, match="not watertight"):
        properties.assert_watertight(damaged)


def test_fit_check_catches_a_piece_over_the_printable_volume(dowels: Split, tmp_path: Path) -> None:
    limit = config.derived(dowels.cfg).printable[0]
    damaged = edit_piece(copy_of(dowels, tmp_path), "X0-Y0-Z0", stretched_to(limit + 1.0))
    with pytest.raises(AssertionError, match="doesn't fit"):
        properties.assert_fits(damaged)


def test_fit_check_holds_a_piece_without_pegs_to_the_usable_volume(
    pegs: Split, tmp_path: Path
) -> None:
    limits = config.derived(pegs.cfg)
    with_pegs = {piece for piece, _, _ in pegs.pegs()}
    plain = next(name for name in pegs.meshes if name not in with_pegs)
    between = (limits.usable[0] + limits.printable[0]) / 2  # legal with a peg, not without one
    damaged = edit_piece(copy_of(pegs, tmp_path), plain, stretched_to(between))
    with pytest.raises(AssertionError, match="doesn't fit"):
        properties.assert_fits(damaged)


def test_fit_check_lets_a_piece_with_a_peg_reach_the_printable_volume(
    pegs: Split, tmp_path: Path
) -> None:
    limits = config.derived(pegs.cfg)
    pegged = next(piece for piece, _, _ in pegs.pegs())
    between = (limits.usable[0] + limits.printable[0]) / 2
    properties.assert_fits(edit_piece(copy_of(pegs, tmp_path), pegged, stretched_to(between)))


def test_volume_check_catches_missing_material(dowels: Split, tmp_path: Path) -> None:
    # 0.1 % of the model: well inside the plan's 0.5 %, and caught by the stricter tolerance.
    block = Manifold.cube((12.6, 12.6, 12.6)).translate((40.0, 40.0, 40.0))

    def without_a_block(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        return manifold_to_trimesh(properties._solid(mesh) - block)

    damaged = edit_piece(copy_of(dowels, tmp_path), "X0-Y0-Z0", without_a_block)
    with pytest.raises(AssertionError, match="volumes are off"):
        properties.assert_volume_balance(damaged)


def test_line_up_check_catches_a_hole_that_moved(dowels: Split, tmp_path: Path) -> None:
    def moved(document: dict[str, Any]) -> None:
        document["connectors"][0]["position_uv"][0] += 3.0

    damaged = edit_document(copy_of(dowels, tmp_path), moved)
    with pytest.raises(AssertionError, match="no hole"):
        properties.assert_holes_line_up(damaged)


def test_line_up_check_catches_a_hole_recorded_outside_its_piece(
    dowels: Split, tmp_path: Path
) -> None:
    def moved(document: dict[str, Any]) -> None:
        document["connectors"][0]["position_uv"][0] += 5000.0

    damaged = edit_document(copy_of(dowels, tmp_path), moved)
    with pytest.raises(AssertionError, match="no material around"):
        properties.assert_holes_line_up(damaged)


def test_reference_volume_check_catches_a_repair_that_filled_a_void(dowels: Split) -> None:
    properties.assert_reference_volume(dowels, dowels.reference_volume)
    with pytest.raises(AssertionError, match="is not the model's"):
        properties.assert_reference_volume(dowels, dowels.reference_volume * 0.999)


def test_line_up_check_catches_a_peg_that_moved(pegs: Split, tmp_path: Path) -> None:
    def moved(document: dict[str, Any]) -> None:
        document["connectors"][0]["position_uv"][0] += 12.0

    damaged = edit_document(copy_of(pegs, tmp_path), moved)
    with pytest.raises(AssertionError, match=r"no (hole|peg)"):
        properties.assert_holes_line_up(damaged)


def test_gap_check_catches_two_holes_too_close(dowels: Split, tmp_path: Path) -> None:
    def closer(document: dict[str, Any]) -> None:
        first = document["connectors"][0]
        other = next(c for c in document["connectors"][1:] if c["face_id"] == first["face_id"])
        other["position_uv"] = [first["position_uv"][0] + 6.0, first["position_uv"][1]]

    damaged = edit_document(copy_of(dowels, tmp_path), closer)
    with pytest.raises(AssertionError, match="mm apart"):
        properties.assert_hole_gaps(damaged)


def test_digest_changes_with_a_single_byte(dowels: Split, tmp_path: Path) -> None:
    copy = copy_of(dowels, tmp_path)
    before = properties.output_digest(copy.out)
    path = copy.out / "assembly.md"
    data = bytearray(path.read_bytes())
    data[0] ^= 1
    path.write_bytes(bytes(data))
    assert properties.output_digest(copy.out) != before
