"""Connector placement: where the dowels (or pegs) of each cut face go, and how long they are.

Fifth stage of the pipeline (PLAN.md §5.1), after the cutting (``cutting.cut``) and before the
labels (Phase 8). ``place`` takes the pieces and their cut faces (cutting frame, mm) and
returns the connectors with the diagnostics W001 (a face without connector), W002 (pins
shortened) and W009 (a single connector). ``safe_region`` is also what plane nudging
(``grid.nudge``) scores cut regions with.

For each face, in face order (docs/ALGORITHMS.md, "Connector placement"):

1. ``safe_region``: the region inset by w + r_h + ch_h, where an axis keeps its wall on the
   face;
2. ``candidates``: the points of a grid of step g inside it, plus each part's polylabel
   point, sorted by (u, v);
3. ``connector_count``: how many to aim for, two whenever two fit (a single round pin lets
   the pieces rotate);
4. ``select``: the trial order, which spreads the connectors out;
5. ``check_candidate``: the 3D checks (ADR-0014): depth rays, the longest standard length that
   fits, exact containment of the hole with its wall, and the gap to the holes already in the
   piece.

Pure: pieces and faces in, connectors out. Guarantees:

- Deterministic: faces in face order, candidates in (u, v) order, every tie broken by (u, v),
  connectors numbered in acceptance order.
- Every connector's axis point lies inside its face's safe region (I6, asserted).
- Each hole, with a wall of w around it and beyond its bottom, lies inside its piece, and no
  two holes of a piece are closer than w (I5).
"""

import functools
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

import numpy as np
import shapely
from manifold3d import Manifold
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Polygon

from stlsplit import config, geometry
from stlsplit.config import (
    GAP_SEARCH_MARGIN,
    LENGTH_TOLERANCE,
    MAX_CANDIDATE_TRIALS,
    RAY_CIRCLE_COUNT,
    RAY_START_OFFSET,
    VOID_RESIDUAL_FRACTION,
    Config,
)
from stlsplit.errors import diagnostic
from stlsplit.models import Connector, ConnectorKind, CutFace, Diagnostic, Piece, Plane

LOGGER = logging.getLogger(__name__)

Points = NDArray[np.float64]
"""Candidate points: an (n, 2) array of plane-local (u, v), mm, sorted by u then v."""

Side = tuple[str, int]
"""A side of a face that needs a hole: the piece's ID, and −1 (neg piece) or +1 (pos piece)."""

# derived() is called for every candidate; a Config is frozen and hashable.
_derived = functools.lru_cache(maxsize=4)(config.derived)


class Placement(NamedTuple):
    """What the placement stage returns.

    Attributes:
        connectors: In face order, then acceptance order on each face.
        diagnostics: W002 and W009, or W001, for each face in face order.
    """

    connectors: list[Connector]
    diagnostics: tuple[Diagnostic, ...]


class Selection(NamedTuple):
    """The outcome of a face's trial order (``select``).

    Attributes:
        accepted: Indices of the accepted candidates, in acceptance order.
        tried: Indices of every candidate that went through the 3D checks, in trial order.
    """

    accepted: list[int]
    tried: list[int]


class Hole(NamedTuple):
    """One hole as the collision check sees it.

    Attributes:
        solid: The hole with its mouth chamfer (``geometry.hole_solid``), cutting frame.
        mouth: Its axis point on the face, cutting frame, mm.
        bottom: Its axis point at the bottom, cutting frame, mm.
    """

    solid: Manifold
    mouth: geometry.Point3
    bottom: geometry.Point3


class Fit(NamedTuple):
    """A candidate that passed the 3D checks (``check_candidate``).

    Attributes:
        length: The pin length L, a standard length, mm.
        holes: The holes it needs, (piece ID, hole), neg piece first.
    """

    length: float
    holes: tuple[tuple[str, Hole], ...]


