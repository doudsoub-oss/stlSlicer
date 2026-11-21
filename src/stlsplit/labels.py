"""Piece labels: text outlines, and where each piece's ID goes on its cut faces.

Stage of the pipeline between the connector placement and the tools (PLAN.md §5.1, Phase 8).
``layout`` takes the pieces, their faces and the connectors (cutting frame, mm) and returns the
pieces with their ``Label`` (2D, plane-local) and one W003 per piece that has no room;
``tools.apply`` engraves them. ``text_outline`` also draws the calibration kit's codes.

For each piece (docs/ALGORITHMS.md, "Label layout"):

1. ``label_region`` on each of its faces: the region inset by w, minus a keep-out disk around
   each connector, minus whatever lacks ``labels.depth + w`` of material behind it (r11);
2. faces are tried by decreasing region area, ties by face ID, until one fits (r11);
3. ``fit_text``: the text is centred on ``label_anchor`` of the region's largest part (the
   polylabel clearance, nearest the centroid; r11), at 0° and 90°, and its height is bisected
   between H_min and H_max. If it doesn't fit there, other positions are tried (r11).

Pure: the font is a path resolved by ``io.resolve_label_font``; matplotlib reading that file is
the one accepted exception to "only ``io`` and ``cli`` touch the file system" (PLAN.md §3.1).
Guarantees:

- Deterministic: the same pieces, settings and font give the same outlines.
- A label lies inside its face's label region, so it never reaches a connector and never cuts
  through the piece: no glyph counter can come off as a loose shell (ADR-0009).
- Labels only go on cut faces, hidden once assembled, never on exterior surfaces.
"""

import functools
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np
import shapely
from manifold3d import CrossSection, Manifold
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from stlsplit import config, connectors, geometry
from stlsplit.config import (
    LABEL_ANCHOR_GRID_DIVISOR,
    LABEL_ANCHOR_SLACK,
    LABEL_ANGLES,
    LABEL_MAX_ANCHORS,
    LABEL_SEARCH_STEPS,
    TEXT_PATH_SIZE,
    TOOL_OVERLAP,
    Config,
)
from stlsplit.errors import diagnostic
from stlsplit.models import Connector, CutFace, Diagnostic, Label, Piece

_PIECE_ID = re.compile(r"X(\d+)-Y(\d+)-Z(\d+)(?:-([a-z]+))?")
"""A piece ID (PLAN.md §4.3): the cell's digits and an optional body suffix."""


class Labelled(NamedTuple):
    """What the label stage returns.

    Attributes:
        pieces: The pieces in the order given, with ``label`` set where one fits.
        diagnostics: One W003 per piece with cut faces but no room, in piece order.
    """

    pieces: list[Piece]
    diagnostics: tuple[Diagnostic, ...]


class Fitted(NamedTuple):
    """A text placed on a region (``fit_text``).

    Attributes:
        outline: The glyphs, plane-local (u, v), mm.
        height: Text height before rotation, mm.
    """

    outline: MultiPolygon
    height: float


def text_outline(text: str, height: float, font: Path) -> CrossSection:
    """Return a text's outline, centred on the origin.

    Glyphs are flattened at ``TEXT_PATH_SIZE``, then scaled, so their curves stay smooth at a
    few millimetres. TrueType outlines are clockwise, hence the EvenOdd fill rule of
    ``geometry.crosssection_from_contours`` (ADR-0009).

    Args:
        text: The text to draw, with at least one visible glyph.
        height: Height of the text's bounding box, mm (> 0).
        font: The font file.

    Returns:
        The outline in a 2D frame, reading along +x with its top towards +y, mm.

    Raises:
        ValueError: ``height`` isn't positive, or the text draws nothing.
    """
    # Imported here: matplotlib is slow to import and most runs of the CLI don't reach this.
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    if height <= 0:
        raise ValueError(f"invalid text height: {height}")
    path = TextPath((0.0, 0.0), text, size=TEXT_PATH_SIZE, prop=FontProperties(fname=font))
    contours = [np.asarray(contour, dtype=np.float64)[:-1] for contour in path.to_polygons()]
    if not contours:
        raise ValueError(f"the text {text!r} draws nothing")
    section = geometry.crosssection_from_contours(contours)
    low_x, low_y, high_x, high_y = section.bounds()
    factor = height / (high_y - low_y)
    centred = section.translate((-(low_x + high_x) / 2, -(low_y + high_y) / 2))
    return centred.scale((factor, factor))


