import re

import pytest

from stlsplit import errors
from stlsplit.errors import (
    DIAGNOSTIC_CODES,
    ConfigError,
    ExitCode,
    InputError,
    RepairError,
    StlsplitError,
)
from stlsplit.models import Diagnostic


def test_registry_codes_are_well_formed_sorted_and_unique() -> None:
    codes = [entry.code for entry in DIAGNOSTIC_CODES]
    assert all(re.fullmatch(r"W\d{3}", code) for code in codes)
    assert codes == sorted(set(codes))


def test_registry_matches_the_plan_severities() -> None:
    # PLAN.md §4.5.
    partial, warning = {"W001"}, {"W002", "W003", "W004", "W006", "W011"}
    for entry in DIAGNOSTIC_CODES:
        expected = (
            "partial" if entry.code in partial else "warning" if entry.code in warning else "info"
        )
        assert entry.severity == expected, entry.code


def test_diagnostic_takes_its_severity_from_the_registry() -> None:
    made = errors.diagnostic("W001", "face X0~X1 got no connector", ["X0~X1"])
    assert made == Diagnostic("W001", "partial", "face X0~X1 got no connector", ("X0~X1",))


def test_unknown_diagnostic_code_is_a_bug() -> None:
    with pytest.raises(ValueError, match="W999"):
        errors.diagnostic("W999", "never registered")


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        pytest.param([], ExitCode.SUCCESS, id="none"),
        pytest.param(["W005"], ExitCode.SUCCESS, id="info"),
        pytest.param(["W002", "W012"], ExitCode.SUCCESS, id="warning-and-info"),
        pytest.param(["W012", "W001"], ExitCode.PARTIAL, id="partial"),
    ],
)
def test_exit_code_for_diagnostics(codes: list[str], expected: ExitCode) -> None:
    diagnostics = [errors.diagnostic(code, "message") for code in codes]
    assert errors.exit_code_for(diagnostics) == expected


def test_exceptions_carry_their_exit_codes() -> None:
    assert StlsplitError().exit_code == ExitCode.INTERNAL
    assert InputError().exit_code == ExitCode.INVALID_INPUT
    assert RepairError().exit_code == ExitCode.UNREPAIRABLE
    error = ConfigError("printer.margin", "must be >= 0, got -1.0")
    assert error.exit_code == ExitCode.INVALID_INPUT
    assert isinstance(error, InputError)
    assert str(error) == "printer.margin: must be >= 0, got -1.0"
