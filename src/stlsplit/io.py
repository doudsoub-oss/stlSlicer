"""Reading and writing files: STL loading, the output-directory policy, the label-font lookup.

With ``cli``, the only module that touches the file system (PLAN.md §3.1). ``load_stl`` is the
first pipeline stage (§5.1): it reads the input STL into the input frame (STL coordinates ×
``--scale``) for ``repair.prepare``. ``resolve_label_font`` and ``check_label_font`` check the
configuration rules that need the file system (§7.5). ``encode_stl`` and ``encode_preview`` turn
the results into bytes, and ``publish_outputs``, the last stage, applies the output-directory
policy (§7.6) and puts them in place, all or nothing.

Guarantees: ``load_stl`` returns a mesh with at least one triangle and finite coordinates, or
raises ``InputError``. ``publish_outputs`` writes only under a name in ``OWNED_OUTPUTS``, never
deletes the output directory itself or a name outside ``OWNED_OUTPUTS``, never follows a symlink
while deleting, and keeps the previous outputs if it fails; ``check_force_keeps`` refuses a run
whose own input lies inside one of those names. The bytes depend only on what they are given
(no timestamp, ADR-0010).
"""

import contextlib
import logging
import os
import shutil
import signal
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import NamedTuple, cast

import numpy as np
import trimesh

from stlsplit.config import (
    LABEL_CHARACTERS,
    MAX_COORDINATE,
    SCALE_WARNING_MAX,
    SCALE_WARNING_MIN,
)
from stlsplit.errors import ConfigError, InputError, diagnostic
from stlsplit.models import Diagnostic

OWNED_OUTPUTS: tuple[str, ...] = (
    "parts",
    "dowels",
    "calibration",
    "assembly.json",
    "assembly.md",
    "preview_exploded.glb",
)
"""Every name stlsplit writes in the output directory, and the only names ``--force`` deletes
(PLAN.md §7.6). The writers below use this same constant."""

STAGING_DIR = ".stlsplit-staging"
"""Folder inside the output directory where a run prepares its files (§7.6, r13). Inside it, so
that moving them into place is a rename on one file system. It is gone after a normal run."""

LOGGER = logging.getLogger(__name__)


class PreviewMesh(NamedTuple):
    """One piece of the exploded preview.

    Attributes:
        name: Its glTF node name, the piece ID.
        mesh: The piece, mm.
        offset: How far it is moved from its place, mm.
        color: RGBA, 0 to 255.
    """

    name: str
    mesh: trimesh.Trimesh
    offset: tuple[float, float, float]
    color: tuple[int, int, int, int]


def load_stl(path: Path, scale: float) -> tuple[trimesh.Trimesh, list[Diagnostic]]:
    """Read an STL file into the input frame (PLAN.md §4.2, Phase 2).

    trimesh merges coincident vertices while loading, so an STL (one separate triangle per
    facet) comes back connected, and it drops triangles with a non-finite coordinate
    (docs/LIBRARY_NOTES.md). The file is always read as STL, whatever its extension.

    Args:
        path: The input file (``INPUT``).
        scale: Uniform factor applied to every coordinate (``model.scale``); STL has no units
            and is read as mm.

    Returns:
        The mesh, mm, input frame; and a W006 diagnostic when its largest dimension is under
        ``SCALE_WARNING_MIN`` or over ``SCALE_WARNING_MAX`` mm, else no diagnostic.

    Raises:
        InputError: The file doesn't exist, isn't a file, can't be parsed as STL, or holds no
            triangle.
        ConfigError: ``scale`` puts a coordinate beyond ``MAX_COORDINATE``.
    """
    if not path.exists():
        raise InputError(f"INPUT {path}: no such file")
    if not path.is_file():
        raise InputError(f"INPUT {path} is not a file")
    try:
        # From an open file: given a path, trimesh hashes the name as UTF-8, which fails on a
        # name that isn't valid UTF-8 (docs/LIBRARY_NOTES.md).
        with path.open("rb") as stream:
            mesh = trimesh.load(stream, file_type="stl", force="mesh")
    except MemoryError:
        raise  # the CLI reports it as such: the file isn't damaged
    except Exception as exc:  # trimesh's parsers raise many types on malformed input
        raise InputError(
            f"INPUT {path}: can't read it as an STL file ({type(exc).__name__}: {exc})"
        ) from exc
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise InputError(f"INPUT {path}: no triangles found; is it an STL file?")
    with np.errstate(over="ignore", invalid="ignore"):  # an overflow is reported just below
        mesh.apply_scale(scale)  # type: ignore[no-untyped-call]  # unannotated in trimesh
        reach = float(np.abs(mesh.vertices).max())
    if not reach <= MAX_COORDINATE:  # also catches a coordinate that overflowed
        raise ConfigError(
            "model.scale",
            f"{scale:g} puts the model's coordinates at {reach:g} mm, over the limit of "
            f"{MAX_COORDINATE:g} mm; use a smaller scale",
        )
    size = float(mesh.extents.max())
    diagnostics = []
    if size < SCALE_WARNING_MIN or size > SCALE_WARNING_MAX:
        diagnostics.append(
            diagnostic(
                "W006",
                f"suspicious scale: the model is {size:.6g} mm along its largest side "
                f"(expected {SCALE_WARNING_MIN:g} to {SCALE_WARNING_MAX:g} mm). STL has no "
                "units and is read as mm: use --scale to convert (25.4 for inches, 1000 for "
                "metres)",
            )
        )
    return mesh, diagnostics


