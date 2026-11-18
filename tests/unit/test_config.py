import math
from typing import Any

import pytest

from stlsplit import config
from stlsplit.config import Config, ModelConfig
from stlsplit.errors import ConfigError, InputError

# Defaults as written in PLAN.md §7.2 and §7.3, in table and key order.
PLAN_DEFAULTS: dict[str, Any] = {
    "printer.bed": (220.0, 220.0, 250.0),
    "printer.margin": 5.0,
    "model.scale": 1.0,
    "model.auto_orient": True,
    "model.simplify": 0.0,
    "repair.deep": False,
    "connectors.type": "dowel",
    "connectors.diameter": 5.0,
    "connectors.length": 20.0,
    "connectors.clearance": 0.2,
    "connectors.min_wall": 2.0,
    "connectors.max_per_face": 4,
    "labels.enabled": True,
    "labels.depth": 0.6,
    "output.preview": True,
    "advanced.axial_play": 0.5,
    "advanced.pin_length_step": 2.0,
    "advanced.pin_min_length_factor": 3.0,
    "advanced.pin_chamfer": 0.5,
    "advanced.pin_flat": 0.4,
    "advanced.hole_chamfer": 0.4,
    "advanced.circular_segments": 64,
    "advanced.connector_spacing_factor": 3.0,
    "advanced.connector_area_factor": 6.0,
    "advanced.section_epsilon": 0.01,
    "advanced.nudge_window": 5.0,
    "advanced.nudge_step": 0.5,
    "advanced.small_piece_volume": 500.0,
    "advanced.label_font": "DejaVuSans-Bold.ttf",
    "advanced.label_min_height": 4.0,
    "advanced.label_max_height": 12.0,
    "advanced.calibration_clearances": (0.10, 0.15, 0.20, 0.25, 0.30),
    "advanced.preview_spread": 0.15,
}

# PLAN.md §7.7.
EXAMPLE_TOML = """\
[printer]
bed = [180, 180, 180]
margin = 4

[connectors]
type = "dowel"
diameter = 6.0
length = 24.0        # full pin; shorter standard lengths: 22, 20, 18 (L_min = 3 × 6 = 18)
clearance = 0.25
min_wall = 2.5

[labels]
enabled = true
depth = 0.6

[advanced]
pin_flat = 0.4
"""

# A valid value different from the default for every key. Some values are chosen to stress
# the TOML writer: floats with no short decimal form, exponents, quotes and backslashes.
NON_DEFAULT: dict[str, Any] = {
    "printer.bed": (180.0, 200.5, 300.0),
    "printer.margin": 4.25,
    "model.scale": 25.4,
    "model.auto_orient": False,
    "model.simplify": 0.05,
    "repair.deep": True,
    "connectors.type": "peg",
    "connectors.diameter": 6.0,
    "connectors.length": 24.0,
    "connectors.clearance": 0.1 + 0.2,
    "connectors.min_wall": 2.5,
    "connectors.max_per_face": 6,
    "labels.enabled": False,
    "labels.depth": 0.8,
    "output.preview": False,
    "advanced.axial_play": 0.3,
    "advanced.pin_length_step": 1.0,
    "advanced.pin_min_length_factor": 2.5,
    "advanced.pin_chamfer": 0.4,
    "advanced.pin_flat": 0.3,
    "advanced.hole_chamfer": 0.3,
    "advanced.circular_segments": 96,
    "advanced.connector_spacing_factor": 4.0,
    "advanced.connector_area_factor": 7.0,
    "advanced.section_epsilon": 1e-5,
    "advanced.nudge_window": 0.0,
    "advanced.nudge_step": 0.25,
    "advanced.small_piece_volume": 1e6,
    "advanced.label_font": '/opt/fonts/My "Font"\\é\t.ttf',
    "advanced.label_min_height": 5.0,
    "advanced.label_max_height": 10.0,
    "advanced.calibration_clearances": (0.05, 0.1, 0.35),
    "advanced.preview_spread": 0.3,
}


