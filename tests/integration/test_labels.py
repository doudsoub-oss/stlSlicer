"""Phase 8: labels laid out on real pieces and engraved by the tools (PLAN.md Phase 8).

Most tests use a 200 x 100 x 100 box on a 120 mm bed, cut once at x = 100: the neg piece's face
is seen from +x, the pos piece's from −x. On an X plane, (u, v) = (world Y, world Z) (§4.2).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from manifold3d import Error, Manifold
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, box
from shapely.geometry.base import BaseGeometry

from stlsplit import cli, config, connectors, cutting, geometry, grid, io, labels, tools
from stlsplit.config import TOOL_OVERLAP, Config
from stlsplit.errors import ExitCode
from stlsplit.models import CutFace, Label, Piece, Plane
from tests.conftest import long_box, tall_figure, u_shape
from tests.integration.test_cutting import even, make, oriented

WriteStl = Callable[[Manifold, str], Path]

SMALL_BED: dict[str, Any] = {
    "printer.bed": (120.0, 120.0, 120.0),
    "connectors.max_per_face": 2,
}
FONT = io.resolve_label_font(Config().advanced.label_font)


class Run(NamedTuple):
    cfg: Config
    cut: cutting.Cut
    placement: connectors.Placement
    labelled: labels.Labelled
    applied: tools.Applied


def run(body: Manifold, overrides: dict[str, Any] | None = None, *, nudge: bool = False) -> Run:
    cfg = make(overrides)
    layout = even(body, config.derived(cfg).usable)
    if nudge:
        layout = grid.nudge(body, layout, cfg)
    result = cutting.cut(body, layout, cfg, body.volume())
    placement = connectors.place(result.pieces, result.faces, cfg)
    labelled = labels.layout(result.pieces, result.faces, placement.connectors, cfg, FONT)
    applied = tools.apply(labelled.pieces, result.faces, placement.connectors, cfg)
    return Run(cfg, result, placement, labelled, applied)


def block() -> Manifold:
    return oriented(Manifold.cube((200.0, 100.0, 100.0)))


def necked() -> Manifold:
    """Two 60 mm boxes joined by a 10 x 10 neck that the default bed cuts at z = 150."""
    lower = Manifold.cube((60.0, 60.0, 145.0))
    upper = Manifold.cube((60.0, 60.0, 145.0)).translate((0.0, 0.0, 155.0))
    neck = Manifold.cube((10.0, 10.0, 12.0)).translate((25.0, 25.0, 144.0))
    return oriented(lower + upper + neck)


def thin_plate() -> Manifold:
    """A 0.3 mm plate just above the cut plane, with one column carrying the height above it."""
    lower = Manifold.cube((100.0, 100.0, 150.0))
    plate = Manifold.cube((100.0, 100.0, 0.3)).translate((0.0, 0.0, 150.0))
    column = Manifold.cube((24.0, 24.0, 150.0)).translate((2.0, 2.0, 150.0))
    return oriented(lower + plate + column)


def face_of(result: Run, face_id: str) -> CutFace:
    return next(face for face in result.cut.faces if face.id == face_id)


def piece_of(pieces: list[Piece], piece_id: str) -> Piece:
    return next(piece for piece in pieces if piece.id == piece_id)


def side_of(piece: Piece, face: CutFace) -> int:
    return -1 if face.piece_neg == piece.id else 1


def label_of(piece: Piece) -> Label:
    assert piece.label is not None
    return piece.label


def codes(diagnostics: tuple[Any, ...]) -> list[str]:
    return [item.code for item in diagnostics]


def iou(first: BaseGeometry, second: BaseGeometry) -> float:
    return float(first.intersection(second).area / first.union(second).area)


def engraved_shape(result: Run, piece_id: str) -> MultiPolygon:
    """What the engraving removed, read back from the final solid at half its depth."""
    before = piece_of(result.labelled.pieces, piece_id)
    label = label_of(before)
    face = face_of(result, label.face_id)
    after = piece_of(result.applied.pieces, piece_id)
    side = side_of(before, face)
    offset = face.plane.offset + side * result.cfg.labels.depth / 2
    section = geometry.section(after.body, face.plane.axis, offset)
    low_u, low_v, high_u, high_v = label.outline.bounds
    window = box(low_u - 0.5, low_v - 0.5, high_u + 0.5, high_v + 0.5)
    return MultiPolygon(geometry.polygon_parts(window.difference(section)))


def centred_text(label: Label) -> BaseGeometry:
    """The plain text at the label's height, unmirrored, centred on the label's bounding box."""
    polygons = geometry.crosssection_to_polygons(
        labels.text_outline(label.text, label.height, FONT), ordered=False
    )
    low_u, low_v, high_u, high_v = label.outline.bounds
    return affinity.translate(MultiPolygon(polygons), (low_u + high_u) / 2, (low_v + high_v) / 2)


def test_a_labelled_piece_is_valid_and_loses_text_area_times_depth() -> None:
    body = block()
    result = run(body, SMALL_BED)
    plain = tools.apply(
        result.cut.pieces, result.cut.faces, result.placement.connectors, result.cfg
    )
    assert len(result.applied.pieces) == 2
    for with_label, without in zip(result.applied.pieces, plain.pieces, strict=True):
        assert with_label.body.status() == Error.NoError
        assert len(with_label.body.decompose()) == 1
        expected = label_of(with_label).outline.area * result.cfg.labels.depth
        lost = without.body.volume() - with_label.body.volume()
        assert lost == pytest.approx(expected, rel=0.10)


def test_the_label_outline_stays_out_of_every_keep_out_disk() -> None:
    result = run(oriented(Manifold.cube((200.0, 60.0, 60.0))), SMALL_BED)
    keep_out = config.derived(result.cfg).label_keep_out
    checked = 0
    for piece in result.labelled.pieces:
        label = label_of(piece)
        for connector in result.placement.connectors:
            if connector.face_id == label.face_id:
                disk = Point(connector.position_uv).buffer(keep_out, quad_segs=64)
                assert not label.outline.intersects(disk)
                checked += 1
    assert checked > 0


def test_a_piece_whose_only_face_is_10_mm_gets_no_label_and_w003() -> None:
    result = run(necked())
    assert [piece.label for piece in result.labelled.pieces] == [None, None]
    assert codes(result.labelled.diagnostics) == ["W003", "W003"]
    assert [item.refs for item in result.labelled.diagnostics] == [
        ("X0-Y0-Z0",),
        ("X0-Y0-Z1",),
    ]


@pytest.mark.parametrize("piece_id", ["X0-Y0-Z0", "X1-Y0-Z0"])
def test_a_label_viewed_from_outside_matches_the_unmirrored_text(piece_id: str) -> None:
    result = run(block(), SMALL_BED)
    piece = piece_of(result.labelled.pieces, piece_id)
    label = label_of(piece)
    shape = engraved_shape(result, piece_id)
    if side_of(piece, face_of(result, label.face_id)) > 0:  # seen from −z: u runs the other way
        low_u, _, high_u, _ = label.outline.bounds
        shape = affinity.scale(shape, -1.0, 1.0, origin=((low_u + high_u) / 2, 0.0))
    assert iou(shape, centred_text(label)) > 0.95


def test_the_label_is_engraved_into_its_own_piece_only() -> None:
    result = run(block(), SMALL_BED)
    for piece in result.labelled.pieces:
        label = label_of(piece)
        face = face_of(result, label.face_id)
        side = side_of(piece, face)
        solid = tools.label_solid(label, face, side, result.cfg)
        assert solid.volume() == pytest.approx(label.outline.area * result.cfg.labels.depth)
        bounds = solid.bounding_box()
        axis = face.plane.axis
        expected = sorted((face.plane.offset, face.plane.offset + side * result.cfg.labels.depth))
        assert (bounds[axis], bounds[axis + 3]) == pytest.approx(tuple(expected))


def test_a_label_never_cuts_through_a_thin_plate() -> None:
    result = run(thin_plate())
    upper = piece_of(result.labelled.pieces, "X0-Y0-Z1")
    label = label_of(upper)  # it moves onto the column, the only part with material behind it
    assert box(4.0, 4.0, 24.0, 24.0).contains(label.outline)
    face = face_of(result, label.face_id)
    backing = result.cfg.labels.depth + result.cfg.connectors.min_wall
    probe = geometry.prism(
        geometry.crosssection_from_polygons(label.outline),
        face.plane.axis,
        face.plane.offset + TOOL_OVERLAP,
        face.plane.offset + backing,
    )
    assert geometry.lies_inside(probe, upper.body)
    final = piece_of(result.applied.pieces, "X0-Y0-Z1")
    assert sum(shell.volume() > 0 for shell in final.body.decompose()) == 1


def test_a_t_beam_gets_a_label_on_each_piece() -> None:
    # The anchor is at the flange and web junction, where the text overflows both.
    web = Manifold.cube((200.0, 12.0, 10.0)).translate((0.0, 54.0, 10.0))
    body = oriented(Manifold.cube((200.0, 120.0, 10.0)) + web)
    result = run(body, {"printer.bed": (120.0, 200.0, 120.0), "connectors.type": "none"})
    assert len(result.labelled.pieces) == 2
    assert all(piece.label is not None for piece in result.labelled.pieces)
    assert result.labelled.diagnostics == ()
    for piece in result.applied.pieces:
        assert len(piece.body.decompose()) == 1


def test_the_tall_figure_keeps_one_shell_after_its_labels() -> None:
    result = run(tall_figure(), nudge=True)
    assert "W003" in codes(result.labelled.diagnostics)
    for piece in result.applied.pieces:
        assert sum(shell.volume() > 0 for shell in piece.body.decompose()) == 1


def test_a_label_stays_off_a_void_just_behind_the_face() -> None:
    void = Manifold.cube((60.0, 60.0, 1.0)).translate((20.0, 20.0, 150.3))
    result = run(oriented(Manifold.cube((100.0, 100.0, 300.0)) - void))
    piece = piece_of(result.labelled.pieces, "X0-Y0-Z1")
    label = label_of(piece)
    wall = result.cfg.connectors.min_wall
    assert label.outline.distance(box(20.0, 20.0, 80.0, 80.0)) >= wall - 0.01


@pytest.mark.parametrize("wall", [0.5, 0.7, 1.0, 2.0, 5.0])
def test_the_label_region_stays_a_full_wall_from_missing_material(wall: float) -> None:
    # Round joins are polygons: uncompensated, their flats fell up to 29 % short of the wall.
    void = Manifold.cube((40.0, 40.0, 0.2)).translate((30.0, 30.0, 150.1))
    body = oriented(Manifold.cube((100.0, 100.0, 300.0)) - void)
    cfg = make(
        {
            "connectors.type": "none",
            "connectors.min_wall": wall,
            "labels.depth": 0.4,
            "advanced.hole_chamfer": 0.1,  # the default 0.4 is over w/2 for the thin walls
        },
    )
    result = cutting.cut(body, even(body, config.derived(cfg).usable), cfg, body.volume())
    upper = piece_of(result.pieces, "X0-Y0-Z1")
    region = labels.label_region(result.faces[0], upper.body, 1, [], cfg)
    assert not region.is_empty
    assert region.distance(box(30.0, 30.0, 70.0, 70.0)) >= wall - 1e-3


def test_a_label_keeps_its_wall_from_every_hole_of_its_piece() -> None:
    body = oriented(Manifold.cube((120.0, 120.0, 120.0)))
    result = run(body, {"printer.bed": (82.0, 82.0, 82.0)})
    wall = result.cfg.connectors.min_wall
    holes: dict[str, list[Manifold]] = {}
    for connector in result.placement.connectors:
        face = face_of(result, connector.face_id)
        for piece_id, solid in connectors.hole_solids(connector, face, result.cfg):
            holes.setdefault(piece_id, []).append(solid)
    labelled = [piece for piece in result.labelled.pieces if piece.label is not None]
    assert len(labelled) == 8
    for piece in labelled:
        label = label_of(piece)
        face = face_of(result, label.face_id)
        solid = tools.label_solid(label, face, side_of(piece, face), result.cfg)
        for hole in holes[piece.id]:
            assert solid.min_gap(hole, wall + 1.0) >= wall - 0.01


def test_the_next_face_is_used_when_the_largest_has_no_room() -> None:
    body = Manifold.cube((200.0, 200.0, 200.0))
    strip = box(0.0, 0.0, 200.0, 7.0)  # 196 x 3 mm after the wall: larger, but under H_min
    square = box(50.0, 50.0, 72.0, 72.0)  # 18 x 18 mm after the wall
    wide = CutFace("X0-Y0-Z0~X0-Y0-Z1", Plane(2, 0, 200.0), "X0-Y0-Z0", "X0-Y0-Z1", strip)
    small = CutFace("X0-Y0-Z0~X1-Y0-Z0", Plane(0, 0, 200.0), "X0-Y0-Z0", "X1-Y0-Z0", square)
    piece = Piece("X0-Y0-Z0", (0, 0, 0), body, [wide.id, small.id], [])
    result = labels.layout([piece], [wide, small], [], Config(), FONT)
    assert label_of(result.pieces[0]).face_id == small.id
    assert result.diagnostics == ()


def test_every_piece_of_the_u_shape_gets_a_label() -> None:
    # Its faces are long and narrow: an anchor near one end of them left all four without one.
    overrides: dict[str, Any] = {"printer.bed": (46.0, 40.0, 40.0)}
    body = grid.orient(u_shape(), make(overrides))[0]
    result = run(body, overrides, nudge=True)
    assert len(result.labelled.pieces) == 4
    assert all(piece.label is not None for piece in result.labelled.pieces)
    assert result.labelled.diagnostics == ()


def test_a_piece_without_a_cut_face_gets_no_label_and_no_w003() -> None:
    piece = Piece("X0-Y0-Z0", (0, 0, 0), Manifold.cube((50.0, 50.0, 50.0)), [], [])
    result = labels.layout([piece], [], [], Config(), FONT)
    assert result.pieces[0].label is None
    assert result.diagnostics == ()


def test_labels_turned_off_engrave_nothing() -> None:
    body = block()
    result = run(body, {**SMALL_BED, "labels.enabled": False})
    assert all(piece.label is None for piece in result.labelled.pieces)
    assert result.labelled.diagnostics == ()
    plain = tools.apply(
        result.cut.pieces, result.cut.faces, result.placement.connectors, result.cfg
    )
    for first, second in zip(result.applied.pieces, plain.pieces, strict=True):
        assert first.body.volume() == pytest.approx(second.body.volume())


def test_peg_pieces_are_labelled_without_touching_their_pegs() -> None:
    result = run(block(), {**SMALL_BED, "connectors.type": "peg"})
    keep_out = config.derived(result.cfg).label_keep_out
    for piece in result.applied.pieces:
        assert len(piece.body.decompose()) == 1
        label = label_of(piece)
        for connector in result.placement.connectors:
            disk = Point(connector.position_uv).buffer(keep_out, quad_segs=64)
            assert not label.outline.intersects(disk)


def test_the_layout_is_deterministic() -> None:
    first, second = run(block(), SMALL_BED), run(block(), SMALL_BED)
    for one, other in zip(first.labelled.pieces, second.labelled.pieces, strict=True):
        assert label_of(one).outline.wkb == label_of(other).outline.wkb


def test_the_dry_run_lists_the_labels(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(long_box(), "model")
    argv = [str(stl), "--dry-run", "--bed", "220", "220", "220"]
    assert cli.main(argv) == ExitCode.SUCCESS
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "labels: 3" in lines
    assert any(line.startswith("label X0-Y0-Z0: 0-0-0 on face X0-Y0-Z0~X1-Y0-Z0") for line in lines)
    assert "labels: 3 of 3 pieces" in captured.err


def test_the_dry_run_with_no_label_lists_none(
    write_stl: WriteStl, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(long_box(), "model")
    argv = [str(stl), "--dry-run", "--bed", "220", "220", "220", "--no-label"]
    assert cli.main(argv) == ExitCode.SUCCESS
    lines = capsys.readouterr().out.splitlines()
    assert "labels: 0" in lines
    assert not any(line.startswith("label ") for line in lines)


@pytest.mark.parametrize("mode", ["dry run", "calibration"])
def test_a_file_that_is_not_a_font_exits_1_naming_the_option(
    mode: str, write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = tmp_path / "notafont.ttf"
    fake.write_bytes(b"hello")
    toml = tmp_path / "font.toml"
    toml.write_text(f"[advanced]\nlabel_font = '{fake}'\n", encoding="utf-8")
    if mode == "dry run":
        argv = [str(write_stl(long_box(), "model")), "--dry-run", "--config", str(toml)]
    else:
        argv = ["--calibrate", "-o", str(tmp_path / "kit"), "--config", str(toml)]
    assert cli.main(argv) == ExitCode.INVALID_INPUT
    assert "advanced.label_font" in capsys.readouterr().err
    assert not (tmp_path / "kit").exists()


def test_a_run_without_labels_does_not_read_the_font(write_stl: WriteStl, tmp_path: Path) -> None:
    fake = tmp_path / "notafont.ttf"
    fake.write_bytes(b"hello")
    toml = tmp_path / "font.toml"
    toml.write_text(f"[advanced]\nlabel_font = '{fake}'\n", encoding="utf-8")
    stl = write_stl(long_box(), "model")
    argv = [
        str(stl),
        "--dry-run",
        "--bed",
        "220",
        "220",
        "220",
        "--no-label",
        "--config",
        str(toml),
    ]
    assert cli.main(argv) == ExitCode.SUCCESS


def test_a_split_reports_w003_for_a_face_without_room(
    write_stl: WriteStl, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stl = write_stl(necked(), "necked")
    code = cli.main([str(stl), "-o", str(tmp_path / "out"), "--no-auto-orient"])
    assert code == ExitCode.PARTIAL  # the 10 mm face has no connector either (W001)
    assert "W003" in capsys.readouterr().err
