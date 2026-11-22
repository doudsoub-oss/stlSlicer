"""The global properties of a split, checked on the files it wrote (PLAN.md Phase 11, task 2).

Each ``assert_*`` reads the output folder rather than the pipeline's objects, so it sees what a
user would print. ``tests/e2e/test_property_checks.py`` proves that each one can fail.
"""

import hashlib
import itertools
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh
from shapely.geometry import Polygon

from stlsplit import config, connectors, labels, tools
from stlsplit import io as stl_io
from stlsplit.config import Config
from stlsplit.models import Connector, CutFace, Plane

FIT_TOLERANCE = 1e-3
"""mm: STL coordinates are float32, which rounds by up to about 1e-4 mm at these sizes."""

VOLUME_TOLERANCE = 1e-4
"""0.01 % of the reference volume. Stricter than the 0.5 % of the plan (r15): the worst error
measured over every case is 0.0001 %, and 0.5 % of a 300 mm cube is a whole 51 mm block."""

GAP_TOLERANCE = 1e-5
"""mm: positions in ``assembly.json`` are rounded to 6 decimals."""

PROBE_SCALE = 0.9
"""A hole or peg is probed at 90 % of its size, so that float noise on its walls doesn't count."""

MISPLACED_FRACTION = 1e-3
"""The share of a probe that may lie on the wrong side of a piece's surface."""

SLEEVE_SCALE = 1.3
"""The sleeve around a hole: the hole at 130 % of its size, minus the hole."""

MIN_SLEEVE_MATERIAL = 0.5
"""The share of a sleeve that must be material. An empty hole alone proves nothing, since a
hole recorded outside its piece is empty too. The lowest share over every case is 0.78."""


def _solid(mesh: trimesh.Trimesh) -> Manifold:
    return Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )


def _resized(solid: Manifold, factor: float) -> Manifold:
    """Scale a solid about the centre of its bounding box."""
    box = solid.bounding_box()
    centre = ((box[0] + box[3]) / 2, (box[1] + box[4]) / 2, (box[2] + box[5]) / 2)
    back = (-centre[0], -centre[1], -centre[2])
    return solid.translate(back).scale(factor).translate(centre)


@dataclass(frozen=True)
class Placed:
    """A connector of ``assembly.json``, rebuilt as the objects the tools take."""

    connector: Connector
    face: CutFace


@dataclass(frozen=True)
class Split:
    """The output folder of one run.

    Attributes:
        out: The folder.
        stderr: The run's log, which holds the reference volume in its ``model:`` line.
    """

    out: Path
    stderr: str

    @cached_property
    def document(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.out / "assembly.json").read_text("utf-8"))
        return loaded

    @cached_property
    def cfg(self) -> Config:
        return config.from_mapping(self.document["settings"], "assembly.json")

    @cached_property
    def reference_volume(self) -> float:
        match = re.search(r"volume ([0-9.e+-]+) mm\^3", self.stderr)
        assert match, "no reference volume in the log"
        return float(match[1])

    @cached_property
    def meshes(self) -> dict[str, trimesh.Trimesh]:
        return {
            piece["id"]: trimesh.load(self.out / piece["file"], force="mesh")
            for piece in self.document["pieces"]
        }

    @cached_property
    def solids(self) -> dict[str, Manifold]:
        return {name: _solid(mesh) for name, mesh in self.meshes.items()}

    @cached_property
    def placed(self) -> list[Placed]:
        faces = {
            face["id"]: CutFace(
                id=face["id"],
                plane=Plane(axis=face["axis"], index=face["plane_index"], offset=face["offset"]),
                piece_neg=face["piece_neg"],
                piece_pos=face["piece_pos"],
                region=Polygon(),  # the holes and pegs are built from the plane alone
            )
            for face in self.document["faces"]
        }
        return [
            Placed(
                Connector(
                    id=item["id"],
                    face_id=item["face_id"],
                    kind=item["kind"],
                    position_uv=(item["position_uv"][0], item["position_uv"][1]),
                    diameter=item["diameter"],
                    pin_length=item["pin_length"],
                    hole_depth_neg=item["hole_depth_neg"],
                    hole_depth_pos=item["hole_depth_pos"],
                ),
                faces[item["face_id"]],
            )
            for item in self.document["connectors"]
        ]

    def holes(self) -> Iterator[tuple[str, str, Manifold]]:
        """Yield (piece ID, connector ID, hole solid) for every hole, real size."""
        for item in self.placed:
            for piece, solid in connectors.hole_solids(item.connector, item.face, self.cfg):
                yield piece, item.connector.id, solid

    def pegs(self) -> Iterator[tuple[str, str, Manifold]]:
        """Yield (piece ID, connector ID, peg solid) for every peg, on its neg piece."""
        for item in self.placed:
            if item.connector.kind == "peg":
                solid = tools.peg_solid(item.connector, item.face, self.cfg)
                yield item.face.piece_neg, item.connector.id, solid


