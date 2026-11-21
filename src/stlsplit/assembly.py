"""Assembly order, the content of ``assembly.json`` and ``assembly.md``, the preview layout.

Stage of the pipeline after the tools (PLAN.md §5.1, Phase 9). ``plan_steps`` takes the final
pieces, their cut faces and connectors (cutting frame, mm) and returns the order of the joins.
``build_document`` gathers everything a run knows into the ``assembly.json`` document
(``schemas/assembly.schema.json``), ``to_json`` and ``to_markdown`` render it, and
``preview_items`` lays the pieces out for ``preview_exploded.glb``.

The order is staged (ADR-0004): X joins, then Y joins, then Z joins. Within a stage the planes
are taken in increasing order. On one plane, the sub-assemblies that its faces connect are taken
apart one at a time, each along a clear straight path, and the joins are that sequence reversed
(PLAN.md Appendix E, r12): joining them in plain face order can pair two sub-assemblies that
each hold pieces on both sides of the plane, and no single move closes such a join.

Pure: nothing here touches the file system; ``cli`` and ``io`` write the files. Guarantees:

- every step joins two different current sub-assemblies along one axis and one direction, and
  all its faces are perpendicular to that axis (I7, asserted);
- every cut face belongs to exactly one step (asserted);
- a step whose path can't be shown to be clear is reported with W013, never silently;
- the same input gives the same output: every order is explicit (ADR-0010).
"""

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import PureWindowsPath
from typing import Any, NamedTuple

from manifold3d import Manifold

from stlsplit import config, geometry
from stlsplit.config import (
    ASSEMBLY_SCHEMA_VERSION,
    ASSEMBLY_SEARCH_STATES,
    OUTPUT_DECIMALS,
    PREVIEW_PALETTE,
    Config,
)
from stlsplit.errors import diagnostic
from stlsplit.models import (
    AssemblyStep,
    Axis,
    Connector,
    CutFace,
    Diagnostic,
    Grid,
    Orientation,
    Piece,
)

_AXES: tuple[Axis, Axis, Axis] = (0, 1, 2)
_AXIS_NAMES = "xyz"
_STAGE_TITLES = ("X joins (rows)", "Y joins (layers)", "Z joins (stack)")
_TROUBLESHOOTING = "docs/TROUBLESHOOTING.md"
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>|#])")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")


class AssemblyPlan(NamedTuple):
    """What ``plan_steps`` returns.

    Attributes:
        steps: The joins, in the order to perform them.
        groups: The final sub-assemblies, each as piece IDs in piece order, sorted by first
            piece. More than one means the model stays in separate parts.
        diagnostics: One W013 per step without a proven clear path, in step order.
    """

    steps: tuple[AssemblyStep, ...]
    groups: tuple[tuple[str, ...], ...]
    diagnostics: tuple[Diagnostic, ...]


class PinCount(NamedTuple):
    """One line of the dowel print list.

    Attributes:
        file: Path in the output directory.
        diameter: d, mm.
        length: L, mm.
        quantity: How many to print.
    """

    file: str
    diameter: float
    length: float
    quantity: int


class PreviewItem(NamedTuple):
    """One piece of the exploded preview.

    Attributes:
        name: The piece ID, used as the glTF node name.
        body: The final piece, mm, cutting frame.
        offset: How far it is moved from its place, mm.
        color: RGBA, 0 to 255, from ``PREVIEW_PALETTE``.
    """

    name: str
    body: Manifold
    offset: tuple[float, float, float]
    color: tuple[int, int, int, int]


