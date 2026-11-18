"""Shared test fixtures (PLAN.md Appendix D).

Fixtures are functions that build a ``Manifold`` in code; ``write_stl`` turns one into a file
in ``tmp_path``. Only the real models in ``tests/fixtures/real/`` are committed. Fixtures from
Appendix D are added in the phase that first uses them.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import trimesh
from manifold3d import Manifold


def cube(size: float = 10.0) -> Manifold:
    """Axis-aligned cube with its minimum corner at the origin, mm."""
    return Manifold.cube((size, size, size))


def manifold_to_trimesh(body: Manifold) -> trimesh.Trimesh:
    """Convert without going through stlsplit, so fixtures don't depend on the code under test."""
    mesh = body.to_mesh()
    return trimesh.Trimesh(
        vertices=np.array(mesh.vert_properties[:, :3], dtype=np.float64),
        faces=np.array(mesh.tri_verts, dtype=np.int64),
        process=False,
    )


@pytest.fixture
def write_stl(tmp_path: Path) -> Callable[[Manifold, str], Path]:
    """Return a helper that writes a manifold to ``tmp_path/<name>.stl`` (binary STL)."""

    def _write(body: Manifold, name: str = "model") -> Path:
        path = tmp_path / f"{name}.stl"
        manifold_to_trimesh(body).export(path, file_type="stl")
        return path

    return _write