def assert_watertight(split: Split) -> None:
    """Property 1: every piece is one closed, consistently wound, valid solid."""
    for name, mesh in split.meshes.items():
        assert mesh.is_watertight, f"{name} is not watertight"
        assert mesh.is_winding_consistent, f"{name} has inconsistent winding"
        assert split.solids[name].status().name == "NoError", f"{name} is not a valid solid"


def assert_fits(split: Split) -> None:
    """Property 2 (r15): a piece fits U, or bed − 2·margin when it carries a peg."""
    limits = config.derived(split.cfg)
    pegged = {piece for piece, _, _ in split.pegs()}
    for name, mesh in split.meshes.items():
        limit = np.array(limits.printable if name in pegged else limits.usable)
        over = mesh.extents - limit
        assert np.all(over <= FIT_TOLERANCE), f"{name}: {mesh.extents} doesn't fit {limit}"


def assert_volume_balance(split: Split) -> None:
    """Property 3: pieces + what the tools removed − the pegs = the reference volume.

    ``assembly.json`` has no label outline, but an engraving's volume doesn't depend on where it
    is: the area of the text at its recorded height, times the engraving depth.
    """
    pieces = sum(solid.volume() for solid in split.solids.values())
    holes = sum(solid.volume() for _, _, solid in split.holes())
    pegs = sum(solid.volume() for _, _, solid in split.pegs())
    font = stl_io.resolve_label_font(split.cfg.advanced.label_font)
    engraved = sum(
        labels.text_outline(piece["label"]["text"], piece["label"]["height"], font).area()
        * split.cfg.labels.depth
        for piece in split.document["pieces"]
        if piece["label"]
    )
    reference = split.reference_volume
    error = abs(pieces + holes + engraved - pegs - reference) / reference
    assert error <= VOLUME_TOLERANCE, f"volumes are off by {100 * error:.5f} %"


def assert_reference_volume(
    split: Split, expected: float, tolerance: float = VOLUME_TOLERANCE
) -> None:
    """The run started from the model's true volume, so repair filled no void.

    The volume balance can't see that: its reference comes from the run's own log, after repair.

    Args:
        split: The run.
        expected: The model's volume at its scale, worked out without stlsplit's repair, mm³.
        tolerance: The relative error allowed.
    """
    error = abs(split.reference_volume - expected) / expected
    assert error <= tolerance, (
        f"reference volume {split.reference_volume} is not the model's {expected}"
    )


def assert_holes_line_up(split: Split) -> None:
    """Property 4: at every connector, both written pieces have their hole or peg in place."""
    for piece, name, hole in split.holes():
        probe = _resized(hole, PROBE_SCALE)
        material = (split.solids[piece] ^ probe).volume()
        assert material <= MISPLACED_FRACTION * probe.volume(), f"{name}: no hole in {piece}"
        sleeve = _resized(hole, SLEEVE_SCALE) - hole
        around = (split.solids[piece] ^ sleeve).volume()
        assert around >= MIN_SLEEVE_MATERIAL * sleeve.volume(), (
            f"{name}: no material around its hole in {piece}"
        )
    for piece, name, peg in split.pegs():
        probe = _resized(peg, PROBE_SCALE)
        missing = (probe - split.solids[piece]).volume()
        assert missing <= MISPLACED_FRACTION * probe.volume(), f"{name}: no peg on {piece}"


def assert_hole_gaps(split: Split) -> None:
    """Property 5: no two holes of a piece are closer than ``min_wall``."""
    wall = split.cfg.connectors.min_wall
    by_piece: dict[str, list[tuple[str, Manifold]]] = {}
    for piece, name, solid in split.holes():
        by_piece.setdefault(piece, []).append((name, solid))
    for piece, holes in by_piece.items():
        for (first, a), (second, b) in itertools.combinations(holes, 2):
            gap = a.min_gap(b, wall + 1.0)
            assert gap >= wall - GAP_TOLERANCE, f"{piece}: {first} and {second} are {gap} mm apart"


def output_digest(out: Path) -> dict[str, str]:
    """Property 6: the SHA-256 of every file of the output folder, by relative path."""
    return {
        path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }
