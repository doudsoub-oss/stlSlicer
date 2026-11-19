"""Configuration: defaults, TOML loading, validation and derived values.

Comes before every stage of the pipeline (PLAN.md §5.1). The CLI builds one validated
``Config`` (built-in defaults ← TOML file ← options typed on the command line; §7.4,
ADR-0011), and every stage reads its numbers from it or from ``derived(cfg)``. This module is
the single home of the numbers in PLAN.md §6: named constants, defaults and formulas live here
and nowhere else.

Pure: TOML arrives as text, never as a path (only ``io`` and ``cli`` touch the file system).
The one rule that needs the file system, "``advanced.label_font`` resolves to an existing
file", is checked by ``io.resolve_label_font``.

Guarantees:
- ``parse_toml``, ``from_mapping`` and ``with_overrides`` reject unknown tables and keys and
  return values of the declared types (TOML integers become floats where floats are declared).
- ``validate`` enforces every rule of §7.5, plus the additions recorded in PLAN.md Appendix E
  (r4).
- ``to_toml`` output reads back into an equal ``Config``.
"""

import itertools
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any, Literal, get_args, get_origin, get_type_hints

from stlsplit.errors import ConfigError, InputError

# --- Named constants (PLAN.md §6.1). Not user options: change them here only. ----------------

POLYLABEL_TOLERANCE = 1e-3
"""Tolerance of the polylabel point used to sort regions, mm (§4.3).

It only orders regions, so it needs to separate distinct regions, not locate the point
precisely.
"""

RAY_START_OFFSET = 0.01
"""ε_ray: rays start this far inside a piece, mm, so the face they leave isn't hit (§6.1)."""

CANDIDATE_GRID_DIVISOR = 4
"""g = d / this: step of the connector candidate grid (§6.1)."""

ISLAND_AREA_FACTOR = 4.0
"""island = factor · π · (d/2)²: cut regions smaller than this are tiny islands (§6.1)."""

CALIBRATION_MIN_WALL = 3.0
"""w_cal = max(w, this), mm: the wall used in the calibration kit (§6.3)."""

LENGTH_TOLERANCE = 1e-9
"""Slack when comparing a pin length to L_min, mm.

Without it, float rounding in L_max − k·Δ can drop a standard length equal to L_min (for
example 16 − 64 × 0.1 < 3.2 × 3 in floats).
"""

GRID_TOLERANCE = 1e-9
"""Relative slack of the even grid (Phase 3), dimensionless.

Cells per axis: ``n = max(1, ceil(extent / U − GRID_TOLERANCE))``, so float noise in an
extent that is an exact multiple of U doesn't add a cell. A cell can then exceed U by up to
this fraction of U (0.2 nm at U = 210), so a cell fits when ``size ≤ U · (1 + GRID_TOLERANCE)``
(PLAN.md Appendix E, r6).
"""

SCALE_WARNING_MIN = 1.0
"""W006 when the model's largest dimension is below this, mm (§4.5): probably not in mm."""
SCALE_WARNING_MAX = 5000.0
"""W006 when the model's largest dimension is above this, mm (§4.5): probably not in mm."""

VOID_RESIDUAL_FRACTION = 1e-6
"""Shell normalization (Phase 2, ADR-0007): an inside-out shell F is a void when
``(F − union of the solids).volume() ≤ this · F.volume()``, i.e. F lies inside the solids.
The same test decides whether a solid lies inside a void."""
SHELL_OVERLAP_FRACTION = 1e-6
"""W010 when the union of the solids is smaller than the sum of their volumes by more than
this fraction (Phase 2): boolean round-off stays far below it, a real overlap far above."""

TOML_INT_MIN = -(2**63)
TOML_INT_MAX = 2**63 - 1
"""Integer range of the TOML spec; ``tomllib`` accepts any size, so it is checked here."""

# Validation bounds (§7.5).
MIN_CIRCULAR_SEGMENTS = 16
MAX_CIRCULAR_SEGMENTS = 256
"""At 256 segments, a 5.4 mm hole's polygon is within 0.0002 mm of its circle, far below print
resolution; more segments only multiply the triangles of every hole (PLAN.md Appendix E, r4)."""
MIN_PIN_LENGTH_STEP = 0.1
"""mm. Bounds the number of standard pin lengths, (L_max − L_min) / Δ + 1 (PLAN.md Appendix E,
r4): a tiny step made ``derived()`` build millions of lengths."""
MAX_SECTION_EPSILON = 0.1
MAX_CALIBRATION_CLEARANCES = 10
PIN_FLAT_DIVISOR = 4
"""``pin_flat`` < d / this: a deeper flat would eat too much of the pin."""
PIN_CHAMFER_DIVISOR = 4
"""``pin_chamfer`` < L_min / this."""
HOLE_CHAMFER_DIVISOR = 2
"""``hole_chamfer`` ≤ w / this."""