class _SubAssemblies:
    """The current sub-assemblies, each named after its first piece in piece order."""

    def __init__(self, piece_ids: Sequence[str]) -> None:
        self._position = {piece_id: n for n, piece_id in enumerate(piece_ids)}
        self._group = {piece_id: piece_id for piece_id in piece_ids}
        self._members: dict[str, tuple[str, ...]] = {p: (p,) for p in piece_ids}

    def of(self, piece_id: str) -> str:
        return self._group[piece_id]

    def members(self, group: str) -> tuple[str, ...]:
        return self._members[group]

    def position(self, group: str) -> int:
        return self._position[group]

    def join(self, first: str, second: str) -> None:
        pieces = self._members.pop(first) + self._members.pop(second)
        merged = tuple(sorted(pieces, key=self._position.__getitem__))
        self._members[merged[0]] = merged
        for piece_id in merged:
            self._group[piece_id] = merged[0]

    def all(self) -> tuple[tuple[str, ...], ...]:
        return tuple(self._members[g] for g in sorted(self._members, key=self.position))


def plan_steps(
    pieces: Sequence[Piece], faces: Sequence[CutFace], placed: Sequence[Connector]
) -> AssemblyPlan:
    """Return the assembly order (PLAN.md Phase 9, task 1; ADR-0004; r12).

    Stage by stage (X, Y, Z) and plane by plane in increasing index, the sub-assemblies that a
    plane's faces connect are taken apart one at a time and put back in reverse order. The one
    taken off must leave the others connected and have a clear path away from the plane; a
    bounded search with backtracking looks for an order where all of them do. The
    sub-assembly with more pieces stays still and the other slides along ±axis; on a tie, the
    one holding the first piece in piece order stays.

    Args:
        pieces: The pieces in piece order, mm, cutting frame, as ``tools.with_pegs`` gives
            them: pegs on, holes and labels not cut. More material can only be more in the
            way, so a clear path stays proven, and a dry run gets the same answer as a split.
        faces: Their cut faces, in face order.
        placed: The connectors, in any order.

    Returns:
        The steps, the final groups and the W013 diagnostics.

    Raises:
        AssertionError: A sub-assembly lies on both sides of a plane, or a face belongs to no
            step or to several (I7; a bug).
    """
    groups = _SubAssemblies([piece.id for piece in pieces])
    bodies = {piece.id: piece.body for piece in pieces}
    per_face = Counter(connector.face_id for connector in placed)
    blocked: dict[tuple[str, str, Axis, int], bool] = {}
    steps: list[AssemblyStep] = []
    diagnostics: list[Diagnostic] = []
    for axis in _AXES:
        on_axis = [face for face in faces if face.plane.axis == axis]
        joins = 0
        for index in sorted({face.plane.index for face in on_axis}):
            on_plane = [face for face in on_axis if face.plane.index == index]
            for cluster in _clusters(on_plane, groups):
                base, additions = _join_order(cluster, on_plane, groups, bodies, axis, blocked)
                for group, clear in additions:
                    joins += 1
                    number = f"{axis + 1}.{joins}"
                    step = _step(number, axis, group, base, clear, on_plane, groups, per_face)
                    steps.append(step)
                    groups.join(group, base)
                    base = groups.of(step.moving[0])
                    if not clear:
                        diagnostics.append(_blocked_step(step))
    covered = sorted(face_id for step in steps for face_id in step.face_ids)
    assert covered == sorted(face.id for face in faces), "I7: a face is not in exactly one step"
    return AssemblyPlan(tuple(steps), groups.all(), tuple(diagnostics))


def _clusters(on_plane: Sequence[CutFace], groups: _SubAssemblies) -> list[list[str]]:
    """The sub-assemblies a plane's faces connect, cluster by cluster, in order of first face.

    Each cluster is sorted by first piece.
    """
    neighbours = _neighbours(on_plane, groups)
    seen: set[str] = set()
    clusters: list[list[str]] = []
    for face in on_plane:
        start = groups.of(face.piece_neg)
        if start in seen:
            continue
        cluster: list[str] = []
        todo = [start]
        while todo:
            group = todo.pop()
            if group in seen:
                continue
            seen.add(group)
            cluster.append(group)
            todo.extend(sorted(neighbours[group], key=groups.position))
        clusters.append(sorted(cluster, key=groups.position))
    return clusters


