"""Every model of the end-to-end suite, with its arguments and its exit code (PLAN.md Phase 11).

Most catalogue fixtures (PLAN.md Appendix D) fit the default bed, and a model that isn't cut
proves nothing about holes. So each case carries the arguments that make it reach what it is
for: a ``--scale`` in most cases, or a bed that puts a plane exactly where the fixture needs it.
``codes`` and ``reaches`` are checked, so a case can't silently stop testing its purpose.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import trimesh
from manifold3d import Manifold

from stlsplit.errors import ExitCode
from tests import conftest as fixtures
from tests.e2e.properties import VOLUME_TOLERANCE

REAL_MODELS = Path(__file__).resolve().parents[1] / "fixtures" / "real"

Model = Callable[[], Manifold | trimesh.Trimesh] | Path
Document = dict[str, Any]

WOVEN = (
    "--bed", "20", "200", "200", "--no-auto-orient", "--connector", "none", "--no-label",
)  # fmt: skip
"""One plane at x = 10, for the fixtures of the assembly order."""

CROSSED = (
    "--bed", "40", "300", "300", "--no-auto-orient", "--connector", "none", "--no-label",
)  # fmt: skip
"""One plane at x = 25, through the four crossings of ``crossed_loop``."""

KNOB_BED = ("--bed", "120", "120", "220", "--no-auto-orient")
"""With ``NO_NUDGE``, planes at x = 100 and y = 100: x = 100 leaves the knob's tip on its own."""

NO_NUDGE = "[advanced]\nnudge_window = 0.0\n"
"""The nudge window has no CLI flag, so these cases pass a ``--config`` file."""

STEP_BED = ("--bed", "200", "200", "20", "--no-auto-orient")
"""Planes every 10 mm along Z: one lies exactly on the step of the step fixtures."""

PEG = ("--connector", "peg")

SIMPLIFY_VOLUME_TOLERANCE = 5e-3
"""``--simplify`` moves surfaces, so the model's volume is only known to 0.5 %."""


@dataclass(frozen=True)
class Case:
    """One run of the CLI.

    Attributes:
        name: The test ID.
        model: A function building the mesh, or a committed STL file.
        arguments: The CLI arguments after the input and ``-o``.
        exit_code: The exit code the run must give.
        codes: Diagnostics the run must report (it may report others).
        toml: Content of a ``--config`` file, if the run needs one.
        volume: The model's true volume before ``--scale``, mm³, for a mesh that needs repair.
            A valid solid or a committed file gets it from its own geometry.
        volume_tolerance: How far the run's reference volume may be from the true one.
        reaches: Whether ``assembly.json`` shows that the run did what the fixture is for.
        needs_deep_repair: The run needs the optional ``deep-repair`` extra.
    """

    name: str
    model: Model
    arguments: tuple[str, ...] = ()
    exit_code: ExitCode = ExitCode.SUCCESS
    codes: frozenset[str] = frozenset()
    toml: str = ""
    volume: float | Callable[[], float] | None = None
    volume_tolerance: float = VOLUME_TOLERANCE
    reaches: Callable[[Document], bool] | None = None
    needs_deep_repair: bool = False

    @property
    def scale(self) -> float:
        if "--scale" not in self.arguments:
            return 1.0
        return float(self.arguments[self.arguments.index("--scale") + 1])


def true_volume(item: Case) -> float:
    """Return the model's volume at its scale, mm³, worked out without stlsplit's repair."""
    if item.volume is not None:
        base = item.volume() if callable(item.volume) else item.volume
    elif isinstance(item.model, Path):
        base = float(trimesh.load(item.model, force="mesh").volume)  # voids count as negative
    else:
        body = item.model()
        assert isinstance(body, Manifold), f"{item.name}: a broken mesh needs its true volume"
        base = body.volume()
    return float(base) * item.scale**3


def scaled(factor: float, *arguments: str) -> tuple[str, ...]:
    return ("--scale", str(factor), *arguments)