def place(pieces: Sequence[Piece], faces: Sequence[CutFace], cfg: Config) -> Placement:
    """Place the connectors of every cut face.

    Faces are processed in face order (``cutting.cut_faces``: by plane, neg cell, then
    polylabel point; not ID string order), and each face's connectors in its trial order, so
    holes accepted earlier constrain the later ones of the same piece.

    Args:
        pieces: The pieces, cutting frame (``cutting.cut``).
        faces: Their cut faces, in face order.
        cfg: The configuration (``connectors`` and ``advanced``).

    Returns:
        The connectors and the diagnostics; nothing at all with ``connectors.type = "none"``.

    Raises:
        AssertionError: A connector lies outside its face's safe region (I6; a bug).
    """
    if cfg.connectors.type == "none":
        return Placement(connectors=[], diagnostics=())
    bodies = {piece.id: piece.body for piece in pieces}
    holes: dict[str, list[Hole]] = {}
    placed: list[Connector] = []
    diagnostics: list[Diagnostic] = []
    for face in faces:
        found, reported = _place_on_face(face, bodies, holes, cfg)
        placed.extend(found)
        diagnostics.extend(reported)
    return Placement(connectors=placed, diagnostics=tuple(diagnostics))


# --- 2D: safe region, candidates, count, trial order (tasks 1 to 4) ---------------------------


def safe_region(region: Polygon, cfg: Config) -> MultiPolygon:
    """Return the safe region of a cut face: where a connector's axis may go.

    The region inset by w + r_h + ch_h (``derived(cfg).inset``, 5.1 mm by default), so a hole
    and its mouth chamfer keep a wall of w on the face. Round joins: at a concave corner of
    the region the inset follows the arc of points exactly ``inset`` from the corner.

    Args:
        region: A cut face's region, plane-local (u, v), mm.
        cfg: The configuration.

    Returns:
        The parts that remain, in shapely's order; empty when nothing has room.
    """
    inset = _derived(cfg).inset
    return MultiPolygon(geometry.polygon_parts(region.buffer(-inset)))


def candidates(safe: MultiPolygon, cfg: Config) -> Points:
    """Return the candidate axis points of a safe region.

    The points (i·g, j·g) for integers i and j that lie strictly inside the safe region, plus
    the polylabel point of each of its parts (also kept only if strictly inside).

    Args:
        safe: The safe region (``safe_region``), (u, v) in mm.
        cfg: The configuration (g = ``derived(cfg).candidate_step``).

    Returns:
        An (n, 2) array, without duplicates, sorted by u then v.
    """
    if safe.is_empty:
        return np.empty((0, 2), dtype=np.float64)
    step = _derived(cfg).candidate_step
    min_u, min_v, max_u, max_v = safe.bounds
    us = np.arange(math.ceil(min_u / step), math.floor(max_u / step) + 1) * step
    vs = np.arange(math.ceil(min_v / step), math.floor(max_v / step) + 1) * step
    grid_u, grid_v = np.meshgrid(us, vs, indexing="ij")
    labels = np.array([geometry.polylabel_point(part) for part in safe.geoms], dtype=np.float64)
    all_u = np.concatenate([grid_u.ravel(), labels[:, 0]])
    all_v = np.concatenate([grid_v.ravel(), labels[:, 1]])
    shapely.prepare(safe)
    inside = shapely.contains_xy(safe, all_u, all_v)
    points = np.column_stack([all_u[inside], all_v[inside]]).astype(np.float64)
    return np.unique(points, axis=0)


def connector_count(safe: MultiPolygon, points: Points, cfg: Config) -> int:
    """Return how many connectors a face aims for (task 3).

    0 without candidates; 1 if no two candidates are at least s_min apart (the diameter of
    their convex hull); otherwise ``clamp(floor(area(safe) / A), 2, k_max)``: two whenever two
    fit, because a single round pin lets the pieces rotate. Never more than k_max, even 1.

    Args:
        safe: The safe region.
        points: Its candidates (``candidates``).
        cfg: The configuration (s_min, A, k_max).

    Returns:
        The target count k.
    """
    if len(points) == 0:
        return 0
    d = _derived(cfg)
    _, _, diameter_squared = _diameter_pair(points)
    if diameter_squared < d.connector_spacing**2:
        return 1
    by_area = math.floor(float(safe.area) / d.area_per_connector)
    return min(cfg.connectors.max_per_face, max(2, by_area))


