"""The calibration kit: a bar of holes of increasing clearance, and the pin to test them.

Not part of the split pipeline: ``stlsplit --calibrate`` runs it on its own (PLAN.md §7.1,
Phase 7, task 6; dimensions in §6.3). ``build_kit`` takes the configuration and a font file
and returns the solids and the README's text; ``cli`` and ``io`` write them.

The holes sit in a row, centred across the bar's width, so a second identical bar, turned half
a turn about its long axis and laid on the first, lines up hole for hole with the same
clearances. Each hole's code, its clearance in hundredths of a millimetre, is engraved on the
long side face y = 0, under the hole.

Pure and deterministic, except for matplotlib reading the font (``labels``).
"""

import math
from pathlib import Path
from typing import NamedTuple

import numpy as np
from manifold3d import Error, Manifold

from stlsplit import config, geometry, labels, tools
from stlsplit.config import (
    CALIBRATION_CODE_DECIMALS,
    CALIBRATION_CODE_GAP,
    CUTTER_PAD,
    LENGTH_TOLERANCE,
    TOOL_OVERLAP,
    CalibrationDims,
    Config,
)
from stlsplit.errors import ConfigError

BLOCK_FILE = "calibration/block.stl"
README_FILE = "calibration/README.md"
BLOCKS_TO_PRINT = 2
"""Two identical bars: a pin can then be tested in one hole, and as a full joint."""

_HUNDREDTHS_PER_MM = 100

_SIDE_FACE = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64
)
"""Proper rotation (3×4) from text coordinates to the side face y = 0: text x along +X, text y
along +Z and the extrusion along −Y, so the text reads correctly from outside the face."""


class Kit(NamedTuple):
    """The calibration kit.

    Attributes:
        block: One bar, its bounding-box minimum at the origin, holes opening towards +Z.
        pin: One pin of the full length, lying on its flat.
        pin_file: Its path in the output directory, ``calibration/pin_d{d:.1f}_l{L:.1f}.stl``.
        pin_count: How many pins to print: one per hole.
        codes: The code of each hole, in hole order.
        code_height: Height of the engraved codes, mm: H_min, or less if they wouldn't fit.
        readme: The text of ``calibration/README.md``.
    """

    block: Manifold
    pin: Manifold
    pin_file: str
    pin_count: int
    codes: tuple[str, ...]
    code_height: float
    readme: str


def build_kit(cfg: Config, font: Path) -> Kit:
    """Build the calibration kit (PLAN.md §6.3).

    Args:
        cfg: The configuration (connector options, ``calibration_clearances``, labels).
        font: The font file (``io.resolve_label_font``).

    Returns:
        The kit.

    Raises:
        ConfigError: The bar doesn't fit the printer, an engraving would reach a hole, two
            holes would touch, or two clearances would be engraved with the same code.
        AssertionError: The bar isn't one valid body (a bug).
    """
    cal = config.derived(cfg).calibration
    _check_kit(cfg, cal)
    clearances = cfg.advanced.calibration_clearances
    codes = tuple(code_text(clearance) for clearance in clearances)
    if len(set(codes)) != len(codes):
        raise ConfigError(
            "advanced.calibration_clearances",
            f"two values would get the same engraved code ({', '.join(codes)}): they must "
            f"differ by at least {10.0 ** -(CALIBRATION_CODE_DECIMALS + 2):g} mm",
        )
    height = _code_height(codes, cal, cfg, font)
    block = _bar(cfg, cal, codes, height, font)
    if block.status() != Error.NoError or len(block.decompose()) != 1:
        raise AssertionError("the calibration bar is not one valid body")
    diameter, length = cfg.connectors.diameter, cfg.connectors.length
    pin_file = f"calibration/pin_d{diameter:.1f}_l{length:.1f}.stl"
    return Kit(
        block=block,
        pin=tools.pin_solid(diameter, length, cfg),
        pin_file=pin_file,
        pin_count=len(clearances),
        codes=codes,
        code_height=height,
        readme=readme_text(cfg, codes, pin_file.rsplit("/", 1)[1]),
    )


def _check_kit(cfg: Config, cal: CalibrationDims) -> None:
    """Refuse a kit that can't be printed or whose walls don't hold (r10).

    The bar lies with its holes vertical and may be turned a quarter turn on the plate. §6.3
    sizes the walls from the nominal hole diameter, but the polygon's vertices reach
    r / cos(π / n), so the walls are measured from there.
    """
    long_side, short_side = sorted(config.derived(cfg).printable[:2], reverse=True)
    height = config.derived(cfg).printable[2]
    if (
        cal.length > long_side + LENGTH_TOLERANCE
        or cal.width > short_side + LENGTH_TOLERANCE
        or cal.thickness > height + LENGTH_TOLERANCE
    ):
        raise ConfigError(
            "printer.bed",
            f"the calibration bar is {cal.length:.6g} x {cal.width:.6g} x {cal.thickness:.6g} "
            f"mm, which doesn't fit the printable {long_side:.6g} x {short_side:.6g} x "
            f"{height:.6g} mm",
        )
    nominal = cfg.connectors.diameter / 2 + cal.max_clearance + cfg.advanced.hole_chamfer
    reach = nominal / math.cos(math.pi / cfg.advanced.circular_segments)
    side_wall = cal.width / 2 - reach
    if cfg.labels.depth >= side_wall:
        raise ConfigError(
            "labels.depth",
            f"must be < {side_wall:.6g} mm for the calibration kit, the wall between the bar's "
            f"side and its widest hole, got {cfg.labels.depth:.6g}",
        )
    if cal.hole_count > 1 and cal.pitch <= 2 * reach:
        raise ConfigError(
            "advanced.circular_segments",
            f"the calibration kit's holes would touch at {cfg.advanced.circular_segments} "
            "segments: use more segments or a larger connectors.min_wall",
        )


