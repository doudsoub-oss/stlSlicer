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

Chooses how the model sits on the bed (ADR-0008). Input: the repaired body (mm, input frame)
and U from `config.derived(cfg).usable`. Output: the body in the **cutting frame** and an
`Orientation` holding the 4×4 input → cutting transform.

**1. Candidates.** The six axis orders, each built as a proper rotation (det = +1), listed in
`grid.ROTATIONS` in tie-break order. Rows are cutting axes: cutting X takes the first signed
input axis, and so on.

| # | Name | cutting (X, Y, Z) = input | R |
|---|---|---|---|
| 1 | `identity` | (+X, +Y, +Z) | `[[1,0,0],[0,1,0],[0,0,1]]` |
| 2 | `90 deg about Z` | (−Y, +X, +Z) | `[[0,-1,0],[1,0,0],[0,0,1]]` |
| 3 | `90 deg about X` | (+X, −Z, +Y) | `[[1,0,0],[0,0,-1],[0,1,0]]` |
| 4 | `90 deg about Y` | (+Z, +Y, −X) | `[[0,0,1],[0,1,0],[-1,0,0]]` |
| 5 | `120 deg about (1,1,1)` | (+Z, +X, +Y) | `[[0,0,1],[1,0,0],[0,1,0]]` |
| 6 | `240 deg about (1,1,1)` | (+Y, +Z, +X) | `[[0,1,0],[0,0,1],[1,0,0]]` |

An odd axis order swaps two axes. A plain permutation matrix would then have det = −1 and
mirror the model (a left shoe becomes a right one), so it is built as the +90° turn about the
third axis, which negates one of the two swapped axes. The even orders are the identity and the
two cyclic permutations.

**2. Choice.** Each candidate's cell count is Π `cell_count(extent_i, U_i)` (below) of its
rotated extent. The extents are just permuted, so no mesh is transformed to compare them.
The lowest count wins. On a tie, the first in the table wins: the model as it is, then the
quarter turn that keeps its Z up, then the other quarter turns, then the diagonal turns.
`--no-auto-orient` always takes the identity.

- 460 × 100 × 100 on the default bed (U = 210 × 210 × 240): the identity needs
  3 · 1 · 1 = 3 cells; rows 4 and 6 put the 460 mm side along Z, 1 · 1 · ceil(460/240) = 2.
  Row 4 is listed first and wins.
- 500 × 100 × 100 on a 220³ bed: every candidate needs 3 cells, so the identity stays.

**3. Cutting frame.** `x_cut = R · x_in + t`: rotate, then translate so that the bounding-box
minimum is the origin. With a signed permutation, both steps are exact, and the minimum is
exactly (0, 0, 0) (docs/LIBRARY_NOTES.md). `Orientation.input_to_cutting` is
`[[R, t], [0, 0, 0, 1]]`, row by row. Phase 9 writes it to `assembly.json`, so any tool can map
the parts back onto the original model.

Code: `grid.orient`, `grid.choose_rotation`, `grid.to_cutting_frame`. Tests:
`tests/unit/test_grid.py` (`test_auto_orient_*`, `test_every_candidate_rotation_is_a_proper_rotation`,
`test_chiral_l_keeps_its_handedness`, for every rotation).

## Even grid

Splits each axis into the fewest equal cells that fit U (ADR-0003). Input: the extent in the
cutting frame and U. Output: a `Grid` (counts, planes, U, extent), plus W012 when the model
already fits.

- **Count per axis:** `n = max(1, ceil(extent / U − 1e-9))`. The slack (`GRID_TOLERANCE`) keeps
  float noise in an extent that is an exact multiple of U from adding a cell: 420.00000000000006
  on U = 210 gives 2 cells, not 3.
- **Planes** at `k · extent / n`, k = 1 … n − 1, with `Plane.index` = k − 1. 500 mm on
  U = 210: 3 cells, planes at 166.666667 and 333.333333. Equal cells give pieces of similar
  size, where filling two beds would leave an 80 mm sliver.
- **Cells** (i, j, k) span, along each axis, two consecutive values of
  `grid.axis_bounds`: 0, the plane offsets, then the extent. `grid.cell_indices` lists them
  sorted by (i, j, k); `grid.cell_bounds` gives one box.
- **Fit check** (`grid.fits`): every cell's size is at most `U · (1 + 1e-9)`; otherwise it is
  a bug (exit 4). The bound is relative because the count's slack is: a cell can be up to
  0.2 nm over U = 210 (PLAN.md Appendix E, r6). It is evaluated as `size / U − 1e-9 ≤ 1`, the
  count's own expression. Written as `size <= U * (1 + 1e-9)`, it rounded differently for one
  float at the edge: a 100 × 100 × 230 box whose bottom sat 2.3e-7 mm below zero (float32
  export noise) counted as one cell on U = 230, then failed the check. With two cells or more,
  the slack leaves a margin of at least 5e-10 for the rounding of `k · extent / n`. With the
  formula, n is also minimal: n − 1 cells would each be larger than U.
