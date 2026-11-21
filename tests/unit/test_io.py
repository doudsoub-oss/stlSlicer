import os
import re
import signal
import struct
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold

from stlsplit import cli, io
from stlsplit.config import MAX_COORDINATE
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
    io.publish_outputs(out, {}, force=False)
    assert out.is_dir()


def test_empty_output_directory_is_accepted(tmp_path: Path) -> None:
    io.publish_outputs(tmp_path, {}, force=False)
    assert tmp_path.is_dir()


def test_output_path_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "out"
    path.write_text("not a folder")
    with pytest.raises(InputError, match="not a directory"):
        io.publish_outputs(path, {}, force=True)
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
    io.publish_outputs(out, {}, force=True)
    assert sorted(p.name for p in out.iterdir()) == ["notes.txt", "other"]
    assert (out / "notes.txt").read_text() == "keep"
    assert (out / "other" / "parts").read_text() == "keep"


def test_force_through_the_cli_keeps_other_files(write_stl: WriteStl, tmp_path: Path) -> None:
    out = tmp_path / "out"
    make_owned_and_other_entries(out)
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "-o", str(out), "--force"]) == ExitCode.SUCCESS
    assert sorted(p.name for p in out.iterdir()) == [
        "assembly.json",
        "assembly.md",
        "notes.txt",
        "other",
        "parts",
        "preview_exploded.glb",
    ]
    assert [p.name for p in (out / "parts").iterdir()] == ["X0-Y0-Z0.stl"]  # old.stl is gone
    assert (out / "notes.txt").read_text() == "keep"
    assert (out / "other" / "parts").read_text() == "keep"


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
    io.publish_outputs(out, {}, force=True)
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
    io.publish_outputs(out, {}, force=True)
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


@pytest.mark.parametrize("scale", [1e14, 1e100, 1e308], ids=["over-limit", "1e100", "overflow"])
def test_scale_beyond_the_coordinate_limit_is_a_config_error(
    write_stl: WriteStl, scale: float
) -> None:
    with pytest.raises(ConfigError, match="use a smaller scale") as exc:
        io.load_stl(write_stl(cube(100.0), "model"), scale)
    assert exc.value.key == "model.scale"


def test_scale_up_to_the_coordinate_limit_is_accepted(write_stl: WriteStl) -> None:
    mesh, diagnostics = io.load_stl(write_stl(cube(100.0), "model"), MAX_COORDINATE / 100.0)
    assert float(mesh.extents.max()) == pytest.approx(MAX_COORDINATE)
    assert [d.code for d in diagnostics] == ["W006"]


def test_out_of_memory_while_loading_is_not_a_damaged_file(
    write_stl: WriteStl, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exhausted(*args: object, **kwargs: object) -> None:
        raise MemoryError

    stl = write_stl(cube(), "model")
    monkeypatch.setattr(io.trimesh, "load", exhausted)
    with pytest.raises(MemoryError):
        io.load_stl(stl, 1.0)


def test_load_stl_reads_a_name_that_is_not_utf8(write_stl: WriteStl, tmp_path: Path) -> None:
    source = write_stl(cube(), "model")
    try:
        path = Path(os.fsdecode(os.fsencode(tmp_path) + b"/caf\xe9.stl"))
        path.write_bytes(source.read_bytes())
    except (OSError, UnicodeError):
        pytest.skip("this file system refuses names that aren't valid UTF-8")
    mesh, _ = io.load_stl(path, 1.0)
    assert len(mesh.faces) == 12


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


# --- writing (Phase 7) ------------------------------------------------------------------------


def test_publish_creates_folders_and_a_binary_stl(tmp_path: Path) -> None:
    mesh = manifold_to_trimesh(cube())
    io.publish_outputs(tmp_path, {"dowels/dowel_d5.0_l20.0.stl": io.encode_stl(mesh)}, force=False)
    path = tmp_path / "dowels" / "dowel_d5.0_l20.0.stl"
    data = path.read_bytes()
    assert data[:80] == b"\x00" * 80  # no timestamp in the header (ADR-0010)
    assert struct.unpack("<I", data[80:84])[0] == len(mesh.faces)
    loaded, _ = io.load_stl(path, 1.0)
    assert loaded.volume == pytest.approx(1000.0)


def test_published_text_keeps_its_utf8_bytes_and_unix_line_ends(tmp_path: Path) -> None:
    text = "first ±\nsecond\n".encode()
    io.publish_outputs(tmp_path, {"calibration/README.md": text}, force=False)
    assert (tmp_path / "calibration" / "README.md").read_bytes() == "first ±\nsecond\n".encode()


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("notes.txt", id="not-owned"),
        pytest.param("other/block.stl", id="not-owned-folder"),
        pytest.param("../calibration/block.stl", id="parent"),
        pytest.param("calibration/../../block.stl", id="escapes-through-an-owned-folder"),
    ],
)
def test_publish_only_writes_owned_outputs(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="owned"):
        io.publish_outputs(tmp_path, {name: b"text"}, force=False)
    with pytest.raises(ValueError, match="owned"):
        mesh = manifold_to_trimesh(cube())
        io.publish_outputs(tmp_path, {"parts/a.stl": b"ok", name: io.encode_stl(mesh)}, force=True)
    assert list(tmp_path.iterdir()) == []


