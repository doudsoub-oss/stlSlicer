# Algorithms

For maintainers. One section per algorithm: inputs, outputs, formulas (with the default numbers
filled in), rationale, edge cases, and links to its tests. Numbers are defined in PLAN.md §6 and
`config.py`; this file links to them.

## Radius-compensated cylinders

Holes are modelled with `n_seg` segments and a vertex radius `r_model = r_h / cos(π / n_seg)`, so
the polygon flats sit at r_h (PLAN.md §6.2). With the defaults (r_h = 2.7, n_seg = 64):
r_model = 2.7033. Without compensation and with manifold3d's default 16 segments, the flats would
sit 0.05 mm inside: a quarter of a 0.2 mm clearance.

- Code: `geometry.cylinder_solid(..., compensate=True)`.
- Tests: `tests/unit/test_geometry.py::test_compensated_cylinder_flats_sit_at_requested_radius`.

## Repair and shell normalization

Turns the loaded mesh into one valid solid without damaging valid models or their voids
(ADR-0007). Input: the mesh from `io.load_stl` (mm, input frame, vertices merged on load).
Output: a `Manifold` with status `NoError` and a positive volume (I1), and a `RepairReport`
whose `reference_volume` is the reference of every later volume check (I3).

**1. Try first.** `Manifold(mesh)`; if its status is `NoError`, no repair runs at all.

**2. Basic repair** (trimesh, `geometry.basic_repair`), in this order: merge duplicate
vertices; drop degenerate faces, then duplicate faces; drop unreferenced vertices; orient the
faces (below); `fill_holes` (closes one-triangle and quad holes only). Then retry. W007 lists
every step that changed something, with its count.

- **Orienting the faces** is `fix_normals(multibody=False)` with one change. Its `fix_winding`
  makes each shell agree with one reference triangle (the shell's first face in
  `face_adjacency` order), not with the majority. When that triangle was the reversed one, it
  reversed the 2047 good triangles of a hollow sphere's void, and the void was filled
  (14.06M mm³ instead of 554 829). So a shell where more than half the faces changed is
  reversed back, then `fix_inversion(multibody=False)` reverses the whole mesh if its volume
  is negative.
- Never `fix_normals(multibody=True)`: it turns internal voids outward. At plan time a hollow
  sphere of 557k mm³ became 27.6M mm³.

**3. Deep repair** (pymeshlab, only with `--deep-repair`): remove non-manifold edges, then
non-manifold vertices, close holes, re-orient faces coherently; retry. Otherwise, or if it
still fails, exit 2 with the counts (`geometry.mesh_defects`):
`the mesh isn't a closed solid after basic repair: 2 open edges, 1 non-manifold edge, 1 body.
Try --deep-repair …`.

**4. Shell normalization** (`repair.normalize_shells`). A valid manifold can still hold
overlapping shells (each shell is closed, so the mesh is valid by index; its volume counts the
overlap twice) or inside-out shells (negative volume). It runs when `decompose()` returns more
than one shell, or one shell with a negative volume:

1. **Containment.** Each shell, taken as a solid (reversed with `geometry.reverse_winding` if
   it faces inwards), gets a **container**: the smallest other shell it lies inside, by
   `(S − T).volume() ≤ 1e-6 · S.volume()` (`VOID_RESIDUAL_FRACTION`). Bounding boxes and
   volumes rule out most pairs before any boolean. Of two identical shells, the first listed
   contains the second.
2. **Roles**, decided from the outside in:
   - a shell without a container is **solid**. If it faces inwards it is turned the right way
     out (W011), unless it lies inside the union of the outermost solids: then it is a **void
     spanning** several overlapping solids;
   - a shell facing the same way as its container plays the same role (a part embedded in a
     solid; a void inside a void, which adds nothing);
   - a shell facing the other way plays the opposite role: a **void** in a solid, a ball in
     that void, a void in that ball, at any depth.
3. **Pieces.** Each solid shell minus the voids it directly contains is one piece.
4. **Result** = union of the pieces − the spanning voids, plus the pieces that lie inside a
   spanning void.
5. **W010** when the union of the pieces is smaller than the sum of their volumes by more than
   1e-6 (`SHELL_OVERLAP_FRACTION`): shells overlapped. **W011** gives the number of shells
   whose role disagreed with the way their faces point.

Why this way:

- A plain union of every shell, `batch_boolean(decompose(), Add)`, fills voids. At plan time
  it made the hollow sphere solid (14.1M mm³ instead of 557k).
- Roles come from a shell's orientation *relative to its container*, not from its sign alone.
  A model inside out as a whole has its outer shell facing in and its void's shell facing out;
  by sign alone the void became a solid of its own (14.06M mm³ instead of 554 829).
- A void is subtracted only from the shell that contains it. Subtracting every void from the
  union of every solid cut two overlapping hollow spheres' walls where each crosses the other's
  void (927 978 mm³ instead of 1 106 891). It also deleted a ball loose inside a void.

**5. Simplify** (`--simplify TOL` > 0): `Manifold.simplify(TOL)`; surfaces move by less than
TOL and the result stays manifold. The reference volume is measured after it, because that
is the body that gets cut. If the tolerance erases the whole model, exit 1 naming `--simplify`.

**Exit 2** also when the normalized mesh encloses no volume: a closed but flat surface (the
same triangles facing both ways) is a valid, empty manifold.

Edge cases and limits:

- Two cubes sharing only an edge or a vertex are accepted as is, as two bodies: manifold3d
  pairs the four half-edges of a shared edge (docs/LIBRARY_NOTES.md).
- Nesting works at any depth. A shell that only partly overlaps another has no container, so
  it is outermost: overlapping solids are unioned, and an inward-facing shell partly outside
  every solid is an inverted body.
- Triangles with a non-finite coordinate are dropped by trimesh while loading, so they never
  reach repair. A stray extra one simply disappears; a real face lost that way leaves a hole
  for basic repair.

Tests: `tests/integration/test_repair.py` (one test per case above),
`tests/unit/test_io.py` (loading, W006), `tests/unit/test_cli.py` (exit 2 through the CLI).

## Auto-orientation
TODO (Phase 3)

## Even grid
TODO (Phase 3)

## Cut regions
TODO (Phase 4)

## Splitting, piece IDs and small-piece merge
TODO (Phase 4)

## Connector placement
TODO (Phase 5)

## Plane nudging
TODO (Phase 6)

## Tool solids, pins and the calibration kit
TODO (Phase 7)

## Label layout
TODO (Phase 8)

## Assembly order
TODO (Phase 9)