class _StrandedOutputsError(InputError):
    """A swap failed and couldn't be undone: the staging folder holds the only old copies."""


def publish_outputs(path: Path, files: Mapping[str, bytes], force: bool) -> None:
    """Replace stlsplit's outputs in ``path`` with ``files``, all or nothing (§7.6, r13).

    A missing directory is created with its parents. An empty one is used as is. A non-empty
    one is refused unless ``force`` is set; then every entry named in ``OWNED_OUTPUTS`` is
    replaced and everything else is kept. An owned name that is a symlink (or a Windows
    junction) is moved and unlinked, never followed.

    The files are first written in full to ``STAGING_DIR``, so a full disk can't touch the
    previous outputs. They are then swapped in by renames, which are undone if one fails. The
    old outputs are deleted last. The disk needs room for both for a moment.

    Args:
        path: The output directory (``-o``).
        files: Content by path relative to ``path``, with ``/`` separators, under a name of
            ``OWNED_OUTPUTS``. Written in sorted name order.
        force: ``--force`` was given.

    Raises:
        ValueError: A path isn't under an owned name (a bug); nothing is touched.
        InputError: ``path`` exists but isn't a directory, is a dangling symlink, is not empty
            and ``force`` is off, or holds old outputs of a run that didn't finish; or a file
            can't be written or moved. The previous outputs are then still in place, or, if
            even undoing the swap failed, in ``STAGING_DIR/old``, as the message says.
    """
    names = sorted(files)
    for name in names:
        _owned_path(path, name)
    created = _check_output_dir(path, force)
    staging = path / STAGING_DIR
    new, old = staging / "new", staging / "old"
    try:
        _remove(staging)
        try:
            new.mkdir(parents=True)
            old.mkdir()
        except OSError as exc:
            raise InputError(f"can't write {staging} ({exc})") from exc
        for name in names:
            _write_bytes(_owned_path(new, name), files[name])
        with _holding_ctrl_c():
            _swap(path, new, old)
            _delete_replaced(staging, old)
    except _StrandedOutputsError:
        raise  # the staging folder holds the only copy of the old outputs: keep it
    except BaseException as exc:  # Ctrl-C too: leave the folder as it was
        if _may_hold_outputs(old):
            raise _StrandedOutputsError(
                f"the run stopped while replacing the outputs in {path} "
                f"({type(exc).__name__}): the previous ones are in {old}"
            ) from exc
        shutil.rmtree(staging, ignore_errors=True)
        if created:
            with contextlib.suppress(OSError):
                path.rmdir()
        raise


@contextlib.contextmanager
def _holding_ctrl_c() -> Iterator[None]:
    """Ignore Ctrl-C while the outputs are swapped and the old ones deleted (§7.6, r14).

    These are a few renames and deletions. Stopped halfway, they could lose the only copy of
    an old output; once the swap is done, the run has succeeded and keeps its exit code.
    """
    try:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except ValueError:  # not the main thread, where Python never raises KeyboardInterrupt
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL if previous is None else previous)


def _may_hold_outputs(old: Path) -> bool:
    """Whether the staging folder's ``old`` may hold outputs; if it can't be read, it may."""
    try:
        return old.is_dir() and any(old.iterdir())
    except OSError:
        return True


