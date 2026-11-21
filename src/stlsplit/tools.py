"""Tool solids: holes, labels, pegs and pins, applied with one batched boolean per piece.

Stage of the pipeline after the labels (PLAN.md §5.1, Phases 7 and 8). ``apply`` takes the
labelled pieces, their faces and the placed connectors (cutting frame, mm) and returns the
drilled, engraved and pegged pieces, with the loose pins grouped by diameter and length.

For each piece: the holes and the label are united once and subtracted once, then the pegs are
united once and added once. The holes are ``connectors.hole_solids``, the very solids the
collision check measured (ADR-0014), one per side from the same axis point, so they line up by
construction. Pegs are added after the cuts, so a hole can never eat a peg.

Every tool reaches ``TOOL_OVERLAP`` past the cut face, because a face's vertices can be off its
plane by float noise: a peg based exactly on the plane can miss the face and stay a separate
shell (docs/LIBRARY_NOTES.md, ``manifold.face_float_noise``).

Pure: geometry in, geometry out; ``cli`` and ``io`` write the files. Guarantees, asserted for
every piece (``check_piece``; a failure is a bug, exit 4):

- the body is valid, with a positive volume, and no tool added or split off a body (I1);
- it fits ``derived(cfg).printable``, a peg included (I2, ADR-0005);
- the volume removed and the volume added equal those of its tools within 5 %.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import NamedTuple

import numpy as np
from manifold3d import Error, Manifold

from stlsplit import config, connectors, geometry, grid
from stlsplit.config import TOOL_OVERLAP, TOOL_VOLUME_TOLERANCE, Config
from stlsplit.errors import ConfigError
from stlsplit.models import Connector, CutFace, Label, Piece

_LAY_DOWN = np.array(
    [[0.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 0.0], [-1.0, 0.0, 0.0, 0.0]], dtype=np.float64
)
"""Proper rotation (3×4) taking a pin built along z, flat on its +x side, to lie along X with
the flat facing −z."""


class PinGroup(NamedTuple):
    """Identical loose pins: one STL file, printed ``quantity`` times.

    Attributes:
        diameter: d, mm.
        length: L, a standard length, mm.
        quantity: How many connectors use this pin.
        file_name: Path in the output directory, ``dowels/dowel_d{d:.1f}_l{L:.1f}.stl``.
        solid: One pin, lying on its flat (``pin_solid``).
    """

    diameter: float
    length: float
    quantity: int
    file_name: str
    solid: Manifold


class Applied(NamedTuple):
    """What the tools stage returns.

    Attributes:
        pieces: The pieces with their holes and pegs, in the order given.
        pins: The loose pins, longest first (``pin_groups``); empty without dowels.
    """

    pieces: list[Piece]
    pins: list[PinGroup]


def apply(
    pieces: Sequence[Piece], faces: Sequence[CutFace], placed: Sequence[Connector], cfg: Config
) -> Applied:
    """Cut every hole and label and add every peg, with one batched boolean per piece.

    Args:
        pieces: The pieces, cutting frame (``labels.layout``, or ``cutting.cut`` without
            labels). They are not modified.
        faces: Their cut faces.
        placed: The connectors (``connectors.place``).
        cfg: The configuration.

    Returns:
        New pieces, in the same order, and the pin groups.

    Raises:
        AssertionError: A piece fails ``check_piece`` (a bug).
    """
    by_id = {face.id: face for face in faces}
    tooling: dict[str, _Tooling] = {piece.id: _Tooling() for piece in pieces}
    for connector in placed:
        face = by_id[connector.face_id]
        cutters = connectors.hole_solids(connector, face, cfg, overlap=TOOL_OVERLAP)
        exact = connectors.hole_solids(connector, face, cfg)
        for (piece_id, cutter), (_, hole) in zip(cutters, exact, strict=True):
            tooling[piece_id].cuts.append(cutter)
            tooling[piece_id].cuts_volume += hole.volume()
        if connector.kind == "peg":
            entry = tooling[face.piece_neg]
            entry.pegs.append(peg_solid(connector, face, cfg, overlap=TOOL_OVERLAP))
            entry.pegs_volume += peg_solid(connector, face, cfg).volume()
    for piece in pieces:
        if piece.label is not None:
            face = by_id[piece.label.face_id]
            side = -1 if face.piece_neg == piece.id else 1
            entry = tooling[piece.id]
            entry.cuts.append(label_solid(piece.label, face, side, cfg, overlap=TOOL_OVERLAP))
            entry.cuts_volume += piece.label.outline.area * cfg.labels.depth
    done = [_apply_to_piece(piece, tooling[piece.id], cfg) for piece in pieces]
    return Applied(pieces=done, pins=pin_groups(placed, cfg))


@dataclass
class _Tooling:
    """One piece's tools, which overlap its face, and the volumes they should change.

    ``cuts`` are its holes and its label: everything the one subtraction removes.
    """

    cuts: list[Manifold] = field(default_factory=list)
    pegs: list[Manifold] = field(default_factory=list)
    cuts_volume: float = 0.0
    pegs_volume: float = 0.0


def _apply_to_piece(piece: Piece, tooling: _Tooling, cfg: Config) -> Piece:
    body = piece.body
    drilled = body - geometry.union_all(tooling.cuts) if tooling.cuts else body
    final = drilled + geometry.union_all(tooling.pegs) if tooling.pegs else drilled
    check_piece(piece.id, body, drilled, final, tooling.cuts_volume, tooling.pegs_volume, cfg)
    return replace(piece, body=final)


def with_pegs(
    pieces: Sequence[Piece], faces: Sequence[CutFace], placed: Sequence[Connector], cfg: Config
) -> list[Piece]:
    """Return the pieces with their pegs, holes and labels not cut, for the clear-path check.

    This is at least as much material as the final piece, so a path clear for it is clear for
    the final piece, and a dry run, which cuts nothing, gets the same answer as a split
    (PLAN.md §7.1, r12). manifold3d's booleans are lazy: a union costs only if it is queried.

    Args:
        pieces: The pieces, cutting frame. They are not modified.
        faces: Their cut faces.
        placed: The connectors.
        cfg: The configuration.

    Returns:
        New pieces where a peg was added, the same objects elsewhere, in the same order.
    """
    by_id = {face.id: face for face in faces}
    pegs: dict[str, list[Manifold]] = {}
    for connector in placed:
        if connector.kind == "peg":
            face = by_id[connector.face_id]
            solid = peg_solid(connector, face, cfg, overlap=TOOL_OVERLAP)
            pegs.setdefault(face.piece_neg, []).append(solid)
    return [
        replace(piece, body=piece.body + geometry.union_all(pegs[piece.id]))
        if piece.id in pegs
        else piece
        for piece in pieces
    ]


def label_solid(
    label: Label, face: CutFace, side: int, cfg: Config, *, overlap: float = 0.0
) -> Manifold:
    """Return a label's engraving: its outline extruded from the face into the piece.

    Engraved, never embossed: an embossed label would collide with the mating piece (Phase 8,
    task 6).

    Args:
        label: The label; its outline is already mirrored for its side.
        face: Its cut face.
        side: −1 if the piece is the face's neg piece (it lies towards local z < offset), +1
            for the pos piece.
        cfg: The configuration (``labels.depth``).
        overlap: How far it also reaches past the face, mm: ``TOOL_OVERLAP`` for the cutter,
            0 for the part that is really removed.

    Returns:
        The solid, cutting frame.
    """
    offset, depth = face.plane.offset, cfg.labels.depth
    low, high = (
        (offset - depth, offset + overlap) if side < 0 else (offset - overlap, offset + depth)
    )
    return geometry.prism(
        geometry.crosssection_from_polygons(label.outline), face.plane.axis, low, high
    )


def peg_solid(
    connector: Connector, face: CutFace, cfg: Config, *, overlap: float = 0.0
) -> Manifold:
    """Return a connector's peg: it stands on the face and points into the pos side.

    A cylinder of radius d/2 from the plane to L/2 above it, with a tip chamfer ch_p.

    Args:
        connector: A placed connector of kind ``peg``.
        face: Its cut face.
        cfg: The configuration (ch_p, n_seg).
        overlap: How far its base also reaches into the neg piece, mm: ``TOOL_OVERLAP`` for
            the union, so it can't miss a face that float noise moved off the plane; 0 for the
            part that shows.

    Returns:
        The peg, cutting frame.
    """
    radius = connector.diameter / 2
    top = connector.pin_length / 2
    chamfer = cfg.advanced.pin_chamfer
    tip = [(radius, top - chamfer), (radius - chamfer, top)] if chamfer > 0 else [(radius, top)]
    profile = [(0.0, -overlap), (radius, -overlap), *tip, (0.0, top)]
    u, v = connector.position_uv
    local = geometry.revolved(profile, cfg.advanced.circular_segments)
    return local.translate((u, v, face.plane.offset)).transform(
        geometry.local_to_world(face.plane.axis)
    )


def pin_solid(diameter: float, length: float, cfg: Config) -> Manifold:
    """Return a loose pin, lying on its flat, ready to print.

    A cylinder of radius d/2, with a chamfer ch_p at both ends and a flat of depth f along its
    length (none when f = 0). The flat is cut by difference (``geometry.split_at``). The polygon
    is turned half a segment so that an edge, not a vertex, faces the bed: a shallow flat would
    otherwise clip only a sliver of a vertex (half the nominal area at 16 segments, f = 0.05).
    The cut goes where the polygon is as wide as the round pin's flat (``_flat_offset``), at
    most twice the polygon's sagitta deeper than f (0.0033 mm with the defaults).

    Args:
        diameter: d, mm.
        length: L, mm.
        cfg: The configuration (ch_p, f, n_seg).

    Returns:
        The pin with its axis along X, its bounding-box minimum at the origin, so the flat is
        on z = 0.
    """
    radius = diameter / 2
    chamfer = cfg.advanced.pin_chamfer
    flat = cfg.advanced.pin_flat
    if chamfer > 0:
        side = [
            (radius - chamfer, 0.0),
            (radius, chamfer),
            (radius, length - chamfer),
            (radius - chamfer, length),
        ]
    else:
        side = [(radius, 0.0), (radius, length)]
    segments = cfg.advanced.circular_segments
    pin = geometry.revolved([(0.0, 0.0), *side, (0.0, length)], segments)
    pin = pin.rotate((0.0, 0.0, math.degrees(math.pi / segments)))
    offset = _flat_offset(radius, flat, segments)
    if offset is not None:
        pin = geometry.split_at(pin, 0, offset)[0]
    lying = pin.transform(_LAY_DOWN)
    low = lying.bounding_box()[:3]
    return lying.translate((-low[0], -low[1], -low[2]))


def _flat_offset(radius: float, flat: float, segments: int) -> float | None:
    """Where to cut a polygon with an edge towards +x so its flat is as wide as a round pin's.

    The polygon's vertices are at angles ±(k + ½)·2π/n. Returns the x at which its outline is
    half the nominal width 2·√(r² − (r − f)²) from the axis, or ``None`` when no cut is needed:
    f = 0, or the edge facing the bed is already that wide.
    """
    if flat <= 0:
        return None
    half_width = math.sqrt(radius**2 - (radius - flat) ** 2)
    step = 2 * math.pi / segments
    index = math.floor(math.asin(half_width / radius) / step - 0.5)
    if index < 0:
        return None
    first, second = (index + 0.5) * step, (index + 1.5) * step
    low, high = radius * math.sin(first), radius * math.sin(second)
    fraction = (half_width - low) / (high - low)
    return radius * (math.cos(first) + fraction * (math.cos(second) - math.cos(first)))


def pin_groups(placed: Sequence[Connector], cfg: Config) -> list[PinGroup]:
    """Group the loose pins by (diameter, length); pegs are part of their piece.

    Args:
        placed: The connectors, in any order.
        cfg: The configuration.

    Returns:
        One group per (d, L), longest first, then by diameter.

    Raises:
        ConfigError: Two groups would be written to the same file (``check_pin_names``).
    """
    check_pin_names(placed)
    counts = Counter((c.diameter, c.pin_length) for c in placed if c.kind == "dowel")
    return [
        PinGroup(
            diameter=diameter,
            length=length,
            quantity=count,
            file_name=_pin_file(diameter, length),
            solid=pin_solid(diameter, length, cfg),
        )
        for (diameter, length), count in sorted(
            counts.items(), key=lambda item: (-item[0][1], item[0][0])
        )
    ]


def check_pin_names(placed: Sequence[Connector]) -> None:
    """Refuse pins of different lengths that would be written to the same file.

    File names keep one decimal (PLAN.md §4.3), so 15.25 and 15.15 mm both read ``l15.2``, and
    one of the two pins would be lost. A dry run calls this too, so it fails as a split would.

    Args:
        placed: The connectors, in any order.

    Raises:
        ConfigError: Two (d, L) pairs share a file name (exit 1).
    """
    names: dict[str, float] = {}
    for key in sorted({(c.diameter, c.pin_length) for c in placed if c.kind == "dowel"}):
        name = _pin_file(*key)
        if name in names:
            raise ConfigError(
                "advanced.pin_length_step",
                f"pins of {names[name]:g} and {key[1]:g} mm would both be written to {name}: "
                "use a connectors.length and a step that are multiples of 0.1",
            )
        names[name] = key[1]


def _pin_file(diameter: float, length: float) -> str:
    return f"dowels/dowel_d{diameter:.1f}_l{length:.1f}.stl"


def check_piece(
    piece_id: str,
    before: Manifold,
    drilled: Manifold,
    final: Manifold,
    holes_volume: float,
    pegs_volume: float,
    cfg: Config,
) -> None:
    """Check a piece after its tools (Phase 7, task 5; I1, I2).

    Args:
        piece_id: For the message.
        before: The body before the tools.
        drilled: After the holes and the label.
        final: After the pegs too.
        holes_volume: Volume of its holes and its label, mm³. Placement and the label layout
            keep them inside the piece and apart from each other.
        pegs_volume: Volume of its pegs, mm³.
        cfg: The configuration.

    Raises:
        AssertionError: The body is invalid or empty, has an outer shell more or less than
            before (a separate peg), doesn't fit ``derived(cfg).printable``, or a volume is off
            by more than ``TOOL_VOLUME_TOLERANCE``. Void shells aren't counted: a hole may
            swallow a void small enough for the containment check to tolerate.
    """
    if final.status() != Error.NoError or final.volume() <= 0:
        raise AssertionError(f"I1: piece {piece_id} is invalid after its tools")
    if _outer_shells(final) != _outer_shells(before):
        raise AssertionError(f"I1: a tool left a separate shell in piece {piece_id}")
    _check_volume(piece_id, "removed", before.volume() - drilled.volume(), holes_volume)
    _check_volume(piece_id, "added", final.volume() - drilled.volume(), pegs_volume)
    box = final.bounding_box()
    limits = config.derived(cfg).printable
    if not all(grid.fits(box[a + 3] - box[a], limits[a]) for a in range(3)):
        size = " x ".join(f"{box[a + 3] - box[a]:.6g}" for a in range(3))
        raise AssertionError(f"I2: piece {piece_id} is {size} mm, over the printable {limits}")


def _outer_shells(body: Manifold) -> int:
    """Shells with a positive volume; a void's shell is inside out (docs/LIBRARY_NOTES.md)."""
    return sum(shell.volume() > 0 for shell in body.decompose())


def _check_volume(piece_id: str, what: str, actual: float, expected: float) -> None:
    if abs(actual - expected) > TOOL_VOLUME_TOLERANCE * expected:
        raise AssertionError(
            f"piece {piece_id}: {actual:.6g} mm^3 {what}, its tools have {expected:.6g} mm^3"
        )
