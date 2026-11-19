"""Command-line interface: argument parsing, orchestration, logging and exit codes.

Last stage of the pipeline (PLAN.md §5.1) and, with ``io``, the only module that touches the
file system. ``main`` parses the arguments, works out the mode (§7.1), builds one validated
``Config`` (built-in defaults ← TOML file ← options typed on the command line; §7.4,
ADR-0011), loads and repairs the input, orients it and builds the grid, prepares the output
directory (§7.6), runs the stages and turns their diagnostics into the exit code (§4.5).
Every failure becomes one line on stderr; ``-v`` adds the traceback. Logs go to stderr; the
dry run's plan goes to stdout, so ``-q`` doesn't hide it.

Load, repair, orientation and grid run before the output directory is prepared, so an
unusable input never creates the directory, and ``--force`` never deletes the previous
outputs for it.

Phase 3: the stages after the grid don't exist yet, so the split and dry-run modes stop with
a warning after the grid, and the calibration mode after the checks.
"""

import argparse
import codecs
import logging
import math
import sys
import time
import traceback
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

from manifold3d import Manifold

from stlsplit import __version__, config, grid, io, repair
from stlsplit.config import Config
from stlsplit.errors import ConfigError, ExitCode, InputError, StlsplitError, exit_code_for
from stlsplit.models import Diagnostic, Grid, Orientation

LOGGER = logging.getLogger("stlsplit")
"""Parent logger of the package; modules log through ``logging.getLogger(__name__)``."""

_CONFIG_KEYS = frozenset(config.keys())


class Mode(Enum):
    """What a run does (PLAN.md §7.1)."""

    SPLIT = "split"
    DRY_RUN = "dry run"
    CALIBRATE = "calibration"
    PRINT_CONFIG = "show config"


class _Parser(argparse.ArgumentParser):
    """An argument parser whose usage errors exit 1, like every other invalid input.

    argparse exits with 2 on a usage error, but 2 means "the mesh can't be repaired" here
    (PLAN.md §4.5), so errors raise ``InputError`` instead. ``--help`` and ``--version``
    still exit 0 through ``SystemExit``.
    """

    def error(self, message: str) -> NoReturn:
        """Raise ``InputError`` for a usage error instead of exiting with 2."""
        raise InputError(f"{message} (see stlsplit --help)")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (PLAN.md §7.2).

    Every option defaults to ``argparse.SUPPRESS``: an option the user didn't type is absent
    from the namespace, so it can't override the TOML file (§7.4, ADR-0011). Configuration
    options store their value under their dotted TOML key (``dest="connectors.clearance"``).

    Returns:
        The ``stlsplit`` parser.
    """
    parser = _Parser(
        prog="stlsplit",
        description="Split an oversized STL model into printable, connectable parts.",
        epilog="Options typed here override the --config file, which overrides the built-in "
        "defaults. Every option: docs/CONFIGURATION.md.",
        argument_default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        metavar="INPUT",
        help="the .stl file to split (not with --calibrate or --print-config)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="DIR",
        help="output directory, created if missing; required unless --dry-run or --print-config",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow a non-empty output directory: replace only stlsplit's own outputs in it",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="TOML configuration file; options typed on the command line override it",
    )

    modes = parser.add_argument_group("modes")
    modes.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    modes.add_argument(
        "--calibrate", action="store_true", help="write the clearance calibration kit to -o DIR"
    )
    modes.add_argument(
        "--print-config",
        action="store_true",
        help="print the effective configuration as TOML and exit",
    )

    model = parser.add_argument_group("printer and model")
    _option(
        model,
        "--bed",
        key="printer.bed",
        text="build volume, mm",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
    )
    _option(
        model,
        "--margin",
        key="printer.margin",
        type=float,
        metavar="MM",
        text="kept free on each side of every axis, mm",
    )
    _option(
        model,
        "--scale",
        key="model.scale",
        type=float,
        metavar="FACTOR",
        text="uniform scale applied after loading",
    )
    _option(
        model,
        "--auto-orient",
        key="model.auto_orient",
        action=argparse.BooleanOptionalAction,
        text="try the 6 axis orders and keep the one with the fewest cells",
    )
    _option(
        model,
        "--simplify",
        key="model.simplify",
        type=float,
        metavar="TOL",
        text="simplify the mesh, moving surfaces by less than TOL mm; 0 turns it off",
    )
    _option(
        model,
        "--deep-repair",
        key="repair.deep",
        action="store_true",
        text="fall back to pymeshlab if basic repair fails (extra deep-repair)",
    )

    connectors = parser.add_argument_group("connectors")
    _option(
        connectors,
        "--connector",
        key="connectors.type",
        choices=config.CONNECTOR_TYPES,
        text="connector type",
    )
    _option(
        connectors,
        "--dowel-diameter",
        key="connectors.diameter",
        type=float,
        metavar="MM",
        text="pin diameter, mm",
    )
    _option(
        connectors,
        "--dowel-length",
        key="connectors.length",
        type=float,
        metavar="MM",
        text="exact length of a full pin, mm",
    )
    _option(
        connectors,
        "--clearance",
        key="connectors.clearance",
        type=float,
        metavar="MM",
        text="radial clearance added to holes, mm (measure it with --calibrate)",
    )
    _option(
        connectors,
        "--min-wall",
        key="connectors.min_wall",
        type=float,
        metavar="MM",
        text="minimum material around and between holes, mm",
    )
    _option(
        connectors,
        "--max-connectors-per-face",
        key="connectors.max_per_face",
        type=int,
        metavar="N",
        text="maximum connectors per cut face",
    )

    output = parser.add_argument_group("labels and output")
    _option(
        output,
        "--label",
        key="labels.enabled",
        action=argparse.BooleanOptionalAction,
        text="engrave piece IDs on a cut face",
    )
    _option(
        output,
        "--label-depth",
        key="labels.depth",
        type=float,
        metavar="MM",
        text="engraving depth, mm",
    )
    _option(
        output,
        "--preview",
        key="output.preview",
        action=argparse.BooleanOptionalAction,
        text="write preview_exploded.glb",
    )

    logs = parser.add_argument_group("logging").add_mutually_exclusive_group()
    logs.add_argument(
        "-v",
        dest="verbose",
        action="store_true",
        help="also show debug messages, stage timings and tracebacks",
    )
    logs.add_argument("-q", dest="quiet", action="store_true", help="show warnings and errors only")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def config_flags(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Map each configuration key that has a CLI option to its first flag.

    Args:
        parser: A parser from ``build_parser``.

    Returns:
        ``{"connectors.clearance": "--clearance", ...}``, in parser order.
    """
    return {
        action.dest: action.option_strings[0]
        for action in parser._actions
        if action.option_strings and action.dest in _CONFIG_KEYS
    }