def _check_output_dir(path: Path, force: bool) -> bool:
    """Apply the policy of §7.6 without deleting anything; return whether ``path`` was created."""
    if path.is_symlink() and not path.exists():
        raise InputError(f"output directory {path} is a dangling symbolic link")
    if not path.exists():
        try:
            path.mkdir(parents=True)
        except OSError as exc:
            raise InputError(f"output directory {path}: can't create it ({exc})") from exc
        return True
    if not path.is_dir():
        raise InputError(f"output directory {path} exists and is not a directory")
    try:
        empty = not any(path.iterdir())
        if empty:
            return False
        if not force:
            raise InputError(
                f"output directory {path} is not empty; use --force to replace stlsplit's "
                "outputs in it (other files are kept)"
            )
        stranded = path / STAGING_DIR / "old"
        if stranded.is_dir() and any(stranded.iterdir()):
            raise InputError(
                f"{stranded} holds outputs of an earlier run that didn't finish, possibly the "
                f"only copy: move what you need out of it, then delete {path / STAGING_DIR}"
            )
    except OSError as exc:
        raise InputError(f"output directory {path}: can't read it ({exc})") from exc
    return False


def _swap(path: Path, new: Path, old: Path) -> None:
    """Move the owned entries to ``old`` and those of ``new`` into ``path``; undo on failure."""
    moved_out: list[str] = []
    moved_in: list[str] = []
    try:
        for name in OWNED_OUTPUTS:
            if os.path.lexists(path / name):  # a dangling symlink counts
                moved_out.append(name)  # before the rename, so the undo can't miss it
                os.replace(path / name, old / name)
        for entry in sorted(new.iterdir()):
            moved_in.append(entry.name)
            os.replace(entry, path / entry.name)
    except BaseException as exc:
        if not _undo_swap(path, new, old, moved_out, moved_in):
            raise _StrandedOutputsError(
                f"can't replace the outputs in {path} ({exc}), and couldn't put the previous "
                f"ones back: they are in {old}"
            ) from exc
        if isinstance(exc, OSError):
            raise InputError(
                f"can't replace the outputs in {path} ({exc}); the previous outputs were kept"
            ) from exc
        raise


def _undo_swap(
    path: Path, new: Path, old: Path, moved_out: Sequence[str], moved_in: Sequence[str]
) -> bool:
    """Put everything back, trying every entry; return whether all of it worked.

    An entry is listed before its rename, so one whose source is missing was never moved.
    """
    restored = True
    for source, target in [
        *((path / name, new / name) for name in reversed(moved_in)),
        *((old / name, path / name) for name in reversed(moved_out)),
    ]:
        if not os.path.lexists(source):
            continue
        try:
            os.replace(source, target)
        except OSError:
            restored = False
    return restored


def _delete_replaced(staging: Path, old: Path) -> None:
    """Delete the replaced outputs. The new ones are in place, so a failure is only a warning."""
    try:
        for entry in old.iterdir():
            _remove(entry)  # never follows a symlink or a junction
        shutil.rmtree(staging)
    except (OSError, InputError) as exc:
        LOGGER.warning(
            "the new outputs are in place, but the old ones couldn't be deleted (%s); "
            "delete %s yourself",
            exc,
            staging,
        )


def check_force_keeps(path: Path, files: Iterable[Path]) -> None:
    """Refuse a ``--force`` run that would delete a file it reads (PLAN.md §7.6).

    With the input in ``out/parts/``, ``stlsplit out/parts/in.stl -o out --force`` would delete
    it. Links are resolved, so a link to a file inside an owned folder counts as that file.
    An owned name that is itself a link doesn't count: it is unlinked, and what it points to
    survives. A path that doesn't exist is ignored, and is reported by whatever reads it.

    Args:
        path: The output directory (``-o``).
        files: The files the run reads: the input, the ``--config`` file, the label font.

    Raises:
        InputError: Deleting an entry of ``OWNED_OUTPUTS`` would delete one of ``files``, or
            the paths can't be compared.
    """
    existing = [file for file in files if file.exists()]
    for name in (*OWNED_OUTPUTS, STAGING_DIR):
        entry = path / name
        if not entry.exists() or entry.is_symlink() or entry.is_junction():
            continue
        for file in existing:
            real = file.resolve()
            try:
                # samefile, not a path comparison: it also holds on case-insensitive disks.
                held = any(entry.samefile(place) for place in (real, *real.parents))
            except OSError as exc:
                raise InputError(f"output directory {path}: can't check {file} ({exc})") from exc
            if held:
                raise InputError(
                    f"--force would delete {file}, which this run reads: it is inside {entry}, "
                    "one of stlsplit's outputs. Move the file or choose another output directory"
                )


