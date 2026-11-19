import struct
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

from stlsplit import cli, io
from stlsplit.errors import ConfigError, ExitCode, InputError
from tests.conftest import cube, manifold_to_trimesh

WriteStl = Callable[[Manifold, str], Path]


def make_owned_and_other_entries(out: Path) -> None:
    """Fill ``out`` with every name stlsplit owns, plus files and folders it doesn't."""
    out.mkdir()
    for folder in ("parts", "dowels", "calibration"):
        (out / folder).mkdir()
        (out / folder / "old.stl").write_text("old")
    for name in ("assembly.json", "assembly.md", "preview_exploded.glb"):
        (out / name).write_text("old")
    (out / "notes.txt").write_text("keep")
    (out / "other").mkdir()
    (out / "other" / "parts").write_text("keep")


def symlink_or_skip(link: Path, target: Path, *, is_dir: bool) -> None:
    # Creating symlinks needs a privilege on some Windows setups; the policy can't be tested
    # there, and skipping only happens when the OS itself refuses the symlink.
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except OSError as exc:
        pytest.skip(f"this system refused to create a symlink: {exc}")


def test_owned_outputs_are_the_names_in_the_plan() -> None:
    assert io.OWNED_OUTPUTS == (
        "parts",
        "dowels",
        "calibration",
        "assembly.json",
        "assembly.md",
        "preview_exploded.glb",
    )


def test_missing_output_directory_is_created_with_its_parents(tmp_path: Path) -> None:
    out = tmp_path / "a" / "b" / "out"
    io.prepare_output_dir(out, force=False)
    assert out.is_dir()


def test_empty_output_directory_is_accepted(tmp_path: Path) -> None:
    io.prepare_output_dir(tmp_path, force=False)
    assert tmp_path.is_dir()


def test_output_path_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "out"
    path.write_text("not a folder")
    with pytest.raises(InputError, match="not a directory"):
        io.prepare_output_dir(path, force=True)
    assert path.read_text() == "not a folder"


def test_non_empty_output_directory_without_force_exits_1(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    make_owned_and_other_entries(out)
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "-o", str(out)]) == ExitCode.INVALID_INPUT
    assert "--force" in capsys.readouterr().err
    assert (out / "parts" / "old.stl").read_text() == "old"
    assert (out / "notes.txt").read_text() == "keep"


def test_force_deletes_only_the_owned_outputs(tmp_path: Path) -> None:
    out = tmp_path / "out"
    make_owned_and_other_entries(out)
    io.prepare_output_dir(out, force=True)
    assert sorted(p.name for p in out.iterdir()) == ["notes.txt", "other"]
    assert (out / "notes.txt").read_text() == "keep"
    assert (out / "other" / "parts").read_text() == "keep"


def test_force_through_the_cli_keeps_other_files(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    make_owned_and_other_entries(out)
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "-o", str(out), "--force"]) == ExitCode.SUCCESS
    assert sorted(p.name for p in out.iterdir()) == ["notes.txt", "other"]


@pytest.mark.parametrize("is_dir", [True, False], ids=["folder", "file"])
def test_force_unlinks_a_symlink_with_an_owned_name_without_following_it(
    tmp_path: Path, is_dir: bool
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if is_dir:
        target = elsewhere / "precious"
        target.mkdir()
        (target / "model.stl").write_text("precious")
        name = "parts"
    else:
        target = elsewhere / "precious.json"
        target.write_text("precious")
        name = "assembly.json"
    out = tmp_path / "out"
    out.mkdir()
    symlink_or_skip(out / name, target, is_dir=is_dir)
    io.prepare_output_dir(out, force=True)
    assert not (out / name).is_symlink()
    assert not (out / name).exists()
    if is_dir:
        assert (target / "model.stl").read_text() == "precious"
    else:
        assert target.read_text() == "precious"


def test_force_on_a_dangling_symlink_with_an_owned_name_unlinks_it(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    symlink_or_skip(out / "parts", tmp_path / "gone", is_dir=True)
    io.prepare_output_dir(out, force=True)
    assert not (out / "parts").is_symlink()


# --- label font (PLAN.md §7.5, ADR-0009) -----------------------------------------------------


def test_bundled_label_font_resolves_to_a_file() -> None:
    path = io.resolve_label_font("DejaVuSans-Bold.ttf")
    assert path.is_file()
    assert path.name == "DejaVuSans-Bold.ttf"


def test_absolute_label_font_path_is_accepted(tmp_path: Path) -> None:
    font = tmp_path / "MyFont.ttf"
    font.write_bytes(b"\x00")
    assert io.resolve_label_font(str(font)) == font


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("NoSuchFont.ttf", id="bundled-name-missing"),
        pytest.param("fonts/DejaVuSans-Bold.ttf", id="relative-path"),
        pytest.param("", id="empty"),
    ],
)
def test_label_font_that_does_not_resolve_is_rejected(name: str) -> None:
    with pytest.raises(ConfigError) as exc:
        io.resolve_label_font(name)
    assert exc.value.key == "advanced.label_font"