def select(
    safe: MultiPolygon,
    points: Points,
    count: int,
    cfg: Config,
    accept: Callable[[int], bool],
) -> Selection:
    """Try candidates in the trial order until ``count`` are accepted (task 4).

    - ``count`` = 1: the polylabel point of the largest part (ties: by polylabel point), then
      the other candidates by decreasing distance to the safe region's boundary.
    - ``count`` ≥ 2: the farthest-apart pair first (the diameter of the candidates' convex
      hull, the endpoint first in (u, v) order first), then farthest-point sampling: the
      untried candidate farthest from the accepted connectors, or from the tried candidates
      while none is accepted. A rejection is thus followed by its neighbours, so the
      connectors stay spread out (PLAN.md Appendix E, r8). A candidate closer than s_min to
      an accepted connector is never tried: once the farthest is, so are all the others.
    - Ties go to the (u, v) order of the candidates.
    - At most ``MAX_CANDIDATE_TRIALS`` candidates are tried.

    Args:
        safe: The safe region.
        points: Its candidates, sorted by (u, v) (``candidates``).
        count: How many to accept (``connector_count``).
        cfg: The configuration (s_min).
        accept: Runs the 3D checks of candidate ``index``; True accepts it.

    Returns:
        The accepted and the tried candidates.
    """
    if count <= 0 or len(points) == 0:
        return Selection(accepted=[], tried=[])
    if count == 1:
        return _select_one(safe, points, accept)
    return _select_spread(points, count, _derived(cfg).connector_spacing, accept)


def _select_one(safe: MultiPolygon, points: Points, accept: Callable[[int], bool]) -> Selection:
    largest = min(safe.geoms, key=lambda part: (-part.area, geometry.polylabel_point(part)))
    lead = geometry.polylabel_point(largest)
    distances = shapely.distance(safe.boundary, shapely.points(points))
    order = [int(i) for i in np.lexsort((np.arange(len(points)), -distances))]
    matches = np.flatnonzero((points[:, 0] == lead[0]) & (points[:, 1] == lead[1]))
    if len(matches):
        first = int(matches[0])
        order.remove(first)
        order.insert(0, first)
    tried: list[int] = []
    for index in order[:MAX_CANDIDATE_TRIALS]:
        tried.append(index)
        if accept(index):
            return Selection(accepted=[index], tried=tried)
    return Selection(accepted=[], tried=tried)


def _select_spread(
    points: Points, count: int, spacing: float, accept: Callable[[int], bool]
) -> Selection:
    first, second, _ = _diameter_pair(points)
    queue = [first] if first == second else [first, second]
    untried = np.ones(len(points), dtype=bool)
    near_accepted = np.full(len(points), np.inf)  # squared distance to the nearest accepted
    near_tried = np.full(len(points), np.inf)
    accepted: list[int] = []
    tried: list[int] = []
    while len(accepted) < count and len(tried) < MAX_CANDIDATE_TRIALS:
        if queue:
            index = queue.pop(0)
        else:
            reference = near_accepted if accepted else near_tried
            index = int(np.argmax(np.where(untried, reference, -np.inf)))  # first = (u, v) order
            if not untried[index]:
                break  # every candidate was tried
        if near_accepted[index] < spacing**2:
            break  # the farthest candidate left is too close, so are all the others
        untried[index] = False
        tried.append(index)
        squared = ((points - points[index]) ** 2).sum(axis=1)
        np.minimum(near_tried, squared, out=near_tried)
        if accept(index):
            accepted.append(index)
            np.minimum(near_accepted, squared, out=near_accepted)
    return Selection(accepted=accepted, tried=tried)