def case(
    name: str,
    model: Model,
    arguments: tuple[str, ...] = (),
    exit_code: ExitCode = ExitCode.SUCCESS,
    *codes: str,
    toml: str = "",
    volume: float | Callable[[], float] | None = None,
    volume_tolerance: float = VOLUME_TOLERANCE,
    reaches: Callable[[Document], bool] | None = None,
) -> Case:
    return Case(
        name,
        model,
        arguments,
        exit_code,
        frozenset(codes),
        toml,
        volume,
        volume_tolerance,
        reaches,
    )


def full_cells() -> Manifold:
    """A 400 mm box: in peg mode, two cells of exactly U = 200, one with its pegs (210 mm)."""
    return Manifold.cube((400.0, 100.0, 100.0))


def hollow_volume() -> float:
    return fixtures.hollow_sphere().volume()


def nested_volume() -> float:
    """The hollow sphere, plus the ball r = 100 in its void, minus the void r = 50 in the ball."""
    ball = Manifold.sphere(100.0, fixtures.SPHERE_SEGMENTS)
    void = Manifold.sphere(50.0, fixtures.SPHERE_SEGMENTS)
    return fixtures.hollow_sphere().volume() + ball.volume() - void.volume()


def overlapping_hollow_volume() -> float:
    first = fixtures.hollow_sphere()
    return (first + first.translate((200.0, 0.0, 0.0))).volume()


def has_suffixed_pieces(document: Document) -> bool:
    return any(re.search(r"-[a-z]+$", piece["id"]) for piece in document["pieces"])


def has_merged_piece(document: Document) -> bool:
    return any(piece["merged_from"] for piece in document["pieces"])


def has_no_merged_piece(document: Document) -> bool:
    return not has_merged_piece(document)


def has_face(axis: int, offset: float, area: float) -> Callable[[Document], bool]:
    """Whether a cut face lies on this plane with this contact area (mm, mm²)."""

    def reaches(document: Document) -> bool:
        return any(
            face["axis"] == axis
            and math.isclose(face["offset"], offset, abs_tol=1e-6)
            and math.isclose(face["area"], area, rel_tol=1e-3)
            for face in document["faces"]
        )

    return reaches


def has_connectors_in_both_arms(document: Document) -> bool:
    """``wide_u_shape``: its arms span x from 0 to 20 and from 80 to 100."""
    xs = [item["position"][0] for item in document["connectors"]]
    return any(x < 20.0 for x in xs) and any(x > 80.0 for x in xs)


SUCCESS = ExitCode.SUCCESS
PARTIAL = ExitCode.PARTIAL
UNREPAIRABLE = ExitCode.UNREPAIRABLE

