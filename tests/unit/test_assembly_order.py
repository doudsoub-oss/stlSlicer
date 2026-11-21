"""Phase 9: the assembly order (PLAN.md Phase 9, ADR-0004).

Most tests use synthetic models: 10 mm cubes on the cells of a grid, with one cut face between
two neighbours, so any contact graph a grid can produce is cheap to build.
"""

from collections.abc import Iterable, Sequence

from hypothesis import given
from hypothesis import strategies as st
from manifold3d import Manifold, OpType
from shapely.geometry import box

from stlsplit import assembly
from stlsplit.models import Axis, Connector, CutFace, Piece, Plane

Cell = tuple[int, int, int]

SIZE = 10.0
"""Side of a synthetic cell, mm."""
AXES: tuple[Axis, Axis, Axis] = (0, 1, 2)


def cell_id(cell: Cell) -> str:
    i, j, k = cell
    return f"X{i}-Y{j}-Z{k}"


def solid(low: Sequence[float], high: Sequence[float]) -> Manifold:
    x0, y0, z0 = low
    x1, y1, z1 = high
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def face(neg: str, pos: str, axis: Axis, index: int, offset: float, number: int = 1) -> CutFace:
    repeat = f"#{number}" if number > 1 else ""
    region = box(0.0, 0.0, 1.0, 1.0)
    return CutFace(f"{neg}~{pos}{repeat}", Plane(axis, index, offset), neg, pos, region)


def synthetic(cells: Iterable[Cell]) -> tuple[list[Piece], list[CutFace]]:
    """One cube per cell and one face per pair of neighbours, in piece and face order."""
    ordered = sorted(set(cells))
    present = set(ordered)
    pieces = [
        Piece(
            cell_id(cell),
            cell,
            solid([v * SIZE for v in cell], [(v + 1) * SIZE for v in cell]),
            [],
            [],
        )
        for cell in ordered
    ]
    faces: list[CutFace] = []
    for axis in AXES:
        for index in range(max((cell[axis] for cell in ordered), default=0)):
            for neg in ordered:
                pos = tuple(v + 1 if a == axis else v for a, v in enumerate(neg))
                if neg[axis] == index and pos in present:
                    offset = (index + 1) * SIZE
                    faces.append(face(cell_id(neg), cell_id(pos), axis, index, offset))  # type: ignore[arg-type]
    return pieces, faces


def dowels(faces: Iterable[CutFace], per_face: int = 1) -> list[Connector]:
    return [
        Connector(f"{f.id}/c{n}", f.id, "dowel", (0.5, 0.5), 5.0, 20.0, 10.5, 10.5)
        for f in faces
        for n in range(1, per_face + 1)
    ]


def connected_groups(pieces: Sequence[Piece], faces: Sequence[CutFace]) -> set[frozenset[str]]:
    groups = {piece.id: frozenset({piece.id}) for piece in pieces}
    for f in faces:
        joined = groups[f.piece_neg] | groups[f.piece_pos]
        for member in joined:
            groups[member] = joined
    return set(groups.values())


def assert_followable(
    pieces: Sequence[Piece], faces: Sequence[CutFace], plan: assembly.AssemblyPlan
) -> None:
    """Every step is one straight move between two current sub-assemblies (I7)."""
    by_id = {f.id: f for f in faces}
    current = {piece.id: frozenset({piece.id}) for piece in pieces}
    covered: list[str] = []
    stages = [int(step.number.split(".")[0]) for step in plan.steps]
    assert stages == sorted(stages)
    for step in plan.steps:
        moving, static = frozenset(step.moving), frozenset(step.static)
        assert moving and static and not moving & static
        assert current[step.moving[0]] == moving
        assert current[step.static[0]] == static
        assert step.number.startswith(f"{step.axis + 1}.")
        expected = {
            f.id
            for f in faces
            if f.plane.axis == step.axis
            and {f.piece_neg, f.piece_pos} & moving
            and {f.piece_neg, f.piece_pos} & static
        }
        assert set(step.face_ids) == expected
        for face_id in step.face_ids:
            f = by_id[face_id]
            assert step.direction == ("-" if f.piece_pos in moving else "+") + "xyz"[step.axis]
        covered.extend(step.face_ids)
        joined = moving | static
        for member in joined:
            current[member] = joined
    assert sorted(covered) == sorted(f.id for f in faces)
    assert {frozenset(group) for group in plan.groups} == connected_groups(pieces, faces)


