import math
from pathlib import Path

import matplotlib
import numpy as np
import pytest
import trimesh
from manifold3d import Error, Manifold
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath

from stlsplit import geometry
from tests.conftest import cube

# Plane-local axes per plane axis (PLAN.md §4.2): (local x, local y, local z) as world axes.
LOCAL_AXES = {0: (1, 2, 0), 1: (2, 0, 1), 2: (0, 1, 2)}


def test_trimesh_manifold_round_trip_keeps_volume() -> None:
    source = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    body = geometry.to_manifold(source)
    assert body.status() == Error.NoError
    assert body.volume() == pytest.approx(source.volume, rel=1e-6)

    back = geometry.to_trimesh(body)
    assert back.is_watertight
    assert back.volume == pytest.approx(source.volume, rel=1e-6)
    # The result must be usable again: arrays from Manifold.to_mesh() are read-only views.
    assert geometry.to_manifold(back).volume() == pytest.approx(source.volume, rel=1e-6)


def test_round_trip_of_a_manifold_keeps_volume() -> None:
    body = cube(10.0) - Manifold.cube((2.0, 2.0, 20.0)).translate((4.0, 4.0, -5.0))
    again = geometry.to_manifold(geometry.to_trimesh(body))
    assert again.volume() == pytest.approx(body.volume(), rel=1e-9)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_frame_matrices_are_proper_rotations_mapping_axes_per_4_2(axis: int) -> None:
    w2l = geometry.world_to_local(axis)
    assert w2l.shape == (3, 4)
    rotation = w2l[:, :3]
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    for local_index, world_index in enumerate(LOCAL_AXES[axis]):
        expected = np.zeros(3)
        expected[local_index] = 1.0
        world_unit = np.zeros(3)
        world_unit[world_index] = 1.0
        assert rotation @ world_unit == pytest.approx(expected)

    l2w = geometry.local_to_world(axis)
    assert l2w.shape == (3, 4)
    assert np.linalg.det(l2w[:, :3]) == pytest.approx(1.0)
    assert l2w[:, :3] == pytest.approx(rotation.T)  # local -> world is the transpose (§4.2)
    assert l2w[:, 3] == pytest.approx(np.zeros(3))
    # Exact inverses: a point on the plane at offset o (local z = o) maps back unchanged.
    offset = 7.5
    point = np.array([1.0, 2.0, 3.0])
    point[axis] = offset
    local = w2l @ np.append(point, 1.0)
    assert local[2] == pytest.approx(offset)
    assert l2w @ np.append(local, 1.0) == pytest.approx(point)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_local_to_world_round_trips_a_solid(axis: int) -> None:
    body = Manifold.cube((1.0, 2.0, 3.0)).translate((4.0, 5.0, 6.0))
    back = body.transform(geometry.world_to_local(axis)).transform(geometry.local_to_world(axis))
    assert back.bounding_box() == pytest.approx(body.bounding_box())


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_transform_then_slice_maps_box_extents_per_4_2(axis: int) -> None:
    size = (1.0, 2.0, 3.0)
    local = Manifold.cube(size).transform(geometry.world_to_local(axis))
    u_axis, v_axis, n_axis = LOCAL_AXES[axis]
    section = local.slice(size[n_axis] / 2)
    assert section.bounds() == pytest.approx((0.0, 0.0, size[u_axis], size[v_axis]))


def cap_polygon(solid: Manifold, z: float) -> np.ndarray:
    """Vertices of the cap at height z, sorted by angle (a slice would add diagonal points)."""
    vertices = np.asarray(solid.to_mesh64().vert_properties[:, :3], dtype=np.float64)
    cap = vertices[np.isclose(vertices[:, 2], z)][:, :2]
    return cap[np.argsort(np.arctan2(cap[:, 1], cap[:, 0]))]


@pytest.mark.parametrize("segments", [16, 64])
def test_compensated_cylinder_flats_sit_at_requested_radius(segments: int) -> None:
    radius = 2.7
    solid = geometry.cylinder_solid(radius, 0.0, 5.0, segments, compensate=True)
    polygon = cap_polygon(solid, 0.0)
    assert len(polygon) == segments
    midpoints = (polygon + np.roll(polygon, -1, axis=0)) / 2
    flat_distances = np.hypot(midpoints[:, 0], midpoints[:, 1])
    assert flat_distances == pytest.approx(radius, abs=1e-9)
    assert solid.bounding_box()[2] == pytest.approx(0.0)
    assert solid.bounding_box()[5] == pytest.approx(5.0)


def test_uncompensated_cylinder_vertices_sit_at_requested_radius() -> None:
    solid = geometry.cylinder_solid(2.7, -1.0, 4.0, 64, compensate=False)
    polygon = cap_polygon(solid, -1.0)
    assert np.hypot(polygon[:, 0], polygon[:, 1]) == pytest.approx(2.7, abs=1e-9)
    assert solid.volume() == pytest.approx(0.5 * 64 * 2.7**2 * math.sin(2 * math.pi / 64) * 5.0)


def test_cylinder_rejects_empty_extent() -> None:
    with pytest.raises(ValueError):
        geometry.cylinder_solid(2.7, 3.0, 3.0, 64, compensate=True)


def test_glyph_zero_with_evenodd_keeps_its_hole() -> None:
    font = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
    contours = TextPath((0, 0), "0", size=10.0, prop=FontProperties(fname=font)).to_polygons()
    assert len(contours) == 2

    section = geometry.crosssection_from_contours(contours)
    polygons = geometry.crosssection_to_polygons(section)
    assert len(polygons) == 1
    glyph = polygons[0]
    assert len(glyph.interiors) == 1
    assert glyph.area == pytest.approx(section.area())
    assert glyph.area < glyph.convex_hull.area * 0.9  # the counter is really empty


def test_crosssection_to_polygons_sorts_by_polylabel() -> None:
    squares = [
        [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)],
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
    ]
    polygons = geometry.crosssection_to_polygons(geometry.crosssection_from_contours(squares))
    assert [p.bounds[0] for p in polygons] == [0.0, 20.0]


def test_ray_depth_returns_millimetres() -> None:
    body = cube(10.0)
    # A 100 mm segment: RayHit.distance would be 0.06 here, the depth must be 6 mm.
    depth = geometry.ray_depth(body, (5.0, 5.0, 4.0), (0.0, 0.0, 1.0), 100.0)
    assert depth == pytest.approx(6.0)
    # Direction length doesn't matter.
    assert geometry.ray_depth(body, (5.0, 5.0, 4.0), (0.0, 0.0, 3.0), 100.0) == pytest.approx(6.0)


def test_ray_depth_is_none_without_hit() -> None:
    body = cube(10.0)
    assert geometry.ray_depth(body, (5.0, 5.0, 4.0), (0.0, 0.0, 1.0), 2.0) is None
    assert geometry.ray_depth(body, (50.0, 5.0, 4.0), (0.0, 0.0, 1.0), 100.0) is None


def test_union_all_merges_overlapping_solids() -> None:
    solids = [cube(10.0), cube(10.0).translate((5.0, 0.0, 0.0)), cube(10.0).translate((30, 0, 0))]
    union = geometry.union_all(solids)
    assert union.volume() == pytest.approx(2500.0)
    assert len(union.decompose()) == 2
    assert geometry.union_all([]).is_empty()