def make(overrides: dict[str, Any]) -> Config:
    return config.with_overrides(Config(), overrides, source="the test")


# --- defaults and derived values -------------------------------------------------------------


def test_defaults_match_the_plan() -> None:
    cfg = Config()
    assert config.keys() == tuple(PLAN_DEFAULTS)
    for key, expected in PLAN_DEFAULTS.items():
        value = config.lookup(cfg, key)
        assert value == expected, key
        assert type(value) is type(expected), key


def test_defaults_are_valid() -> None:
    config.validate(Config())


def test_derived_values_match_plan_section_6() -> None:
    d = config.derived(Config())
    assert d.usable == (210.0, 210.0, 240.0)
    assert d.pin_min_length == 15.0
    assert d.standard_lengths == (20.0, 18.0, 16.0)
    assert d.hole_depths == (10.5, 9.5, 8.5)
    assert d.peg_protrusion == 10.0
    assert d.hole_radius == pytest.approx(2.7)
    assert d.hole_radius_model == pytest.approx(2.7 / math.cos(math.pi / 64))
    assert d.hole_radius_model == pytest.approx(2.7033, abs=1e-4)
    assert d.inset == pytest.approx(5.1)
    assert d.candidate_step == 1.25
    assert d.connector_spacing == 15.0
    assert d.area_per_connector == 900.0
    assert d.island_area == pytest.approx(78.54, abs=0.01)
    assert d.label_keep_out == pytest.approx(5.1)


def test_peg_mode_reduces_the_usable_volume_by_the_protrusion() -> None:
    assert config.derived(make({"connectors.type": "peg"})).usable == (200.0, 200.0, 230.0)


def test_example_configuration_gives_standard_lengths_24_to_18() -> None:
    d = config.derived(config.parse_toml(EXAMPLE_TOML, "my_printer.toml"))
    assert d.pin_min_length == 18.0
    assert d.standard_lengths == (24.0, 22.0, 20.0, 18.0)


def test_standard_lengths_keep_a_length_equal_to_the_minimum_despite_rounding() -> None:
    # In floats, 16 − 64 × 0.1 = 9.599999999999999 and 3.2 × 3 = 9.600000000000001: a plain
    # ">= L_min" would drop the 9.6 mm pin.
    cfg = make(
        {
            "connectors.diameter": 3.0,
            "connectors.length": 16.0,
            "advanced.pin_length_step": 0.1,
            "advanced.pin_min_length_factor": 3.2,
        }
    )
    lengths = config.derived(cfg).standard_lengths
    assert len(lengths) == 65
    assert lengths[-1] == pytest.approx(9.6)


def test_hole_depth_is_half_the_pin_plus_the_axial_play() -> None:
    assert config.hole_depth(Config(), 18.0) == 9.5


def test_calibration_kit_dimensions_match_plan_section_6_3() -> None:
    cal = config.derived(Config()).calibration
    assert cal.max_clearance == 0.30
    assert cal.hole_outer == pytest.approx(6.4)
    assert cal.wall == 3.0
    assert cal.hole_count == 5
    assert cal.pitch == pytest.approx(9.4)
    assert cal.length == pytest.approx(50.0)
    assert cal.width == pytest.approx(12.4)
    assert cal.thickness == pytest.approx(13.5)


def test_calibration_wall_follows_a_min_wall_thicker_than_three_mm() -> None:
    assert config.derived(make({"connectors.min_wall": 4.0})).calibration.wall == 4.0


# --- TOML loading ----------------------------------------------------------------------------


