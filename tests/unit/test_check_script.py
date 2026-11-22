"""``scripts/check.py`` enforces the coverage minimum (PLAN.md §9.4, Phase 11, task 3)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fast", [False, True], ids=["full", "fast"])
def test_the_test_command_fails_under_85_percent_coverage(fast: bool) -> None:
    pytest_command = next(c for c in load_script().commands(fast) if "pytest" in c)
    assert "--cov-fail-under=85" in pytest_command


def test_the_coverage_minimum_is_not_in_the_pytest_configuration() -> None:
    # In addopts or coverage's fail_under, it would fail every single-test command.
    text = (SCRIPT.parents[1] / "pyproject.toml").read_text("utf-8")
    assert "fail_under" not in text
    assert "cov-fail-under" not in text