ConnectorType = Literal["dowel", "peg", "none"]
CONNECTOR_TYPES: tuple[str, ...] = get_args(ConnectorType)


# --- Settings, one dataclass per TOML table (PLAN.md §7.2, §7.3) ----------------------------


@dataclass(frozen=True)
class PrinterConfig:
    """``[printer]``.

    Attributes:
        bed: Build volume (X, Y, Z), mm.
        margin: Kept free on each side of every axis, mm: U = bed − 2·margin.
    """

    bed: tuple[float, float, float] = (220.0, 220.0, 250.0)
    margin: float = 5.0


@dataclass(frozen=True)
class ModelConfig:
    """``[model]``.

    Attributes:
        scale: Uniform scale applied after loading.
        auto_orient: Try the 6 axis orders and keep the one with the fewest cells.
        simplify: ``Manifold.simplify`` tolerance, mm; 0 turns it off.
    """

    scale: float = 1.0
    auto_orient: bool = True
    simplify: float = 0.0


@dataclass(frozen=True)
class RepairConfig:
    """``[repair]``.

    Attributes:
        deep: Use the pymeshlab fallback when basic repair fails (extra ``deep-repair``).
    """

    deep: bool = False


@dataclass(frozen=True)
class ConnectorsConfig:
    """``[connectors]``.

    Attributes:
        type: ``dowel``, ``peg`` or ``none`` (ADR-0005).
        diameter: d, pin diameter, mm.
        length: L_max, the exact length of a full pin, mm (§6.2).
        clearance: c, radial clearance added to holes, mm.
        min_wall: w, minimum material around and between holes, mm.
        max_per_face: k_max, maximum connectors per cut face.
    """

    type: ConnectorType = "dowel"
    diameter: float = 5.0
    length: float = 20.0
    clearance: float = 0.2
    min_wall: float = 2.0
    max_per_face: int = 4


@dataclass(frozen=True)
class LabelsConfig:
    """``[labels]``.

    Attributes:
        enabled: Engrave piece IDs.
        depth: t_lab, engraving depth, mm.
    """

    enabled: bool = True
    depth: float = 0.6


@dataclass(frozen=True)
class OutputConfig:
    """``[output]``.

    Attributes:
        preview: Write ``preview_exploded.glb``.
    """

    preview: bool = True


@dataclass(frozen=True)
class AdvancedConfig:
    """``[advanced]``, TOML only. Every value appears in PLAN.md §6.

    Attributes:
        axial_play: a, hole depth beyond the pin end on each side, mm.
        pin_length_step: Δ, step between standard pin lengths, mm.
        pin_min_length_factor: L_min = factor · d.
        pin_chamfer: ch_p, pin and peg end chamfer, mm.
        pin_flat: f, depth of the flat pins are printed on, mm (0 = round pins).
        hole_chamfer: ch_h, hole mouth chamfer, mm.
        circular_segments: n_seg, segments per circle.
        connector_spacing_factor: s_min = factor · d.
        connector_area_factor: A = (factor · d)², face area per connector.
        section_epsilon: ε, half-thickness of the section probe, mm (ADR-0002).
        nudge_window: W_n, how far a plane may be nudged, mm (0 disables nudging).
        nudge_step: δ_n, nudge step, mm.
        small_piece_volume: V_small, mm³ (0 disables merging).
        label_font: A font bundled with matplotlib, or an absolute path (ADR-0009).
        label_min_height: H_min, mm.
        label_max_height: H_max, mm.
        calibration_clearances: Clearances of the calibration kit, mm, increasing.
        preview_spread: Exploded-view offset per grid step, as a fraction of the model size.
    """

    axial_play: float = 0.5
    pin_length_step: float = 2.0
    pin_min_length_factor: float = 3.0
    pin_chamfer: float = 0.5
    pin_flat: float = 0.4
    hole_chamfer: float = 0.4
    circular_segments: int = 64
    connector_spacing_factor: float = 3.0
    connector_area_factor: float = 6.0
    section_epsilon: float = 0.01
    nudge_window: float = 5.0
    nudge_step: float = 0.5
    small_piece_volume: float = 500.0
    label_font: str = "DejaVuSans-Bold.ttf"
    label_min_height: float = 4.0
    label_max_height: float = 12.0
    calibration_clearances: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30)
    preview_spread: float = 0.15


