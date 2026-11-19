"""Try-first repair and shell normalization: one valid solid from the loaded mesh.

Second pipeline stage (PLAN.md §5.1), after ``io.load_stl`` and before ``grid.orient``. Input:
the loaded triangle mesh, mm, input frame. Output: one ``Manifold`` in the same frame, and a
``RepairReport`` whose ``reference_volume`` every later volume check uses (I3).

ADR-0007: the mesh is first tried as is, so a valid model is never repaired. Only if that
fails does basic repair run (trimesh), then deep repair (pymeshlab, ``--deep-repair``). Shells
are then normalized by their orientation relative to the shell that contains them:
overlapping solids are unioned (W010), voids are kept at any depth of nesting, inside-out
shells are turned the right way out (W011) (PLAN.md Appendix E, r5). Never
``fix_normals(multibody=True)`` and never a union of every shell: both fill voids.

Guarantees: the returned body has status ``NoError`` and a positive volume (I1), or
``RepairError`` (exit 2) is raised. docs/ALGORITHMS.md, "Repair and shell normalization".
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from manifold3d import Error, Manifold

from stlsplit import geometry
from stlsplit.config import SHELL_OVERLAP_FRACTION, VOID_RESIDUAL_FRACTION, Config
from stlsplit.errors import ConfigError, RepairError, diagnostic
from stlsplit.models import Diagnostic

if TYPE_CHECKING:  # trimesh is only called through geometry's wrappers (ADR-0001)
    import trimesh

_INSTALL_DEEP_REPAIR = 'pip install "stlsplit[deep-repair]"'
_REPAIR_ELSEWHERE = (
    'repair the model in MeshLab or with your slicer\'s "fix model", then run stlsplit again'
)


@dataclass(frozen=True)
class RepairReport:
    """What ``prepare`` found and did.

    Attributes:
        steps: Repair steps that changed the mesh, in the order applied; empty when the mesh
            was valid as is.
        bodies: Separate solids in the result (a void's shell is not a body).
        voids: Internal voids kept.
        inverted: Inside-out shells turned the right way out.
        reference_volume: Volume of the returned body, mm³, measured after ``--simplify``
            since that body is the one cut: the reference of every later volume check (I3).
        diagnostics: W007, W010 and W011 when they apply, in that order.
    """

    steps: tuple[str, ...]
    bodies: int
    voids: int
    inverted: int
    reference_volume: float
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ShellReport:
    """What ``normalize_shells`` found.

    Attributes:
        voids: Voids kept: shells bounding an empty space inside a solid.
        inverted: Shells turned the right way out (their role disagreed with their faces).
        diagnostics: W010 (solids overlapped) and W011 (shells turned), in that order.
    """

    voids: int
    inverted: int
    diagnostics: tuple[Diagnostic, ...]


def prepare(mesh: "trimesh.Trimesh", cfg: Config) -> tuple[Manifold, RepairReport]:
    """Turn the loaded mesh into one valid, normalized solid (PLAN.md Phase 2, ADR-0007).

    1. Try the mesh as is; a valid mesh skips repair entirely.
    2. Otherwise basic repair (``geometry.basic_repair``), then retry; W007 lists the steps.
    3. Still invalid: deep repair with ``--deep-repair``, else ``RepairError``.
    4. Shell normalization (:func:`normalize_shells`).
    5. ``Manifold.simplify(model.simplify)`` when it is > 0.

    Args:
        mesh: The mesh from ``io.load_stl``, mm, input frame.
        cfg: Validated configuration (``repair.deep``, ``model.simplify``).

    Returns:
        The solid, input frame, and the report.

    Raises:
        RepairError: The mesh isn't a closed solid after the repairs allowed (the message
            gives the open-edge, non-manifold-edge and body counts, and what to try), or it
            encloses no volume.
        ConfigError: ``--simplify`` removed the whole model (exit 1, naming the option).
    """
    steps: list[str] = []
    body = geometry.to_manifold(mesh)
    if body.status() != Error.NoError:
        mesh, basic_steps = geometry.basic_repair(mesh)
        steps.extend(basic_steps)
        body = geometry.to_manifold(mesh)
    if body.status() != Error.NoError:
        body = _deep_repair(mesh, cfg)
        steps.append("deep repair with pymeshlab")
    diagnostics: list[Diagnostic] = []
    if steps:
        diagnostics.append(diagnostic("W007", "the mesh was repaired: " + "; ".join(steps)))

    body, shells = normalize_shells(body)
    diagnostics.extend(shells.diagnostics)
    if body.is_empty() or body.volume() <= 0:
        raise RepairError(
            "the mesh encloses no volume (a flat or zero-thickness surface?); " + _REPAIR_ELSEWHERE
        )
    if cfg.model.simplify > 0:
        body = body.simplify(cfg.model.simplify)
        if body.is_empty() or body.volume() <= 0:
            raise ConfigError(
                "model.simplify",
                f"a tolerance of {cfg.model.simplify:g} mm removed the whole model; use a "
                "smaller one (surfaces move by less than the tolerance)",
            )
    volume = body.volume()
    if body.status() != Error.NoError:  # I1; manifold3d results are always valid
        raise AssertionError(f"prepared body has status {body.status()}")
    report = RepairReport(
        steps=tuple(steps),
        bodies=sum(1 for shell in body.decompose() if shell.volume() > 0),  # not voids
        voids=shells.voids,
        inverted=shells.inverted,
        reference_volume=volume,
        diagnostics=tuple(diagnostics),
    )
    return body, report


def normalize_shells(body: Manifold) -> tuple[Manifold, ShellReport]:
    """Normalize the shells of a valid manifold into one solid (ADR-0007).

    A single shell facing outwards (positive volume) is returned untouched. Otherwise every
    shell from ``decompose()`` gets a role, from its orientation relative to the smallest
    shell that contains it (:func:`_roles`):

    - an outermost shell is solid; one facing inwards is turned the right way out (W011),
      unless it lies inside the union of the outermost solids: then it is a void spanning
      several overlapping solids;
    - a nested shell facing the same way as its container plays the same role (a part
      embedded in a solid, a void inside a void); facing the other way, the opposite role (a
      void in a solid, a ball in that void, a void in that ball, and so on).

    Each solid shell, minus the voids it directly contains, is one piece. The result is the
    union of the pieces (W010 when they overlap), minus the spanning voids, plus the pieces
    that lie inside a spanning void. A void is thus only ever subtracted from the shell that
    holds it, so overlapping hollow parts keep their walls. The roles don't depend on a shell
    being oriented like the file's other shells, so a model inside out as a whole keeps its
    voids.

    Args:
        body: A valid manifold (status ``NoError``), mm, any frame.

    Returns:
        The normalized solid, same frame, and the report.
    """
    shells = body.decompose()
    if len(shells) <= 1 and body.volume() > 0:
        return body, ShellReport(voids=0, inverted=0, diagnostics=())
    outward = [shell.volume() > 0 for shell in shells]
    solids = [
        shell if out else geometry.reverse_winding(shell)
        for shell, out in zip(shells, outward, strict=True)
    ]
    parents = _parents(solids)
    solid = _roles(solids, outward, parents)
    count = len(solids)

    def spanning(index: int) -> bool:
        return parents[index] is None and not solid[index]

    def under_spanning(index: int) -> bool:
        parent = parents[index]
        while parent is not None:
            if spanning(parent):
                return True
            parent = parents[parent]
        return False

    pieces: list[Manifold] = []
    late: list[Manifold] = []  # pieces inside a spanning void, added after it is subtracted
    for index in range(count):
        if not solid[index]:
            continue
        own_voids = [solids[v] for v in range(count) if parents[v] == index and not solid[v]]
        piece = solids[index] - geometry.union_all(own_voids) if own_voids else solids[index]
        (late if under_spanning(index) else pieces).append(piece)
    merged = geometry.union_all(pieces + late)
    spanning_voids = [solids[index] for index in range(count) if spanning(index)]
    result = merged
    if spanning_voids:
        result = geometry.union_all(
            [geometry.union_all(pieces) - geometry.union_all(spanning_voids), *late]
        )

    def holds_space(index: int) -> bool:  # a void inside a void adds nothing
        parent = parents[index]
        return not solid[index] and (parent is None or solid[parent])

    voids = sum(1 for index in range(count) if holds_space(index))
    inverted = sum(1 for index in range(count) if solid[index] != outward[index])
    diagnostics: list[Diagnostic] = []
    total = sum(piece.volume() for piece in pieces + late)
    if total - merged.volume() > SHELL_OVERLAP_FRACTION * total:
        diagnostics.append(
            diagnostic(
                "W010",
                f"overlapping shells were merged: {len(pieces) + len(late)} solids of "
                f"{total:.10g} mm^3 in all make {merged.volume():.10g} mm^3 once unioned",
            )
        )
    if inverted:
        diagnostics.append(
            diagnostic(
                "W011",
                f"{inverted} inside-out shell{' was' if inverted == 1 else 's were'} turned "
                "the right way out (faces pointing inwards); check that the model looks as "
                "expected",
            )
        )
    return result, ShellReport(voids=voids, inverted=inverted, diagnostics=tuple(diagnostics))


def _parents(solids: list[Manifold]) -> list[int | None]:
    """Return the index of the smallest shell containing each shell; ``None`` if outermost.

    Containment is tested on the shells as solids (all facing outwards). Two identical
    shells contain each other: the one listed first counts as the container, so there is no
    cycle. Bounding boxes and volumes rule out most pairs before any boolean.
    """
    volumes = np.array([solid.volume() for solid in solids])
    boxes = np.array([solid.bounding_box() for solid in solids])
    parents: list[int | None] = []
    for index, solid in enumerate(solids):
        candidates = np.flatnonzero(
            (boxes[:, :3] <= boxes[index, :3]).all(axis=1)
            & (boxes[:, 3:] >= boxes[index, 3:]).all(axis=1)
            & (volumes >= volumes[index] * (1.0 - VOID_RESIDUAL_FRACTION))
        )
        containers = []
        for other in (int(c) for c in candidates):
            if other == index or not _inside(solid, solids[other]):
                continue
            same_size = volumes[other] <= volumes[index] * (1.0 + VOID_RESIDUAL_FRACTION)
            if other > index and same_size and _inside(solids[other], solid):
                continue  # identical shells: the first one is the container
            containers.append(other)
        smallest = min(containers, key=lambda other: (volumes[other], other), default=None)
        parents.append(smallest)
    return parents


def _roles(solids: list[Manifold], outward: list[bool], parents: list[int | None]) -> list[bool]:
    """Return whether each shell bounds solid material (True) or a void (False).

    See :func:`normalize_shells`. Containers are decided before the shells they contain.
    """
    outermost_solids = geometry.union_all(
        [solids[i] for i in range(len(solids)) if parents[i] is None and outward[i]]
    )
    roles: dict[int, bool] = {}
    for index in sorted(range(len(solids)), key=lambda i: (_depth(parents, i), i)):
        parent = parents[index]
        if parent is None:
            roles[index] = outward[index] or not _inside(solids[index], outermost_solids)
        elif outward[index] == outward[parent]:
            roles[index] = roles[parent]
        else:
            roles[index] = not roles[parent]
    return [roles[index] for index in range(len(solids))]


def _depth(parents: list[int | None], index: int) -> int:
    depth, parent = 0, parents[index]
    while parent is not None:
        depth += 1
        if depth > len(parents):  # _parents never builds a cycle
            raise AssertionError("cycle in shell containment")
        parent = parents[parent]
    return depth


def _inside(shell: Manifold, container: Manifold) -> bool:
    """Whether ``shell`` lies inside ``container``, up to ``VOID_RESIDUAL_FRACTION``."""
    return bool((shell - container).volume() <= VOID_RESIDUAL_FRACTION * shell.volume())


def _deep_repair(mesh: "trimesh.Trimesh", cfg: Config) -> Manifold:
    """Run deep repair if allowed and possible; raise ``RepairError`` otherwise."""
    if not cfg.repair.deep:
        raise _unrepairable(
            mesh,
            "after basic repair",
            f"Try --deep-repair (needs {_INSTALL_DEEP_REPAIR}), or {_REPAIR_ELSEWHERE}",
        )
    if not geometry.deep_repair_available():
        raise _unrepairable(
            mesh,
            "after basic repair",
            f"--deep-repair needs pymeshlab: {_INSTALL_DEEP_REPAIR}",
        )
    repaired = geometry.deep_repair(mesh)
    if repaired is not None:
        body = geometry.to_manifold(repaired)
        if body.status() == Error.NoError:
            return body
    stage = "after deep repair" if repaired is not None else "and pymeshlab refused to repair it"
    raise _unrepairable(repaired if repaired is not None else mesh, stage, _REPAIR_ELSEWHERE)


def _unrepairable(mesh: "trimesh.Trimesh", stage: str, hint: str) -> RepairError:
    defects = geometry.mesh_defects(mesh)
    return RepairError(
        f"the mesh isn't a closed solid {stage}: "
        f"{_count(defects.open_edges, 'open edge')}, "
        f"{_count(defects.non_manifold_edges, 'non-manifold edge')}, "
        f"{_count(defects.bodies, 'body', 'bodies')}. {hint[0].upper()}{hint[1:]}"
    )


def _count(number: int, singular: str, plural: str | None = None) -> str:
    return f"{number} {singular if number == 1 else plural or singular + 's'}"
