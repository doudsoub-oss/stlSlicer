"""Runs scripts/api_spike.py so library regressions show up in the normal test run."""

import importlib.util
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[1] / "scripts" / "api_spike.py"


def test_api_spike_main_succeeds() -> None:
    spec = importlib.util.spec_from_file_location("api_spike", SPIKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([]) == 0