- **Peg mode:** U is smaller by L_max/2 per axis (200 × 200 × 230 by default), because pegs
  stick out of their cell (ADR-0005). It comes from `config.derived`, like every number.
- **One cell on every axis:** W012 (info), "nothing to cut". The pipeline continues with one
  piece, without faces, connectors or labels, and exits 0.

Nudging (Phase 6) then moves planes within ± `nudge_window`, keeping every cell inside U.

Code: `grid.even_grid`, `grid.cell_count`. Tests: `tests/unit/test_grid.py` (the long box,
the tolerance cases, peg mode, W012, and the hypothesis properties
`test_every_cell_fits_the_usable_volume` and `test_cell_counts_are_minimal`).

## Sections and cut faces

Turns the normalized body and the grid into pieces and the cut faces between them. Input: the
body in the cutting frame and the `Grid`. Output: `Piece`s (ID, cell, body, face IDs) and
`CutFace`s (ID, plane, neg and pos piece, region in plane-local (u, v)). Code:
`cutting.split_cells`, `cutting.cut_faces`, `geometry.cut_region`, `geometry.clip_to_cells`.

**1. Splitting.** Along the X planes first, then each X slab along the Y planes, then each
of those along the Z planes; empty results are dropped. Each side is cut **by difference**
(`geometry.split_at`: the body minus a box covering the other side). `split_by_plane`,
`trim_by_plane` and intersections leave a zero-thickness two-sided sheet where a model face
lies exactly on the plane: a column on a plinth cut at the step kept the plinth's 40 × 40 top,
4000 mm² of surface instead of 1000 (docs/LIBRARY_NOTES.md). Such a sheet joined separate
columns into one piece and gave the pieces the wrong bounding boxes and shadows. With the
difference, no rule is needed to keep planes away from model faces (PLAN.md Appendix E, r7).

**2. Bodies.** Each cell's material is split into bodies by `geometry.bodies`: each outer
shell minus the voids it holds. `decompose()` alone returns a void as an inside-out shell of
its own, and dropping it (its volume is negative) would fill the void (PLAN.md Appendix E,
r7). Bodies under 1e-6 mm³ (`MIN_BODY_VOLUME`) are split debris and dropped.

**3. Piece IDs** (PLAN.md §4.3). One body: `X{i}-Y{j}-Z{k}`. Several: `-a`, `-b`, … in the
order (bbox min z, min y, min x, larger volume first), and `-aa`, `-ab`, … after `-z`. Ties
beyond that keep `decompose()` order, which is deterministic. Pieces are listed in cell order,
then suffix: the **piece order** used everywhere else.

**4. Contact region** of a plane (ADR-0002): `slice(o − ε) ∩ slice(o + ε)` of the normalized
body, ε = 0.01 mm, as shapely polygons with holes. A single slice is one-sided when a model
face lies on the plane: a 40 × 40 plate on a 10 × 10 column, sliced at the step, gives
1600 mm² instead of the 100 mm² contact. The intersection is right in both step directions
(`plinth_step`, `overhang_step`), so planes never need to keep away from model faces. Features
thinner than 2ε at the plane are ignored.

**5. Cut faces.** For every plane and every pair of cells adjacent across it (neg cell in
cell order):

1. Clip the region to the rectangle the two cells share (`clip_to_cells`), split it into
   connected polygons and drop parts of 1e-6 mm² or less (float slivers along a cell edge).
2. Take each polygon's polylabel point p (the interior point farthest from the boundary).
3. The neg piece is the neg cell's piece whose section at `o − 0.05` contains p; the pos piece
   likewise at `o + 0.05`. Sections are cached per plane. If no piece matches on a side, the
   probe is retried at 0.005 mm; if none matches still, the polygon is too thin for a connector
   and is skipped (logged at debug level).
4. One `CutFace` per polygon: `{neg}~{pos}`, plus `#2`, `#3`, … when the same two pieces share
   several regions, in polylabel order (u, then v). Two pieces can only share one plane, so
   the numbering is per cell pair.

Faces are in **face order**: by plane (X planes first, by index), then neg cell, then polylabel
point; `Piece.face_ids` follows it.

**6. Checks** (PLAN.md §5.3): every piece is `NoError` with a positive volume (I1), and the
volumes add up to the reference volume within 0.1 % (I3); otherwise `AssertionError`, a bug
(exit 4). Every face has one piece on each side, and its region lies inside both pieces'
sections (I4, by construction; tested).