def test_plan_example_configuration_loads() -> None:
    cfg = config.parse_toml(EXAMPLE_TOML, "my_printer.toml")
    assert cfg.printer.bed == (180.0, 180.0, 180.0)
    assert cfg.printer.margin == 4.0
    assert type(cfg.printer.margin) is float  # TOML integers are accepted for floats
    assert cfg.connectors.diameter == 6.0
    assert cfg.connectors.length == 24.0
    assert cfg.connectors.clearance == 0.25
    assert cfg.connectors.min_wall == 2.5
    assert cfg.model == ModelConfig()  # tables the file doesn't mention keep their defaults


def test_unknown_toml_table_is_rejected_and_named() -> None:
    with pytest.raises(ConfigError) as exc:
        config.parse_toml("[printr]\nbed = [1, 2, 3]\n", "my.toml")
    assert exc.value.key == "printr"
    assert "unknown table" in str(exc.value)
    assert "my.toml" in str(exc.value)


def test_unknown_toml_key_is_rejected_and_named() -> None:
    with pytest.raises(ConfigError) as exc:
        config.parse_toml("[connectors]\nclearence = 0.2\n", "my.toml")
    assert exc.value.key == "connectors.clearence"
    assert "unknown key" in str(exc.value)
    assert "clearance" in str(exc.value)  # the known keys are listed


def test_invalid_toml_syntax_is_an_input_error_naming_the_file() -> None:
    with pytest.raises(InputError, match=r"my\.toml"):
        config.parse_toml("[printer\nbed = 1\n", "my.toml")


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        pytest.param('[printer]\nmargin = "5"\n', "printer.margin", id="string-for-number"),
        pytest.param("[printer]\nmargin = true\n", "printer.margin", id="bool-for-number"),
        pytest.param("[model]\nauto_orient = 1\n", "model.auto_orient", id="int-for-bool"),
        pytest.param(
            "[connectors]\nmax_per_face = 4.0\n", "connectors.max_per_face", id="float-for-int"
        ),
        pytest.param(
            "[connectors]\nmax_per_face = true\n", "connectors.max_per_face", id="bool-for-int"
        ),
        pytest.param("[printer]\nbed = [220, 220]\n", "printer.bed", id="bed-two-values"),
        pytest.param("[printer]\nbed = 220\n", "printer.bed", id="bed-not-an-array"),
        pytest.param('[connectors]\ntype = "dovetail"\n', "connectors.type", id="bad-choice"),
        pytest.param(
            "[advanced]\ncalibration_clearances = 0.2\n",
            "advanced.calibration_clearances",
            id="clearances-not-an-array",
        ),
        pytest.param("[advanced]\nlabel_font = 3\n", "advanced.label_font", id="int-for-string"),
        pytest.param("printer = 5\n", "printer", id="table-not-a-table"),
        pytest.param("bed = [1, 2, 3]\n", "bed", id="key-outside-a-table"),
        # tomllib accepts integers of any size; float() of this one overflows.
        pytest.param("[model]\nscale = 1" + "0" * 400 + "\n", "model.scale", id="huge-int-float"),
        pytest.param(
            "[advanced]\ncircular_segments = 9223372036854775808\n",  # 2**63, past TOML's range
            "advanced.circular_segments",
            id="int-past-64-bits",
        ),
        # Hex literals aren't limited by Python's 4300-digit rule, so this parses; the message
        # must not try to print it in decimal.
        pytest.param("[model]\nscale = 0x" + "F" * 5000 + "\n", "model.scale", id="huge-hex-float"),
        pytest.param(
            "[connectors]\nmax_per_face = 0x" + "F" * 5000 + "\n",
            "connectors.max_per_face",
            id="huge-hex-int",
        ),
    ],
)
def test_wrong_toml_type_is_rejected_and_named(toml: str, key: str) -> None:
    with pytest.raises(ConfigError) as exc:
        config.parse_toml(toml, "my.toml")
    assert exc.value.key == key


# --- validation (PLAN.md §7.5) ---------------------------------------------------------------

ELEVEN_CLEARANCES = tuple(0.05 * i for i in range(11))