def code_text(clearance: float) -> str:
    """Return a clearance's code: hundredths of a millimetre, without trailing zeros.

    Args:
        clearance: Radial clearance, mm.

    Returns:
        ``"20"`` for 0.20, ``"12.3"`` for 0.123, up to ``CALIBRATION_CODE_DECIMALS`` decimals.
    """
    text = f"{clearance * _HUNDREDTHS_PER_MM:.{CALIBRATION_CODE_DECIMALS}f}"
    return text.rstrip("0").rstrip(".")


def hole_position(cal: CalibrationDims, index: int) -> float:
    """Return the X of a hole's axis, mm: w_cal + hole_outer / 2 + index · pitch (§6.3)."""
    return cal.wall + cal.hole_outer / 2 + index * cal.pitch


def readme_text(cfg: Config, codes: tuple[str, ...], pin_name: str) -> str:
    """Return the kit's README: how to print, test, read the codes and choose.

    Args:
        cfg: The configuration.
        codes: The codes, in hole order.
        pin_name: The pin's file name.

    Returns:
        Markdown text, ending with a newline, with no date or path.
    """
    clearances = cfg.advanced.calibration_clearances
    rows = "\n".join(
        f"| {code} | {clearance:g} |" for code, clearance in zip(codes, clearances, strict=True)
    )
    return f"""# Calibration kit

Print this kit once to find the hole clearance that suits your printer and filament.

## Print

- `block.stl`: print {BLOCKS_TO_PRINT}, lying on the large face, with the holes vertical.
- `{pin_name}`: print {len(codes)} (one per hole), lying on the flat side.
- Use the material and settings you will use for the real pieces.

## Test

1. Push a pin into each hole of one block, by hand. The right fit goes in with firm thumb
   pressure and doesn't wobble.
2. To test a full joint, turn the second block half a turn about its long axis and lay it on
   the first: matching holes face each other, with the same clearance.

## Read the codes

Each hole's code is engraved on the long side, under the hole. It is the radial clearance in
hundredths of a millimetre:

| Code | Clearance (mm) |
|---|---|
{rows}

## Choose

Take the tightest hole that fits as described, and pass its clearance to stlsplit:

```bash
stlsplit model.stl -o out --clearance <clearance in mm>
```

These holes print vertically. Horizontal holes print tighter, so if most holes in your real
pieces will be horizontal, pick one step looser.
"""


def _code_height(codes: tuple[str, ...], cal: CalibrationDims, cfg: Config, font: Path) -> float:
    """H_min, or as much of it as fits: within one pitch and on the side face (r10)."""
    wanted = cfg.advanced.label_min_height
    bounds = [labels.text_outline(code, wanted, font).bounds() for code in codes]
    widest = max(float(high_x - low_x) for low_x, _, high_x, _ in bounds)
    return min(
        wanted,
        wanted * (cal.pitch - CALIBRATION_CODE_GAP) / widest,
        cal.thickness - 2 * CALIBRATION_CODE_GAP,
    )


def _bar(
    cfg: Config, cal: CalibrationDims, codes: tuple[str, ...], height: float, font: Path
) -> Manifold:
    """The bar minus its holes and codes, in one batched union and one subtraction."""
    depth = config.hole_depth(cfg, cfg.connectors.length)
    tools_to_cut: list[Manifold] = []
    clearances = cfg.advanced.calibration_clearances
    for index, (clearance, code) in enumerate(zip(clearances, codes, strict=True)):
        x = hole_position(cal, index)
        tools_to_cut.append(
            geometry.hole_solid(
                2,
                cal.thickness,
                (x, cal.width / 2),
                -1,
                depth,
                cfg.connectors.diameter / 2 + clearance,
                cfg.advanced.hole_chamfer,
                cfg.advanced.circular_segments,
                overlap=TOOL_OVERLAP,
            )
        )
        outline = labels.text_outline(code, height, font)
        engraving = Manifold.extrude(outline, cfg.labels.depth + CUTTER_PAD).translate(
            (0.0, 0.0, -cfg.labels.depth)
        )
        tools_to_cut.append(engraving.transform(_SIDE_FACE).translate((x, 0.0, cal.thickness / 2)))
    bar = geometry.box_solid((0.0, 0.0, 0.0), (cal.length, cal.width, cal.thickness))
    return bar - geometry.union_all(tools_to_cut)
