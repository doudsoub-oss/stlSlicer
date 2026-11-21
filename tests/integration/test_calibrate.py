"""Phase 7: the calibration kit (PLAN.md Phase 7, task 6, and §6.3).

With the defaults the bar is 50 x 12.4 x 13.5 mm: five holes of 10.5 mm, 9.4 mm apart, with the
codes 10, 15, 20, 25 and 30 engraved on the long side face y = 0.
"""

import math
from typing import Any

import pytest
from manifold3d import Manifold
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from stlsplit import calibrate, config, geometry, io, labels, tools
from stlsplit.config import CALIBRATION_CODE_GAP, Config
from stlsplit.errors import ConfigError
from tests.integration.test_cutting import make

FONT = io.resolve_label_font(Config().advanced.label_font)
ENGRAVING_PROBE = 0.3
"""y of the section through the engraved codes, mm (less than the 0.6 mm depth)."""


def kit(overrides: dict[str, Any] | None = None) -> tuple[Config, calibrate.Kit]:
    cfg = make(overrides)
    return cfg, calibrate.build_kit(cfg, FONT)


def holes(section: MultiPolygon) -> list[Polygon]:
    """The holes of a one-part section, in increasing X (section axis Z: u = X)."""
    assert len(section.geoms) == 1
    rings = [Polygon(ring) for ring in section.geoms[0].interiors]
    return sorted(rings, key=lambda ring: ring.centroid.x)


def polygon_area(apothem: float, segments: int) -> float:
    return segments * math.tan(math.pi / segments) * apothem**2


def engraved(block: Manifold, cal: config.CalibrationDims) -> Polygon | MultiPolygon:
    """What is missing from the side face, at ``ENGRAVING_PROBE``: (u, v) = (Z, X)."""
    section = geometry.section(block, 1, ENGRAVING_PROBE)
    return box(0.0, 0.0, cal.thickness, cal.length).difference(section)


def expected_codes(cfg: Config, result: calibrate.Kit) -> Polygon | MultiPolygon:
    """The codes as they should read from outside, mapped to that section's (Z, X)."""
    cal = config.derived(cfg).calibration
    outlines = []
    for index, code in enumerate(result.codes):
        centre_x = cal.wall + cal.hole_outer / 2 + index * cal.pitch
        parts = geometry.crosssection_to_polygons(
            labels.text_outline(code, result.code_height, FONT)
        )
        # Text x runs along +X and text y along +Z, seen from outside the face y = 0.
        outlines += [
            affinity.affine_transform(part, [0, 1, 1, 0, cal.thickness / 2, centre_x])
            for part in parts
        ]
    return unary_union(outlines)


# --- the bar ----------------------------------------------------------------------------------


def test_bar_has_the_dimensions_of_section_6_3() -> None:
    _, result = kit()
    b = result.block.bounding_box()
    assert b[:3] == pytest.approx((0.0, 0.0, 0.0))
    assert b[3:] == pytest.approx((50.0, 12.4, 13.5))
    assert result.block.status().name == "NoError"
    assert len(result.block.decompose()) == 1


def test_bar_has_one_hole_per_clearance_with_its_radius() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    found = holes(geometry.section(result.block, 2, cal.thickness - 1.0))
    assert len(found) == 5
    d = cfg.connectors.diameter
    for ring, clearance in zip(found, cfg.advanced.calibration_clearances, strict=True):
        expected = polygon_area(d / 2 + clearance, cfg.advanced.circular_segments)
        assert ring.area == pytest.approx(expected, rel=1e-4)


def test_holes_are_in_a_row_centred_across_the_width_one_pitch_apart() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    found = holes(geometry.section(result.block, 2, cal.thickness - 1.0))
    for index, ring in enumerate(found):
        assert ring.centroid.x == pytest.approx(cal.wall + cal.hole_outer / 2 + index * cal.pitch)
        assert ring.centroid.y == pytest.approx(cal.width / 2)


def test_holes_are_h_of_l_max_deep() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    floor = cal.thickness - config.hole_depth(cfg, cfg.connectors.length)
    assert len(holes(geometry.section(result.block, 2, floor + 0.01))) == 5
    assert len(holes(geometry.section(result.block, 2, floor - 0.01))) == 0