def _neighbours(on_plane: Sequence[CutFace], groups: _SubAssemblies) -> dict[str, set[str]]:
    neighbours: dict[str, set[str]] = {}
    for face in on_plane:
        neg, pos = groups.of(face.piece_neg), groups.of(face.piece_pos)
        neighbours.setdefault(neg, set()).add(pos)
        neighbours.setdefault(pos, set()).add(neg)
    return neighbours


def _join_order(
    cluster: Sequence[str],
    on_plane: Sequence[CutFace],
    groups: _SubAssemblies,
    bodies: Mapping[str, Manifold],
    axis: Axis,
    blocked: dict[tuple[str, str, Axis, int], bool],
) -> tuple[str, list[tuple[str, bool]]]:
    """Take a cluster apart, then reverse the sequence.

    Returns:
        The sub-assembly left at the end, which the others are added to; and those others, in
        the order to add them, each with whether its path is clear.
    """
    # Only this cluster's faces: a cluster already joined now lies on both sides of the plane.
    members = set(cluster)
    own_faces = [face for face in on_plane if groups.of(face.piece_neg) in members]
    sides = _sides(own_faces, groups)
    neighbours = _neighbours(own_faces, groups)

    def is_clear(group: str, current: Sequence[str]) -> bool:
        return _path_is_clear(group, current, sides, groups, bodies, axis, blocked)

    order = _clear_order(cluster, neighbours, is_clear)
    if order is not None:
        left = next(group for group in cluster if group not in order)
        return left, [(group, True) for group in reversed(order)]
    # No fully clear order was found: keep every clear move possible and report the others.
    remaining = list(cluster)
    removed: list[tuple[str, bool]] = []
    while len(remaining) > 1:
        # A connected graph always has at least two vertices whose removal keeps it connected.
        free = [g for g in remaining if _stays_connected(g, remaining, neighbours)]
        choice = next((g for g in free if is_clear(g, remaining)), None)
        clear = choice is not None
        chosen = free[0] if choice is None else choice
        remaining.remove(chosen)
        removed.append((chosen, clear))
    removed.reverse()
    return remaining[0], removed


def _clear_order(
    cluster: Sequence[str],
    neighbours: Mapping[str, set[str]],
    is_clear: Callable[[str, Sequence[str]], bool],
) -> list[str] | None:
    """Find an order to take a cluster apart in which every move is clear (r12).

    Depth-first, trying sub-assemblies in piece order, so the result is deterministic. Taking
    off a harmless one can strand another, hence the backtracking; the sets that led nowhere
    are remembered. A loop, not recursion: a cluster can hold thousands of bodies.

    Args:
        cluster: The sub-assemblies, sorted by first piece.
        neighbours: Which sub-assemblies touch on this plane.
        is_clear: Whether one can leave, given those still in place.

    Returns:
        The order to take them off, all but the last one left; ``None`` if there is no such
        order, or none within ``ASSEMBLY_SEARCH_STATES`` states.
    """

    def candidates(current: list[str]) -> Iterator[str]:
        return (
            group
            for group in current
            if _stays_connected(group, current, neighbours) and is_clear(group, current)
        )

    remaining = list(cluster)
    order: list[str] = []
    dead: set[frozenset[str]] = set()
    stack = [candidates(remaining)]
    states = 0
    while len(remaining) > 1:
        for group in stack[-1]:
            rest = [g for g in remaining if g != group]
            if frozenset(rest) in dead:
                continue
            states += 1
            if states > ASSEMBLY_SEARCH_STATES:
                return None
            order.append(group)
            remaining = rest
            stack.append(candidates(rest))
            break
        else:
            dead.add(frozenset(remaining))
            stack.pop()
            if not order:
                return None
            restored = {*remaining, order.pop()}
            remaining = [g for g in cluster if g in restored]
    return order