def test_2x2x1_gives_two_x_joins_then_one_y_join() -> None:
    pieces, faces = synthetic((i, j, 0) for i in range(2) for j in range(2))
    plan = assembly.plan_steps(pieces, faces, dowels(faces))
    assert [step.number for step in plan.steps] == ["1.1", "1.2", "2.1"]
    assert [step.axis for step in plan.steps] == [0, 0, 1]
    assert_followable(pieces, faces, plan)


def test_the_y_join_of_a_2x2x1_covers_both_of_its_faces() -> None:
    pieces, faces = synthetic((i, j, 0) for i in range(2) for j in range(2))
    last = assembly.plan_steps(pieces, faces, dowels(faces, 2)).steps[-1]
    assert sorted(last.face_ids) == ["X0-Y0-Z0~X0-Y1-Z0", "X1-Y0-Z0~X1-Y1-Z0"]
    assert last.connector_count == 4


def test_stage_numbers_follow_the_axis_even_without_x_joins() -> None:
    pieces, faces = synthetic([(0, 0, 0), (0, 1, 0)])
    assert assembly.plan_steps(pieces, faces, []).steps[0].number == "2.1"


def test_the_larger_sub_assembly_stays_still() -> None:
    pieces, faces = synthetic([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
    last = assembly.plan_steps(pieces, faces, []).steps[-1]
    assert last.moving == ("X2-Y0-Z0",)
    assert last.static == ("X0-Y0-Z0", "X1-Y0-Z0")
    assert last.direction == "-x"


def test_of_two_equal_sub_assemblies_the_one_with_the_first_piece_stays() -> None:
    pieces, faces = synthetic([(0, 0, 0), (1, 0, 0)])
    step = assembly.plan_steps(pieces, faces, []).steps[0]
    assert step.static == ("X0-Y0-Z0",)
    assert step.moving == ("X1-Y0-Z0",)


def test_a_neg_side_sub_assembly_moves_towards_plus() -> None:
    # X0-a and X0-b are two prongs of a fork: X1 holds them together. The fork's base, the
    # larger side once one prong is on, stays still while the other prong slides in along +x.
    a = "X0-Y0-Z0-a"
    b = "X0-Y0-Z0-b"
    base = "X1-Y0-Z0"
    pieces = [
        Piece(a, (0, 0, 0), solid((0, 0, 0), (10, 10, 10)), [], []),
        Piece(b, (0, 0, 0), solid((0, 20, 0), (10, 30, 10)), [], []),
        Piece(base, (1, 0, 0), solid((10, 0, 0), (20, 30, 10)), [], []),
    ]
    faces = [face(a, base, 0, 0, 10.0), face(b, base, 0, 0, 10.0)]
    plan = assembly.plan_steps(pieces, faces, [])
    assert plan.steps[-1].direction == "+x"
    assert_followable(pieces, faces, plan)


def test_a_join_without_connector_is_glue_only() -> None:
    pieces, faces = synthetic([(0, 0, 0), (1, 0, 0)])
    assert assembly.plan_steps(pieces, faces, []).steps[0].connector_count == 0


def test_groups_that_are_never_joined_are_separate_parts() -> None:
    pieces, faces = synthetic([(0, 0, 0), (1, 0, 0), (0, 2, 0)])
    plan = assembly.plan_steps(pieces, faces, [])
    assert plan.groups == (("X0-Y0-Z0", "X1-Y0-Z0"), ("X0-Y2-Z0",))


def test_a_single_piece_has_no_step() -> None:
    pieces, faces = synthetic([(0, 0, 0)])
    plan = assembly.plan_steps(pieces, faces, [])
    assert plan.steps == ()
    assert plan.groups == (("X0-Y0-Z0",),)
    assert plan.diagnostics == ()


def test_several_regions_of_one_pair_are_one_join() -> None:
    a, b = "X0-Y0-Z0", "X1-Y0-Z0"
    pieces = [
        Piece(a, (0, 0, 0), solid((0, 0, 0), (10, 10, 10)), [], []),
        Piece(b, (1, 0, 0), solid((10, 0, 0), (20, 10, 10)), [], []),
    ]
    faces = [face(a, b, 0, 0, 10.0), face(a, b, 0, 0, 10.0, 2)]
    plan = assembly.plan_steps(pieces, faces, dowels(faces))
    assert len(plan.steps) == 1
    assert plan.steps[0].connector_count == 2


cells = st.sets(
    st.tuples(st.integers(0, 2), st.integers(0, 2), st.integers(0, 1)), min_size=1, max_size=18
)


@given(cells)
def test_every_connected_group_is_joined_exactly_once_per_stage(chosen: set[Cell]) -> None:
    pieces, faces = synthetic(chosen)
    plan = assembly.plan_steps(pieces, faces, [])
    assert_followable(pieces, faces, plan)
    groups = len(pieces)
    for axis in AXES:
        groups_after = len(connected_groups(pieces, [f for f in faces if f.plane.axis <= axis]))
        assert sum(step.axis == axis for step in plan.steps) == groups - groups_after
        groups = groups_after


@given(cells)
def test_the_order_is_deterministic(chosen: set[Cell]) -> None:
    pieces, faces = synthetic(chosen)
    connectors = dowels(faces)
    first = assembly.plan_steps(pieces, faces, connectors)
    assert assembly.plan_steps(pieces, faces, connectors) == first


def interlocked() -> tuple[list[Piece], list[CutFace]]:
    """Two pieces on the same side of a plane, each in the other's way along X.

    Over y 0 to 10, a lies below b; over y 20 to 30, b lies below a. Neither can leave towards −x
    first, and the piece on the other side of the plane holds them together.
    """
    a = "X0-Y0-Z0-a"
    b = "X0-Y0-Z0-b"
    far = "X1-Y0-Z0"
    body_a = Manifold.batch_boolean(
        [
            solid((0, 0, 0), (4, 10, 10)),
            solid((0, 10, 0), (10, 20, 10)),
            solid((6, 20, 0), (10, 30, 10)),
        ],
        OpType.Add,
    )
    body_b = Manifold.batch_boolean(
        [
            solid((6, 0, 0), (10, 10, 20)),
            solid((0, 20, 0), (4, 30, 20)),
            solid((0, 0, 12), (10, 30, 20)),
        ],
        OpType.Add,
    )
    pieces = [
        Piece(a, (0, 0, 0), body_a, [], []),
        Piece(b, (0, 0, 0), body_b, [], []),
        Piece(far, (1, 0, 0), solid((10, 0, 0), (20, 30, 20)), [], []),
    ]
    return pieces, [face(a, far, 0, 0, 10.0), face(b, far, 0, 0, 10.0)]


def test_a_step_without_a_clear_path_gets_w013() -> None:
    pieces, faces = interlocked()
    plan = assembly.plan_steps(pieces, faces, [])
    assert_followable(pieces, faces, plan)
    assert [d.code for d in plan.diagnostics] == ["W013"]
    assert plan.diagnostics[0].severity == "partial"
    blocked = [step for step in plan.steps if not step.clear_path]
    assert len(blocked) == 1
    assert plan.diagnostics[0].refs == blocked[0].moving
    assert blocked[0].number in plan.diagnostics[0].message


def test_ordinary_steps_have_a_clear_path() -> None:
    pieces, faces = synthetic((i, j, 0) for i in range(3) for j in range(3))
    plan = assembly.plan_steps(pieces, faces, [])
    assert all(step.clear_path for step in plan.steps)
    assert plan.diagnostics == ()