def _diameter_pair(points: Points) -> tuple[int, int, float]:
    """The farthest-apart pair of candidates and its squared distance.

    i < j, and among equal pairs the first in (u, v) order. The endpoints of the diameter are
    vertices of the convex hull, so only those are compared.
    """
    if len(points) == 1:
        return 0, 0, 0.0
    hull = shapely.get_coordinates(shapely.convex_hull(shapely.multipoints(points)))
    vertices = sorted({int(np.argmin(((points - corner) ** 2).sum(axis=1))) for corner in hull})
    corners = points[vertices]
    squared = ((corners[:, None, :] - corners[None, :, :]) ** 2).sum(axis=2)
    upper = np.triu(squared, k=1)
    rows, columns = np.nonzero(upper == upper.max())  # row-major: the smallest (i, j) first
    return vertices[int(rows[0])], vertices[int(columns[0])], float(upper.max())


# --- 3D checks (task 5) -----------------------------------------------------------------------


def check_candidate(
    face: CutFace,
    uv: tuple[float, float],
    bodies: Mapping[str, Manifold],
    holes: Mapping[str, Sequence[Hole]],
    cfg: Config,
) -> Fit | None:
    """Run the 3D checks of one candidate (task 5, ADR-0014).

    On each side that needs a hole (both for dowels, the pos side only for pegs):

    1. depth: ``available_depth``;
    2. pin length: the standard lengths whose hole fits the smallest available depth
       (``lengths_that_fit``), longest first;
    3. containment: the longest of them for which ``fits_inside`` holds on every side; this
       catches pieces that narrow behind the face where the rays miss it;
    4. collisions: each new hole (``geometry.hole_solid``: r_h, chamfer ch_h, depth h(L)) is at
       least w from every hole already accepted in the same piece (``min_gap``, searching up
       to w + ``GAP_SEARCH_MARGIN``), up to ``LENGTH_TOLERANCE``; otherwise the candidate is
       rejected, not shortened. Two holes whose bounding boxes are w apart are far enough;
       two holes where one's axis meets the other (a ray cast) cross, so they are too close
       without asking ``min_gap``, which is slow on crossing solids (2 ms against 0.15).

    Args:
        face: The cut face.
        uv: The candidate axis point, plane-local (u, v), mm.
        bodies: Piece bodies by ID, cutting frame.
        holes: Holes already accepted, by piece ID.
        cfg: The configuration.

    Returns:
        The pin length and the holes, or ``None`` if the candidate is rejected.
    """
    sides = _sides(face, "peg" if cfg.connectors.type == "peg" else "dowel")
    available = [available_depth(bodies[piece], face.plane, uv, side, cfg) for piece, side in sides]
    limits = [depth for depth in available if depth is not None]
    lengths = lengths_that_fit(min(limits) if limits else None, cfg)
    length = _longest_fit(bodies, face.plane, uv, sides, lengths, cfg)
    if length is None:
        return None
    depth = config.hole_depth(cfg, length)
    new = tuple((piece, _hole(face.plane, uv, side, depth, cfg)) for piece, side in sides)
    wall = cfg.connectors.min_wall
    for piece, hole in new:
        if any(_too_close(hole, other, wall) for other in holes.get(piece, ())):
            return None
    return Fit(length=length, holes=new)