def _sides(on_plane: Sequence[CutFace], groups: _SubAssemblies) -> dict[str, int]:
    """Which side of the plane each sub-assembly lies on: −1 for neg, +1 for pos."""
    neg = {groups.of(face.piece_neg) for face in on_plane}
    pos = {groups.of(face.piece_pos) for face in on_plane}
    assert not neg & pos, f"I7: a sub-assembly lies on both sides of a plane: {sorted(neg & pos)}"
    return {group: -1 for group in neg} | {group: 1 for group in pos}


def _stays_connected(
    group: str, remaining: Sequence[str], neighbours: Mapping[str, set[str]]
) -> bool:
    rest = [g for g in remaining if g != group]
    allowed = set(rest)
    reached: set[str] = set()
    todo = [rest[0]]
    while todo:
        current = todo.pop()
        if current not in reached:
            reached.add(current)
            todo.extend(neighbours[current] & allowed)
    return len(reached) == len(rest)


def _path_is_clear(
    group: str,
    remaining: Sequence[str],
    sides: Mapping[str, int],
    groups: _SubAssemblies,
    bodies: Mapping[str, Manifold],
    axis: Axis,
    blocked: dict[tuple[str, str, Axis, int], bool],
) -> bool:
    """Whether a sub-assembly can leave the plane with nothing on its own side in the way.

    What lies across the plane can't be in the way: the sub-assembly moves away from it.
    """
    side = sides[group]
    others = [
        piece
        for other in remaining
        if other != group and sides[other] == side
        for piece in groups.members(other)
    ]
    for mover in groups.members(group):
        for other_piece in others:
            key = (mover, other_piece, axis, side)
            if key not in blocked:
                blocked[key] = geometry.blocks_exit(bodies[mover], bodies[other_piece], axis, side)
            if blocked[key]:
                return False
    return True


def _step(
    number: str,
    axis: Axis,
    group: str,
    base: str,
    clear: bool,
    on_plane: Sequence[CutFace],
    groups: _SubAssemblies,
    per_face: Mapping[str, int],
) -> AssemblyStep:
    """Build the step that joins ``group``, which lies on one side of the plane, to ``base``."""
    between = [
        face
        for face in on_plane
        if {groups.of(face.piece_neg), groups.of(face.piece_pos)} == {group, base}
    ]
    group_is_neg = groups.of(between[0].piece_neg) == group
    assert all((groups.of(face.piece_neg) == group) == group_is_neg for face in between), (
        "I7: a join needs two directions"
    )
    group_size, base_size = len(groups.members(group)), len(groups.members(base))
    group_moves = group_size < base_size or (
        group_size == base_size and groups.position(group) > groups.position(base)
    )
    moving, static = (group, base) if group_moves else (base, group)
    towards_plus = group_is_neg == group_moves
    return AssemblyStep(
        number=number,
        axis=axis,
        moving=groups.members(moving),
        static=groups.members(static),
        direction=("+" if towards_plus else "-") + _AXIS_NAMES[axis],
        face_ids=tuple(face.id for face in between),
        connector_count=sum(per_face[face.id] for face in between),
        clear_path=clear,
    )


def _blocked_step(step: AssemblyStep) -> Diagnostic:
    return diagnostic(
        "W013",
        f"step {step.number}: no clear straight path could be shown for "
        f"{', '.join(step.moving)} along {step.direction}; try the move dry before gluing",
        step.moving,
    )


# --- assembly.json -----------------------------------------------------------------------------


