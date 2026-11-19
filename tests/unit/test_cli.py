import codecs
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import trimesh
from manifold3d import Manifold

from stlsplit import __version__, cli, config, errors
from stlsplit.config import Config
from stlsplit.errors import ExitCode
from tests.conftest import capless_sphere, cube, long_box, missing_face_cube, two_bodies
from tests.unit.test_config import EXAMPLE_TOML

WriteStl = Callable[[Manifold | trimesh.Trimesh, str], Path]


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"stlsplit {__version__}"


def test_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "stlsplit", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "usage: stlsplit" in result.stdout


def resolve(argv: list[str]) -> Config:
    return cli.resolve_config(cli.build_parser().parse_args(argv))


def write_toml(tmp_path: Path, text: str, name: str = "my.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- precedence (PLAN.md §7.4, ADR-0011) -----------------------------------------------------


@pytest.mark.parametrize(
    ("key", "default", "toml", "flags", "from_toml", "from_cli"),
    [
        pytest.param(
            "connectors.clearance",
            0.2,
            "[connectors]\nclearance = 0.3\n",
            ["--clearance", "0.25"],
            0.3,
            0.25,
            id="float",
        ),
        pytest.param(
            "labels.enabled",
            True,
            "[labels]\nenabled = false\n",
            ["--label"],
            False,
            True,
            id="bool-pair-on",
        ),
        pytest.param(
            "output.preview",
            True,
            "[output]\npreview = true\n",
            ["--no-preview"],
            True,
            False,
            id="bool-pair-off",
        ),
        pytest.param(
            "printer.bed",
            (220.0, 220.0, 250.0),
            "[printer]\nbed = [180, 180, 180]\n",
            ["--bed", "200", "210", "220"],
            (180.0, 180.0, 180.0),
            (200.0, 210.0, 220.0),
            id="bed-triple",
        ),
        pytest.param(
            "connectors.type",
            "dowel",
            '[connectors]\ntype = "none"\n',
            ["--connector", "peg"],
            "none",
            "peg",
            id="connector-choice",
        ),
    ],
)
def test_precedence_is_defaults_then_toml_then_cli(
    tmp_path: Path,
    key: str,
    default: Any,
    toml: str,
    flags: list[str],
    from_toml: Any,
    from_cli: Any,
) -> None:
    path = write_toml(tmp_path, toml)
    assert config.lookup(resolve([]), key) == default
    assert config.lookup(resolve(["--config", str(path)]), key) == from_toml
    assert config.lookup(resolve(["--config", str(path), *flags]), key) == from_cli


def test_cli_value_equal_to_the_default_still_overrides_toml(tmp_path: Path) -> None:
    path = write_toml(tmp_path, "[connectors]\nclearance = 0.3\n")
    assert resolve(["--config", str(path), "--clearance", "0.2"]).connectors.clearance == 0.2


def test_options_not_typed_are_absent_from_the_namespace() -> None:
    namespace = cli.build_parser().parse_args([])
    assert vars(namespace) == {}


def test_every_config_option_maps_to_a_real_key() -> None:
    flags = cli.config_flags(cli.build_parser())
    assert set(flags) <= set(config.keys())
    assert flags["connectors.clearance"] == "--clearance"
    assert flags["labels.enabled"] == "--label"


# --- configuration errors exit 1 -------------------------------------------------------------


def test_unknown_toml_key_exits_1_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_toml(tmp_path, "[connectors]\nclearence = 0.2\n")
    assert cli.main(["--print-config", "--config", str(path)]) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert "connectors.clearence" in err
    assert len(err.splitlines()) == 1


def test_invalid_value_exits_1_naming_the_flag_the_key_and_the_range(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--print-config", "--clearance", "-0.1"]) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert "--clearance (connectors.clearance)" in err
    assert ">= 0" in err


def test_missing_label_font_exits_1_naming_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_toml(tmp_path, '[advanced]\nlabel_font = "NoSuchFont.ttf"\n')
    assert cli.main(["--print-config", "--config", str(path)]) == ExitCode.INVALID_INPUT
    assert "advanced.label_font" in capsys.readouterr().err


def test_huge_toml_integer_exits_1_not_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_toml(tmp_path, "[model]\nscale = 1" + "0" * 400 + "\n")
    assert cli.main(["--print-config", "--config", str(path)]) == ExitCode.INVALID_INPUT
    assert "model.scale" in capsys.readouterr().err


@pytest.mark.parametrize(
    "encode",
    [
        pytest.param(lambda text: codecs.BOM_UTF8 + text.encode("utf-8"), id="utf-8-bom"),
        pytest.param(lambda text: codecs.BOM_UTF16_LE + text.encode("utf-16-le"), id="utf-16-le"),
        pytest.param(lambda text: codecs.BOM_UTF16_BE + text.encode("utf-16-be"), id="utf-16-be"),
    ],
)
def test_config_file_with_a_byte_order_mark_is_read(
    tmp_path: Path, encode: Callable[[str], bytes]
) -> None:
    # Windows editors add a UTF-8 BOM, and PowerShell 5.1's ">" writes UTF-16.
    path = tmp_path / "my.toml"
    path.write_bytes(encode("[connectors]\nclearance = 0.3\n"))
    assert resolve(["--config", str(path)]).connectors.clearance == 0.3


def test_print_config_survives_a_console_that_is_not_utf8(tmp_path: Path) -> None:
    # On Windows a redirected stdout uses the locale encoding (cp1252 here), not UTF-8.
    font = tmp_path / "José 字.ttf"
    font.write_bytes(b"\x00")
    path = write_toml(tmp_path, f"[advanced]\nlabel_font = {json.dumps(str(font))}\n")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "stlsplit", "--print-config", "-q", "--config", str(path)],
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == ExitCode.SUCCESS, result.stderr
    printed = tmp_path / "printed.toml"
    printed.write_bytes(result.stdout)
    assert resolve(["--config", str(printed)]) == resolve(["--config", str(path)])


def test_unreadable_config_file_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.toml"
    assert cli.main(["--print-config", "--config", str(missing)]) == ExitCode.INVALID_INPUT
    assert "missing.toml" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(["--print-config", "--margin", "abc"], "--margin", id="bad-number"),
        pytest.param(["--print-config", "--connector", "glue"], "--connector", id="bad-choice"),
        pytest.param(["--print-config", "--bed", "1", "2"], "--bed", id="bed-two-values"),
        pytest.param(["--print-config", "--bogus"], "--bogus", id="unknown-option"),
        pytest.param(["--print-config", "-v", "-q"], "-q", id="verbose-and-quiet"),
    ],
)
def test_usage_error_exits_1_not_argparse_2(
    argv: list[str], expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert expected in err
    assert len(err.splitlines()) == 1


# --- modes (PLAN.md §7.1, §7.5) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param([], "INPUT", id="neither-input-nor-calibrate"),
        pytest.param(["model.stl", "--calibrate", "-o", "out"], "--calibrate", id="both"),
        pytest.param(["model.stl"], "--output", id="split-without-output"),
        pytest.param(["--calibrate"], "--output", id="calibrate-without-output"),
        pytest.param(["model.stl", "--print-config"], "--print-config", id="print-with-input"),
        pytest.param(["--calibrate", "--print-config"], "--print-config", id="print-calibrate"),
        pytest.param(["--calibrate", "--dry-run", "-o", "out"], "--dry-run", id="dry-run-no-input"),
    ],
)
def test_mode_error_exits_1_before_touching_anything(
    argv: list[str],
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(argv) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert expected in err
    assert len(err.splitlines()) == 1
    assert list(tmp_path.iterdir()) == []


def test_missing_input_file_exits_1_and_leaves_the_output_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert cli.main([str(tmp_path / "missing.stl"), "-o", str(out)]) == ExitCode.INVALID_INPUT
    assert "missing.stl" in capsys.readouterr().err
    assert not out.exists()


def test_split_prepares_the_output_directory(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out" / "nested"
    assert cli.main([str(write_stl(cube(), "model")), "-o", str(out)]) == ExitCode.SUCCESS
    assert out.is_dir()


def test_calibrate_prepares_the_output_directory(tmp_path: Path) -> None:
    out = tmp_path / "calibration-out"
    assert cli.main(["--calibrate", "-o", str(out)]) == ExitCode.SUCCESS
    assert out.is_dir()


def test_dry_run_accepts_and_ignores_the_output_option(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "--dry-run", "-o", str(out)]) == ExitCode.SUCCESS
    assert not out.exists()


# --- load and repair (PLAN.md Phase 2) -------------------------------------------------------


def test_unrepairable_mesh_exits_2_and_keeps_the_previous_outputs(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Load and repair run before the output directory is prepared, so --force never deletes
    # the previous outputs for a mesh that can't be used.
    out = tmp_path / "out"
    (out / "parts").mkdir(parents=True)
    (out / "parts" / "old.stl").write_text("old")
    broken = write_stl(capless_sphere(), "broken")
    argv = [str(broken), "-o", str(out), "--force", "-q"]
    assert cli.main(argv) == ExitCode.UNREPAIRABLE
    err = capsys.readouterr().err
    assert err.startswith("stlsplit: error: ")
    assert len(err.splitlines()) == 1
    assert "open edges" in err
    assert (out / "parts" / "old.stl").is_file()


def test_load_warnings_are_shown_even_when_repair_fails(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = write_stl(capless_sphere(), "broken")
    assert cli.main([str(broken), "--dry-run", "--scale", "0.001"]) == ExitCode.UNREPAIRABLE
    err = capsys.readouterr().err
    assert "W006" in err
    assert err.index("W006") < err.index("stlsplit: error: ")


def test_dry_run_logs_the_model_summary_and_the_stage_timings(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(two_bodies(), "model")
    assert cli.main([str(stl), "--dry-run", "-v"]) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    summary = next(line for line in err.splitlines() if line.startswith("model: "))
    assert "24 triangles" in summary
    assert "2 bodies" in summary
    assert "0 voids" in summary
    assert "volume 2000 mm^3" in summary
    assert "30 x 10 x 10 mm" in summary
    assert "repair: none" in summary
    assert "debug: stage load: " in err
    assert "debug: stage repair: " in err


def test_simplify_that_erases_the_model_exits_1_naming_the_flag(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "--dry-run", "--simplify", "1000", "-q"]) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert "--simplify (model.simplify)" in err
    assert len(err.splitlines()) == 1


def test_repair_diagnostics_are_reported(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(missing_face_cube(), "model")
    assert cli.main([str(stl), "--dry-run"]) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "W007 " in err
    assert "repair: " in err
    assert "repair: none" not in err


# --- orientation and grid (PLAN.md Phase 3) -------------------------------------------------


def test_dry_run_prints_the_grid_on_stdout(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(long_box(), "model")
    argv = [str(stl), "--dry-run", "--bed", "220", "220", "220", "-q"]
    assert cli.main(argv) == ExitCode.SUCCESS
    lines = capsys.readouterr().out.splitlines()  # -q hides logs, not the plan
    assert "rotation: identity; cutting (X, Y, Z) = input (+X, +Y, +Z)" in lines
    assert "input_to_cutting: [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]" in lines
    assert "extent: 500 x 100 x 100 mm" in lines
    assert "usable volume: 210 x 210 x 210 mm" in lines
    assert "cells: 3 x 1 x 1 = 3" in lines
    assert "planes X: 166.666667, 333.333333" in lines
    assert "planes Y: none" in lines
    assert "planes Z: none" in lines


def test_dry_run_prints_the_rotation_and_translation(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(Manifold.cube((460.0, 100.0, 100.0)).translate((5.0, 0.0, 0.0)), "model")
    assert cli.main([str(stl), "--dry-run"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "rotation: 90 deg about Y; cutting (X, Y, Z) = input (+Z, +Y, -X)" in lines
    assert "input_to_cutting: [0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 465], [0, 0, 0, 1]" in lines
    assert "extent: 100 x 100 x 460 mm" in lines
    assert "cells: 1 x 1 x 2 = 2" in lines
    assert "planes Z: 230" in lines
    assert "grid: 1 x 1 x 2 = 2 cells; rotation 90 deg about Y" in captured.err


def test_model_that_fits_reports_w012_and_exits_0(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(write_stl(cube(), "model")), "--dry-run"]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert "W012 " in captured.err
    assert "cells: 1 x 1 x 1 = 1" in captured.out.splitlines()


def test_split_logs_the_grid_and_prints_no_plan(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(long_box(), "model")
    assert cli.main([str(stl), "-o", str(tmp_path / "out")]) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    assert "grid: 3 x 1 x 1 = 3 cells; rotation identity" in captured.err
    assert captured.out == ""


# --- --print-config --------------------------------------------------------------------------


def test_print_config_output_loads_back_into_an_equal_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_toml(tmp_path, EXAMPLE_TOML)
    argv = ["--print-config", "--config", str(path), "--clearance", "0.15", "--no-label"]
    assert cli.main(argv) == ExitCode.SUCCESS
    printed = capsys.readouterr().out
    expected = resolve(argv)
    assert expected.connectors.diameter == 6.0  # from the file
    assert expected.connectors.clearance == 0.15  # from the command line
    assert config.parse_toml(printed, "printed") == expected


def test_print_config_output_is_a_valid_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--print-config", "--bed", "180", "180", "200"]) == ExitCode.SUCCESS
    first = capsys.readouterr().out
    path = write_toml(tmp_path, first, "printed.toml")
    assert cli.main(["--print-config", "--config", str(path)]) == ExitCode.SUCCESS
    assert capsys.readouterr().out == first


# --- errors, exit 4 and logging --------------------------------------------------------------


def test_error_is_one_line_and_the_traceback_comes_only_with_verbose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--print-config", "--margin", "-1"]) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert err.startswith("stlsplit: error: ")
    assert len(err.splitlines()) == 1
    assert cli.main(["--print-config", "--margin", "-1", "-v"]) == ExitCode.INVALID_INPUT
    assert "Traceback" in capsys.readouterr().err


def test_unexpected_exception_exits_4_and_asks_for_a_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(cfg: Config) -> str:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(config, "to_toml", broken)
    assert cli.main(["--print-config", "-q"]) == ExitCode.INTERNAL  # -q: only the error line
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "internal error" in err
    assert "kaboom" in err
    assert "-v" in err
    assert cli.main(["--print-config", "-v"]) == ExitCode.INTERNAL
    assert "Traceback" in capsys.readouterr().err


def test_default_logging_shows_info(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(write_stl(cube(), "model")), "--dry-run"]) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "configuration: built-in defaults" in err
    assert "warning: " in err  # the dry run isn't implemented yet
    assert "stage " not in err


def test_quiet_hides_info_but_keeps_warnings(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(write_stl(cube(), "model")), "--dry-run", "-q"]) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "configuration:" not in err
    assert "warning: " in err


def test_verbose_shows_stage_timings(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([str(write_stl(cube(), "model")), "--dry-run", "-v"]) == ExitCode.SUCCESS
    err = capsys.readouterr().err
    assert "debug: stage configuration: " in err
    assert " s\n" in err


# --- diagnostics -----------------------------------------------------------------------------


def test_reported_partial_diagnostic_gives_exit_3(capsys: pytest.CaptureFixture[str]) -> None:
    cli.setup_logging(0)
    diagnostics = [
        errors.diagnostic("W009", "face has a single connector", ("A~B",)),
        errors.diagnostic("W001", "face got no connector", ("A~C",)),
    ]
    assert cli.report_diagnostics(diagnostics) == ExitCode.PARTIAL
    err = capsys.readouterr().err
    assert "W001" in err
    assert "A~C" in err


def test_reported_info_and_warning_diagnostics_give_exit_0() -> None:
    diagnostics = [errors.diagnostic("W012", "nothing to cut"), errors.diagnostic("W002", "short")]
    assert cli.report_diagnostics(diagnostics) == ExitCode.SUCCESS