def label_text(piece_id: str) -> str:
    """Return a piece's short ID: ``X1-Y0-Z2-b`` becomes ``1-0-2b`` (PLAN.md §4.3).

    Args:
        piece_id: A piece ID.

    Returns:
        The grid digits joined by ``-``, then the suffix if any.

    Raises:
        ValueError: ``piece_id`` is not a piece ID.
    """
    match = _PIECE_ID.fullmatch(piece_id)
    if match is None:
        raise ValueError(f"not a piece ID: {piece_id!r}")
    i, j, k, suffix = match.groups()
    return f"{i}-{j}-{k}{suffix or ''}"


def layout(
    pieces: Sequence[Piece],
    faces: Sequence[CutFace],
    placed: Sequence[Connector],
    cfg: Config,
    font: Path,
) -> Labelled:
    """Choose each piece's label: its text, face, position, rotation and height.

    Args:
        pieces: The pieces, cutting frame (``cutting.cut``). They are not modified.
        faces: Their cut faces.
        placed: The connectors (``connectors.place``).
        cfg: The configuration (``labels``, H_min, H_max, w, the keep-out radius).
        font: The font file (``io.resolve_label_font``).

    Returns:
        New pieces, in the same order, and the W003 diagnostics. With ``labels.enabled`` off,
        the pieces unchanged and nothing to report. A piece without a cut face gets no label:
        the cutting stage has already reported it (W008).
    """
    if not cfg.labels.enabled:
        return Labelled(pieces=list(pieces), diagnostics=())
    by_id = {face.id: face for face in faces}
    holes: dict[str, list[Manifold]] = {}
    for connector in placed:
        for piece_id, solid in connectors.hole_solids(connector, by_id[connector.face_id], cfg):
            holes.setdefault(piece_id, []).append(solid)
    done: list[Piece] = []
    reported: list[Diagnostic] = []
    for piece in pieces:
        if not piece.face_ids:
            done.append(piece)
            continue
        own = holes.get(piece.id, [])
        drilled = piece.body - geometry.union_all(own) if own else piece.body
        label = _label_piece(piece, drilled, by_id, placed, cfg, font)
        if label is None:
            reported.append(_no_room(piece, cfg))
        done.append(replace(piece, label=label))
    return Labelled(pieces=done, diagnostics=tuple(reported))


def _label_piece(
    piece: Piece,
    drilled: Manifold,
    faces: Mapping[str, CutFace],
    placed: Sequence[Connector],
    cfg: Config,
    font: Path,
) -> Label | None:
    """The label on the largest face region that has room for it (ties: face ID; r11)."""
    regions: list[tuple[MultiPolygon, CutFace, int]] = []
    for face_id in piece.face_ids:
        face = faces[face_id]
        side = -1 if face.piece_neg == piece.id else 1
        regions.append((label_region(face, drilled, side, placed, cfg), face, side))
    text = label_text(piece.id)
    for region, face, side in sorted(regions, key=lambda item: (-item[0].area, item[1].id)):
        # A pos piece's face is seen from −z, where u runs the other way (§4.2).
        fitted = fit_text(text, region, side > 0, cfg, font)
        if fitted is not None:
            return Label(text=text, face_id=face.id, outline=fitted.outline, height=fitted.height)
    return None


def _no_room(piece: Piece, cfg: Config) -> Diagnostic:
    count = len(piece.face_ids)
    message = (
        f"piece {piece.id} has no label: none of its {count} cut face{'s' if count > 1 else ''} "
        f"has room for text {cfg.advanced.label_min_height:g} mm high, with "
        f"{cfg.connectors.min_wall:g} mm of material around and behind it"
    )
    return diagnostic("W003", message, (piece.id,))


def label_region(
    face: CutFace,
    drilled: Manifold,
    side: int,
    placed: Sequence[Connector],
    cfg: Config,
) -> MultiPolygon:
    """Return where a label may go on one side of a cut face.

    The face's region inset by w, minus a disk of the keep-out radius around each of the
    face's connectors (Phase 8, task 2), minus every point closer than w to a spot without
    ``labels.depth + w`` of material behind the face: a thin plate, a sloped surface, a void
    or a hole of another face (r11). Without this, an engraving can go right through the piece
    and the counters of ``0``, ``8`` or ``b`` come off as loose shells.

    Args:
        face: The cut face.
        drilled: The piece with all its holes, cutting frame, mm.
        side: −1 if the piece is the face's neg piece, +1 for the pos piece.
        placed: The connectors; only those of this face are used.
        cfg: The configuration.

    Returns:
        The parts that remain, plane-local (u, v), mm; empty when nothing has room.
    """
    wall = cfg.connectors.min_wall
    room: BaseGeometry = face.region.buffer(-wall)
    keep_out = config.derived(cfg).label_keep_out
    disks = [
        _disk(c.position_uv, keep_out, cfg.advanced.circular_segments)
        for c in placed
        if c.face_id == face.id
    ]
    if disks:
        room = room.difference(shapely.union_all(disks))
    if not room.is_empty:
        unbacked = _unbacked(face, drilled, side, cfg)
        if unbacked:
            room = room.difference(shapely.union_all(unbacked))
    return MultiPolygon(geometry.polygon_parts(room))