@pytest.mark.parametrize(
    ("overrides", "key", "rule"),
    [
        pytest.param({"printer.bed": (220.0, 0.0, 250.0)}, "printer.bed", "> 0", id="bed"),
        pytest.param({"printer.margin": -1.0}, "printer.margin", ">= 0", id="margin"),
        pytest.param(
            {"printer.margin": 110.0},
            "printer.margin",
            "< half the smallest bed dimension (110.0)",
            id="margin-vs-bed",
        ),
        pytest.param({"model.scale": 0.0}, "model.scale", "> 0", id="scale"),
        pytest.param({"model.simplify": -0.1}, "model.simplify", ">= 0", id="simplify"),
        pytest.param({"connectors.diameter": 0.0}, "connectors.diameter", "> 0", id="diameter"),
        pytest.param(
            {"connectors.clearance": -0.01}, "connectors.clearance", ">= 0", id="clearance"
        ),
        pytest.param({"connectors.min_wall": 0.0}, "connectors.min_wall", "> 0", id="min-wall"),
        pytest.param(
            {"connectors.max_per_face": 0}, "connectors.max_per_face", ">= 1", id="max-per-face"
        ),
        pytest.param(
            {"connectors.length": 14.9},
            "connectors.length",
            ">= L_min = pin_min_length_factor x diameter = 15.0",
            id="length-vs-l-min",
        ),
        pytest.param({"labels.depth": 0.0}, "labels.depth", "> 0", id="label-depth"),
        pytest.param(
            {"labels.depth": 2.0},
            "labels.depth",
            "< connectors.min_wall (2.0)",
            id="label-depth-vs-min-wall",
        ),
        pytest.param(
            {
                "connectors.type": "peg",
                "printer.bed": (100.0, 20.0, 100.0),
                "printer.margin": 0.0,
                "connectors.length": 40.0,
            },
            "connectors.length",
            "peg mode",
            id="peg-mode-usable-volume",
        ),
        pytest.param({"advanced.axial_play": -0.1}, "advanced.axial_play", ">= 0", id="play"),
        pytest.param(
            {"advanced.pin_length_step": 0.0}, "advanced.pin_length_step", ">= 0.1", id="step"
        ),
        pytest.param(
            {"advanced.pin_length_step": 0.09},
            "advanced.pin_length_step",
            ">= 0.1",
            id="step-below-minimum",
        ),
        pytest.param(
            {"advanced.pin_min_length_factor": 0.0},
            "advanced.pin_min_length_factor",
            "> 0",
            id="pin-min-length-factor",
        ),
        pytest.param({"advanced.pin_flat": -0.1}, "advanced.pin_flat", ">= 0", id="pin-flat"),
        pytest.param(
            {"advanced.pin_flat": 1.25},
            "advanced.pin_flat",
            "< connectors.diameter / 4 (1.25)",
            id="pin-flat-vs-diameter",
        ),
        pytest.param(
            {"advanced.pin_chamfer": -0.1}, "advanced.pin_chamfer", ">= 0", id="pin-chamfer"
        ),
        pytest.param(
            {"advanced.pin_chamfer": 3.75},
            "advanced.pin_chamfer",
            "< L_min / 4 (3.75)",
            id="pin-chamfer-vs-l-min",
        ),
        pytest.param(
            {"advanced.hole_chamfer": -0.1}, "advanced.hole_chamfer", ">= 0", id="hole-chamfer"
        ),
        pytest.param(
            {"advanced.hole_chamfer": 1.01},
            "advanced.hole_chamfer",
            "<= connectors.min_wall / 2 (1.0)",
            id="hole-chamfer-vs-min-wall",
        ),
        pytest.param(
            {"advanced.circular_segments": 15},
            "advanced.circular_segments",
            ">= 16",
            id="circular-segments",
        ),
        pytest.param(
            {"advanced.circular_segments": 257},
            "advanced.circular_segments",
            "<= 256",
            id="circular-segments-max",
        ),
        pytest.param(
            {"advanced.connector_spacing_factor": 0.0},
            "advanced.connector_spacing_factor",
            "> 0",
            id="connector-spacing-factor",
        ),
        pytest.param(
            {"advanced.connector_area_factor": 0.0},
            "advanced.connector_area_factor",
            "> 0",
            id="connector-area-factor",
        ),
        pytest.param(
            {"advanced.section_epsilon": 0.0}, "advanced.section_epsilon", "> 0", id="epsilon"
        ),
        pytest.param(
            {"advanced.section_epsilon": 0.11},
            "advanced.section_epsilon",
            "<= 0.1",
            id="epsilon-max",
        ),
        pytest.param(
            {"advanced.nudge_window": -0.5}, "advanced.nudge_window", ">= 0", id="nudge-window"
        ),
        pytest.param({"advanced.nudge_step": 0.0}, "advanced.nudge_step", "> 0", id="nudge-step"),
        pytest.param(
            {"advanced.small_piece_volume": -1.0},
            "advanced.small_piece_volume",
            ">= 0",
            id="small-piece-volume",
        ),
        pytest.param(
            {"advanced.label_min_height": 0.0},
            "advanced.label_min_height",
            "> 0",
            id="label-min-height",
        ),
        pytest.param(
            {"advanced.label_min_height": 12.5},
            "advanced.label_min_height",
            "<= advanced.label_max_height (12.0)",
            id="label-min-vs-max-height",
        ),
        pytest.param(
            {"advanced.calibration_clearances": ()},
            "advanced.calibration_clearances",
            "1 to 10 values",
            id="clearances-empty",
        ),
        pytest.param(
            {"advanced.calibration_clearances": ELEVEN_CLEARANCES},
            "advanced.calibration_clearances",
            "1 to 10 values",
            id="clearances-eleven",
        ),
        pytest.param(
            {"advanced.calibration_clearances": (-0.05, 0.1)},
            "advanced.calibration_clearances",
            ">= 0",
            id="clearances-negative",
        ),
        pytest.param(
            {"advanced.calibration_clearances": (0.2, 0.1)},
            "advanced.calibration_clearances",
            "increasing",
            id="clearances-unsorted",
        ),
        pytest.param(
            {"advanced.calibration_clearances": (0.1, 0.1)},
            "advanced.calibration_clearances",
            "increasing",
            id="clearances-duplicate",
        ),
        pytest.param(
            {"advanced.preview_spread": -0.1}, "advanced.preview_spread", ">= 0", id="spread"
        ),
        pytest.param({"model.scale": math.inf}, "model.scale", "finite", id="infinite"),
        pytest.param({"printer.margin": math.nan}, "printer.margin", "finite", id="nan"),
        pytest.param(
            {"printer.bed": (220.0, math.inf, 250.0)}, "printer.bed", "finite", id="bed-infinite"
        ),
    ],
)
def test_validation_rejects_bad_value(overrides: dict[str, Any], key: str, rule: str) -> None:
    cfg = make(overrides)
    with pytest.raises(ConfigError) as exc:
        config.validate(cfg)
    assert exc.value.key == key
    assert rule in exc.value.problem


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"printer.margin": 0.0}, id="margin-zero"),
        pytest.param({"printer.margin": 109.9}, id="margin-just-under-half-bed"),
        pytest.param({"model.simplify": 0.0}, id="simplify-zero"),
        pytest.param({"connectors.clearance": 0.0}, id="clearance-zero"),
        pytest.param({"connectors.max_per_face": 1}, id="one-connector"),
        pytest.param({"connectors.length": 15.0}, id="length-equals-l-min"),
        pytest.param({"labels.depth": 1.99}, id="label-depth-just-under-min-wall"),
        pytest.param({"advanced.axial_play": 0.0}, id="no-play"),
        pytest.param({"advanced.pin_flat": 0.0}, id="round-pins"),
        pytest.param({"advanced.pin_chamfer": 0.0}, id="no-pin-chamfer"),
        pytest.param({"advanced.hole_chamfer": 0.0}, id="no-hole-chamfer"),
        pytest.param({"advanced.hole_chamfer": 1.0}, id="hole-chamfer-half-min-wall"),
        pytest.param({"advanced.circular_segments": 16}, id="sixteen-segments"),
        pytest.param({"advanced.circular_segments": 256}, id="max-segments"),
        pytest.param({"advanced.pin_length_step": 0.1}, id="smallest-step"),
        pytest.param({"advanced.nudge_window": 0.0}, id="nudging-off"),
        pytest.param({"advanced.section_epsilon": 0.1}, id="epsilon-max"),
        pytest.param({"advanced.small_piece_volume": 0.0}, id="merging-off"),
        pytest.param({"advanced.label_min_height": 12.0}, id="label-min-equals-max"),
        pytest.param({"advanced.calibration_clearances": (0.2,)}, id="one-clearance"),
        pytest.param(
            {"advanced.calibration_clearances": ELEVEN_CLEARANCES[1:]}, id="ten-clearances"
        ),
        pytest.param({"advanced.calibration_clearances": (0.0, 0.1)}, id="zero-clearance"),
        pytest.param({"advanced.preview_spread": 0.0}, id="no-spread"),
        pytest.param(
            {"connectors.type": "peg", "printer.bed": (100.0, 10.1, 100.0), "printer.margin": 0.0},
            id="peg-mode-just-fits",
        ),
    ],
)
def test_boundary_value_is_accepted(overrides: dict[str, Any]) -> None:
    config.validate(make(overrides))