CASES: tuple[Case, ...] = (
    # Plain solids.
    case("cube_fits", fixtures.cube, (), SUCCESS, "W012"),
    case("cube", fixtures.cube, scaled(35)),
    case("long_box", fixtures.long_box),
    case("cylinder", fixtures.cylinder),
    case("torus", fixtures.torus, scaled(2.4)),
    case(
        "two_bodies",
        fixtures.two_bodies,
        scaled(12, "--bed", "400", "70", "400", "--no-auto-orient"),
        reaches=has_suffixed_pieces,
    ),
    case("box_with_bubble", fixtures.box_with_bubble),
    case("chiral_l", fixtures.chiral_l, scaled(9)),
    case(
        "dense_sphere",
        fixtures.dense_sphere,
        scaled(3, "--simplify", "0.05", "--bed", *["120"] * 3),
        volume_tolerance=SIMPLIFY_VOLUME_TOLERANCE,
    ),
    # Meshes that need repair or shell normalization.
    case("soup_cube", fixtures.soup_cube, scaled(35), volume=1000.0),
    case(
        "missing_face_cube",
        fixtures.missing_face_cube,
        scaled(35),
        SUCCESS,
        "W007",
        volume=1000.0,
    ),
    case("capless_sphere", fixtures.capless_sphere, scaled(9), UNREPAIRABLE),
    case("finned_cube", fixtures.finned_cube, scaled(23), UNREPAIRABLE),
    case("flat_sheet", fixtures.flat_sheet, scaled(35), UNREPAIRABLE),
    case(
        "edge_touching_cubes",
        fixtures.edge_touching_cubes,
        scaled(18),
        SUCCESS,
        "W008",
        volume=2000.0,
    ),
    case(
        "overlapping_shells",
        fixtures.overlapping_shells,
        scaled(12),
        SUCCESS,
        "W010",
        volume=12000.0,
    ),
    case("inverted_body", fixtures.inverted_body, scaled(12), SUCCESS, "W011", volume=2000.0),
    case("inside_out_cube", fixtures.inside_out_cube, scaled(35), SUCCESS, "W011", volume=1000.0),
    case("embedded_cube", fixtures.embedded_cube, scaled(18), SUCCESS, "W010", volume=8000.0),
    case(
        "void_across_two_cubes",
        fixtures.void_across_two_cubes,
        scaled(12),
        SUCCESS,
        "W010",
        volume=11680.0,
    ),
    case(
        "void_across_two_cubes_with_a_body",
        lambda: fixtures.void_across_two_cubes(body_inside=True),
        scaled(12),
        SUCCESS,
        "W010",
        volume=11688.0,
    ),
    case("duplicated_cube", fixtures.duplicated_cube, scaled(35), SUCCESS, "W010", volume=1000.0),
    case(
        "duplicated_cube_inside_out",
        lambda: fixtures.duplicated_cube(inside_out=True),
        scaled(35),
        SUCCESS,
        "W010",
        "W011",
        volume=1000.0,
    ),
    # Hollow models: their thin walls have no room for a connector.
    case("hollow_sphere", fixtures.hollow_sphere, (), PARTIAL, "W001"),
    case("ball_in_hollow_sphere", fixtures.ball_in_hollow_sphere, (), PARTIAL, "W001"),
    case(
        "void_in_ball_in_hollow_sphere",
        fixtures.void_in_ball_in_hollow_sphere,
        (),
        PARTIAL,
        "W001",
        volume=nested_volume,
    ),
    case(
        "inside_out_hollow_sphere",
        fixtures.inside_out_hollow_sphere,
        (),
        PARTIAL,
        "W011",
        volume=hollow_volume,
    ),
    case(
        "hollow_sphere_flipped_outer_triangle",
        lambda: fixtures.hollow_sphere_with_a_flipped_triangle(0),
        (),
        PARTIAL,
        "W007",
        volume=hollow_volume,
    ),
    case(
        "hollow_sphere_flipped_void_triangle",
        lambda: fixtures.hollow_sphere_with_a_flipped_triangle(1),
        (),
        PARTIAL,
        "W007",
        volume=hollow_volume,
    ),
    case(
        "overlapping_hollow_spheres",
        fixtures.overlapping_hollow_spheres,
        (),
        PARTIAL,
        "W010",
        volume=overlapping_hollow_volume,
    ),
    # Shapes that test the cut faces, the connectors and the nudging.
    case("tall_figure", fixtures.tall_figure, (), PARTIAL, "W001"),
    case(
        "plinth_step",
        fixtures.plinth_step,
        STEP_BED,
        PARTIAL,
        "W001",
        reaches=has_face(2, 10.0, 100.0),
    ),
    case(
        "overhang_step",
        fixtures.overhang_step,
        STEP_BED,
        PARTIAL,
        "W001",
        reaches=has_face(2, 10.0, 100.0),
    ),
    case(
        "knob",
        fixtures.knob_on_grid,
        KNOB_BED,
        SUCCESS,
        "W005",
        toml=NO_NUDGE,
        reaches=has_merged_piece,
    ),
    case(
        "knob_blocked",
        lambda: fixtures.knob_on_grid(blocked=True),
        KNOB_BED,
        PARTIAL,  # the tip stays on its own, and its 36 mm² face has no room for a connector
        "W001",
        "W004",
        toml=NO_NUDGE,
        reaches=has_no_merged_piece,
    ),
    case(
        "knob_rounded",
        lambda: fixtures.knob_on_grid(rounded=True),
        KNOB_BED,
        SUCCESS,
        "W005",
        toml=NO_NUDGE,
        reaches=has_merged_piece,
    ),
    case(
        "u_shape",
        fixtures.u_shape,
        ("--bed", "200", "20", "200", "--no-auto-orient"),
        PARTIAL,
        "W001",
        reaches=has_face(1, 10.0, 1400.0),
    ),
    case(
        "wide_u_shape",
        fixtures.wide_u_shape,
        ("--bed", "200", "40", "200", "--no-auto-orient"),
        reaches=has_connectors_in_both_arms,
    ),
    case("wedge", fixtures.wedge, scaled(4.5)),
    # The assembly order.
    case("crossed_loop", fixtures.crossed_loop, CROSSED),
    case("hooked_strips", fixtures.hooked_strips, WOVEN),
    case("interlocked_bodies", fixtures.interlocked_bodies, WOVEN, PARTIAL, "W013"),
    # Extreme models.
    case("many_bodies", fixtures.many_bodies, (), PARTIAL, "W001", "W008"),
    case("thin_plate", fixtures.thin_plate, (), PARTIAL, "W001"),
    case("finned_block", fixtures.finned_block),
    case("slit_block", fixtures.slit_block, (), PARTIAL, "W001"),
    # Pegs, on a few models of each kind: they stick out of their cell.
    case("full_cells_with_pegs", full_cells, ("--no-auto-orient", *PEG)),
    case("cube_with_pegs", fixtures.cube, scaled(35, *PEG)),
    case("torus_with_pegs", fixtures.torus, scaled(2.4, *PEG)),
    case("wide_u_shape_with_pegs", fixtures.wide_u_shape, scaled(3.5, *PEG)),
    case("overhang_step_with_pegs", fixtures.overhang_step, scaled(9, *PEG)),
    case(
        "knob_with_pegs",
        fixtures.knob_on_grid,
        ("--bed", "130", "130", "220", "--no-auto-orient", *PEG),  # U = 110, as with dowels
        SUCCESS,
        "W005",
        toml=NO_NUDGE,
        reaches=has_merged_piece,
    ),
    case(
        "knob_too_long_to_merge_with_pegs",
        fixtures.knob_on_grid,
        (*KNOB_BED, *PEG),  # U = 100: the merged piece would be 105 mm long
        PARTIAL,
        "W001",
        "W004",
        toml=NO_NUDGE,
        reaches=has_no_merged_piece,
    ),
    # Real scans (tests/fixtures/README.md).
    case("discobolus", REAL_MODELS / "discobolus.stl", scaled(3), PARTIAL, "W001"),
    case("zeus_artemision", REAL_MODELS / "zeus_artemision.stl", scaled(3), PARTIAL, "W001"),
    case("memnon", REAL_MODELS / "memnon.stl", scaled(3)),
    case("memnon_with_pegs", REAL_MODELS / "memnon.stl", scaled(3, *PEG)),
    Case(
        "finned_cube_deep_repair",
        fixtures.finned_cube,
        scaled(23, "--deep-repair"),
        SUCCESS,
        frozenset({"W007"}),
        volume=1000.0,
        needs_deep_repair=True,
    ),
)

WRITING_CASES = tuple(item for item in CASES if item.exit_code != UNREPAIRABLE)
"""The runs that write their outputs."""

REFUSED_CASES = tuple(item for item in CASES if item.exit_code == UNREPAIRABLE)
"""The runs that stop before writing anything."""
