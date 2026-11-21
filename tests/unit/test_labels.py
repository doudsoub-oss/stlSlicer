"""Phase 8: label text, font, and the 2D fit of a label on a region (PLAN.md Phase 8).

With the defaults H_min = 4 and H_max = 12 mm, and ``1-0-2b`` is 17.96 mm wide at 4 mm.
"""

from pathlib import Path

import matplotlib
import pytest
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

from stlsplit import geometry, io, labels
from stlsplit.config import LABEL_MAX_ANCHORS, TEXT_PATH_SIZE, Config
from stlsplit.errors import ConfigError

CFG = Config()
FONT = io.resolve_label_font(CFG.advanced.label_font)
TEXT = "1-0-2b"


def iou(first: BaseGeometry, second: BaseGeometry) -> float:
    return float(first.intersection(second).area / first.union(second).area)


def even_odd_area(glyph: str, height: float) -> float:
    """A glyph's area from its raw contours: the outer one minus its counters."""
    path = TextPath((0.0, 0.0), glyph, size=TEXT_PATH_SIZE, prop=FontProperties(fname=FONT))
    contours = sorted((Polygon(c) for c in path.to_polygons()), key=lambda p: -p.area)
    _, low, _, high = contours[0].bounds
    area = contours[0].area - sum(contour.area for contour in contours[1:])
    return float(area * (height / (high - low)) ** 2)


@pytest.mark.parametrize(
    ("piece", "text"),
    [
        ("X0-Y0-Z0", "0-0-0"),
        ("X1-Y0-Z2-b", "1-0-2b"),
        ("X10-Y0-Z2-aa", "10-0-2aa"),
    ],
)
def test_label_text_is_the_grid_digits_plus_the_suffix(piece: str, text: str) -> None:
    assert labels.label_text(piece) == text


@pytest.mark.parametrize("piece", ["", "X1-Y0", "A1-Y0-Z2", "X1-Y0-Z2-B", "X1-Y0-Z2-b-c"])
def test_label_text_rejects_what_is_not_a_piece_id(piece: str) -> None:
    with pytest.raises(ValueError, match="piece ID"):
        labels.label_text(piece)


def test_the_bundled_font_is_where_the_labels_load_it_from() -> None:
    bundled = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
    assert bundled.is_file()
    assert bundled == FONT


@pytest.mark.parametrize("glyph", ["0", "8", "b"])
def test_text_with_counters_keeps_its_holes(glyph: str) -> None:
    fitted = labels.fit_text(glyph, box(-50.0, -50.0, 50.0, 50.0), False, CFG, FONT)
    assert fitted is not None
    assert sum(len(part.interiors) for part in fitted.outline.geoms) >= 1
    assert fitted.outline.area == pytest.approx(even_odd_area(glyph, fitted.height), rel=1e-3)


def test_a_large_region_gets_the_largest_height_at_0_degrees() -> None:
    fitted = labels.fit_text(TEXT, box(0.0, 0.0, 100.0, 100.0), False, CFG, FONT)
    assert fitted is not None
    assert fitted.height == CFG.advanced.label_max_height
    low_u, low_v, high_u, high_v = fitted.outline.bounds
    assert high_u - low_u > high_v - low_v  # reads along u: 0 degrees wins the tie


def test_a_tall_region_turns_the_text_a_quarter_turn() -> None:
    fitted = labels.fit_text(TEXT, box(0.0, 0.0, 20.0, 120.0), False, CFG, FONT)
    assert fitted is not None
    assert fitted.height == CFG.advanced.label_max_height
    low_u, low_v, high_u, high_v = fitted.outline.bounds
    assert high_v - low_v > high_u - low_u


def test_the_height_stops_where_the_region_does() -> None:
    region = box(0.0, 0.0, 30.0, 30.0)
    fitted = labels.fit_text(TEXT, region, False, CFG, FONT)
    assert fitted is not None
    assert region.contains(fitted.outline)
    low_u, _, high_u, _ = fitted.outline.bounds
    assert high_u - low_u == pytest.approx(30.0, abs=0.02)  # as wide as the region allows
    assert CFG.advanced.label_min_height < fitted.height < CFG.advanced.label_max_height


def test_no_label_without_room_for_the_minimum_height() -> None:
    assert labels.fit_text(TEXT, box(0.0, 0.0, 6.0, 6.0), False, CFG, FONT) is None


def test_an_accepted_label_lies_inside_a_region_with_a_hole() -> None:
    region = box(0.0, 0.0, 60.0, 60.0).difference(Point(15.0, 15.0).buffer(8.0))
    for mirrored in (False, True):
        fitted = labels.fit_text(TEXT, region, mirrored, CFG, FONT)
        assert fitted is not None
        assert region.contains(fitted.outline)