def test_write_failure_is_an_input_error(tmp_path: Path) -> None:
    # The first file sits where the second one's folder should go.
    files = {"calibration": b"a file", "calibration/README.md": b"text"}
    with pytest.raises(InputError, match="can't write") as exc:
        io.publish_outputs(tmp_path, files, force=False)
    assert exc.value.exit_code == ExitCode.INVALID_INPUT
    assert list(tmp_path.iterdir()) == []


# --- all-or-nothing replacement (PLAN.md §7.6, r13) --------------------------------------------

NEW_FILES = {"parts/new.stl": b"new", "assembly.json": b"new json"}
"""Replaces two owned entries, so a swap is four renames: two out, two in."""


def earlier_run(out: Path) -> None:
    (out / "parts").mkdir(parents=True)
    (out / "parts" / "old.stl").write_text("old")
    (out / "assembly.json").write_text("old json")
    (out / "notes.txt").write_text("keep")


def assert_earlier_run_is_intact(out: Path) -> None:
    assert sorted(p.name for p in out.iterdir()) == ["assembly.json", "notes.txt", "parts"]
    assert [p.name for p in (out / "parts").iterdir()] == ["old.stl"]
    assert (out / "parts" / "old.stl").read_text() == "old"
    assert (out / "assembly.json").read_text() == "old json"
    assert (out / "notes.txt").read_text() == "keep"


def test_publish_replaces_the_outputs_and_leaves_no_staging_folder(tmp_path: Path) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    io.publish_outputs(out, NEW_FILES, force=True)
    assert sorted(p.name for p in out.iterdir()) == ["assembly.json", "notes.txt", "parts"]
    assert [p.name for p in (out / "parts").iterdir()] == ["new.stl"]
    assert (out / "assembly.json").read_bytes() == b"new json"
    assert (out / "notes.txt").read_text() == "keep"


@pytest.mark.parametrize("error", [InputError("can't write it"), KeyboardInterrupt()])
def test_a_failed_write_keeps_the_previous_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = io._write_bytes
    calls = []

    def fail_on_the_second(target: Path, data: bytes) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise error
        real(target, data)

    monkeypatch.setattr(io, "_write_bytes", fail_on_the_second)
    with pytest.raises(type(error)):
        io.publish_outputs(out, NEW_FILES, force=True)
    assert_earlier_run_is_intact(out)


def test_a_failed_write_removes_the_directory_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(target: Path, data: bytes) -> None:
        raise InputError("can't write it")

    monkeypatch.setattr(io, "_write_bytes", fail)
    with pytest.raises(InputError):
        io.publish_outputs(tmp_path / "out", NEW_FILES, force=False)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failing_rename", [0, 1, 2, 3])
def test_a_failed_swap_restores_the_previous_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_rename: int
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = os.replace
    calls = []

    def flaky(source: Path, target: Path) -> None:
        calls.append(source)
        if len(calls) - 1 == failing_rename:
            raise PermissionError("the file is open in another program")
        real(source, target)

    monkeypatch.setattr(io.os, "replace", flaky)
    with pytest.raises(InputError, match="previous outputs were kept"):
        io.publish_outputs(out, NEW_FILES, force=True)
    assert_earlier_run_is_intact(out)