def check_mode(ns: argparse.Namespace) -> Mode:
    """Work out the mode and reject invalid combinations (PLAN.md §7.1, §7.5).

    Runs before anything is read or written.

    Args:
        ns: Parsed arguments.

    Returns:
        The mode.

    Raises:
        InputError: Not exactly one of INPUT, ``--calibrate`` or a bare ``--print-config``;
            ``--dry-run`` without INPUT; or no ``-o`` for a mode that writes files.
    """
    has_input = "input" in ns
    calibrate = "calibrate" in ns
    if "dry_run" in ns and not has_input:
        raise InputError("--dry-run needs an INPUT file (it doesn't apply to --calibrate)")
    if "print_config" in ns:
        if has_input or calibrate:
            raise InputError("--print-config takes no INPUT and no --calibrate")
        return Mode.PRINT_CONFIG
    if has_input and calibrate:
        raise InputError("give either an INPUT file or --calibrate, not both")
    if not has_input and not calibrate:
        raise InputError("missing INPUT file (or use --calibrate or --print-config)")
    if "dry_run" in ns:
        return Mode.DRY_RUN
    if "output" not in ns:
        raise InputError("missing -o/--output DIR (required unless --dry-run or --print-config)")
    return Mode.CALIBRATE if calibrate else Mode.SPLIT


def resolve_config(ns: argparse.Namespace) -> Config:
    """Build the effective configuration: defaults ← ``--config`` file ← typed options.

    Args:
        ns: Parsed arguments.

    Returns:
        The validated configuration (PLAN.md §7.4, §7.5).

    Raises:
        InputError: The ``--config`` file can't be read or isn't valid TOML.
        ConfigError: Unknown key, wrong type, or a validation rule fails (the label font
            included).
    """
    cfg = Config()
    if "config" in ns:
        path: Path = ns.config
        cfg = config.parse_toml(_read_config_file(path), source=str(path))
    overrides = {key: value for key, value in vars(ns).items() if key in _CONFIG_KEYS}
    cfg = config.with_overrides(cfg, overrides, source="the command line")
    config.validate(cfg)
    io.resolve_label_font(cfg.advanced.label_font)
    return cfg


