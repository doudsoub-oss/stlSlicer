"""Phase 9: every output of a split (PLAN.md Phase 9, docs/OUTPUT_FORMAT.md).

Most tests split a 200 x 200 x 100 box on a 120 mm bed into 2 x 2 x 1 pieces, with at most two
connectors per face.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import matplotlib
import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

from stlsplit import (
    __version__,
    assembly,
    cli,
    config,
    connectors,
    cutting,
    geometry,
    grid,
    io,
    tools,
)
from stlsplit.config import OUTPUT_DECIMALS, PREVIEW_PALETTE, Config
from stlsplit.errors import ExitCode
from tests.conftest import crossed_loop, hooked_strips, interlocked_bodies, torus, two_bodies
from tests.unit.test_assembly_order import assert_followable

WriteStl = Callable[[Manifold | trimesh.Trimesh, str], Path]

SMALL_BED = ["--bed", "120", "120", "120", "--max-connectors-per-face", "2"]
ISO_TIMESTAMP = re.compile(rb"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def plate() -> Manifold:
    return Manifold.cube((200.0, 200.0, 100.0))


def split(stl: Path, out: Path, *options: str) -> int:
    return cli.main([str(stl), "-o", str(out), *SMALL_BED, *options])


def document(out: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((out / "assembly.json").read_text(encoding="utf-8"))
    return loaded


def schema() -> dict[str, Any]:
    text = resources.files("stlsplit").joinpath("schemas/assembly.schema.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- pieces ----------------------------------------------------------------------------------


@pytest.mark.parametrize("connector", ["dowel", "peg", "none"])
def test_every_exported_stl_reloads_watertight_and_fits(
    write_stl: WriteStl, tmp_path: Path, connector: str
) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out, "--connector", connector) == ExitCode.SUCCESS
    cfg = config.with_overrides(
        Config(),
        {
            "printer.bed": (120.0, 120.0, 120.0),
            "connectors.type": connector,
        },
        "test",
    )
    limits = config.derived(cfg)
    files = sorted((out / "parts").glob("*.stl"))
    assert [path.stem for path in files] == [
        "X0-Y0-Z0",
        "X0-Y1-Z0",
        "X1-Y0-Z0",
        "X1-Y1-Z0",
    ]
    largest = np.zeros(3)
    for path in files:
        mesh, _ = io.load_stl(path, 1.0)
        assert mesh.is_watertight, path.name
        assert np.all(mesh.extents <= np.array(limits.printable) + 1e-6), path.name
        largest = np.maximum(largest, mesh.extents)
    if connector == "peg":  # r10: a pegged piece fits the printable volume, not U
        assert np.any(largest > np.array(limits.usable) + 1.0)
    else:
        assert np.all(largest <= np.array(limits.usable) + 1e-6)


def test_pieces_stay_in_the_cutting_frame(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    mesh, _ = io.load_stl(out / "parts" / "X1-Y1-Z0.stl", 1.0)
    assert mesh.bounds[0] == pytest.approx((100.0, 100.0, 0.0), abs=1e-5)
    assert mesh.bounds[1] == pytest.approx((200.0, 200.0, 100.0), abs=1e-5)


# --- assembly.json ---------------------------------------------------------------------------


def test_the_schema_is_valid_and_packaged() -> None:
    jsonschema.Draft202012Validator.check_schema(schema())


@pytest.mark.parametrize("connector", ["dowel", "peg", "none"])
def test_assembly_json_validates_against_the_schema(
    write_stl: WriteStl, tmp_path: Path, connector: str
) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out, "--connector", connector) == ExitCode.SUCCESS
    loaded = document(out)
    jsonschema.Draft202012Validator(schema()).validate(loaded)
    assert loaded["schema_version"] == 1


@pytest.mark.parametrize(
    ("model", "options"),
    [
        pytest.param(lambda: Manifold.cube((10.0, 10.0, 10.0)), (), id="one-piece"),
        pytest.param(two_bodies, ("--bed", "30", "30", "30"), id="separate-bodies"),
        pytest.param(torus, ("--no-label",), id="no-label"),
    ],
)
def test_assembly_json_validates_on_other_models(
    write_stl: WriteStl,
    tmp_path: Path,
    model: Callable[[], Manifold],
    options: tuple[str, ...],
) -> None:
    out = tmp_path / "out"
    code = cli.main([str(write_stl(model(), "model")), "-o", str(out), *options])
    assert code in (ExitCode.SUCCESS, ExitCode.PARTIAL)
    jsonschema.Draft202012Validator(schema()).validate(document(out))


def test_assembly_json_holds_the_run(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "my model"), out) == ExitCode.SUCCESS
    loaded = document(out)
    assert loaded["tool"] == {"name": "stlsplit", "version": __version__}
    assert loaded["input"] == {"file_name": "my model.stl"}
    assert loaded["settings"]["printer"]["bed"] == [120.0, 120.0, 120.0]
    assert loaded["settings"]["connectors"]["max_per_face"] == 2
    assert len(loaded["frame"]["input_to_cutting"]) == 4
    assert loaded["grid"]["counts"] == [2, 2, 1]
    assert loaded["grid"]["planes"] == {"x": [100.0], "y": [100.0], "z": []}
    assert [piece["id"] for piece in loaded["pieces"]] == [
        "X0-Y0-Z0",
        "X0-Y1-Z0",
        "X1-Y0-Z0",
        "X1-Y1-Z0",
    ]
    assert loaded["pieces"][0]["file"] == "parts/X0-Y0-Z0.stl"
    assert len(loaded["faces"]) == 4
    assert len(loaded["connectors"]) == 8
    assert loaded["pin_groups"] == [
        {
            "file": "dowels/dowel_d5.0_l20.0.stl",
            "diameter": 5.0,
            "length": 20.0,
            "quantity": 8,
        }
    ]
    assert [step["number"] for step in loaded["steps"]] == ["1.1", "1.2", "2.1"]
    assert loaded["separate_parts"] == [["X0-Y0-Z0", "X0-Y1-Z0", "X1-Y0-Z0", "X1-Y1-Z0"]]


def test_connector_positions_are_in_the_cutting_frame(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    loaded = document(out)
    faces = {face["id"]: face for face in loaded["faces"]}
    for connector in loaded["connectors"]:
        face = faces[connector["face_id"]]
        position = connector["position"]
        assert position[face["axis"]] == face["offset"]
        u_axis, v_axis = ((face["axis"] + 1) % 3, (face["axis"] + 2) % 3)
        assert (position[u_axis], position[v_axis]) == tuple(connector["position_uv"])


def test_floats_in_assembly_json_are_rounded(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    arguments = [str(write_stl(torus(), "model")), "-o", str(out), "--bed", "60", "60", "60"]
    assert cli.main(arguments) in (ExitCode.SUCCESS, ExitCode.PARTIAL)
    text = (out / "assembly.json").read_text(encoding="utf-8")
    decimals = [len(m) for m in re.findall(r"\d\.(\d+)", text)]
    assert decimals
    assert max(decimals) <= OUTPUT_DECIMALS
    assert "-0.0," not in text


# --- assembly.md -----------------------------------------------------------------------------


def test_assembly_md_gives_a_followable_procedure(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    text = (out / "assembly.md").read_text(encoding="utf-8")
    assert "## Summary" in text
    assert "## Print list" in text
    assert "`parts/X0-Y0-Z0.stl`" in text
    assert "`dowels/dowel_d5.0_l20.0.stl`" in text
    assert "### Stage 1: X joins" in text
    assert "### Stage 2: Y joins" in text
    assert "**1.1**" in text
    assert "**2.1**" in text
    assert text.count("Let the glue set before the next stage.") == 1
    assert "2 x 20 mm" in text


def test_assembly_md_marks_glue_only_joins(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out, "--connector", "none") == ExitCode.SUCCESS
    assert "glue only" in (out / "assembly.md").read_text(encoding="utf-8")


def test_assembly_md_lists_diagnostics_with_their_reference(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    model = write_stl(Manifold.cube((10.0, 10.0, 10.0)), "model")
    assert cli.main([str(model), "-o", str(out)]) == ExitCode.SUCCESS
    text = (out / "assembly.md").read_text(encoding="utf-8")
    assert "## Diagnostics" in text
    assert "**W012**" in text
    assert "`docs/TROUBLESHOOTING.md`, W012" in text


def test_assembly_md_lists_separate_parts(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    model = write_stl(two_bodies(), "model")
    assert cli.main([str(model), "-o", str(out), "--bed", "30", "30", "30"]) in (
        ExitCode.SUCCESS,
        ExitCode.PARTIAL,
    )
    loaded = document(out)
    text = (out / "assembly.md").read_text(encoding="utf-8")
    assert len(loaded["separate_parts"]) > 1
    assert "## Separate parts" in text


def test_assembly_md_escapes_the_input_file_name(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "a|b*c"), out) == ExitCode.SUCCESS
    assert "a\\|b\\*c.stl" in (out / "assembly.md").read_text(encoding="utf-8")


def test_an_undecodable_file_name_can_still_be_rendered(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    loaded = document(out)
    loaded["input"]["file_name"] = "caf\udce9.stl"  # what os.fsdecode gives for a Latin-1 name
    assert assembly.to_json(loaded).isascii()
    assert "caf" in assembly.to_markdown(loaded).encode("utf-8").decode("utf-8")


# --- preview ---------------------------------------------------------------------------------


def test_preview_moves_the_pieces_apart_and_colours_them(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    scene = trimesh.load(out / "preview_exploded.glb", force="scene")
    assert len(scene.graph.nodes_geometry) == 4
    transform, _ = scene.graph["X0-Y0-Z0"]
    # 0.15 of the 200 mm size, half a grid step away from the centre.
    assert transform[:3, 3] == pytest.approx((-15.0, -15.0, 0.0))
    transform, _ = scene.graph["X1-Y1-Z0"]
    assert transform[:3, 3] == pytest.approx((15.0, 15.0, 0.0))
    colours = {
        tuple(int(v) for v in np.asarray(g.visual.material.baseColorFactor)[:3])
        for g in scene.geometry.values()
    }
    assert colours == {tuple(colour[:3]) for colour in PREVIEW_PALETTE[:4]}


def test_no_preview_writes_no_glb(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out, "--no-preview") == ExitCode.SUCCESS
    assert not (out / "preview_exploded.glb").exists()


def test_the_palette_has_twelve_distinct_colours() -> None:
    assert len(set(PREVIEW_PALETTE)) == 12


# --- determinism and privacy (ADR-0010) ------------------------------------------------------


def test_no_output_holds_the_temp_path_or_a_timestamp(write_stl: WriteStl, tmp_path: Path) -> None:
    font = tmp_path / "fonts" / "MyLabels.ttf"
    font.parent.mkdir()
    shutil.copy(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf", font)
    toml = tmp_path / "settings.toml"
    toml.write_text(f"[advanced]\nlabel_font = {json.dumps(str(font))}\n", encoding="utf-8")
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out, "--config", str(toml)) == ExitCode.SUCCESS
    assert document(out)["settings"]["advanced"]["label_font"] == "MyLabels.ttf"
    needles = {str(tmp_path).encode(), json.dumps(str(tmp_path))[1:-1].encode()}
    files = [path for path in out.rglob("*") if path.is_file()]
    assert len(files) >= 8
    for path in files:
        data = path.read_bytes()
        assert not any(needle in data for needle in needles), path.name
        assert ISO_TIMESTAMP.search(data) is None, path.name


def test_two_processes_give_byte_identical_output_directories(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    stl = write_stl(torus(), "model")
    results = []
    for seed in ("1", "4242"):
        out = tmp_path / f"run{seed}"
        command = [sys.executable, "-m", "stlsplit", str(stl), "-o", str(out)]
        command += ["--bed", "60", "60", "60", "-q"]
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(command, capture_output=True, env=environment, check=False)
        assert done.returncode in (ExitCode.SUCCESS, ExitCode.PARTIAL), done.stderr
        results.append(digests(out))
    assert results[0] == results[1]
    assert {"assembly.json", "assembly.md", "preview_exploded.glb"} <= set(results[0])


# --- the pipeline --------------------------------------------------------------------------


def test_a_failure_while_building_the_outputs_keeps_the_previous_ones(
    write_stl: WriteStl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("a bug in the preview")

    monkeypatch.setattr(io, "encode_preview", fail)
    out = tmp_path / "out"
    (out / "parts").mkdir(parents=True)
    old = out / "parts" / "old.stl"
    old.write_text("old")
    assert split(write_stl(plate(), "model"), out, "--force") == ExitCode.INTERNAL
    assert old.read_text() == "old"


def test_the_console_summary_gives_the_results(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert split(write_stl(plate(), "model"), out) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "not implemented" not in err
    assert "summary: 4 pieces, 8 connectors, 8 dowels to print, 0 diagnostics" in err
    assert f"output: {out}" in err
    assert "exit code: 0" in err


def test_the_console_summary_gives_a_partial_exit_code(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    thin = Manifold.cube((200.0, 6.0, 6.0))  # no room for a connector: W001
    assert split(write_stl(thin, "model"), out) == ExitCode.PARTIAL
    assert "exit code: 3" in capsys.readouterr().err
    assert [item["code"] for item in document(out)["diagnostics"]].count("W001") == 1


def test_a_dry_run_ends_without_a_warning(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(plate(), "model")
    assert cli.main([str(stl), "--dry-run", *SMALL_BED]) == ExitCode.SUCCESS
    assert "not implemented" not in capsys.readouterr().err


def test_a_loop_crossing_a_plane_four_times_gets_a_followable_order() -> None:
    """The join rule of r12: one direction per join, on a real mesh."""
    cfg = config.with_overrides(
        Config(),
        {
            "printer.bed": (40.0, 300.0, 300.0),
            "model.auto_orient": False,
            "advanced.nudge_window": 0.0,
        },
        "test",
    )
    body, _ = grid.orient(crossed_loop(), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    result = cutting.cut(body, layout, cfg, body.volume())
    assert len(result.pieces) == 4
    assert len(result.faces) == 4
    plan = assembly.plan_steps(result.pieces, result.faces, [])
    assert_followable(result.pieces, result.faces, plan)
    assert plan.diagnostics == ()
    # The far plate must go on last: placed first, it would block the near plate's way in.
    assert plan.steps[-1].moving == ("X0-Y0-Z0-a",)
    assert plan.steps[-1].direction == "+x"
    assert geometry.bodies(body)


WOVEN = [
    "--bed", "20", "200", "200", "--no-auto-orient", "--connector", "none", "--no-label",
    "--no-preview",
]  # fmt: skip


def test_a_clear_order_is_found_when_the_first_choice_would_strand_a_piece(
    write_stl: WriteStl, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert cli.main([str(write_stl(hooked_strips(), "model")), "-o", str(out), *WOVEN]) == 0
    loaded = document(out)
    assert len(loaded["pieces"]) == 6
    assert all(step["clear_path"] for step in loaded["steps"])
    assert "W013" not in [item["code"] for item in loaded["diagnostics"]]


def test_the_search_for_a_clear_order_is_bounded(
    write_stl: WriteStl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assembly, "ASSEMBLY_SEARCH_STATES", 0)
    out = tmp_path / "out"
    stl = write_stl(hooked_strips(), "model")
    assert cli.main([str(stl), "-o", str(out), *WOVEN]) == ExitCode.PARTIAL
    assert "W013" in [item["code"] for item in document(out)["diagnostics"]]


def test_a_dry_run_exits_as_the_split_does_on_a_blocked_step(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(interlocked_bodies(), "model")
    assert cli.main([str(stl), "-o", str(tmp_path / "out"), *WOVEN]) == ExitCode.PARTIAL
    capsys.readouterr()
    assert cli.main([str(stl), "--dry-run", *WOVEN]) == ExitCode.PARTIAL
    assert "W013" in capsys.readouterr().err
    assert not (tmp_path / "dry").exists()


def test_the_path_check_sees_pegs_but_no_holes() -> None:
    cfg = config.with_overrides(
        Config(),
        {"printer.bed": (120.0, 120.0, 120.0), "connectors.type": "peg"},
        "test",
    )
    body, _ = grid.orient(plate(), cfg)
    layout, _ = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
    result = cutting.cut(body, layout, cfg, body.volume())
    placed = connectors.place(result.pieces, result.faces, cfg).connectors
    solids = tools.with_pegs(result.pieces, result.faces, placed, cfg)
    assert [piece.id for piece in solids] == [piece.id for piece in result.pieces]
    grew = [
        after.body.volume() - before.body.volume()
        for before, after in zip(result.pieces, solids, strict=True)
    ]
    assert all(change >= -1e-6 for change in grew)  # nothing is drilled
    assert max(grew) > 0.0  # the pegs are there
    none = config.with_overrides(cfg, {"connectors.type": "dowel"}, "test")
    assert tools.with_pegs(result.pieces, result.faces, [], none)[0] is result.pieces[0]
