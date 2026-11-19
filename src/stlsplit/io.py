"""Reading and writing files: STL loading, the output-directory policy, the label-font lookup.

With ``cli``, the only module that touches the file system (PLAN.md §3.1). ``load_stl`` is the
first pipeline stage (§5.1): it reads the input STL into the input frame (STL coordinates ×
``--scale``) for ``repair.prepare``. ``prepare_output_dir`` applies the output-directory policy
(§7.6), and ``resolve_label_font`` checks the one configuration rule that needs the file
system (§7.5). Writing the outputs comes in Phase 9.

Guarantees: ``load_stl`` returns a mesh with at least one triangle and finite coordinates, or
raises ``InputError``. ``prepare_output_dir`` never deletes the output directory itself, never
deletes a name outside ``OWNED_OUTPUTS``, and never follows a symlink while deleting.
"""

import shutil
from pathlib import Path

import trimesh

from stlsplit.config import SCALE_WARNING_MAX, SCALE_WARNING_MIN
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
(PLAN.md §7.6). The writer (Phase 9) uses this same constant."""


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
    """
    if not path.exists():
        raise InputError(f"INPUT {path}: no such file")
    if not path.is_file():
        raise InputError(f"INPUT {path} is not a file")
    try:
        mesh = trimesh.load(path, file_type="stl", force="mesh")
    except Exception as exc:  # trimesh's parsers raise many types on malformed input
        raise InputError(
            f"INPUT {path}: can't read it as an STL file ({type(exc).__name__}: {exc})"
        ) from exc
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise InputError(f"INPUT {path}: no triangles found; is it an STL file?")
    mesh.apply_scale(scale)  # type: ignore[no-untyped-call]  # unannotated in trimesh
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


def prepare_output_dir(path: Path, force: bool) -> None:
    """Make ``path`` ready to receive the outputs (PLAN.md §7.6).

    A missing directory is created with its parents. An empty one is used as is. A non-empty
    one is refused unless ``force`` is set; then only the entries named in ``OWNED_OUTPUTS``
    are deleted, everything else is kept. An owned name that is a symlink (or a Windows
    junction) is unlinked, never followed.

    Args:
        path: The output directory (``-o``).
        force: ``--force`` was given.

    Raises:
        InputError: ``path`` exists but isn't a directory, is a dangling symlink, is not empty
            and ``force`` is off, or can't be created, read or cleaned.
    """
    if path.is_symlink() and not path.exists():
        raise InputError(f"output directory {path} is a dangling symbolic link")
    if not path.exists():
        try:
            path.mkdir(parents=True)
        except OSError as exc:
            raise InputError(f"output directory {path}: can't create it ({exc})") from exc
        return
    if not path.is_dir():
        raise InputError(f"output directory {path} exists and is not a directory")
    try:
        empty = not any(path.iterdir())
    except OSError as exc:
        raise InputError(f"output directory {path}: can't read it ({exc})") from exc
    if empty:
        return
    if not force:
        raise InputError(
            f"output directory {path} is not empty; use --force to replace stlsplit's outputs "
            "in it (other files are kept)"
        )
    for name in OWNED_OUTPUTS:
        _remove(path / name)


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