def resolve_label_font(name: str) -> Path:
    """Return the font file that ``advanced.label_font`` names (PLAN.md §7.5, ADR-0009).

    Args:
        name: A bare file name, looked up among the fonts bundled with matplotlib, or an
            absolute path.

    Returns:
        The path of an existing font file.

    Raises:
        ConfigError: ``name`` is a relative path with folders, or names no existing file.
    """
    candidate = Path(name)
    if candidate.is_absolute():
        path = candidate
    elif name and candidate.name == name:
        import matplotlib  # imported here: slow, and only needed for this check

        # The bundled fonts' location is checked by scripts/api_spike.py (LIBRARY_NOTES.md).
        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name
    else:
        raise ConfigError(
            "advanced.label_font",
            "must be the file name of a font bundled with matplotlib (e.g. "
            f'"DejaVuSans-Bold.ttf") or an absolute path, got "{name}"',
        )
    if not path.is_file():
        raise ConfigError("advanced.label_font", f"no such font file: {path}")
    return path


def check_label_font(path: Path) -> None:
    """Check that a font can draw every label and calibration code (PLAN.md §7.5, r11).

    Run only by the modes that draw text, so ``--print-config`` and a run with ``--no-label``
    don't depend on the font's content.

    Args:
        path: An existing file (``resolve_label_font``).

    Raises:
        ConfigError: It can't be read as a font, has no glyph for a character of
            ``LABEL_CHARACTERS`` (symbol fonts), or draws several of them with one glyph
            (placeholder fonts such as Last Resort): their text would be unreadable.
    """
    from matplotlib.ft2font import FT2Font  # imported here: matplotlib is slow to import

    try:
        font = FT2Font(str(path))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigError("advanced.label_font", f"can't read {path} as a font") from exc
    glyphs = {c: font.get_char_index(ord(c)) for c in LABEL_CHARACTERS}
    missing = "".join(c for c, glyph in glyphs.items() if glyph == 0)
    if missing:
        raise ConfigError(
            "advanced.label_font", f"{path.name} has no glyph for these characters: {missing}"
        )
    if len(set(glyphs.values())) < len(glyphs):
        raise ConfigError(
            "advanced.label_font",
            f"{path.name} draws several of these characters with the same glyph: "
            f"{LABEL_CHARACTERS}",
        )


def encode_stl(mesh: trimesh.Trimesh) -> bytes:
    """Return a mesh as a binary STL with an all-zero header (no timestamp, ADR-0010).

    Args:
        mesh: The mesh, mm.

    Returns:
        The file's bytes.
    """
    return cast(bytes, mesh.export(file_type="stl"))


def encode_preview(items: Sequence[PreviewMesh]) -> bytes:
    """Return the exploded preview as a GLB file (PLAN.md Phase 9, task 5).

    Nodes, geometries and materials are named after the pieces, so the bytes depend only on
    what is given (ADR-0010).

    Args:
        items: The pieces, in piece order.

    Returns:
        The file's bytes.
    """
    scene = trimesh.Scene()
    for item in items:
        mesh = item.mesh.copy()
        material = trimesh.visual.material.PBRMaterial(  # type: ignore[no-untyped-call]
            name=f"{item.name}-color", baseColorFactor=list(item.color)
        )
        mesh.visual = trimesh.visual.TextureVisuals(material=material)  # type: ignore[no-untyped-call]
        transform = np.eye(4)
        transform[:3, 3] = item.offset
        scene.add_geometry(mesh, node_name=item.name, geom_name=item.name, transform=transform)
    return cast(bytes, scene.export(file_type="glb"))  # type: ignore[no-untyped-call]


def _owned_path(root: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if not parts or parts[0] not in OWNED_OUTPUTS or ".." in parts:
        raise ValueError(f"{name} is not under one of stlsplit's owned outputs")
    return root.joinpath(*parts)


def _write_bytes(target: Path, data: bytes) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        raise InputError(f"can't write {target} ({exc})") from exc


def _remove(entry: Path) -> None:
    try:
        if entry.is_symlink() or entry.is_junction():
            entry.unlink()  # removes the link itself, never what it points to
        elif entry.is_dir():
            shutil.rmtree(entry)
        elif entry.exists():
            entry.unlink()
    except OSError as exc:
        raise InputError(f"can't remove {entry} ({exc})") from exc