def build_document(
    *,
    version: str,
    input_name: str,
    cfg: Config,
    orientation: Orientation,
    layout: Grid,
    pieces: Sequence[Piece],
    faces: Sequence[CutFace],
    placed: Sequence[Connector],
    pins: Sequence[PinCount],
    plan: AssemblyPlan,
    diagnostics: Iterable[Diagnostic],
) -> dict[str, Any]:
    """Return the ``assembly.json`` document (docs/OUTPUT_FORMAT.md), floats already rounded.

    Args:
        version: The tool version.
        input_name: The input's file name, without any folder (ADR-0010).
        cfg: The effective configuration. Only the file name of ``label_font`` is kept, since
            it may be an absolute path.
        orientation: From ``grid.orient``.
        layout: The final grid.
        pieces: The final pieces, in piece order, mm, cutting frame.
        faces: Their cut faces, in face order.
        placed: The connectors, in face and acceptance order.
        pins: The dowel print list, longest first.
        plan: From ``plan_steps``.
        diagnostics: Everything the stages reported, in the order they reported it.

    Returns:
        JSON-ready data: dicts, lists, strings, numbers and ``None``.
    """
    settings = config.as_dict(cfg)
    settings["advanced"]["label_font"] = PureWindowsPath(cfg.advanced.label_font).name
    by_face: dict[str, list[Connector]] = {}
    for connector in placed:
        by_face.setdefault(connector.face_id, []).append(connector)
    face_by_id = {face.id: face for face in faces}
    document = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "tool": {"name": "stlsplit", "version": version},
        "input": {"file_name": input_name},
        "settings": settings,
        "frame": {
            "rotation": orientation.name,
            "input_to_cutting": orientation.input_to_cutting,
        },
        "grid": {
            "usable": layout.usable,
            "counts": layout.counts,
            "extent": layout.extent,
            "planes": {
                name: [plane.offset for plane in planes]
                for name, planes in zip(_AXIS_NAMES, layout.planes, strict=True)
            },
        },
        "pieces": [_piece_record(piece) for piece in pieces],
        "faces": [_face_record(face, by_face.get(face.id, [])) for face in faces],
        "connectors": [_connector_record(c, face_by_id[c.face_id]) for c in placed],
        "pin_groups": [
            {"file": p.file, "diameter": p.diameter, "length": p.length, "quantity": p.quantity}
            for p in pins
        ],
        "steps": [_step_record(step, by_face) for step in plan.steps],
        "separate_parts": plan.groups,
        "diagnostics": [
            {"code": d.code, "severity": d.severity, "message": d.message, "refs": d.refs}
            for d in diagnostics
        ],
    }
    rounded: dict[str, Any] = _rounded(document)
    return rounded


def _piece_record(piece: Piece) -> dict[str, Any]:
    box = piece.body.bounding_box()
    label = piece.label
    return {
        "id": piece.id,
        "file": f"parts/{piece.id}.stl",
        "grid_index": piece.grid_index,
        "volume": piece.body.volume(),
        "bounding_box": {"min": box[:3], "max": box[3:]},
        "face_ids": piece.face_ids,
        "merged_from": piece.merged_from,
        "label": (
            None
            if label is None
            else {"text": label.text, "face_id": label.face_id, "height": label.height}
        ),
    }


def _face_record(face: CutFace, connectors: Sequence[Connector]) -> dict[str, Any]:
    return {
        "id": face.id,
        "axis": face.plane.axis,
        "plane_index": face.plane.index,
        "offset": face.plane.offset,
        "piece_neg": face.piece_neg,
        "piece_pos": face.piece_pos,
        "area": face.region.area,
        "connector_ids": [connector.id for connector in connectors],
    }


def _connector_record(connector: Connector, face: CutFace) -> dict[str, Any]:
    u, v = connector.position_uv
    return {
        "id": connector.id,
        "face_id": connector.face_id,
        "kind": connector.kind,
        "position": geometry.local_point(face.plane.axis, u, v, face.plane.offset),
        "position_uv": connector.position_uv,
        "diameter": connector.diameter,
        "pin_length": connector.pin_length,
        "hole_depth_neg": connector.hole_depth_neg,
        "hole_depth_pos": connector.hole_depth_pos,
    }