def _disk(center: tuple[float, float], radius: float, segments: int) -> Polygon:
    """A polygon containing the circle: its flats at ``radius``, as holes have (§6.2)."""
    quarter = math.ceil(segments / 4)
    return Point(center).buffer(radius / math.cos(math.pi / (4 * quarter)), quad_segs=quarter)


def _unbacked(face: CutFace, drilled: Manifold, side: int, cfg: Config) -> list[Polygon]:
    """Where a label would lack material behind it, grown by w, plane-local (u, v).

    The probe is the whole region, from just inside the face (a probe starting on the face
    would depend on float noise, ``TOOL_OVERLAP``) to depth ``labels.depth + w``. Anything it
    finds missing is projected on the face. Slivers along the region's edge are harmless: grown
    by w, they cover only the band the inset by w has already removed.
    """
    axis, offset = face.plane.axis, face.plane.offset
    wall = cfg.connectors.min_wall
    near = offset + side * TOOL_OVERLAP
    far = offset + side * (cfg.labels.depth + wall)
    footprint = geometry.crosssection_from_polygons(face.region)
    probe = geometry.prism(footprint, axis, min(near, far), max(near, far))
    missing = probe - drilled
    if missing.is_empty():
        return []
    segments = cfg.advanced.circular_segments
    # Compensated like _disk: the flats of the round corners must be at w, not their vertices.
    reach = wall / math.cos(math.pi / segments)
    blocked = geometry.grow(geometry.shadow(missing, axis), reach, segments)
    return geometry.crosssection_to_polygons(blocked, ordered=False)


def fit_text(
    text: str, region: BaseGeometry, mirrored: bool, cfg: Config, font: Path
) -> Fitted | None:
    """Place a text on a region at the largest height that fits (Phase 8, task 4).

    The text is centred on ``label_anchor`` of the region's largest part (ties: by polylabel
    point). Its height is bisected between H_min and H_max at each angle of
    ``LABEL_ANGLES``. Containment isn't always monotonic in the height (a gap between two
    glyphs can straddle an obstacle), so only sizes actually tested are accepted.

    If not even H_min fits there, each part in turn, largest first, tries its
    ``fallback_anchors`` and the first position that fits is kept (r11): at a T junction the
    anchor is where the text overflows both arms, with room along either.

    Args:
        text: The text.
        region: Where it may go, plane-local (u, v), mm (``label_region``).
        mirrored: Mirror it in u, about the anchor, so that it reads correctly from −z. The
            region is tested against the mirrored shape, the one that is engraved.
        cfg: The configuration (H_min, H_max).
        font: The font file.

    Returns:
        The largest fit (the first angle on a tie), or ``None`` if not even H_min fits.
    """
    parts = sorted(
        geometry.polygon_parts(region),
        key=lambda part: (-part.area, geometry.polylabel_point(part)),
    )
    if not parts:
        return None
    unit = MultiPolygon(
        geometry.crosssection_to_polygons(text_outline(text, 1.0, font), ordered=False)
    )
    shapely.prepare(region)
    fitted = _fit_at(unit, label_anchor(parts[0]), region, mirrored, cfg)
    if fitted is not None:
        return fitted
    low_x, low_y, high_x, high_y = unit.bounds
    length = (high_x - low_x) * cfg.advanced.label_min_height
    tall = (high_y - low_y) * cfg.advanced.label_min_height
    for part in parts:
        if not _may_hold(part, length, tall):
            continue
        for anchor in fallback_anchors(part, cfg):
            fitted = _fit_at(unit, anchor, region, mirrored, cfg)
            if fitted is not None:
                return fitted
    return None


