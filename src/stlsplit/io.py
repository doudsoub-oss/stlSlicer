"""Reading and writing files: the output-directory policy and the label-font lookup.

With ``cli``, the only module that touches the file system (PLAN.md §3.1). It runs before the
first pipeline stage (§5.1): ``prepare_output_dir`` applies the output-directory policy
(§7.6), and ``resolve_label_font`` checks the one configuration rule that needs the file
system (§7.5). STL loading (Phase 2) and writing the outputs (Phase 9) come later.

Guarantees: ``prepare_output_dir`` never deletes the output directory itself, never deletes a
name outside ``OWNED_OUTPUTS``, and never follows a symlink while deleting.
"""

import shutil
from pathlib import Path

from stlsplit.errors import ConfigError, InputError

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