def test_a_swap_that_cannot_be_undone_keeps_the_old_outputs_and_says_where(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = os.replace
    calls = []

    def fails_from_the_third(source: Path, target: Path) -> None:
        calls.append(source)
        if len(calls) >= 3:
            raise PermissionError("the disk went read-only")
        real(source, target)

    monkeypatch.setattr(io.os, "replace", fails_from_the_third)
    with pytest.raises(InputError, match=re.escape(io.STAGING_DIR)):
        io.publish_outputs(out, NEW_FILES, force=True)
    old = out / io.STAGING_DIR / "old"
    assert (old / "parts" / "old.stl").read_text() == "old"
    assert (old / "assembly.json").read_text() == "old json"


@pytest.mark.parametrize("rename", [0, 1, 2, 3])
def test_ctrl_c_during_the_swap_lets_it_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rename: int
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    handler = signal.getsignal(signal.SIGINT)
    real = os.replace
    calls = []

    def pressed_after_the_rename(source: Path, target: Path) -> None:
        real(source, target)
        calls.append(source)
        if len(calls) - 1 == rename:
            signal.raise_signal(signal.SIGINT)

    monkeypatch.setattr(io.os, "replace", pressed_after_the_rename)
    io.publish_outputs(out, NEW_FILES, force=True)
    assert len(calls) > rename
    assert [p.name for p in (out / "parts").iterdir()] == ["new.stl"]
    assert (out / "assembly.json").read_bytes() == b"new json"
    assert not (out / io.STAGING_DIR).exists()
    assert signal.getsignal(signal.SIGINT) is handler


def test_ctrl_c_while_deleting_the_old_outputs_keeps_the_new_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = io._remove

    def pressed(entry: Path) -> None:
        if entry.parent.name == "old":
            signal.raise_signal(signal.SIGINT)
        real(entry)

    monkeypatch.setattr(io, "_remove", pressed)
    io.publish_outputs(out, NEW_FILES, force=True)
    assert (out / "assembly.json").read_bytes() == b"new json"
    assert not (out / io.STAGING_DIR).exists()


@pytest.mark.parametrize("rename", [0, 1, 2, 3])
def test_an_exception_right_after_a_rename_is_undone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rename: int
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = os.replace
    calls = []

    def stopped_after_the_rename(source: Path, target: Path) -> None:
        real(source, target)
        calls.append(source)
        if len(calls) - 1 == rename:
            raise KeyboardInterrupt

    monkeypatch.setattr(io.os, "replace", stopped_after_the_rename)
    with pytest.raises(KeyboardInterrupt):
        io.publish_outputs(out, NEW_FILES, force=True)
    assert_earlier_run_is_intact(out)


def test_an_exception_during_the_undo_keeps_the_old_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = os.replace
    calls = []

    def stopped_twice(source: Path, target: Path) -> None:
        calls.append(source)
        if len(calls) == 3:  # the first rename of the undo
            raise KeyboardInterrupt
        real(source, target)
        if len(calls) == 2:  # both old outputs have just moved out
            raise KeyboardInterrupt

    monkeypatch.setattr(io.os, "replace", stopped_twice)
    with pytest.raises(InputError, match=re.escape(io.STAGING_DIR)):
        io.publish_outputs(out, NEW_FILES, force=True)
    old = out / io.STAGING_DIR / "old"
    assert (old / "parts" / "old.stl").read_text() == "old"
    assert (old / "assembly.json").read_text() == "old json"


def test_old_outputs_that_cannot_be_deleted_only_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = io._remove

    def refuse_old(entry: Path) -> None:
        if entry.parent.name == "old":
            raise InputError(f"can't remove {entry}")
        real(entry)

    monkeypatch.setattr(io, "_remove", refuse_old)
    io.publish_outputs(out, NEW_FILES, force=True)
    assert (out / "assembly.json").read_bytes() == b"new json"
    assert io.STAGING_DIR in caplog.text


def test_force_clears_a_leftover_staging_folder_without_old_outputs(tmp_path: Path) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    (out / io.STAGING_DIR / "new" / "parts").mkdir(parents=True)
    (out / io.STAGING_DIR / "new" / "parts" / "half.stl").write_text("half")
    (out / io.STAGING_DIR / "old").mkdir()
    io.publish_outputs(out, NEW_FILES, force=True)
    assert not (out / io.STAGING_DIR).exists()
    assert [p.name for p in (out / "parts").iterdir()] == ["new.stl"]


def test_force_refuses_to_delete_old_outputs_stranded_in_the_staging_folder(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    stranded = out / io.STAGING_DIR / "old" / "dowels"
    stranded.mkdir(parents=True)
    (stranded / "only_copy.stl").write_text("precious")
    with pytest.raises(InputError, match=re.escape(io.STAGING_DIR)):
        io.publish_outputs(out, NEW_FILES, force=True)
    assert (stranded / "only_copy.stl").read_text() == "precious"
    assert (out / "parts" / "old.stl").read_text() == "old"


def test_force_check_refuses_an_input_inside_the_staging_folder(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / io.STAGING_DIR).mkdir(parents=True)
    model = out / io.STAGING_DIR / "in.stl"
    model.write_text("keep")
    with pytest.raises(InputError, match="--force would delete"):
        io.check_force_keeps(out, [model])


def test_a_failed_write_through_the_cli_keeps_the_previous_outputs(
    write_stl: WriteStl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    earlier_run(out)
    real = io._write_bytes

    def disk_full(target: Path, data: bytes) -> None:
        if target.name == "assembly.md":
            raise InputError(f"can't write {target} (no space left on device)")
        real(target, data)

    monkeypatch.setattr(io, "_write_bytes", disk_full)
    stl = write_stl(cube(), "model")
    assert cli.main([str(stl), "-o", str(out), "--force"]) == ExitCode.INVALID_INPUT
    assert_earlier_run_is_intact(out)


def test_a_failed_calibration_write_keeps_the_previous_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    earlier_run(out)

    def disk_full(target: Path, data: bytes) -> None:
        raise InputError(f"can't write {target} (no space left on device)")

    monkeypatch.setattr(io, "_write_bytes", disk_full)
    assert cli.main(["--calibrate", "-o", str(out), "--force"]) == ExitCode.INVALID_INPUT
    assert_earlier_run_is_intact(out)


# --- --force never deletes a file the run reads -----------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("parts/in.stl", id="in-an-owned-folder"),
        pytest.param("dowels/deep/down/in.stl", id="deep-in-an-owned-folder"),
        pytest.param("calibration/my.toml", id="in-the-calibration-folder"),
        pytest.param("assembly.md", id="an-owned-file"),
    ],
)
def test_force_check_refuses_a_file_force_would_delete(tmp_path: Path, name: str) -> None:
    out = tmp_path / "out"
    file = out / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("keep")
    with pytest.raises(InputError, match="--force would delete") as exc:
        io.check_force_keeps(out, [tmp_path, file])
    assert str(file) in str(exc.value)
    assert exc.value.exit_code == ExitCode.INVALID_INPUT
    assert file.read_text() == "keep"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("model.stl", id="beside-the-outputs"),
        pytest.param("parts.stl", id="name-starting-like-an-owned-one"),
        pytest.param("other/parts/in.stl", id="owned-name-in-another-folder"),
    ],
)
def test_force_check_accepts_a_file_force_would_keep(tmp_path: Path, name: str) -> None:
    out = tmp_path / "out"
    (out / "parts").mkdir(parents=True)
    file = out / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("keep")
    io.check_force_keeps(out, [file])
    io.publish_outputs(out, {}, force=True)
    assert file.read_text() == "keep"