def _step_record(step: AssemblyStep, by_face: Mapping[str, Sequence[Connector]]) -> dict[str, Any]:
    used = [connector for face_id in step.face_ids for connector in by_face.get(face_id, [])]
    dowels = Counter((c.diameter, c.pin_length) for c in used if c.kind == "dowel")
    return {
        "number": step.number,
        "stage": step.axis + 1,
        "axis": step.axis,
        "moving": step.moving,
        "static": step.static,
        "direction": step.direction,
        "face_ids": step.face_ids,
        "connector_count": step.connector_count,
        "pegs": sum(c.kind == "peg" for c in used),
        "dowels": [
            {"diameter": diameter, "length": length, "quantity": count}
            for (diameter, length), count in sorted(
                dowels.items(), key=lambda item: (-item[0][1], item[0][0])
            )
        ],
        "glue_only": step.connector_count == 0,
        "clear_path": step.clear_path,
    }


def _rounded(value: Any) -> Any:
    """Copy a document with its floats rounded (§4.1), tuples as lists and no ``-0.0``."""
    if isinstance(value, float):
        return round(value, OUTPUT_DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, Mapping):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(item) for item in value]
    return value


def to_json(document: Mapping[str, Any]) -> str:
    """Return the document as JSON text: ASCII, two-space indent, keys in document order.

    Args:
        document: From ``build_document``.

    Returns:
        The text, ending with a newline.
    """
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


# --- assembly.md -------------------------------------------------------------------------------


def to_markdown(document: Mapping[str, Any]) -> str:
    """Return ``assembly.md``: summary, print list, steps by stage, diagnostics (Phase 9, task 4).

    Diagnostics name their section of ``docs/TROUBLESHOOTING.md`` in plain text: a relative
    link wouldn't resolve from the user's output folder (PLAN.md Appendix E, r12).

    Args:
        document: From ``build_document``.

    Returns:
        The Markdown text, ending with a newline.
    """
    lines = [f"# Assembly of {_escaped(document['input']['file_name'])}", ""]
    tool = document["tool"]
    lines += [f"Written by {tool['name']} {tool['version']}.", ""]
    lines += _summary_lines(document)
    lines += _print_list_lines(document)
    lines += _step_lines(document)
    lines += _separate_part_lines(document)
    lines += _diagnostic_lines(document)
    return "\n".join(lines).rstrip("\n") + "\n"


def _escaped(text: str) -> str:
    """A file name as plain Markdown text, whatever characters it holds."""
    readable = text.encode("utf-8", "backslashreplace").decode("utf-8")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", _CONTROL_CHARACTERS.sub(" ", readable))


def _number(value: float) -> str:
    return f"{value:.{OUTPUT_DECIMALS}f}".rstrip("0").rstrip(".")


def _summary_lines(document: Mapping[str, Any]) -> list[str]:
    counts = " x ".join(str(n) for n in document["grid"]["counts"])
    dowels = sum(group["quantity"] for group in document["pin_groups"])
    return [
        "## Summary",
        "",
        f"- Pieces: {len(document['pieces'])}",
        f"- Grid: {counts}",
        f"- Connectors: {len(document['connectors'])}",
        f"- Dowels to print: {dowels}",
        f"- Assembly steps: {len(document['steps'])}",
        f"- Diagnostics: {len(document['diagnostics'])}",
        "",
    ]


def _print_list_lines(document: Mapping[str, Any]) -> list[str]:
    lines = ["## Print list", "", "### Parts", "", "Print one of each.", ""]
    lines += ["| File | Label | Size (mm) |", "|---|---|---|"]
    for piece in document["pieces"]:
        box = piece["bounding_box"]
        size = " x ".join(
            _number(high - low) for low, high in zip(box["min"], box["max"], strict=True)
        )
        label = piece["label"]["text"] if piece["label"] else "none"
        lines.append(f"| `{piece['file']}` | {label} | {size} |")
    lines.append("")
    if document["pin_groups"]:
        lines += ["### Dowels", "", "Print them lying on their flat side.", ""]
        lines += ["| File | Quantity | Diameter (mm) | Length (mm) |", "|---|---|---|---|"]
        for group in document["pin_groups"]:
            lines.append(
                f"| `{group['file']}` | {group['quantity']} | {_number(group['diameter'])} | "
                f"{_number(group['length'])} |"
            )
        lines.append("")
    return lines