Examples with the default ε: a 200 mm cube on a 120³ bed (U = 110) gives 8 pieces and 12 faces
of 100 × 100 mm. A torus cut through its hole gives 2 pieces and 2 faces on the one plane,
`X0-Y0-Z0~X1-Y0-Z0` and `…#2`. The hollow sphere r = 150 cut once gives a ring face
π(150² − 148²) ≈ 1872 mm² with one hole.

Tests: `tests/unit/test_sections.py` (ring, U shape, separate squares, both steps, axes,
clipping, shadows, voids), `tests/integration/test_cutting.py` (the cube, torus, hollow
sphere, model faces on a plane, suffix order, voids, skipped regions, the hypothesis
properties `test_piece_volumes_add_up_to_the_reference_volume` and
`test_cutting_adds_no_surface_but_the_cut_faces`, determinism).

## Small-piece merge

Grid cuts can leave slivers that are hard to print and to handle (ADR-0012). Input: the pieces
and faces in piece and face order, U from the grid (peg-adjusted), V_small =
`advanced.small_piece_volume` (500 mm³; 0 turns merging off). Code:
`cutting.merge_small_pieces`.

Each piece S with a volume under V_small, in piece order, is merged into its neighbour P only
if all of these hold; otherwise it gets **W004** with the reason:

1. S shares cut faces with **exactly one** piece P. With none, S is a separate body: no merge
   (W008 below).
2. S hasn't absorbed a piece itself. It would then span two cells, and the guard below is
   defined for one cell (r7).
3. The bounding box of P and S together fits U (`grid.fits`, the count's own arithmetic).
4. **Footprint guard.** No other piece of S's cell (as cut, including one merged elsewhere
   since) overlaps S's shadow along the axis a of the shared faces, grown by 0.05 mm
   (`MERGE_MARGIN`), by more than 1e-6 mm². Shadows are `project()` after rotating a to Z.
5. The merged piece can be cut cleanly (below).

**Cutting the merged piece.** P ∪ S is never computed as a union: the halves of a split glue
back with a face left inside wherever the plane passes through mesh vertices (a box with a
vertex ring on the plane keeps 100 mm²; a rounded knob cut through its equator keeps up to
117 mm²; docs/LIBRARY_NOTES.md). Instead, the normalized body is clipped (by difference,
`geometry.clip`) to P's cell joined to one prism per absorbed piece: its shadow grown by
0.05 mm and kept within its own cell, from 0.05 mm inside P's cell to the far side of its
cell. Inside a prism the plane is never cut. The guard, checked on the same grown shadow,
keeps the other pieces of the absorbed piece's cell out of its prism, and keeping each prism in
its own cell keeps every other cell out (a piece absorbed across a second plane could
otherwise reach into a neighbour's cell). The merged piece is the body that holds S (largest
overlap with S, not merely the right volume: P's cell may hold another body of the same
volume), and its volume must be P + S within 1e-6; otherwise something else was caught and the
merge is refused (W004).

A merge (**W005**) replaces P's body, drops the faces between P and S, and appends S to
`P.merged_from`; P keeps its ID and its other faces. After all merges, every piece without a
cut face gets **W008** (no connector, no label), unless the grid is a single cell (W012
already says nothing was cut). Two small halves of a tiny body end as one piece that way: the
first merges into the second, which has no face left.

**Why the footprint guard keeps assembly possible** (proof sketch; assembly order is
ADR-0004: X joins build rows, Y joins build layers, Z joins stack the layers). Let S lie in
cell c and P in c', adjacent across a plane π of axis a.

- S's shadow along a lies inside c's cross-section, so sweeping S along a stays inside the
  column of cells along a through c, and inside that column, inside c on the static side of
  π (S starts on P's side and slides in from there).
- In the join along a (the stage of axis a), the moving sub-assembly holds P and S, the static
  one holds cell c and the cells beyond it. The only static material S could hit on its way
  in is in c, inside S's shadow, which the guard keeps empty. Nothing else moves relative
  to S.
- In the earlier stages, S travels with P along the other axes. It sits in the region of c,
  where no piece of P's row or layer is, and the pieces of c's row or layer aren't part of
  that assembly yet. In the later stages, c and c' are already in the same sub-assembly.
- S touches no piece but P, so its cut faces all lie on π and are dropped with the merge:
  every remaining face is still perpendicular to its join axis (I7).

The guard is conservative: it also rejects pieces in S's shadow on the far side of S, which
S never reaches.

Examples (`tests/integration/test_cutting.py`): the `knob` tip (180 mm³) merges into the box
half (W005). With a block over the tip's footprint (`knob(blocked=True)`), or a fin 0.025 mm
beside it, it stays on its own (W004). A small piece between two pieces, one that would make
the merged piece 105 mm on U = 102, and one that already absorbed another all give W004.

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