# --- printing the configuration as TOML ------------------------------------------------------


def test_non_default_values_cover_every_key_and_are_valid() -> None:
    assert set(NON_DEFAULT) == set(config.keys())
    for key, value in NON_DEFAULT.items():
        assert value != PLAN_DEFAULTS[key], key
    config.validate(make(NON_DEFAULT))


@pytest.mark.parametrize(
    "cfg",
    [
        pytest.param(Config(), id="defaults"),
        pytest.param(config.parse_toml(EXAMPLE_TOML, "my_printer.toml"), id="plan-example"),
        pytest.param(make(NON_DEFAULT), id="every-key-changed"),
    ],
)
def test_to_toml_round_trips_to_an_equal_config(cfg: Config) -> None:
    assert config.parse_toml(config.to_toml(cfg), "printed") == cfg


def test_integer_over_pythons_digit_limit_is_an_input_error() -> None:
    # tomllib raises a plain ValueError here, not TOMLDecodeError.
    with pytest.raises(InputError, match=r"my\.toml"):
        config.parse_toml("[model]\nscale = " + "1" * 5000 + "\n", "my.toml")


def test_largest_64_bit_integer_is_accepted() -> None:
    cfg = config.parse_toml("[connectors]\nmax_per_face = 9223372036854775807\n", "my.toml")
    assert cfg.connectors.max_per_face == 2**63 - 1


def test_to_toml_output_is_ascii_and_round_trips_any_text() -> None:
    # Pure ASCII survives any console encoding (Windows redirects stdout in the locale's).
    # The name has an accent, a CJK character, an astral character and DEL.
    cfg = make({"advanced.label_font": "C:/Users/José/字/\U0001d4db\x7f.ttf"})
    text = config.to_toml(cfg)
    assert text.isascii()
    assert config.parse_toml(text, "printed") == cfg


def test_to_toml_lists_every_table_in_order() -> None:
    text = config.to_toml(Config())
    tables = [line for line in text.splitlines() if line.startswith("[")]
    assert tables == [
        "[printer]",
        "[model]",
        "[repair]",
        "[connectors]",
        "[labels]",
        "[output]",
        "[advanced]",
    ]