def test_the_anchor_is_the_polylabel_point_of_the_largest_part() -> None:
    small, large = box(0.0, 0.0, 30.0, 30.0), box(100.0, 0.0, 180.0, 80.0)
    fitted = labels.fit_text(TEXT, small.union(large), False, CFG, FONT)
    assert fitted is not None
    low_u, low_v, high_u, high_v = fitted.outline.bounds
    assert ((low_u + high_u) / 2, (low_v + high_v) / 2) == pytest.approx((140.0, 40.0), abs=1e-3)


@pytest.mark.parametrize(
    ("width", "height", "middle"),
    [(100.0, 8.0, (50.0, 4.0)), (20.0, 120.0, (10.0, 60.0)), (60.0, 30.0, (30.0, 15.0))],
)
def test_the_anchor_of_a_long_face_is_its_middle(
    width: float, height: float, middle: tuple[float, float]
) -> None:
    assert labels.label_anchor(box(0.0, 0.0, width, height)) == pytest.approx(middle, abs=1e-6)


def test_a_long_narrow_face_fits_the_text_along_its_length() -> None:
    fitted = labels.fit_text(TEXT, box(0.0, 0.0, 100.0, 8.0), False, CFG, FONT)
    assert fitted is not None
    assert fitted.height == pytest.approx(8.0, abs=0.01)


def test_the_anchor_of_a_concave_part_stays_inside_it() -> None:
    l_shape = box(0.0, 0.0, 60.0, 12.0).union(box(0.0, 0.0, 12.0, 60.0))
    assert not l_shape.contains(l_shape.centroid.buffer(4.0))
    assert l_shape.contains(Point(labels.label_anchor(l_shape)))


@pytest.mark.parametrize("mirrored", [False, True])
def test_text_moves_off_the_anchor_when_it_does_not_fit_there(mirrored: bool) -> None:
    # A T: the anchor is at the junction of bar and stem, where 4 mm text overflows the bar.
    region = box(0.0, 0.0, 116.0, 6.0).union(box(54.0, 0.0, 62.0, 16.0))
    fitted = labels.fit_text(TEXT, region, mirrored, CFG, FONT)
    assert fitted is not None
    assert region.contains(fitted.outline)
    low_u, low_v, high_u, high_v = fitted.outline.bounds
    centre = Point((low_u + high_u) / 2, (low_v + high_v) / 2)
    assert centre.distance(Point(labels.label_anchor(region))) > 0.1


def test_a_smaller_part_takes_the_label_when_the_largest_is_too_thin() -> None:
    thin, square = box(0.0, 0.0, 116.0, 3.5), box(0.0, 20.0, 20.0, 40.0)
    assert thin.area > square.area
    fitted = labels.fit_text(TEXT, MultiPolygon([thin, square]), False, CFG, FONT)
    assert fitted is not None
    assert square.contains(fitted.outline)


def test_fallback_positions_are_bounded_and_nearest_the_anchor_first() -> None:
    part = box(0.0, 0.0, 400.0, 400.0)
    points = labels.fallback_anchors(part, CFG)
    assert len(points) == LABEL_MAX_ANCHORS
    assert points[0] == pytest.approx(labels.label_anchor(part))
    distances = [Point(point).distance(Point(points[0])) for point in points]
    assert distances == sorted(distances)
    assert all(part.contains(Point(point)) for point in points)


def test_the_default_font_passes_the_font_check() -> None:
    io.check_label_font(FONT)


def test_a_file_that_is_not_a_font_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "notafont.ttf"
    fake.write_bytes(b"hello")
    with pytest.raises(ConfigError) as exc:
        io.check_label_font(fake)
    assert exc.value.key == "advanced.label_font"


@pytest.mark.parametrize("name", ["STIXSizOneSymBol.ttf", "LastResortHE-Regular.ttf"])
def test_a_font_that_cannot_draw_the_labels_is_refused(name: str) -> None:
    with pytest.raises(ConfigError, match="glyph") as exc:
        io.check_label_font(io.resolve_label_font(name))
    assert exc.value.key == "advanced.label_font"


def test_mirrored_text_is_the_plain_text_flipped_in_u_about_the_anchor() -> None:
    region = box(0.0, 0.0, 100.0, 100.0)
    plain = labels.fit_text(TEXT, region, False, CFG, FONT)
    mirrored = labels.fit_text(TEXT, region, True, CFG, FONT)
    assert plain is not None
    assert mirrored is not None
    assert mirrored.height == plain.height
    assert iou(plain.outline, mirrored.outline) < 0.9  # the text isn't symmetric
    flipped = affinity.scale(mirrored.outline, -1.0, 1.0, origin=(50.0, 50.0))
    assert iou(plain.outline, flipped) > 0.99


def test_crosssection_from_polygons_keeps_holes_and_area() -> None:
    shape = box(0.0, 0.0, 10.0, 10.0).difference(box(3.0, 3.0, 7.0, 7.0))
    section = geometry.crosssection_from_polygons(shape)
    assert section.area() == pytest.approx(84.0)
    back = geometry.crosssection_to_polygons(section, ordered=False)
    assert len(back) == 1
    assert len(back[0].interiors) == 1