@dataclass(frozen=True)
class Config:
    """The whole configuration; each field is one TOML table, in the order ``to_toml`` writes.

    Build it with ``Config()`` for the defaults, or with ``parse_toml`` and ``with_overrides``;
    then call ``validate`` before using it.
    """

    printer: PrinterConfig = field(default_factory=PrinterConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    repair: RepairConfig = field(default_factory=RepairConfig)
    connectors: ConnectorsConfig = field(default_factory=ConnectorsConfig)
    labels: LabelsConfig = field(default_factory=LabelsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)


# Field types per table, in declaration order: drives key listing, coercion and TOML output.
_TABLE_CLASSES: dict[str, Any] = get_type_hints(Config)
_FIELD_TYPES: dict[str, dict[str, Any]] = {
    name: {f.name: get_type_hints(cls)[f.name] for f in fields(cls)}
    for name, cls in _TABLE_CLASSES.items()
}


def keys() -> tuple[str, ...]:
    """Return every configuration key as ``"table.key"``, in table and declaration order."""
    return tuple(f"{table}.{name}" for table, names in _FIELD_TYPES.items() for name in names)


def lookup(cfg: Config, key: str) -> Any:
    """Return the value of one dotted key, e.g. ``lookup(cfg, "printer.bed")``.

    Args:
        cfg: The configuration.
        key: A key from ``keys()``.

    Returns:
        The value, of the field's declared type.

    Raises:
        ConfigError: ``key`` is not a configuration key.
    """
    table, name = _split_key(key)
    return getattr(getattr(cfg, table), name)


# --- Loading and merging ---------------------------------------------------------------------


def parse_toml(text: str, source: str) -> Config:
    """Parse a TOML configuration on top of the built-in defaults.

    Args:
        text: TOML document.
        source: Where the text comes from, for messages (the file name as given).

    Returns:
        The defaults with the document's values applied. Not validated yet.

    Raises:
        InputError: The text is not valid TOML.
        ConfigError: Unknown table or key, or a value of the wrong type.
    """
    try:
        data = tomllib.loads(text)
    except ValueError as exc:
        # TOMLDecodeError is a ValueError; tomllib also raises a plain ValueError for an
        # integer over Python's 4300-digit conversion limit.
        raise InputError(f"{source}: invalid TOML: {exc}") from exc
    return from_mapping(data, source)


def from_mapping(data: Mapping[str, Any], source: str) -> Config:
    """Apply a parsed TOML document (tables of keys) on top of the built-in defaults.

    Args:
        data: The document, as ``tomllib`` returns it.
        source: Where it comes from, for messages.

    Returns:
        The resulting configuration. Not validated yet.

    Raises:
        ConfigError: Unknown table or key (the first one in document order), a table that
            isn't a table, or a value of the wrong type.
    """
    overrides: dict[str, Any] = {}
    for table, values in data.items():
        if table not in _FIELD_TYPES:
            known = ", ".join(_FIELD_TYPES)
            raise ConfigError(table, f"unknown table in {source}; the tables are: {known}")
        if not isinstance(values, Mapping):
            raise ConfigError(table, f"must be a table, [{table}], got {_show(values)}")
        for name, value in values.items():
            if name not in _FIELD_TYPES[table]:
                known = ", ".join(_FIELD_TYPES[table])
                raise ConfigError(
                    f"{table}.{name}",
                    f"unknown key in {source}; the keys of [{table}] are: {known}",
                )
            overrides[f"{table}.{name}"] = value
    return with_overrides(Config(), overrides, source)


def with_overrides(cfg: Config, overrides: Mapping[str, Any], source: str) -> Config:
    """Return ``cfg`` with some values replaced.

    Args:
        cfg: The configuration to start from.
        overrides: New values by dotted key (``"connectors.clearance": 0.25``).
        source: Where the values come from, for messages.

    Returns:
        A new configuration. Not validated yet.

    Raises:
        ConfigError: Unknown key or a value of the wrong type.
    """
    changes: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        table, name = _split_key(key)
        changes.setdefault(table, {})[name] = _coerce(value, _FIELD_TYPES[table][name], key, source)
    return replace(
        cfg, **{table: replace(getattr(cfg, table), **values) for table, values in changes.items()}
    )


# --- Validation (PLAN.md §7.5) ---------------------------------------------------------------


def validate(cfg: Config) -> None:
    """Check every rule of PLAN.md §7.5 except the label-font file check.

    Rules run in a fixed order and the first failure is raised, so a rule may assume that the
    ones before it hold. The font check is ``io.resolve_label_font``.

    Args:
        cfg: The configuration to check.

    Raises:
        ConfigError: A rule fails. The message gives the allowed range and the value found.
    """
    _check_finite(cfg)
    p, m, c, lab, adv = cfg.printer, cfg.model, cfg.connectors, cfg.labels, cfg.advanced
    l_min = _pin_min_length(cfg)

    _check(all(v > 0 for v in p.bed), "printer.bed", "every value must be > 0", p.bed)
    _check(p.margin >= 0, "printer.margin", "must be >= 0", p.margin)
    half_bed = min(p.bed) / 2
    _check(
        p.margin < half_bed,
        "printer.margin",
        f"must be < half the smallest bed dimension ({_show(half_bed)})",
        p.margin,
    )
    _check(m.scale > 0, "model.scale", "must be > 0", m.scale)
    _check(m.simplify >= 0, "model.simplify", "must be >= 0", m.simplify)

    _check(c.diameter > 0, "connectors.diameter", "must be > 0", c.diameter)
    _check(c.clearance >= 0, "connectors.clearance", "must be >= 0", c.clearance)
    _check(c.min_wall > 0, "connectors.min_wall", "must be > 0", c.min_wall)
    _check(c.max_per_face >= 1, "connectors.max_per_face", "must be >= 1", c.max_per_face)
    _check(
        adv.pin_min_length_factor > 0,
        "advanced.pin_min_length_factor",
        "must be > 0",
        adv.pin_min_length_factor,
    )
    _check(
        c.length >= l_min - LENGTH_TOLERANCE,
        "connectors.length",
        f"must be >= L_min = pin_min_length_factor x diameter = {_show(l_min)}",
        c.length,
    )
    _check(lab.depth > 0, "labels.depth", "must be > 0", lab.depth)
    _check(
        lab.depth < c.min_wall,
        "labels.depth",
        f"must be < connectors.min_wall ({_show(c.min_wall)})",
        lab.depth,
    )
    if c.type == "peg":
        smallest = min(_usable_without_pegs(cfg))
        _check(
            c.length / 2 < smallest,
            "connectors.length",
            "in peg mode, length / 2 (the peg protrusion) must be < the smallest usable size, "
            f"bed - 2 x margin ({_show(smallest)})",
            c.length,
        )

    _check(adv.axial_play >= 0, "advanced.axial_play", "must be >= 0", adv.axial_play)
    _check(
        adv.pin_length_step >= MIN_PIN_LENGTH_STEP,
        "advanced.pin_length_step",
        f"must be >= {_show(MIN_PIN_LENGTH_STEP)}",
        adv.pin_length_step,
    )
    _check(adv.pin_flat >= 0, "advanced.pin_flat", "must be >= 0", adv.pin_flat)
    flat_max = c.diameter / PIN_FLAT_DIVISOR
    _check(
        adv.pin_flat < flat_max,
        "advanced.pin_flat",
        f"must be < connectors.diameter / {PIN_FLAT_DIVISOR} ({_show(flat_max)})",
        adv.pin_flat,
    )
    _check(adv.pin_chamfer >= 0, "advanced.pin_chamfer", "must be >= 0", adv.pin_chamfer)
    chamfer_max = l_min / PIN_CHAMFER_DIVISOR
    _check(
        adv.pin_chamfer < chamfer_max,
        "advanced.pin_chamfer",
        f"must be < L_min / {PIN_CHAMFER_DIVISOR} ({_show(chamfer_max)})",
        adv.pin_chamfer,
    )
    _check(adv.hole_chamfer >= 0, "advanced.hole_chamfer", "must be >= 0", adv.hole_chamfer)
    hole_chamfer_max = c.min_wall / HOLE_CHAMFER_DIVISOR
    _check(
        adv.hole_chamfer <= hole_chamfer_max,
        "advanced.hole_chamfer",
        f"must be <= connectors.min_wall / {HOLE_CHAMFER_DIVISOR} ({_show(hole_chamfer_max)})",
        adv.hole_chamfer,
    )
    _check(
        MIN_CIRCULAR_SEGMENTS <= adv.circular_segments <= MAX_CIRCULAR_SEGMENTS,
        "advanced.circular_segments",
        f"must be >= {MIN_CIRCULAR_SEGMENTS} and <= {MAX_CIRCULAR_SEGMENTS}",
        adv.circular_segments,
    )
    _check(
        adv.connector_spacing_factor > 0,
        "advanced.connector_spacing_factor",
        "must be > 0",
        adv.connector_spacing_factor,
    )
    _check(
        adv.connector_area_factor > 0,
        "advanced.connector_area_factor",
        "must be > 0",
        adv.connector_area_factor,
    )
    _check(adv.section_epsilon > 0, "advanced.section_epsilon", "must be > 0", adv.section_epsilon)
    _check(
        adv.section_epsilon <= MAX_SECTION_EPSILON,
        "advanced.section_epsilon",
        f"must be <= {_show(MAX_SECTION_EPSILON)}",
        adv.section_epsilon,
    )
    _check(adv.nudge_window >= 0, "advanced.nudge_window", "must be >= 0", adv.nudge_window)
    _check(adv.nudge_step > 0, "advanced.nudge_step", "must be > 0", adv.nudge_step)
    _check(
        adv.small_piece_volume >= 0,
        "advanced.small_piece_volume",
        "must be >= 0",
        adv.small_piece_volume,
    )
    _check(
        adv.label_min_height > 0, "advanced.label_min_height", "must be > 0", adv.label_min_height
    )
    _check(
        adv.label_min_height <= adv.label_max_height,
        "advanced.label_min_height",
        f"must be <= advanced.label_max_height ({_show(adv.label_max_height)})",
        adv.label_min_height,
    )
    clearances = adv.calibration_clearances
    _check(
        1 <= len(clearances) <= MAX_CALIBRATION_CLEARANCES,
        "advanced.calibration_clearances",
        f"must have 1 to {MAX_CALIBRATION_CLEARANCES} values",
        clearances,
    )
    _check(
        all(v >= 0 for v in clearances),
        "advanced.calibration_clearances",
        "every value must be >= 0",
        clearances,
    )
    _check(
        all(a < b for a, b in itertools.pairwise(clearances)),
        "advanced.calibration_clearances",
        "must be in strictly increasing order",
        clearances,
    )
    _check(adv.preview_spread >= 0, "advanced.preview_spread", "must be >= 0", adv.preview_spread)


# --- Derived values (PLAN.md §6.1, §6.3) -----------------------------------------------------


@dataclass(frozen=True)
class CalibrationDims:
    """Dimensions of the calibration kit (PLAN.md §6.3), mm.

    Attributes:
        max_clearance: c_max, the largest clearance tested.
        hole_outer: Hole diameter at the mouth, chamfer included: d + 2·c_max + 2·ch_h.
        wall: w_cal = max(w, ``CALIBRATION_MIN_WALL``).
        hole_count: n_cal, one hole per clearance.
        pitch: Distance between hole centres: hole_outer + w_cal.
        length: Bar length: n_cal·hole_outer + (n_cal + 1)·w_cal.
        width: Bar width: hole_outer + 2·w_cal.
        thickness: Bar thickness: h(L_max) + w_cal.
    """

    max_clearance: float
    hole_outer: float
    wall: float
    hole_count: int
    pitch: float
    length: float
    width: float
    thickness: float


@dataclass(frozen=True)
class Derived:
    """Every value PLAN.md §6 derives from the configuration; build it with ``derived``.

    Attributes:
        usable: U per axis (X, Y, Z), mm: bed − 2·m, minus p in peg mode.
        pin_min_length: L_min = ``pin_min_length_factor`` · d, mm.
        standard_lengths: The standard pin lengths {L_max − k·Δ ≥ L_min}, longest first, mm.
        hole_depths: h(L) for each standard length, same order, mm.
        peg_protrusion: p = L_max / 2, mm.
        hole_radius: r_h = d/2 + c, mm.
        hole_radius_model: r_model = r_h / cos(π / n_seg), mm: polygon flats sit at r_h.
        inset: w + r_h + ch_h, mm: inset of a cut region to get its safe region.
        candidate_step: g = d / ``CANDIDATE_GRID_DIVISOR``, mm.
        connector_spacing: s_min = ``connector_spacing_factor`` · d, mm.
        area_per_connector: A = (``connector_area_factor`` · d)², mm².
        island_area: ``ISLAND_AREA_FACTOR`` · π · (d/2)², mm².
        label_keep_out: r_h + ch_h + w, mm: label keep-out radius around a connector.
        calibration: The calibration kit dimensions (§6.3).
    """

    usable: tuple[float, float, float]
    pin_min_length: float
    standard_lengths: tuple[float, ...]
    hole_depths: tuple[float, ...]
    peg_protrusion: float
    hole_radius: float
    hole_radius_model: float
    inset: float
    candidate_step: float
    connector_spacing: float
    area_per_connector: float
    island_area: float
    label_keep_out: float
    calibration: CalibrationDims


def hole_depth(cfg: Config, length: float) -> float:
    """Return h(L) = L/2 + a, the depth of each hole for a pin of length L (PLAN.md §6.2).

    Args:
        cfg: The configuration (gives a, ``advanced.axial_play``).
        length: Pin length L, mm.

    Returns:
        The hole depth on each side of the face, mm.
    """
    return length / 2 + cfg.advanced.axial_play


def derived(cfg: Config) -> Derived:
    """Compute every derived value of PLAN.md §6 in one place.

    Args:
        cfg: A configuration that passed ``validate``.

    Returns:
        The derived values.

    Raises:
        ValueError: ``cfg`` breaks a rule ``validate`` checks (a bug in the caller).
    """
    c, adv = cfg.connectors, cfg.advanced
    l_min = _pin_min_length(cfg)
    lengths = _standard_lengths(c.length, adv.pin_length_step, l_min)
    protrusion = c.length / 2
    ux, uy, uz = _usable_without_pegs(cfg)
    usable = (
        (ux - protrusion, uy - protrusion, uz - protrusion) if c.type == "peg" else (ux, uy, uz)
    )
    hole_radius = c.diameter / 2 + c.clearance

    clearances = adv.calibration_clearances
    if not clearances:
        raise ValueError("advanced.calibration_clearances is empty; validate the config first")
    max_clearance = max(clearances)
    hole_outer = c.diameter + 2 * max_clearance + 2 * adv.hole_chamfer
    wall = max(c.min_wall, CALIBRATION_MIN_WALL)
    count = len(clearances)
    calibration = CalibrationDims(
        max_clearance=max_clearance,
        hole_outer=hole_outer,
        wall=wall,
        hole_count=count,
        pitch=hole_outer + wall,
        length=count * hole_outer + (count + 1) * wall,
        width=hole_outer + 2 * wall,
        thickness=hole_depth(cfg, c.length) + wall,
    )

    return Derived(
        usable=usable,
        pin_min_length=l_min,
        standard_lengths=lengths,
        hole_depths=tuple(hole_depth(cfg, length) for length in lengths),
        peg_protrusion=protrusion,
        hole_radius=hole_radius,
        hole_radius_model=hole_radius / math.cos(math.pi / adv.circular_segments),
        inset=c.min_wall + hole_radius + adv.hole_chamfer,
        candidate_step=c.diameter / CANDIDATE_GRID_DIVISOR,
        connector_spacing=adv.connector_spacing_factor * c.diameter,
        area_per_connector=(adv.connector_area_factor * c.diameter) ** 2,
        island_area=ISLAND_AREA_FACTOR * math.pi * (c.diameter / 2) ** 2,
        label_keep_out=hole_radius + adv.hole_chamfer + c.min_wall,
        calibration=calibration,
    )


# --- Printing (``--print-config``) -----------------------------------------------------------


def to_toml(cfg: Config) -> str:
    r"""Return the configuration as a TOML document that ``parse_toml`` reads back exactly.

    Every table and key is written, in declaration order. Floats use ``repr``, the shortest
    text that reads back to the same float. The text is pure ASCII (other characters become
    ``\u`` escapes), so it survives a console that doesn't use UTF-8, such as a redirected
    stdout on Windows.

    Args:
        cfg: The configuration.

    Returns:
        The TOML text, ending with a newline.
    """
    lines: list[str] = []
    for table, names in _FIELD_TYPES.items():
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        section = getattr(cfg, table)
        lines.extend(f"{name} = {_toml_value(getattr(section, name))}" for name in names)
    return "\n".join(lines) + "\n"


# --- Helpers ---------------------------------------------------------------------------------

_TOML_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}
_ASCII_PRINTABLE_START = 0x20
_ASCII_DELETE = 0x7F
_BMP_END = 0xFFFF