def test_two_bars_flipped_face_to_face_line_up_hole_for_hole() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    # Turned half a turn about the long axis, then laid on the first bar.
    flipped = result.block.rotate((180.0, 0.0, 0.0)).translate((0.0, cal.width, 2 * cal.thickness))
    lower = holes(geometry.section(result.block, 2, cal.thickness - 1.0))
    upper = holes(geometry.section(flipped, 2, cal.thickness + 1.0))
    assert len(upper) == len(lower)
    for a, b in zip(lower, upper, strict=True):
        assert a.centroid.x == pytest.approx(b.centroid.x, abs=1e-6)
        assert a.centroid.y == pytest.approx(b.centroid.y, abs=1e-6)
        assert a.area == pytest.approx(b.area, rel=1e-6)


# --- the codes --------------------------------------------------------------------------------


def test_codes_are_the_clearances_in_hundredths() -> None:
    _, result = kit()
    assert result.codes == ("10", "15", "20", "25", "30")
    assert result.code_height == Config().advanced.label_min_height


def test_codes_are_engraved_so_the_volume_decreases() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    missing = engraved(result.block, cal)
    assert missing.area > 0
    depth = cfg.labels.depth
    drilled = Manifold.cube((cal.length, cal.width, cal.thickness)) - geometry.union_all(
        [
            geometry.hole_solid(
                2,
                cal.thickness,
                (cal.wall + cal.hole_outer / 2 + i * cal.pitch, cal.width / 2),
                -1,
                config.hole_depth(cfg, cfg.connectors.length),
                cfg.connectors.diameter / 2 + clearance,
                cfg.advanced.hole_chamfer,
                cfg.advanced.circular_segments,
            )
            for i, clearance in enumerate(cfg.advanced.calibration_clearances)
        ]
    )
    assert drilled.volume() - result.block.volume() == pytest.approx(missing.area * depth, rel=1e-3)


def test_codes_read_correctly_from_outside_the_face() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    missing = engraved(result.block, cal)
    expected = expected_codes(cfg, result)
    assert missing.symmetric_difference(expected).area < 0.01 * expected.area


def test_each_code_stays_within_its_pitch() -> None:
    cfg, result = kit()
    cal = config.derived(cfg).calibration
    for index, code in enumerate(result.codes):
        outline = labels.text_outline(code, result.code_height, FONT)
        low_x, _, high_x, _ = outline.bounds()
        assert high_x - low_x <= cal.pitch - CALIBRATION_CODE_GAP, (index, code)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"connectors.diameter": 2.0, "connectors.length": 8.0}, id="small-pin"),
        pytest.param({"advanced.label_min_height": 12.0}, id="large-text"),
        pytest.param({"advanced.calibration_clearances": (0.1, 0.1234)}, id="long-code"),
    ],
)
def test_codes_shrink_only_as_far_as_needed_to_fit(overrides: dict[str, Any]) -> None:
    cfg, result = kit(overrides)
    cal = config.derived(cfg).calibration
    assert result.code_height < cfg.advanced.label_min_height
    assert result.code_height <= cal.thickness - 2 * CALIBRATION_CODE_GAP
    widths = []
    for code in result.codes:
        low_x, _, high_x, _ = labels.text_outline(code, result.code_height, FONT).bounds()
        widths.append(high_x - low_x)
    assert max(widths) <= cal.pitch - CALIBRATION_CODE_GAP + 1e-6
    # Neighbouring codes don't touch: one part per glyph at least, and a valid solid.
    assert result.block.status().name == "NoError"
    assert len(result.block.decompose()) == 1


@pytest.mark.parametrize(
    ("clearance", "code"),
    [
        pytest.param(0.0, "0", id="zero"),
        pytest.param(0.05, "5", id="one-digit"),
        pytest.param(0.15, "15", id="float-noise"),
        pytest.param(0.29, "29", id="float-noise-below"),
        pytest.param(0.123, "12.3", id="one-decimal"),
        pytest.param(0.1234, "12.34", id="two-decimals"),
        pytest.param(1.0, "100", id="three-digits"),
    ],
)
def test_code_text(clearance: float, code: str) -> None:
    assert calibrate.code_text(clearance) == code


def test_close_clearances_keep_different_codes() -> None:
    _, result = kit({"advanced.calibration_clearances": (0.123, 0.124)})
    assert result.codes == ("12.3", "12.4")