def available_depth(
    body: Manifold, plane: Plane, uv: tuple[float, float], side: int, cfg: Config
) -> float | None:
    """Return the depth available for a hole behind a face, or ``None`` for "enough" (task 5.1).

    Casts 1 + ``RAY_CIRCLE_COUNT`` rays: one on the axis and the others evenly on a circle of
    radius r_h + w (``derived(cfg).probe_radius``) around it. Each starts ``RAY_START_OFFSET``
    inside the piece (never on the face, whose reporting depends on the library; §13) and
    runs along the inward normal for ``derived(cfg).ray_length`` = h(L_max) + w + 1 mm.
    Depths are measured from the face, so 12 mm of material gives 12, minus w: 10.

    Args:
        body: The piece on that side, cutting frame, mm.
        plane: The face's plane.
        uv: The axis point, plane-local (u, v), mm.
        side: −1 for the neg piece (inward is −axis), +1 for the pos piece.
        cfg: The configuration.

    Returns:
        The smallest first-hit depth minus w, mm (possibly negative), or ``None`` if no ray
        hits anything.
    """
    d = _derived(cfg)
    direction = geometry.local_point(plane.axis, 0.0, 0.0, float(side))
    start = plane.offset + side * RAY_START_OFFSET
    nearest: float | None = None
    for du, dv in _ray_offsets(d.probe_radius):
        origin = geometry.local_point(plane.axis, uv[0] + du, uv[1] + dv, start)
        hit = geometry.ray_depth(body, origin, direction, d.ray_length)
        if hit is not None:
            depth = RAY_START_OFFSET + hit
            nearest = depth if nearest is None else min(nearest, depth)
    return None if nearest is None else nearest - cfg.connectors.min_wall


def lengths_that_fit(available: float | None, cfg: Config) -> tuple[float, ...]:
    """Return the standard pin lengths whose hole depth h(L) fits the available depth (task 5.2).

    Args:
        available: From ``available_depth``, mm; ``None`` means every length fits.
        cfg: The configuration (standard lengths and h(L), §6.2).

    Returns:
        The lengths, longest first; empty if even L_min doesn't fit.
    """
    d = _derived(cfg)
    return tuple(
        length
        for length, depth in zip(d.standard_lengths, d.hole_depths, strict=True)
        if available is None or depth <= available + LENGTH_TOLERANCE
    )


def fits_inside(
    body: Manifold, plane: Plane, uv: tuple[float, float], side: int, length: float, cfg: Config
) -> bool:
    """Whether a hole for a pin of length L, with its wall, lies inside the piece (task 5.3).

    The probe is a cylinder of radius r_h + w (flats at that radius) from the face to depth
    h(L) + w; it must lie inside the piece up to ``VOID_RESIDUAL_FRACTION`` (1e-6) of its
    volume (``geometry.lies_inside``).

    Args:
        body: The piece on that side, cutting frame, mm.
        plane: The face's plane.
        uv: The axis point, plane-local (u, v), mm.
        side: −1 for the neg piece, +1 for the pos piece.
        length: Pin length L, mm.
        cfg: The configuration.

    Returns:
        True if the probe lies inside the piece.
    """
    return geometry.lies_inside(_probe(plane, uv, side, length, cfg), body)


def _probe(
    plane: Plane, uv: tuple[float, float], side: int, length: float, cfg: Config
) -> Manifold:
    """The containment cylinder of ``fits_inside``: radius r_h + w, depth h(L) + w."""
    return geometry.hole_solid(
        plane.axis,
        plane.offset,
        uv,
        side,
        config.hole_depth(cfg, length) + cfg.connectors.min_wall,
        _derived(cfg).probe_radius,
        0.0,
        cfg.advanced.circular_segments,
    )


def _longest_fit(
    bodies: Mapping[str, Manifold],
    plane: Plane,
    uv: tuple[float, float],
    sides: Sequence[Side],
    lengths: Sequence[float],
    cfg: Config,
) -> float | None:
    """The longest of ``lengths`` (longest first) that fits on every side, or ``None``.

    When the longest fails, ``_no_length_fits`` can reject the candidate at once. Without it,
    a 60 mm pin with a 0.1 mm step tried 451 lengths per rejected candidate (Phase 10).
    """
    for position, pin in enumerate(lengths):
        if all(fits_inside(bodies[piece], plane, uv, side, pin, cfg) for piece, side in sides):
            return pin
        if (
            position == 0
            and len(lengths) > 1
            and any(
                _no_length_fits(bodies[piece], plane, uv, side, lengths, cfg)
                for piece, side in sides
            )
        ):
            return None
    return None


