# Library notes

Every library behaviour the code relies on, the version it was verified with, the code that
depends on it, and the check in [`scripts/api_spike.py`](../scripts/api_spike.py) that proves it.
After any dependency upgrade, run `python scripts/api_spike.py` and update this file
(CONTRIBUTING.md, "Upgrade a dependency").

## Verified versions

Verified on 2026-11-18, Linux x86_64, CPython 3.13.18 (all 22 checks pass). The `>=` minimums in
`pyproject.toml` are these versions (numpy 2.5.5; the plan's own run on 2026-11-17 used 2.5.3 and
found the same behaviours).

Also verified on CPython 3.12.16 and 3.14.10 (Linux): `pip install -e ".[dev]"`, `scripts/check.py`
and the spike all pass with the same package versions. networkx 3.7 excludes CPython 3.14.1
specifically; later 3.14 releases are fine.

| Package | Version | Licence |
|---|---|---|
| manifold3d | 3.5.5 | Apache-2.0 |
| trimesh | 5.2.1 | MIT |
| numpy | 2.5.5 | BSD-3-Clause |
| scipy | 1.18.1 | BSD-3-Clause |
| networkx | 3.7 | BSD-3-Clause |
| shapely | 2.2.0 | BSD-3-Clause |
| matplotlib | 3.11.2 | PSF-based (matplotlib licence) |

## Behaviours

"Used by" names the code that relies on the behaviour; entries marked *(planned)* name the phase
whose code will.

### manifold3d

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `Mesh(vert_properties, tri_verts)` takes C-contiguous float32 (N×3) and uint32 (M×3) arrays. Arrays returned by `to_mesh()` are **read-only views**: copy before reuse. `to_mesh64()` gives float64 vertices (manifold keeps double precision internally). | 3.5.5 | `geometry.to_manifold`, `geometry.to_trimesh` | `manifold.mesh_arrays` |
| `status()` is `Error.NoError` for a valid solid and something else for an open mesh; `volume()` is exact for a cube. | 3.5.5 | `geometry.to_manifold` callers; I1 | `manifold.status_volume` |
| `split_by_plane(normal, offset)` returns (the side the normal points to, the other side). | 3.5.5 | `cutting` *(Phase 4)* | `manifold.split_by_plane` |
| `trim_by_plane` keeps the normal's side; `decompose`, `batch_boolean(list, OpType.Add)` and `project()` work. | 3.5.5 | `geometry.union_all`; `cutting` *(Phase 4)* | `manifold.trim_decompose_batch_project` |
| `cylinder(height, radius_low, radius_high=-1, circular_segments=0, center=False)` uses **16 segments at r = 2.5** by default; `circular_segments` overrides it. | 3.5.5 | `geometry.cylinder_solid` (always passes `segments`); §6.2 | `manifold.cylinder_default_segments` |
| `transform(3×4)` followed by `slice(z)` maps axes as in PLAN.md §4.2. | 3.5.5 | `geometry.world_to_local` | `manifold.transform_slice_axes` |
| `CrossSection(contours, FillRule.EvenOdd)`, `decompose()` and `to_polygons()` work; outer contours come back with positive area and holes negative. | 3.5.5 | `geometry.crosssection_from_contours`, `geometry.crosssection_to_polygons` | `manifold.crosssection_evenodd` |
| `^` intersects two CrossSections; `Manifold.extrude(cs, h)` works. | 3.5.5 | `geometry` sections *(Phase 4)*, `labels` *(Phase 8)* | `manifold.crosssection_xor_extrude` |
| `ray_cast(origin, endpoint)` returns hits sorted by distance, nearest first (checked through three bodies in both directions). `RayHit.distance` is a **fraction of the segment**, not mm; `RayHit.position` is in mm. A face the origin lies on is not reported. | 3.5.5 | `geometry.ray_depth` | `manifold.ray_cast` |
| `min_gap(other, search_length)` gives 2.0 for two r = 2.7 cylinders (64 segments) with axes 7.4 mm apart, and 0 when they cross. | 3.5.5 | `connectors` *(Phase 5)*; I5, ADR-0014 | `manifold.min_gap` |
| `simplify(tolerance)` keeps the result manifold. | 3.5.5 | `repair` `--simplify` *(Phase 2)* | `manifold.simplify` |
| A difference whose cutter face is coplanar with a model face opens the hole through that face, with no closing skin (exact volume and surface area, and a ray from above reaches the pocket floor); a union whose face is coplanar with a model face gives one body with the exact volume. | 3.5.5 | `tools` *(Phase 7)* | `manifold.coplanar_booleans` |
| `slice` exactly at a step height is one-sided (column under a plate: 1600 mm² instead of the 100 mm² contact); the intersection of the slices at ±ε gives 100 mm² for both step directions. | 3.5.5 | `geometry.cut_region` *(Phase 4)*; ADR-0002 | `manifold.slice_at_step` |
| The stub file `manifold3d.pyi` ships without `py.typed`, so mypy ignores it: manifold3d is in the `ignore_missing_imports` list in `pyproject.toml`. | 3.5.5 | type checking | — (mypy run) |

### trimesh

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `load(..., force="mesh")` merges vertices by default (a 36-vertex soup loads as 8). Build "soup" fixtures with `process=False`. | 5.2.1 | `io.load_stl` *(Phase 2)* | `trimesh.load_merges_vertices` |
| `nondegenerate_faces`, `unique_faces`, `update_faces` and `remove_unreferenced_vertices` work: each removes exactly the degenerate face, duplicate face or unreferenced vertex planted in a box. | 5.2.1 | `repair` *(Phase 2)* | `trimesh.cleanup_methods` |
| `repair.fill_holes` closes a quad hole (one side of a box) but not a large one (a sphere without its cap). It needs networkx: without it, `ModuleNotFoundError` (checked in a child process where networkx looks uninstalled). | 5.2.1 | `repair` *(Phase 2)* | `trimesh.fill_holes` |
| `repair.fix_normals(multibody=False)` keeps a hollow sphere's void; `multibody=True` turns it solid. Never use `multibody=True` (ADR-0007). | 5.2.1 | `repair` *(Phase 2)* | `trimesh.fix_normals_multibody` |
| Binary STL export starts with an 80-byte zero header (no timestamp: determinism). | 5.2.1 | `io` export *(Phase 9)*; ADR-0010 | `trimesh.stl_zero_header` |
| `Scene.export(file_type="glb")` works when numpy, scipy and networkx are the only importable third-party packages (checked in a child process where every other installed package looks uninstalled). | 5.2.1 | `io` preview *(Phase 9)* | `trimesh.glb_export` |

### shapely

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| Negative `buffer`, `ops.polylabel`, `contains` and `intersection` work as expected on a 10 mm square. | 2.2.0 | `geometry.crosssection_to_polygons` (polylabel); `connectors` *(Phase 5)* | `shapely.operations` |

### matplotlib

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `DejaVuSans-Bold.ttf` is bundled at `matplotlib.get_data_path()/fonts/ttf/`. The outer contours of `TextPath` glyphs are **clockwise**, so the Positive fill rule loses them: use EvenOdd (ADR-0009). | 3.11.2 | `labels` *(Phase 8)*; `geometry.crosssection_from_contours` | `matplotlib.font_and_glyph_winding` |

### Determinism

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| A small split-and-drill pipeline (manifold3d booleans, trimesh STL export) run in two separate processes with random hash seeds writes byte-identical files. | all above | ADR-0010, N1 | `determinism.subprocess_bytes` |

## Tooling notes

- `ruff format` also formats Python code blocks inside Markdown files; that would rewrite the
  aligned examples in PLAN.md and the docs, so `*.md` is excluded in `pyproject.toml`.
