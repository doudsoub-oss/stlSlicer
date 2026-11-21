"""Phase 10: the robustness matrix, through the CLI in a subprocess (PLAN.md Phase 10, task 3).

Each case asserts a known outcome: its exit code and diagnostics, valid output files when there
are any, and one error line with no traceback unless ``-v`` when the run stops early (task 4).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import trimesh
from manifold3d import Manifold

from stlsplit.config import MAX_COORDINATE, MAX_GRID_CELLS
from stlsplit.errors import ExitCode
from tests.conftest import (
    capless_sphere,
    cube,
    finned_block,
    hollow_sphere,
    many_bodies,
    thin_plate,
)

pytestmark = pytest.mark.e2e

WriteStl = Callable[[Manifold | trimesh.Trimesh, str], Path]

TIMEOUT_SECONDS = 120.0
"""A hang fails the test instead of blocking the suite."""

CORNER_PIECE_VOLUME = 3375.0
"""mm³: the 15 mm cubes around the centre of ``many_bodies``."""


def stlsplit(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stlsplit", *(str(item) for item in arguments)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def document(out: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((out / "assembly.json").read_text("utf-8"))
    return loaded


def codes(data: dict[str, Any]) -> set[str]:
    return {item["code"] for item in data["diagnostics"]}


def assert_parts_are_watertight(out: Path, count: int) -> None:
    parts = sorted((out / "parts").glob("*.stl"))
    assert len(parts) == count
    for part in parts:
        assert trimesh.load(part, force="mesh").is_watertight, part.name


def error_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("stlsplit:")]


# --- the matrix -------------------------------------------------------------------------------


def test_more_than_a_hundred_bodies_keep_distinct_ids(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(many_bodies(), "many"), "-o", out)
    assert done.returncode == ExitCode.PARTIAL, done.stderr
    data = document(out)
    ids = [piece["id"] for piece in data["pieces"]]
    assert len(ids) == len(set(ids)) == 216
    assert sum(name.endswith("-aa") for name in ids) == 8  # one per cell: past -z
    assert_parts_are_watertight(out, 216)
    # Only the 15 mm cubes around the centre lack the room for three sets of holes.
    missing = [item for item in data["diagnostics"] if item["code"] == "W001"]
    assert len(missing) == 8
    corners = {
        piece["id"]
        for piece, stl in zip(data["pieces"], sorted_parts(out, ids), strict=True)
        if trimesh.load(stl, force="mesh").bounding_box.volume <= CORNER_PIECE_VOLUME + 1.0
    }
    for item in missing:
        assert set(item["refs"][0].split("~")) <= corners


def sorted_parts(out: Path, ids: list[str]) -> list[Path]:
    return [out / "parts" / f"{name}.stl" for name in ids]


def test_every_face_too_thin_gives_w001_and_exit_3(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(hollow_sphere(), "hollow"), "-o", out)
    assert done.returncode == ExitCode.PARTIAL, done.stderr
    data = document(out)
    assert data["faces"]
    assert not data["connectors"]
    assert sum(item["code"] == "W001" for item in data["diagnostics"]) == len(data["faces"])
    assert_parts_are_watertight(out, len(data["pieces"]))


def test_model_that_already_fits_is_one_part(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(cube(), "small"), "-o", out)
    assert done.returncode == ExitCode.SUCCESS, done.stderr
    data = document(out)
    assert codes(data) == {"W012"}
    assert not data["connectors"]
    assert_parts_are_watertight(out, 1)


def test_thin_plate_is_cut_without_connectors(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(thin_plate(), "plate"), "-o", out)
    assert done.returncode == ExitCode.PARTIAL, done.stderr
    assert "W001" in codes(document(out))
    assert_parts_are_watertight(out, len(document(out)["pieces"]))


def test_thin_fin_stays_part_of_valid_pieces(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(finned_block(), "fin"), "-o", out)
    assert done.returncode == ExitCode.SUCCESS, done.stderr
    assert_parts_are_watertight(out, len(document(out)["pieces"]))


def test_tiny_model_is_written_with_a_scale_warning(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(cube(), "tiny"), "--scale", 1e-3, "-o", out)
    assert done.returncode == ExitCode.SUCCESS, done.stderr
    data = document(out)
    assert codes(data) == {"W006", "W012"}
    assert_parts_are_watertight(out, 1)
    text = resources.files("stlsplit").joinpath("schemas/assembly.schema.json").read_text("utf-8")
    jsonschema.Draft202012Validator(json.loads(text)).validate(data)


@pytest.mark.parametrize("scale", [1e-4, 1e-6, 1e-30], ids=["1e-4", "1e-6", "1e-30"])
def test_model_too_small_to_record_is_refused(
    write_stl: WriteStl, tmp_path: Path, scale: float
) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(cube(), "tiny"), "--scale", scale, "-o", out)
    assert done.returncode == ExitCode.INVALID_INPUT, done.stderr
    assert "W006" in done.stderr
    assert "--scale" in error_lines(done.stderr)[0]
    assert not out.exists()


def test_model_over_the_cell_limit_is_refused(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = stlsplit(write_stl(cube(100.0), "huge"), "--scale", 1e6, "-o", out)
    assert done.returncode == ExitCode.INVALID_INPUT, done.stderr
    assert "W006" in done.stderr
    assert f"limit of {MAX_GRID_CELLS}" in error_lines(done.stderr)[0]
    assert not out.exists()


@pytest.mark.parametrize("scale", [1e100, 1e305, 1e308], ids=["1e100", "1e305", "overflow"])
def test_scale_beyond_the_coordinate_limit_is_refused(
    write_stl: WriteStl, tmp_path: Path, scale: float
) -> None:
    done = stlsplit(write_stl(cube(100.0), "model"), "--scale", scale, "-o", tmp_path / "out")
    assert done.returncode == ExitCode.INVALID_INPUT, done.stderr
    assert "--scale" in error_lines(done.stderr)[0]
    assert "Warning" not in done.stderr.replace("warning:", "")


def test_model_at_the_coordinate_limit_is_cut(write_stl: WriteStl) -> None:
    # From -5e9 to 5e9 mm, the widest model the limit accepts, on a bed that cuts it in two.
    body = Manifold.cube((10.0, 10.0, 10.0), True)
    bed = 6e9
    done = stlsplit(
        write_stl(body, "wide"),
        "--scale",
        MAX_COORDINATE / 5.0,
        "--bed",
        bed,
        bed,
        bed,
        "--connector",
        "none",
        "--no-label",
        "--dry-run",
    )
    assert done.returncode == ExitCode.SUCCESS, done.stderr


def test_scale_that_collapses_the_coordinates_has_no_volume(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    done = stlsplit(write_stl(cube(), "model"), "--scale", 1e-300, "-o", tmp_path / "out")
    assert done.returncode == ExitCode.UNREPAIRABLE, done.stderr
    assert "no volume" in error_lines(done.stderr)[0]


def test_input_name_that_is_not_utf8_runs_normally(write_stl: WriteStl, tmp_path: Path) -> None:
    source = write_stl(cube(), "model")
    try:
        path = Path(os.fsdecode(os.fsencode(tmp_path) + b"/caf\xe9.stl"))
        shutil.copy(source, path)
    except (OSError, UnicodeError):
        pytest.skip("this file system refuses names that aren't valid UTF-8")
    out = tmp_path / "out"
    done = stlsplit(path, "-o", out)
    assert done.returncode == ExitCode.SUCCESS, done.stderr
    assert document(out)["input"]["file_name"] == "caf\\udce9.stl"
    assert "caf" in (out / "assembly.md").read_text("utf-8")


# --- early exits: one line, a traceback only with -v (task 4) ------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        pytest.param("missing", ExitCode.INVALID_INPUT, id="missing-file"),
        pytest.param("garbage", ExitCode.INVALID_INPUT, id="not-an-stl"),
        pytest.param("open", ExitCode.UNREPAIRABLE, id="open-mesh"),
        pytest.param("too-many-cells", ExitCode.INVALID_INPUT, id="too-many-cells"),
    ],
)
def test_early_exit_is_one_line_with_a_traceback_only_with_verbose(
    write_stl: WriteStl, tmp_path: Path, case: str, expected: ExitCode
) -> None:
    arguments: list[object]
    if case == "missing":
        arguments = [tmp_path / "missing.stl"]
    elif case == "garbage":
        garbage = tmp_path / "garbage.stl"
        garbage.write_bytes(b"\x00\x01 this is not an STL file")
        arguments = [garbage]
    elif case == "open":
        arguments = [write_stl(capless_sphere(), "open")]
    else:
        arguments = [write_stl(cube(100.0), "huge"), "--scale", 1e6]
    arguments += ["--dry-run"]

    plain = stlsplit(*arguments)
    assert plain.returncode == expected
    assert len(error_lines(plain.stderr)) == 1
    assert plain.stderr.splitlines()[-1].startswith("stlsplit: error: ")
    assert "Traceback" not in plain.stderr

    verbose = stlsplit(*arguments, "-v")
    assert verbose.returncode == expected
    assert "Traceback" in verbose.stderr


def test_closed_stdout_is_one_line(write_stl: WriteStl) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "stlsplit", str(write_stl(cube(500.0), "big")), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    process.stdout.close()  # like `stlsplit ... --dry-run | head`, before the plan is written
    assert process.stderr is not None
    stderr = process.stderr.read()
    process.stderr.close()
    assert process.wait(timeout=TIMEOUT_SECONDS) == ExitCode.INVALID_INPUT
    assert len(error_lines(stderr)) == 1
    assert "standard output" in error_lines(stderr)[0]
    assert "Traceback" not in stderr
    assert "Exception ignored" not in stderr


def test_closed_stderr_keeps_the_exit_code_and_the_outputs(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    process = subprocess.Popen(
        [sys.executable, "-m", "stlsplit", str(write_stl(cube(300.0), "model")), "-o", str(out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert process.stderr is not None
    process.stderr.close()  # like `stlsplit ... 2>&1 | head`
    assert process.wait(timeout=TIMEOUT_SECONDS) == ExitCode.SUCCESS
    assert (out / "assembly.json").is_file()


def test_ctrl_c_during_the_imports_is_one_line_and_exit_130() -> None:
    # The signal is raised while `stlsplit.cli` is being imported, whatever the machine's speed.
    code = (
        "import builtins, signal, sys\n"
        "import stlsplit.__main__ as entry\n"
        "real = builtins.__import__\n"
        "def importing(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'stlsplit' and 'cli' in (fromlist or ()):\n"
        "        signal.raise_signal(signal.SIGINT)\n"
        "    return real(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = importing\n"
        "sys.argv = ['stlsplit', '--print-config']\n"
        "raise SystemExit(entry.run())\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    assert done.returncode == ExitCode.INTERRUPTED, done.stderr
    assert done.stderr == "stlsplit: error: interrupted\n"
    assert done.stdout == ""


@pytest.mark.skipif(os.name == "nt", reason="file descriptors can't be closed the same way")
@pytest.mark.parametrize(
    ("arguments", "closed", "expected"),
    [
        pytest.param(["--print-config"], 1, ExitCode.INVALID_INPUT, id="stdout"),
        pytest.param(["--print-config", "--margin", "-1"], 2, ExitCode.INVALID_INPUT, id="stderr"),
    ],
)
def test_stream_closed_from_the_start_keeps_the_exit_code(
    arguments: list[str], closed: int, expected: ExitCode
) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "stlsplit", *arguments],
        stdout=subprocess.PIPE if closed != 1 else None,
        stderr=subprocess.PIPE if closed != 2 else None,
        preexec_fn=lambda: os.close(closed),
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    assert done.returncode == expected
    if closed == 2:
        assert done.stdout == b""  # the error line must not land on stdout


def test_version_into_a_closed_pipe_exits_0() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "stlsplit", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    process.stdout.close()
    assert process.stderr is not None
    stderr = process.stderr.read()
    process.stderr.close()
    assert process.wait(timeout=TIMEOUT_SECONDS) == ExitCode.SUCCESS
    assert "Exception ignored" not in stderr


@pytest.mark.skipif(os.name == "nt", reason="SIGINT can't target one process on Windows")
def test_ctrl_c_is_one_line_and_exit_130(write_stl: WriteStl) -> None:
    stl = write_stl(Manifold.sphere(200.0, 512), "sphere")
    process = subprocess.Popen(
        [sys.executable, "-m", "stlsplit", str(stl), "--dry-run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stderr is not None
    first = process.stderr.readline()  # the run has started: it logs its configuration
    assert first.startswith("configuration:")
    process.send_signal(signal.SIGINT)
    stderr = first + process.stderr.read()
    process.stderr.close()
    assert process.wait(timeout=TIMEOUT_SECONDS) == ExitCode.INTERRUPTED
    assert len(error_lines(stderr)) == 1
    assert "interrupted" in error_lines(stderr)[0]
    assert "Traceback" not in stderr