def test_force_check_ignores_missing_paths(tmp_path: Path) -> None:
    (tmp_path / "out" / "parts").mkdir(parents=True)
    io.check_force_keeps(tmp_path / "out", [tmp_path / "out" / "parts" / "missing.stl"])
    io.check_force_keeps(tmp_path / "no-such-dir", [tmp_path / "missing.stl"])


def test_force_check_handles_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "in.stl").write_text("keep")
    monkeypatch.chdir(tmp_path / "parts")
    with pytest.raises(InputError, match="--force would delete"):
        io.check_force_keeps(Path(".."), [Path("in.stl")])


def test_force_check_follows_a_link_to_a_file_force_would_delete(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "parts").mkdir(parents=True)
    (out / "parts" / "in.stl").write_text("keep")
    link = tmp_path / "link.stl"
    symlink_or_skip(link, out / "parts" / "in.stl", is_dir=False)
    with pytest.raises(InputError, match="--force would delete"):
        io.check_force_keeps(out, [link])


def test_force_check_sees_through_a_linked_output_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "parts").mkdir(parents=True)
    (real / "parts" / "in.stl").write_text("keep")
    link = tmp_path / "out"
    symlink_or_skip(link, real, is_dir=True)
    with pytest.raises(InputError, match="--force would delete"):
        io.check_force_keeps(link, [real / "parts" / "in.stl"])


def test_force_check_accepts_a_file_behind_an_owned_symlink(tmp_path: Path) -> None:
    # An owned name that is a symlink is unlinked, never followed: the file survives.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "in.stl").write_text("keep")
    out = tmp_path / "out"
    out.mkdir()
    symlink_or_skip(out / "parts", elsewhere, is_dir=True)
    io.check_force_keeps(out, [out / "parts" / "in.stl"])
    io.publish_outputs(out, {}, force=True)
    assert (elsewhere / "in.stl").read_text() == "keep"