def _fit_at(
    unit: MultiPolygon,
    anchor: tuple[float, float],
    region: BaseGeometry,
    mirrored: bool,
    cfg: Config,
) -> Fitted | None:
    """The largest height that fits centred on ``anchor``, the first angle on a tie."""
    best: Fitted | None = None
    for angle in LABEL_ANGLES:
        shape_at = functools.partial(_placed, unit, angle=angle, mirrored=mirrored, anchor=anchor)
        height = _largest_height(
            region, shape_at, cfg.advanced.label_min_height, cfg.advanced.label_max_height
        )
        if height is not None and (best is None or height > best.height):
            best = Fitted(outline=shape_at(height), height=height)
    return best


def _may_hold(part: Polygon, length: float, tall: float) -> bool:
    """Whether a part's bounding box can hold a text of this size, at 0° or 90°."""
    low_u, low_v, high_u, high_v = part.bounds
    across, along = high_u - low_u, high_v - low_v
    return bool((across >= length and along >= tall) or (across >= tall and along >= length))


def fallback_anchors(part: Polygon, cfg: Config) -> list[tuple[float, float]]:
    """Return the positions tried on a part when the text doesn't fit at the first anchor (r11).

    Args:
        part: A part of a label region, plane-local (u, v), mm.
        cfg: The configuration (the grid step is H_min / ``LABEL_ANCHOR_GRID_DIVISOR``).

    Returns:
        ``label_anchor(part)``, then the grid points strictly inside the part by increasing
        distance to it (ties: u, then v), ``LABEL_MAX_ANCHORS`` positions at most.
    """
    first = label_anchor(part)
    step = cfg.advanced.label_min_height / LABEL_ANCHOR_GRID_DIVISOR
    low_u, low_v, high_u, high_v = part.bounds
    us = np.arange(math.ceil(low_u / step), math.floor(high_u / step) + 1) * step
    vs = np.arange(math.ceil(low_v / step), math.floor(high_v / step) + 1) * step
    grid_u, grid_v = np.meshgrid(us, vs, indexing="ij")
    all_u, all_v = grid_u.ravel(), grid_v.ravel()
    inside = shapely.contains_xy(part, all_u, all_v)
    all_u, all_v = all_u[inside], all_v[inside]
    order = np.lexsort((all_v, all_u, (all_u - first[0]) ** 2 + (all_v - first[1]) ** 2))
    chosen = order[: LABEL_MAX_ANCHORS - 1]
    return [first, *zip(all_u[chosen].tolist(), all_v[chosen].tolist(), strict=True)]


def label_anchor(part: Polygon) -> tuple[float, float]:
    """Return where a label is centred: the middle of the part's widest zone (r11).

    The polylabel point gives the largest clearance, but on a long face every point of the
    middle line ties and the library returns one near an end (a 100 × 8 face gets (4, 4)), so
    the text runs off the face. Among the points within ``LABEL_ANCHOR_SLACK`` of that
    clearance, this takes the one nearest the part's centroid: (50, 4) there. When two are
    equally near, GEOS's choice is the same for the same input (ADR-0010).

    Args:
        part: A polygon with a positive area, plane-local (u, v), mm.

    Returns:
        (u, v), mm, inside the part.
    """
    u, v = geometry.polylabel_point(part)
    clearance = float(part.boundary.distance(Point(u, v)))
    if clearance <= LABEL_ANCHOR_SLACK:
        return u, v
    core = part.buffer(-(clearance - LABEL_ANCHOR_SLACK))
    if core.is_empty:
        return u, v
    nearest = nearest_points(core, part.centroid)[0]
    return float(nearest.x), float(nearest.y)


def _placed(
    unit: MultiPolygon,
    height: float,
    angle: float,
    mirrored: bool,
    anchor: tuple[float, float],
) -> MultiPolygon:
    """Scale, rotate, then mirror in u about the origin, and move to the anchor."""
    radians = math.radians(angle)
    cos, sin = height * math.cos(radians), height * math.sin(radians)
    flip = -1.0 if mirrored else 1.0
    placed: MultiPolygon = affinity.affine_transform(
        unit, [flip * cos, -flip * sin, sin, cos, anchor[0], anchor[1]]
    )
    return placed


def _largest_height(
    region: BaseGeometry, shape_at: Callable[[float], MultiPolygon], low: float, high: float
) -> float | None:
    """Bisect for the largest height whose shape lies in ``region``; ``None`` if ``low`` doesn't."""
    if not region.contains(shape_at(low)):
        return None
    if region.contains(shape_at(high)):
        return high
    for _ in range(LABEL_SEARCH_STEPS):
        middle = (low + high) / 2
        if region.contains(shape_at(middle)):
            low = middle
        else:
            high = middle
    return low