def _split_key(key: str) -> tuple[str, str]:
    table, _, name = key.partition(".")
    if name not in _FIELD_TYPES.get(table, {}):
        raise ConfigError(key, "unknown configuration key")
    return table, name


def _describe(hint: Any) -> str:
    if hint is bool:
        return "true or false"
    if hint is int:
        return "an integer"
    if hint is float:
        return "a number"
    if hint is str:
        return "a string"
    if get_origin(hint) is Literal:
        return "one of " + ", ".join(f'"{choice}"' for choice in get_args(hint))
    args = get_args(hint)
    if len(args) == 2 and args[1] is Ellipsis:
        return f"an array, each value {_describe(args[0])}"
    return f"an array of {len(args)} values, each {_describe(args[0])}"


def _coerce(value: Any, hint: Any, key: str, source: str) -> Any:
    ok: bool
    if hint is bool:
        ok = isinstance(value, bool)
    elif hint is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        if ok and not TOML_INT_MIN <= value <= TOML_INT_MAX:
            raise ConfigError(
                key,
                f"must be an integer that fits in 64 bits, got {_describe_big(value)} "
                f"(from {source})",
            )
    elif hint is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        if ok:
            try:
                value = float(value)
            except OverflowError:  # an integer too large for a float
                raise ConfigError(
                    key, f"must be a finite number, got {_describe_big(value)} (from {source})"
                ) from None
    elif hint is str:
        ok = isinstance(value, str)
    elif get_origin(hint) is Literal:
        ok = isinstance(value, str) and value in get_args(hint)
    elif get_origin(hint) is tuple:
        args = get_args(hint)
        variadic = len(args) == 2 and args[1] is Ellipsis
        ok = isinstance(value, list | tuple) and (variadic or len(value) == len(args))
        if ok:
            element_types = itertools.repeat(args[0]) if variadic else iter(args)
            return tuple(
                _coerce(v, t, key, source) for v, t in zip(value, element_types, strict=False)
            )
    else:
        raise TypeError(f"{key}: unsupported field type {hint!r}")
    if not ok:
        raise ConfigError(key, f"must be {_describe(hint)}, got {_show(value)} (from {source})")
    return value


