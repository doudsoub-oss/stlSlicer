"""The end-to-end properties, on every model (PLAN.md Phase 11, task 2).

Each model runs through the CLI in a subprocess once for all its properties, and a second time,
with another hash seed and working folder, for the byte-identical check.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import trimesh

from stlsplit import geometry
from tests.conftest import manifold_to_trimesh
from tests.e2e import properties
from tests.e2e.cases import REFUSED_CASES, WRITING_CASES, Case, true_volume

pytestmark = pytest.mark.e2e

TIMEOUT_SECONDS = 300.0
"""A hang fails the test instead of blocking the suite."""


@dataclass(frozen=True)
class Finished:
    case: Case
    stl: Path
    returncode: int
    split: properties.Split


def write_model(case: Case, path: Path) -> Path:
    if isinstance(case.model, Path):
        shutil.copyfile(case.model, path)
        return path
    body = case.model()
    mesh = body if isinstance(body, trimesh.Trimesh) else manifold_to_trimesh(body)
    mesh.export(path, file_type="stl")
    return path


def run_cli(stl: Path, out: Path, case: Case, seed: int) -> subprocess.CompletedProcess[str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    arguments = list(case.arguments)
    if case.toml:
        settings = out.parent / "settings.toml"
        settings.write_text(case.toml, "utf-8")
        arguments += ["--config", str(settings)]
    return subprocess.run(
        [sys.executable, "-m", "stlsplit", str(stl), "-o", str(out), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=TIMEOUT_SECONDS,
        cwd=out.parent,
        env={**os.environ, "PYTHONHASHSEED": str(seed)},
        check=False,
    )


@pytest.fixture(scope="module", params=WRITING_CASES, ids=lambda item: item.name)
def finished(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Finished]:
    case: Case = request.param
    if case.needs_deep_repair and (problem := geometry.deep_repair_problem()):
        pytest.skip(f"the optional deep-repair extra isn't usable: {problem}")
    root = tmp_path_factory.mktemp(case.name)
    stl = write_model(case, root / "model.stl")
    done = run_cli(stl, root / "first" / "out", case, seed=1)
    if not (root / "first" / "out" / "assembly.json").is_file():
        pytest.fail(f"exit {done.returncode}, no assembly.json:\n{done.stderr[-2000:]}")
    yield Finished(
        case, stl, done.returncode, properties.Split(root / "first" / "out", done.stderr)
    )
    shutil.rmtree(root, ignore_errors=True)  # pytest keeps its recent temporary folders


def test_exit_code_matches_the_case(finished: Finished) -> None:
    assert finished.returncode == finished.case.exit_code, finished.split.stderr[-2000:]
    reported = {item["code"] for item in finished.split.document["diagnostics"]}
    assert finished.case.codes <= reported


def test_the_case_reaches_what_its_fixture_is_for(finished: Finished) -> None:
    reaches = finished.case.reaches
    assert reaches is None or reaches(finished.split.document)


def test_repair_keeps_the_true_volume_of_the_model(finished: Finished) -> None:
    properties.assert_reference_volume(
        finished.split, true_volume(finished.case), finished.case.volume_tolerance
    )


def test_every_piece_is_watertight(finished: Finished) -> None:
    properties.assert_watertight(finished.split)


def test_every_piece_fits_the_printer(finished: Finished) -> None:
    properties.assert_fits(finished.split)


def test_volumes_balance(finished: Finished) -> None:
    properties.assert_volume_balance(finished.split)


def test_holes_line_up_across_every_cut_face(finished: Finished) -> None:
    properties.assert_holes_line_up(finished.split)


def test_holes_of_a_piece_keep_the_minimum_wall(finished: Finished) -> None:
    properties.assert_hole_gaps(finished.split)


def test_two_runs_are_byte_identical(finished: Finished, tmp_path: Path) -> None:
    again = run_cli(finished.stl, tmp_path / "second" / "out", finished.case, seed=2)
    assert again.returncode == finished.returncode, again.stderr[-2000:]
    first = properties.output_digest(finished.split.out)
    assert properties.output_digest(tmp_path / "second" / "out") == first


@pytest.mark.parametrize("case", REFUSED_CASES, ids=lambda item: item.name)
def test_a_mesh_that_cannot_be_repaired_exits_with_its_code_and_writes_nothing(
    case: Case, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    done = run_cli(write_model(case, tmp_path / "model.stl"), out, case, seed=1)
    assert done.returncode == case.exit_code, done.stderr[-2000:]
    assert not out.exists()
    assert json.dumps(done.stderr).count("stlsplit: error:") == 1