def setup_logging(verbosity: int) -> None:
    """Send the package's log messages to stderr.

    Info messages are printed as they are; other levels get a ``warning:`` or ``debug:``
    prefix. Calling it again replaces the previous setup.

    Args:
        verbosity: −1 for ``-q`` (warnings and errors), 0 by default (info), 1 for ``-v``
            (debug, with stage timings).
    """
    if verbosity > 0:
        level = logging.DEBUG
    elif verbosity < 0:
        level = logging.WARNING
    else:
        level = logging.INFO
    handler = _StderrHandler()
    handler.setFormatter(_Formatter())
    for old in list(LOGGER.handlers):
        LOGGER.removeHandler(old)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time a pipeline stage; the duration is logged at debug level (shown with ``-v``).

    Args:
        name: Stage name for the log line.
    """
    start = time.perf_counter()
    yield
    LOGGER.debug("stage %s: %.3f s", name, time.perf_counter() - start)


def report_diagnostics(diagnostics: Iterable[Diagnostic]) -> ExitCode:
    """Log every diagnostic and return the run's exit code.

    ``info`` diagnostics are logged at info level, ``warning`` and ``partial`` ones at warning
    level, in the order given.

    Args:
        diagnostics: Everything the stages reported.

    Returns:
        ``PARTIAL`` (3) if any diagnostic is ``partial``, else ``SUCCESS`` (0).
    """
    collected = list(diagnostics)
    for item in collected:
        level = logging.INFO if item.severity == "info" else logging.WARNING
        refs = f" [{', '.join(item.refs)}]" if item.refs else ""
        LOGGER.log(level, "%s %s%s", item.code, item.message, refs)
    return exit_code_for(collected)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        The process exit code (PLAN.md §4.5). ``--help`` and ``--version`` raise
        ``SystemExit(0)`` instead, as argparse does.
    """
    parser = build_parser()
    verbose = False
    try:
        ns = parser.parse_args(argv)
        verbose = "verbose" in ns
        setup_logging(1 if verbose else -1 if "quiet" in ns else 0)
        return int(_run(ns))
    except ConfigError as exc:
        flag = config_flags(parser).get(exc.key)
        message = f"{flag} ({exc.key}): {exc.problem}" if flag else str(exc)
        _print_error(f"error: {message}", exc, verbose)
        return int(exc.exit_code)
    except StlsplitError as exc:
        _print_error(f"error: {exc}", exc, verbose)
        return int(exc.exit_code)
    except Exception as exc:
        _print_error(
            f"internal error: {type(exc).__name__}: {exc}. This is a bug; please report it "
            "with the full output of the same command run with -v",
            exc,
            verbose,
        )
        return int(ExitCode.INTERNAL)


def _run(ns: argparse.Namespace) -> ExitCode:
    mode = check_mode(ns)
    with stage("configuration"):
        cfg = resolve_config(ns)
    LOGGER.info("configuration: %s", _describe_sources(ns))
    if mode is Mode.PRINT_CONFIG:
        sys.stdout.write(config.to_toml(cfg))
        return ExitCode.SUCCESS
    exit_code = ExitCode.SUCCESS
    if mode is not Mode.CALIBRATE:
        # Each stage's diagnostics are logged as soon as it returns, so a load warning (W006)
        # is still shown when repair then fails.
        with stage("load"):
            mesh, loaded = io.load_stl(ns.input, cfg.model.scale)
        exit_code = max(exit_code, report_diagnostics(loaded))
        with stage("repair"):
            body, report = repair.prepare(mesh, cfg)
        LOGGER.info("%s", _model_summary(body, report))
        exit_code = max(exit_code, report_diagnostics(report.diagnostics))
        with stage("orientation"):
            body, orientation = grid.orient(body, cfg)
        with stage("grid"):
            layout, grid_diagnostics = grid.even_grid(grid.extent(body), config.derived(cfg).usable)
        LOGGER.info(
            "grid: %s = %d cells; rotation %s",
            " x ".join(str(n) for n in layout.counts),
            math.prod(layout.counts),
            orientation.name,
        )
        exit_code = max(exit_code, report_diagnostics(grid_diagnostics))
        if mode is Mode.DRY_RUN:
            sys.stdout.write(dry_run_report(orientation, layout))
    if mode is Mode.DRY_RUN:
        if "output" in ns:
            LOGGER.debug("-o is ignored with --dry-run: a dry run writes nothing")
    else:
        with stage("output directory"):
            io.prepare_output_dir(ns.output, force="force" in ns)
    LOGGER.warning(
        "the %s mode is not implemented yet (PLAN.md Phase 4 onwards); stopping here",
        mode.value,
    )
    return exit_code