def _no_length_fits(
    body: Manifold,
    plane: Plane,
    uv: tuple[float, float],
    side: int,
    lengths: Sequence[float],
    cfg: Config,
) -> bool:
    """Whether the shortest probe already leaves too much outside for any length to fit.

    Every longer probe contains the shortest, so it leaves at least that volume outside the
    piece, and its allowance is at most ``VOID_RESIDUAL_FRACTION`` of the longest probe. This
    gives the same answer as trying each length, including at the tolerance edge, where a
    binary search wouldn't: the allowance grows with L, so containment isn't monotonic there.
    """
    outside = (_probe(plane, uv, side, lengths[-1], cfg) - body).volume()
    allowance = VOID_RESIDUAL_FRACTION * _probe(plane, uv, side, lengths[0], cfg).volume()
    return bool(outside > allowance)


def hole_solids(
    connector: Connector, face: CutFace, cfg: Config, *, overlap: float = 0.0
) -> list[tuple[str, Manifold]]:
    """Return a connector's holes as the collision check sees them (``geometry.hole_solid``).

    Args:
        connector: A placed connector.
        face: Its cut face.
        cfg: The configuration (r_h, ch_h, n_seg).
        overlap: How far each solid also reaches past the face, mm: ``TOOL_OVERLAP`` for the
            cutters of ``tools.apply``, 0 for the holes' real shape.

    Returns:
        (piece ID, hole solid in the cutting frame) per side with a hole, neg piece first.
    """
    depths = {-1: connector.hole_depth_neg, 1: connector.hole_depth_pos}
    return [
        (piece, _hole(face.plane, connector.position_uv, side, depths[side], cfg, overlap).solid)
        for piece, side in _sides(face, connector.kind)
    ]


def _sides(face: CutFace, kind: ConnectorKind) -> tuple[Side, ...]:
    """The sides that need a hole: both for dowels; for pegs the pos side (ADR-0005)."""
    if kind == "peg":
        return ((face.piece_pos, 1),)
    return ((face.piece_neg, -1), (face.piece_pos, 1))


def _hole(
    plane: Plane,
    uv: tuple[float, float],
    side: int,
    depth: float,
    cfg: Config,
    overlap: float = 0.0,
) -> Hole:
    solid = geometry.hole_solid(
        plane.axis,
        plane.offset,
        uv,
        side,
        depth,
        _derived(cfg).hole_radius,
        cfg.advanced.hole_chamfer,
        cfg.advanced.circular_segments,
        overlap=overlap,
    )
    mouth = geometry.local_point(plane.axis, uv[0], uv[1], plane.offset)
    bottom = geometry.local_point(plane.axis, uv[0], uv[1], plane.offset + side * depth)
    return Hole(solid=solid, mouth=mouth, bottom=bottom)


@functools.lru_cache(maxsize=4)
def _ray_offsets(radius: float) -> tuple[tuple[float, float], ...]:
    """The axis, then ``RAY_CIRCLE_COUNT`` points evenly on a circle, from angle 0, in (u, v)."""
    circle = tuple(
        (
            radius * math.cos(2 * math.pi * k / RAY_CIRCLE_COUNT),
            radius * math.sin(2 * math.pi * k / RAY_CIRCLE_COUNT),
        )
        for k in range(RAY_CIRCLE_COUNT)
    )
    return ((0.0, 0.0), *circle)


def _too_close(hole: Hole, other: Hole, wall: float) -> bool:
    """Whether two holes are closer than ``wall``.

    Bounding boxes ``wall`` apart: far enough. An axis meeting the other hole: they cross (a
    hit is a point of one hole on the other's surface, a distance of 0). Otherwise
    ``min_gap``. The first two only skip work: the answer is ``min_gap``'s.
    """
    a, b = hole.solid.bounding_box(), other.solid.bounding_box()
    if any(a[axis] - b[axis + 3] >= wall or b[axis] - a[axis + 3] >= wall for axis in range(3)):
        return False
    if other.solid.ray_cast(hole.mouth, hole.bottom) or hole.solid.ray_cast(
        other.mouth, other.bottom
    ):
        return True
    gap = hole.solid.min_gap(other.solid, wall + GAP_SEARCH_MARGIN)
    return bool(gap < wall - LENGTH_TOLERANCE)