def _step_lines(document: Mapping[str, Any]) -> list[str]:
    lines = ["## Assembly steps", ""]
    steps = document["steps"]
    if not steps:
        return [*lines, "Nothing to assemble.", ""]
    lines += [
        "Directions are the axes of the part files. Do a dry fit of each move before gluing.",
        "",
    ]
    stages = sorted({step["stage"] for step in steps})
    for stage in stages:
        lines += [f"### Stage {stage}: {_STAGE_TITLES[stage - 1]}", ""]
        lines += [_step_line(step) for step in steps if step["stage"] == stage]
        lines.append("")
        if stage != stages[-1]:
            lines += ["Let the glue set before the next stage.", ""]
    return lines


def _step_line(step: Mapping[str, Any]) -> str:
    moving = ", ".join(f"`{piece}`" for piece in step["moving"])
    static = ", ".join(f"`{piece}`" for piece in step["static"])
    line = f"- **{step['number']}** Slide {moving} along {step['direction']} onto {static}. "
    if step["glue_only"]:
        line += "No connector: glue only."
    else:
        held = [f"{d['quantity']} x {_number(d['length'])} mm" for d in step["dowels"]]
        parts = [f"Dowels: {', '.join(held)}"] if held else []
        if step["pegs"]:
            parts.append(f"Pegs: {step['pegs']}")
        line += "; ".join(parts) + "."
    if not step["clear_path"]:
        line += " **No clear path was shown for this move (W013): try it dry first.**"
    return line


def _separate_part_lines(document: Mapping[str, Any]) -> list[str]:
    groups = document["separate_parts"]
    if len(groups) < 2:
        return []
    lines = ["## Separate parts", "", "These groups are never joined to each other:", ""]
    lines += [
        f"{n}. " + ", ".join(f"`{piece}`" for piece in group) for n, group in enumerate(groups, 1)
    ]
    return [*lines, ""]


def _diagnostic_lines(document: Mapping[str, Any]) -> list[str]:
    lines = ["## Diagnostics", ""]
    if not document["diagnostics"]:
        return [*lines, "None.", ""]
    for item in document["diagnostics"]:
        refs = f" IDs: {', '.join(f'`{ref}`' for ref in item['refs'])}." if item["refs"] else ""
        lines.append(
            f"- **{item['code']}** ({item['severity']}): {item['message'].rstrip('.')}.{refs} "
            f"See `{_TROUBLESHOOTING}`, {item['code']}."
        )
    return [*lines, ""]


# --- preview -----------------------------------------------------------------------------------


def preview_items(pieces: Sequence[Piece], layout: Grid, cfg: Config) -> list[PreviewItem]:
    """Lay the pieces out for the exploded preview (PLAN.md Phase 9, task 5).

    Along each axis a piece moves away from the grid's centre by ``preview_spread`` × the
    model's size on that axis, per grid step. Colours cycle through ``PREVIEW_PALETTE`` in piece
    order.

    Args:
        pieces: The final pieces, in piece order, mm, cutting frame.
        layout: The grid.
        cfg: The configuration.

    Returns:
        One item per piece, in the same order.
    """
    spread = cfg.advanced.preview_spread
    items = []
    for number, piece in enumerate(pieces):
        x, y, z = (
            spread * size * (index - (count - 1) / 2)
            for index, count, size in zip(
                piece.grid_index, layout.counts, layout.extent, strict=True
            )
        )
        color = PREVIEW_PALETTE[number % len(PREVIEW_PALETTE)]
        items.append(PreviewItem(piece.id, piece.body, (x, y, z), color))
    return items