def dry_run_report(orientation: Orientation, layout: Grid) -> str:
    """Return the plan the dry run prints on stdout (PLAN.md §7.1, Phase 3 task 7). ASCII only.

    It grows as phases land; Phase 3 prints the orientation and the grid. Numbers are rounded
    to 6 decimals, without trailing zeros (§4.1).

    Args:
        orientation: From ``grid.orient``.
        layout: From ``grid.even_grid``.

    Returns:
        The text, one item per line, ending with a newline.
    """
    matrix = orientation.input_to_cutting
    lines = [
        f"rotation: {orientation.name}; cutting (X, Y, Z) = input ({_axis_mapping(matrix)})",
        "input_to_cutting: "
        + ", ".join("[" + ", ".join(_number(v) for v in row) + "]" for row in matrix),
        f"extent: {_sizes(layout.extent)} mm",
        f"usable volume: {_sizes(layout.usable)} mm",
        f"cells: {' x '.join(str(n) for n in layout.counts)} = {math.prod(layout.counts)}",
    ]
    for name, planes in zip("XYZ", layout.planes, strict=True):
        offsets = ", ".join(_number(plane.offset) for plane in planes)
        lines.append(f"planes {name}: {offsets or 'none'}")
    return "\n".join(lines) + "\n"


def _axis_mapping(matrix: tuple[tuple[float, float, float, float], ...]) -> str:
    """Which signed input axis each cutting axis takes, e.g. ``+Z, +Y, -X``."""
    terms = []
    for row in matrix[:3]:
        axis = next(index for index in range(3) if row[index] != 0)
        terms.append(("+" if row[axis] > 0 else "-") + "XYZ"[axis])
    return ", ".join(terms)


def _sizes(values: Iterable[float]) -> str:
    return " x ".join(_number(value) for value in values)


def _number(value: float) -> str:
    """A float rounded to 6 decimals, without trailing zeros; never ``-0``."""
    # + 0.0 turns the -0.0 that round() gives for tiny negatives into 0.0.
    return f"{round(value, 6) + 0.0:.6f}".rstrip("0").rstrip(".")


def _model_summary(body: Manifold, report: repair.RepairReport) -> str:
    """One line about the repaired model, input frame (PLAN.md Phase 2, task 5). ASCII only."""
    box = body.bounding_box()
    low, high = box[:3], box[3:]
    size = " x ".join(f"{b - a:.6g}" for a, b in zip(low, high, strict=True))
    corner = ", ".join(f"{a:.6g}" for a in low)
    triangles = _plural(body.num_tri(), "triangle")
    bodies = _plural(report.bodies, "body", "bodies")
    return (
        f"model: {triangles}, {bodies}, {_plural(report.voids, 'void')}; "
        f"{size} mm from ({corner}); volume {report.reference_volume:.10g} mm^3; "
        f"repair: {'; '.join(report.steps) if report.steps else 'none'}"
    )


def _plural(number: int, singular: str, plural: str | None = None) -> str:
    return f"{number} {singular if number == 1 else plural or singular + 's'}"


def _describe_sources(ns: argparse.Namespace) -> str:
    sources = ["built-in defaults"]
    if "config" in ns:
        sources.append(str(ns.config))
    count = sum(1 for key in vars(ns) if key in _CONFIG_KEYS)
    if count:
        sources.append(f"{count} command-line option{'s' if count > 1 else ''}")
    return " <- ".join(sources)


def _read_config_file(path: Path) -> str:
    """Read the ``--config`` file: UTF-8 with or without a BOM, or UTF-16 with a BOM.

    TOML is UTF-8, but Windows editors add a UTF-8 BOM and PowerShell 5.1's ``>`` writes
    UTF-16, which is how many users will save ``--print-config`` output.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(f"--config {path}: can't read it ({exc.strerror})") from exc
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    encoding = "utf-16" if utf16 else "utf-8-sig"
    try:
        return data.decode(encoding)
    except UnicodeDecodeError as exc:
        name = "UTF-16" if utf16 else "UTF-8"
        raise InputError(f"--config {path}: not valid {name} text ({exc.reason})") from exc


def _option(
    group: argparse._ArgumentGroup, *flags: str, key: str, text: str, **kwargs: Any
) -> None:
    """Add a configuration option stored under its TOML key, with its default in the help."""
    group.add_argument(*flags, dest=key, help=f"{text} (default: {_default_text(key)})", **kwargs)


def _default_text(key: str) -> str:
    value = config.lookup(Config(), key)
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, tuple):
        return " ".join(f"{v:g}" for v in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _print_error(line: str, exc: BaseException, verbose: bool) -> None:
    """Print one line on stderr; with ``-v``, the traceback first."""
    if verbose:
        traceback.print_exception(exc, file=sys.stderr)
    print("stlsplit: " + " ".join(line.splitlines()), file=sys.stderr)


class _StderrHandler(logging.Handler):
    """Write log lines to the ``sys.stderr`` of the moment (tests replace it between runs)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


class _Formatter(logging.Formatter):
    """Info lines as they are; other levels prefixed with their name (``warning: ...``)."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno == logging.INFO:
            return message
        return f"{record.levelname.lower()}: {message}"
