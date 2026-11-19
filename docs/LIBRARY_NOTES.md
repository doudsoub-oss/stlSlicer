# Library notes

Every library behaviour the code relies on, the version it was verified with, the code that
depends on it, and the check in [`scripts/api_spike.py`](../scripts/api_spike.py) that proves it.
After any dependency upgrade, run `python scripts/api_spike.py` and update this file
(CONTRIBUTING.md, "Upgrade a dependency").

## Verified versions

Verified on 2026-11-18, Linux x86_64, CPython 3.13.18 (all 22 checks pass then; Phase 2 added
five checks and the optional pymeshlab one, all 27 passing on 2026-11-19; Phase 4 added
`manifold.coplanar_cuts`, `manifold.union_of_split_halves` and `manifold.decompose_void_shells`,
all 31 passing on 2026-11-19; Phase 5 added `manifold.revolve_hole`, all 32 passing on
2026-11-19). The `>=` minimums in
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
| pymeshlab (optional, extra `deep-repair`) | 2025.7.post1 | GPL-3.0 |

## Behaviours

"Used by" names the code that relies on the behaviour; entries marked *(planned)* name the phase
whose code will.

### manifold3d

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `Mesh(vert_properties, tri_verts)` takes C-contiguous float32 (N×3) and uint32 (M×3) arrays. Arrays returned by `to_mesh()` are **read-only views**: copy before reuse. `to_mesh64()` gives float64 vertices (manifold keeps double precision internally). | 3.5.5 | `geometry.to_manifold`, `geometry.to_trimesh` | `manifold.mesh_arrays` |
| `status()` is `Error.NoError` for a valid solid and something else for an open mesh; `volume()` is exact for a cube. | 3.5.5 | `repair.prepare`; I1 | `manifold.status_volume` |
| `split_by_plane(normal, offset)` returns (the side the normal points to, the other side). | 3.5.5 | nothing: it leaves flaps on coplanar model faces (`manifold.coplanar_cuts`), so `geometry.split_at` cuts by difference | `manifold.split_by_plane` |
| `trim_by_plane` keeps the normal's side; `decompose`, `batch_boolean(list, OpType.Add)` and `project()` work. | 3.5.5 | `geometry.union_all`, `geometry.bodies`, `geometry.shadow` (`trim_by_plane` itself isn't used: it leaves flaps too) | `manifold.trim_decompose_batch_project` |
| `cylinder(height, radius_low, radius_high=-1, circular_segments=0, center=False)` uses **16 segments at r = 2.5** by default; `circular_segments` overrides it. | 3.5.5 | `geometry.cylinder_solid` (always passes `segments`); §6.2 | `manifold.cylinder_default_segments` |
| `transform(3×4)` followed by `slice(z)` maps axes as in PLAN.md §4.2. | 3.5.5 | `geometry.world_to_local` | `manifold.transform_slice_axes` |
| `transform` with a signed permutation (det = +1) is exact: the bounding box is permuted exactly, and the volume and `NoError` status are unchanged. `translate(−min)` then puts the bounding-box minimum **exactly** at (0, 0, 0), even at awkward float coordinates (checked on a box scaled by 25.4). `bounding_box()` is `(xmin, ymin, zmin, xmax, ymax, zmax)`. | 3.5.5 | `grid.to_cutting_frame`, `grid.extent` | `manifold.signed_permutation_exact` |
| `CrossSection(contours, FillRule.EvenOdd)`, `decompose()` and `to_polygons()` work; outer contours come back with positive area and holes negative. An **empty** cross-section (a slice that misses the body) decomposes into one component with no contours. | 3.5.5 | `geometry.crosssection_from_contours`, `geometry.crosssection_to_polygons`, `geometry.section` (skips the empty component) | `manifold.crosssection_evenodd` (the empty case: `tests/unit/test_sections.py`) |
| `^` intersects two CrossSections (and two Manifolds); `Manifold.extrude(cs, h)` works. | 3.5.5 | `geometry.cut_region`, `geometry.overlap_area`, `geometry.prism`, `cutting._cut_merged` (footprints), `cutting._overlap` (a volume only: a Manifold intersection can leave flaps, row below); `labels` *(Phase 8)* | `manifold.crosssection_xor_extrude` |
| `ray_cast(origin, endpoint)` returns hits sorted by distance, nearest first (checked through three bodies in both directions). `RayHit.distance` is a **fraction of the segment**, not mm; `RayHit.position` is in mm. A face the origin lies on is not reported. | 3.5.5 | `geometry.ray_depth` (`connectors.available_depth`); `connectors._too_close` (an axis meeting another hole) | `manifold.ray_cast` |
| `min_gap(other, search_length)` gives 2.0 for two r = 2.7 cylinders (64 segments) with axes 7.4 mm apart, **within float noise below it** (1.999999999999993), 0 when they cross, and `search_length` when nothing is that close. It is slow on crossing solids: about 2 ms for two 64-segment holes, against 0.15 ms when they are close but apart. | 3.5.5 | `connectors._too_close` (gap ≥ w − `LENGTH_TOLERANCE`; bounding boxes and a ray cast first); I5, ADR-0014 | `manifold.min_gap` |
| **Booleans are lazy**: `+`, `-`, `^` and `batch_boolean` return at once, and the work is done at the first query (`bounding_box()`, `volume()`, `ray_cast`, …). A union of a 64-segment cylinder and a cone costs about 3 ms there. `Manifold.revolve` of the same profile builds the mesh directly (0.14 ms), with the same volume (to 1e-5 mm³) and, like `Manifold.cylinder`, a vertex at angle 0 on +x. | 3.5.5 | `geometry.hole_solid` (revolves the hole profile; one per candidate and side) | `manifold.revolve_hole` |
| `simplify(tolerance)` keeps the result manifold. | 3.5.5 | `repair.prepare` (`--simplify`) | `manifold.simplify` |
| A difference whose cutter face is coplanar with a model face opens the hole through that face, with no closing skin (exact volume and surface area, and a ray from above reaches the pocket floor); a union whose face is coplanar with a model face gives one body with the exact volume. | 3.5.5 | `tools` *(Phase 7)* | `manifold.coplanar_booleans` |
| `slice` exactly at a step height is one-sided (column under a plate: 1600 mm² instead of the 100 mm² contact); the intersection of the slices at ±ε gives 100 mm² for both step directions. | 3.5.5 | `geometry.cut_region`; ADR-0002 | `manifold.slice_at_step` |
| **Cuts by intersection leave flaps on coplanar faces.** When a model face lies exactly on the cutting plane, `split_by_plane`, `trim_by_plane` and an intersection with a box keep that face as a **zero-thickness, two-sided sheet** on the kept side: a 10 × 10 × 20 column on a 40 × 40 × 10 plinth, cut at the step, comes out with 4000 mm² of surface instead of 1000 and a 40 × 40 bounding box, still `NoError`, one body, the exact volume. Which side gets it depends on the face's direction. A **difference** with a box covering the other side is clean on both sides. | 3.5.5 | `geometry.split_at`, `geometry.clip` (every solid cut of the pipeline) | `manifold.coplanar_cuts` |
| **Gluing split halves back is not reliable.** The two halves of `split_by_plane` united with `+` are clean when the plane cuts through triangles (a cube cut at x = 5: 600 mm²), but when the plane passes through existing vertices a face stays inside, with the exact volume, `NoError` and one body: a box with a vertex ring on the plane gives 700 mm² instead of 600, a rounded knob cut at its equator keeps up to 117 mm². Cutting the whole in one go (the box joined to a prism over the half's shadow grown with `CrossSection.offset(0.05, JoinType.Round)`, kept by difference) gives the clean 600 mm². | 3.5.5 | `cutting._cut_merged` (never glues); ADR-0012 | `manifold.union_of_split_halves` |
| `decompose()` of a solid with a void returns the void as a **separate inside-out shell** (negative volume), and `Manifold.compose` of an outer shell and an inside-out shell drops the void. Reversing the void's triangles through `to_mesh64()` and `Mesh64` (float64 vertices, `uint64` indices) gives the solid of the void exactly, and the outer shell minus it is the original. | 3.5.5 | `geometry.bodies`, `geometry.reverse_winding` | `manifold.decompose_void_shells` |
| Validity is checked **by index only**: overlapping closed shells are `NoError` with their volumes summed (two 10 mm cubes overlapping by half: 2000 mm³), and an inside-out closed cube is `NoError` with volume −1000 as one shell. `decompose()` of a hollow sphere gives one positive and one negative shell. Reversing the triangles of `to_mesh()` (copied) gives the opposite signed volume; `geometry.reverse_winding` does it in float64 (`to_mesh64()`, `Mesh64`; row above). | 3.5.5 | `repair.normalize_shells`, `geometry.reverse_winding` (ADR-0007) | `manifold.signed_shells` |
| Two cubes sharing only an edge (vertices merged as on load) are **accepted as is**: `NoError`, two shells, 2000 mm³. The four half-edges of the shared edge pair up, so this is not a repair case (PLAN.md Appendix E, r5). | 3.5.5 | `repair.prepare` (no repair for it) | `manifold.edge_touching_cubes` |
| The stub file `manifold3d.pyi` ships without `py.typed`, so mypy ignores it: manifold3d is in the `ignore_missing_imports` list in `pyproject.toml`. | 3.5.5 | type checking | — (mypy run) |

### trimesh

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `load(..., force="mesh")` merges vertices by default (a 36-vertex soup loads as 8). Build "soup" fixtures with `process=False`. | 5.2.1 | `io.load_stl` | `trimesh.load_merges_vertices` |
| `load(..., file_type="stl", force="mesh")` **drops triangles with a non-finite coordinate** (a box plus one NaN triangle loads as the 12-face box, all vertices finite). Empty, garbage and facet-less files load as a mesh with no faces; a truncated binary STL raises (here `ModuleNotFoundError: charset_normalizer`; the type may vary, so `io.load_stl` catches any exception). | 5.2.1 | `io.load_stl` | `trimesh.load_drops_non_finite` (the empty and truncated cases: `tests/unit/test_io.py`) |
| `nondegenerate_faces`, `unique_faces`, `update_faces` and `remove_unreferenced_vertices` work: each removes exactly the degenerate face, duplicate face or unreferenced vertex planted in a box. | 5.2.1 | `geometry.basic_repair` | `trimesh.cleanup_methods` |
| `repair.fill_holes` closes a quad hole (one side of a box) but not a large one (a sphere without its cap). It needs networkx: without it, `ModuleNotFoundError` (checked in a child process where networkx looks uninstalled). | 5.2.1 | `geometry.basic_repair` | `trimesh.fill_holes` |
| `repair.fix_normals(multibody=False)` keeps a hollow sphere's void; `multibody=True` turns it solid. Never use `multibody=True` (ADR-0007). | 5.2.1 | `geometry._orient_faces` (same steps as `fix_normals(multibody=False)`) | `trimesh.fix_normals_multibody` |
| `repair.fix_winding` makes each connected group of faces agree with **one reference face**, the group's first face in `face_adjacency` order (`next(iter(g.nodes()))` in its source), **not with the majority**: with that face reversed in a hollow sphere's void, it reverses the void's 2047 other faces (and the void is then filled). `stlsplit` reverses back any group where more than half the faces changed. | 5.2.1 | `geometry._orient_faces` | `trimesh.fix_winding_reference_face` |
| `apply_scale` and `repair.fix_winding` have no type annotations, so mypy's strict mode needs a `# type: ignore[no-untyped-call]` on those calls. | 5.2.1 | `io.load_stl`, `geometry._orient_faces` | — (mypy run) |
| Binary STL export starts with an 80-byte zero header (no timestamp: determinism). | 5.2.1 | `io` export *(Phase 9)*; ADR-0010 | `trimesh.stl_zero_header` |
| `Scene.export(file_type="glb")` works when numpy, scipy and networkx are the only importable third-party packages (checked in a child process where every other installed package looks uninstalled). | 5.2.1 | `io` preview *(Phase 9)* | `trimesh.glb_export` |

### shapely

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| Negative `buffer`, `ops.polylabel`, `contains` and `intersection` work as expected on a 10 mm square. The vectorized `shapely.contains_xy` **excludes the boundary**. | 2.2.0 | `geometry.polylabel_point`, `geometry.clip_to_cells` (intersection), `cutting._piece_at` (contains); `connectors.safe_region` (buffer), `connectors.candidates` (`contains_xy`) | `shapely.operations` |

### pymeshlab (optional)

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| The filters `meshing_repair_non_manifold_edges`, `meshing_repair_non_manifold_vertices`, `meshing_close_holes` and `meshing_re_orient_faces_coherently` exist with these names, and in that order turn a box with a stray triangle on one edge (1 non-manifold edge, 2 open edges) into a valid 1000 mm³ box. Failures raise `pymeshlab.PyMeshLabException`. The filters are **plugins that need system libraries**: without `libOpenGL.so.0` (Ubuntu package `libopengl0`, absent from the GitHub Ubuntu image), `import pymeshlab` works but prints "Unable to load the following plugins" and `meshing_close_holes` is missing (an `AttributeError` when called). `geometry.deep_repair_problem` checks every filter first. | 2025.7.post1 | `geometry.deep_repair`, `geometry.deep_repair_problem` | `pymeshlab.repair_filters` (skipped when pymeshlab isn't installed; fails if its plugins didn't load) |

### matplotlib

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| `DejaVuSans-Bold.ttf` is bundled at `matplotlib.get_data_path()/fonts/ttf/`. The outer contours of `TextPath` glyphs are **clockwise**, so the Positive fill rule loses them: use EvenOdd (ADR-0009). | 3.11.2 | `io.resolve_label_font`; `labels` *(Phase 8)*; `geometry.crosssection_from_contours` | `matplotlib.font_and_glyph_winding` |

### Determinism

| Behaviour | Version | Used by | Spike check |
|---|---|---|---|
| A small split-and-drill pipeline (manifold3d booleans, trimesh STL export) run in two separate processes with random hash seeds writes byte-identical files. | all above | ADR-0010, N1 | `determinism.subprocess_bytes` |

## Tooling notes

- `ruff format` also formats Python code blocks inside Markdown files; that would rewrite the
  aligned examples in PLAN.md and the docs, so `*.md` is excluded in `pyproject.toml`.
