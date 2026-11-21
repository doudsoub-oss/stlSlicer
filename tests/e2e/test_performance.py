"""Phase 10: a large model split within the time budget (PLAN.md N2, Phase 10 task 2).

Marked ``slow``: not in the default run, run weekly in CI, or with ``pytest -m slow --no-cov``.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import manifold_to_trimesh, refined_sphere_union

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

BUDGET_SECONDS = 120.0
"""The target of PLAN.md Phase 10: under 2 minutes."""

TRIANGLE_TOLERANCE = 0.05
"""How far the generated model may be from the requested triangle count."""


@pytest.mark.parametrize("triangles", [1_000_000, 2_000_000], ids=["1M", "2M"])
def test_large_model_splits_into_eight_pieces_within_the_budget(
    tmp_path: Path, triangles: int
) -> None:
    body = refined_sphere_union(triangles)
    assert body.num_tri() == pytest.approx(triangles, rel=TRIANGLE_TOLERANCE)
    stl = tmp_path / "large.stl"
    manifold_to_trimesh(body).export(stl, file_type="stl")
    del body
    out = tmp_path / "out"
    try:
        start = time.perf_counter()
        done = subprocess.run(
            [sys.executable, "-m", "stlsplit", str(stl), "-o", str(out), "-v"],
            capture_output=True,
            text=True,
            timeout=2 * BUDGET_SECONDS,
            check=False,
        )
        elapsed = time.perf_counter() - start
        assert done.returncode == 0, done.stderr[-2000:]
        assert len(json.loads((out / "assembly.json").read_text("utf-8"))["pieces"]) == 8
    finally:  # these files are large, and pytest keeps its recent temporary folders
        stl.unlink(missing_ok=True)
        shutil.rmtree(out, ignore_errors=True)
    print(f"\n{triangles} triangles: {elapsed:.1f} s")
    print("\n".join(re.findall(r"stage .+: [\d.]+ s", done.stderr)))
    assert elapsed < BUDGET_SECONDS