def test_missing_absolute_label_font_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        io.resolve_label_font(str(tmp_path / "missing.ttf"))
    assert exc.value.key == "advanced.label_font"


# --- STL loading (PLAN.md Phase 2) -----------------------------------------------------------


def test_load_stl_reads_a_cube_without_diagnostics(write_stl: WriteStl) -> None:
    mesh, diagnostics = io.load_stl(write_stl(cube(), "model"), 1.0)
    assert len(mesh.faces) == 12
    assert mesh.extents == pytest.approx((10.0, 10.0, 10.0))
    assert diagnostics == []


def test_load_stl_applies_the_scale(write_stl: WriteStl) -> None:
    mesh, _ = io.load_stl(write_stl(cube(), "model"), 2.5)
    assert mesh.extents == pytest.approx((25.0, 25.0, 25.0))


@pytest.mark.parametrize(
    "scale",
    [
        pytest.param(0.05, id="0.5mm"),
        pytest.param(600.0, id="6m"),
    ],
)
def test_suspicious_scale_gives_w006(write_stl: WriteStl, scale: float) -> None:
    _, diagnostics = io.load_stl(write_stl(cube(), "model"), scale)
    assert [d.code for d in diagnostics] == ["W006"]
    assert "--scale" in diagnostics[0].message


def test_triangle_with_a_non_finite_coordinate_is_dropped_on_load(tmp_path: Path) -> None:
    # trimesh removes it while loading (docs/LIBRARY_NOTES.md), so NaN never reaches repair:
    # the cube loses nothing but the planted triangle.
    mesh = manifold_to_trimesh(cube())
    vertices = np.vstack([mesh.vertices, [(np.nan, 0.0, 0.0)]])
    faces = np.vstack([mesh.faces, [(0, 1, len(mesh.vertices))]])
    path = tmp_path / "nan.stl"
    trimesh.Trimesh(vertices, faces, process=False).export(path, file_type="stl")
    loaded, _ = io.load_stl(path, 1.0)
    assert len(loaded.faces) == 12
    assert np.isfinite(loaded.vertices).all()


def test_missing_input_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no such file"):
        io.load_stl(tmp_path / "missing.stl", 1.0)


def test_input_that_is_a_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="not a file"):
        io.load_stl(tmp_path, 1.0)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x00\x01this is not an STL file" * 3, id="garbage"),
        pytest.param(b"solid empty\nendsolid empty\n", id="ascii-without-triangles"),
    ],
)
def test_file_without_triangles_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "model.stl"
    path.write_bytes(content)
    with pytest.raises(InputError, match="no triangles") as exc:
        io.load_stl(path, 1.0)
    assert exc.value.exit_code == ExitCode.INVALID_INPUT


def test_truncated_binary_stl_is_rejected(tmp_path: Path) -> None:
    # The header announces 5 triangles but the file holds 1; trimesh then raises.
    triangle = struct.pack("<12f", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0) + b"\x00\x00"
    path = tmp_path / "truncated.stl"
    path.write_bytes(b"\x00" * 80 + struct.pack("<I", 5) + triangle)
    with pytest.raises(InputError) as exc:
        io.load_stl(path, 1.0)
    assert "truncated.stl" in str(exc.value)