def _describe_big(value: int) -> str:
    # Never in decimal: Python refuses to convert integers over 4300 digits to text.
    return f"an integer of {value.bit_length()} bits"


def _check(ok: bool, key: str, rule: str, value: object) -> None:
    if not ok:
        raise ConfigError(key, f"{rule}, got {_show(value)}")


def _check_finite(cfg: Config) -> None:
    for key in keys():
        value = lookup(cfg, key)
        numbers = value if isinstance(value, tuple) else (value,)
        if any(isinstance(v, float) and not math.isfinite(v) for v in numbers):
            raise ConfigError(key, f"must be a finite number, got {_show(value)}")


def _pin_min_length(cfg: Config) -> float:
    return cfg.advanced.pin_min_length_factor * cfg.connectors.diameter


def _usable_without_pegs(cfg: Config) -> tuple[float, float, float]:
    bx, by, bz = cfg.printer.bed
    margin = cfg.printer.margin
    return (bx - 2 * margin, by - 2 * margin, bz - 2 * margin)


def _standard_lengths(l_max: float, step: float, l_min: float) -> tuple[float, ...]:
    if step <= 0:
        raise ValueError("advanced.pin_length_step must be > 0; validate the config first")
    lengths: list[float] = []
    k = 0
    while (length := l_max - k * step) >= l_min - LENGTH_TOLERANCE:
        lengths.append(length)
        k += 1
    return tuple(lengths)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, tuple | list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"no TOML form for {value!r}")


def _toml_string(text: str) -> str:
    out: list[str] = []
    for char in text:
        if char in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[char])
        elif _ASCII_PRINTABLE_START <= ord(char) < _ASCII_DELETE:
            out.append(char)
        elif ord(char) <= _BMP_END:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(f"\\U{ord(char):08X}")
    return '"' + "".join(out) + '"'


def _show(value: object) -> str:
    """Format a value for a message: as TOML when possible, else ``repr``."""
    try:
        return _toml_value(value)
    except TypeError:
        return repr(value)