def test_clearances_with_the_same_code_are_rejected() -> None:
    cfg = make({"advanced.calibration_clearances": (0.12341, 0.12342)})
    with pytest.raises(ConfigError, match=r"advanced\.calibration_clearances"):
        calibrate.build_kit(cfg, FONT)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(  # the polygon's vertices reach past the §6.3 wall
            {
                "advanced.circular_segments": 16,
                "advanced.hole_chamfer": 0.0,
                "connectors.min_wall": 3.0,
                "labels.depth": 2.99,
                "advanced.calibration_clearances": (0.08,),
            },
            id="16-segments",
        ),
        pytest.param(
            {
                "printer.bed": (400.0, 400.0, 400.0),
                "connectors.diameter": 60.0,
                "connectors.length": 180.0,
                "advanced.hole_chamfer": 0.0,
                "connectors.min_wall": 3.0,
                "labels.depth": 2.99,
                "advanced.calibration_clearances": (0.08,),
            },
            id="large-pin",
        ),
    ],
)
def test_engraving_that_would_reach_a_hole_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match=r"labels\.depth"):
        calibrate.build_kit(make(overrides), FONT)


def test_holes_that_would_touch_each_other_are_rejected() -> None:
    cfg = make(
        {
            "printer.bed": (2000.0, 2000.0, 2000.0),
            "connectors.diameter": 170.0,
            "connectors.length": 510.0,
            "connectors.min_wall": 3.0,
            "advanced.circular_segments": 16,
            "advanced.hole_chamfer": 0.0,
            "advanced.calibration_clearances": (0.1, 0.2),
        }
    )
    with pytest.raises(ConfigError, match=r"advanced\.circular_segments"):
        calibrate.build_kit(cfg, FONT)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"connectors.min_wall": 1e6, "labels.depth": 0.6}, id="huge-wall"),
        pytest.param({"connectors.min_wall": 1e300}, id="absurd-wall"),
        pytest.param({"advanced.calibration_clearances": (1e300,)}, id="absurd-clearance"),
        pytest.param({"printer.bed": (40.0, 40.0, 250.0)}, id="longer-than-the-bed"),
        pytest.param({"printer.bed": (220.0, 220.0, 12.0)}, id="taller-than-the-bed"),
    ],
)
def test_a_bar_that_does_not_fit_the_printer_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match=r"printer\.bed"):
        calibrate.build_kit(make(overrides), FONT)


def test_a_bar_may_be_turned_a_quarter_turn_to_fit_the_bed() -> None:
    # 50 x 12.4 mm on a 22 x 70 mm plate with 5 mm margins: only along Y.
    _, result = kit({"printer.bed": (22.4, 70.0, 250.0), "connectors.length": 20.0})
    assert result.block.status().name == "NoError"


# --- text outlines ----------------------------------------------------------------------------


def test_text_outline_has_the_requested_height_and_is_centred() -> None:
    outline = labels.text_outline("10", 4.0, FONT)
    low_x, low_y, high_x, high_y = outline.bounds()
    assert high_y - low_y == pytest.approx(4.0)
    assert (low_x + high_x) / 2 == pytest.approx(0.0, abs=1e-9)
    assert (low_y + high_y) / 2 == pytest.approx(0.0, abs=1e-9)


def test_text_outline_keeps_the_counter_of_a_zero() -> None:
    polygons = geometry.crosssection_to_polygons(labels.text_outline("0", 4.0, FONT))
    assert len(polygons) == 1
    assert len(polygons[0].interiors) == 1


# --- the pin and the README -------------------------------------------------------------------


def test_one_pin_per_clearance_of_the_full_length() -> None:
    cfg, result = kit()
    assert result.pin_count == len(cfg.advanced.calibration_clearances)
    assert result.pin_file == "calibration/pin_d5.0_l20.0.stl"
    expected = tools.pin_solid(cfg.connectors.diameter, cfg.connectors.length, cfg)
    assert result.pin.volume() == pytest.approx(expected.volume())


def test_readme_explains_printing_testing_and_reading_the_codes() -> None:
    cfg, result = kit()
    text = result.readme
    assert "block.stl" in text
    assert "pin_d5.0_l20.0.stl" in text
    assert "holes vertical" in text
    assert "looser" in text
    assert "horizontal" in text
    assert "--clearance" in text
    for code, clearance in zip(result.codes, cfg.advanced.calibration_clearances, strict=True):
        assert f"| {code} | {clearance:g} |" in text


def test_the_kit_is_deterministic() -> None:
    _, first = kit()
    _, second = kit()
    assert first.readme == second.readme
    assert first.block.volume() == second.block.volume()
    a, b = first.block.to_mesh(), second.block.to_mesh()
    assert a.vert_properties.tobytes() == b.vert_properties.tobytes()
    assert a.tri_verts.tobytes() == b.tri_verts.tobytes()