# --- one face, and its diagnostics (tasks 6 and 7) --------------------------------------------


def _place_on_face(
    face: CutFace,
    bodies: Mapping[str, Manifold],
    holes: dict[str, list[Hole]],
    cfg: Config,
) -> tuple[list[Connector], list[Diagnostic]]:
    safe = safe_region(face.region, cfg)
    points = candidates(safe, cfg)
    count = connector_count(safe, points, cfg)
    fits: dict[int, Fit] = {}

    def accept(index: int) -> bool:
        fit = check_candidate(face, _uv(points, index), bodies, holes, cfg)
        if fit is None:
            return False
        fits[index] = fit
        for piece, hole in fit.holes:  # later candidates, of this face too, must clear it
            holes.setdefault(piece, []).append(hole)
        return True

    selection = select(safe, points, count, cfg, accept)
    LOGGER.debug(
        "face %s: %d candidates, aiming for %d; %d tried, %d accepted",
        face.id,
        len(points),
        count,
        len(selection.tried),
        len(selection.accepted),
    )
    kind: ConnectorKind = "peg" if cfg.connectors.type == "peg" else "dowel"
    found: list[Connector] = []
    for number, index in enumerate(selection.accepted, start=1):
        u, v = _uv(points, index)
        connector_id = f"{face.id}/c{number}"
        if not shapely.contains_xy(safe, u, v):
            raise AssertionError(f"I6: {connector_id} at ({u}, {v}) is outside the safe region")
        length = fits[index].length
        depth = config.hole_depth(cfg, length)
        found.append(
            Connector(
                id=connector_id,
                face_id=face.id,
                kind=kind,
                position_uv=(u, v),
                diameter=cfg.connectors.diameter,
                pin_length=length,
                hole_depth_neg=0.0 if kind == "peg" else depth,
                hole_depth_pos=depth,
            )
        )
    return found, _face_diagnostics(face, found, len(points), count, selection, cfg)


def _uv(points: Points, index: int) -> tuple[float, float]:
    return float(points[index, 0]), float(points[index, 1])


def _face_diagnostics(
    face: CutFace,
    found: Sequence[Connector],
    candidate_count: int,
    count: int,
    selection: Selection,
    cfg: Config,
) -> list[Diagnostic]:
    """W001 for a face without connector; otherwise W002 for shortened pins, W009 for one."""
    if not found:
        if count == 0:
            reason = (
                f"no room: inset by {_derived(cfg).inset:.6g} mm for the wall, the hole and its "
                "chamfer, nothing is left"
            )
        else:
            tried = len(selection.tried)
            which = (
                f"the first {tried} of its {candidate_count} candidate points"
                if tried < candidate_count
                else f"all {candidate_count} candidate point{'s' if candidate_count > 1 else ''}"
            )
            reason = (
                f"{which} failed the 3D checks (too little material behind the face, a wall "
                "too close to the hole, or another hole too close)"
            )
        message = f"face {face.id} ({face.region.area:.6g} mm^2) got no connector: {reason}"
        return [diagnostic("W001", message, (face.id,))]
    reported: list[Diagnostic] = []
    full = cfg.connectors.length
    short = [c for c in found if c.pin_length < full]
    if short:
        noun = "peg" if short[0].kind == "peg" else "pin"
        lengths = ", ".join(f"{c.id.rsplit('/', 1)[1]} {c.pin_length:g} mm" for c in short)
        message = (
            f"face {face.id}: {len(short)} {noun}{'s' if len(short) > 1 else ''} shortened below "
            f"the full length {full:g} mm, the pieces being too shallow behind the face: {lengths}"
        )
        reported.append(diagnostic("W002", message, (face.id, *(c.id for c in short))))
    if len(found) == 1:
        message = (
            f"face {face.id} has a single connector: the pieces can rotate around it until glued"
        )
        reported.append(diagnostic("W009", message, (face.id, found[0].id)))
    return reported
