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

Nudging (below) then moves planes within ± `nudge_window`, keeping every cell inside U.

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

Decides where the connectors of every cut face go and how long their pins are. Input: the
pieces and cut faces from the cutting stage. Output: `Connector`s (ID `{face}/c{n}`, kind,
axis point (u, v), d, pin length L, hole depth on each side) and the diagnostics W001, W002
and W009. Code: `connectors.place` and the functions below; every number is in PLAN.md §6.
The values in brackets are the defaults (d = 5, c = 0.2, w = 2, ch_h = 0.4, L_max = 20).

Faces are processed in **face order** (by plane, neg cell, polylabel point: the order of
`cutting.cut_faces`, not the order of the ID strings), and each face's candidates in its
trial order. A hole accepted on one face constrains the faces processed after it.

**1. Safe region** (`safe_region`): the region inset by `w + r_h + ch_h` [5.1 mm], with round
joins. An axis inside it leaves a wall of w around the hole and its mouth chamfer on the
face. A 40 × 40 face keeps 29.8 × 29.8 = 888 mm²; the 2 mm ring of the hollow sphere keeps
nothing, so it gets W001 (no room). The inset can split a region: a U whose 10 mm base has
no room keeps one strip per arm.

**2. Candidates** (`candidates`): the points (i·g, j·g) [g = d/4 = 1.25 mm] strictly inside
the safe region (shapely's `contains_xy` excludes the boundary), plus the polylabel point of
each part, without duplicates, sorted by (u, v).

**3. Count** (`connector_count`):
- 0 without candidates;
- 1 if no two candidates are at least s_min [3d = 15 mm] apart, checked on the diameter of
  their convex hull;
- otherwise `clamp(floor(area(safe) / A), 2, k_max)` [A = (6d)² = 900 mm², k_max = 4].

**Two connectors whenever two fit**: a single round pin lets the pieces rotate. The 40 × 40
face (888 mm² < A) still aims for 2; a 100 × 100 face (8064 mm²) for 4. k_max = 1 gives 1.

**4. Trial order** (`select`); ties always go to the (u, v) order of the candidates:
- k = 1: the polylabel point of the largest part first, then the other candidates by
  decreasing distance to the safe region's boundary.
- k ≥ 2: the farthest-apart pair first (the hull diameter), then farthest-point sampling: the
  untried candidate **farthest from the accepted connectors**, or from the tried candidates
  while none is accepted. A rejected candidate is thus followed by its neighbours, and the
  connectors stay spread out (PLAN.md Appendix E, r8). A candidate closer than s_min to an
  accepted connector is never tried: when the farthest one is, so are all the others, and the
  face stops there.
- At most `MAX_CANDIDATE_TRIALS` [256] candidates per face go through the 3D checks; a face
  whose first 256 all fail gets W001, which says so.

On the 100 × 100 face the order is (6.25, 6.25), (93.75, 93.75), (6.25, 93.75),
(93.75, 6.25): both diagonals are diameters, and the first in (u, v) order wins.

**5. 3D checks** (`check_candidate`, ADR-0014), on each side that needs a hole: both for
dowels; for pegs only the pos side, since the peg stands on the neg piece.

1. **Depth** (`available_depth`). Nine rays: one on the axis and eight on a circle of radius
   `r_h + w` [4.7 mm] around it (`RAY_CIRCLE_COUNT`). Each starts `RAY_START_OFFSET`
   [0.01 mm] inside the piece and runs along the inward normal for `h(L_max) + w + 1`
   [13.5 mm]. Never start a ray on the face: whether the face itself is reported depends on
   the library (trimesh reports it at 0, manifold3d doesn't). Depths are measured **from the
   face** (the offset added back), and the available depth is the smallest one minus w, or
   "enough" if no ray hits. 12 mm of material behind the face gives 10.
2. **Pin length** (`lengths_that_fit`): the standard lengths [20, 18, 16] whose hole depth
   `h(L) = L/2 + a` [10.5, 9.5, 8.5] is at most the available depth on every side, longest
   first. With 10 mm available, 20 doesn't fit and 18 does (W002); with 4 mm, none (W001).
3. **Exact containment** (`fits_inside`): a cylinder of radius `r_h + w` (flats at that
   radius) from the face to depth `h(L) + w` must lie inside the piece, up to 1e-6 of its
   volume. If it doesn't, try the next shorter L; if none passes, reject the candidate. This
   catches pieces that narrow behind the face between the rays: a small void 4.1 mm from the
   axis, between two rays, fails it.
4. **Collisions**: each new hole (`geometry.hole_solid`: radius r_h, mouth chamfer ch_h,
   depth h(L), the shape the tools will cut in Phase 7) must be at least w from every hole
   already accepted in the same piece (`min_gap`, searching up to w + 1 mm), up to
   `LENGTH_TOLERANCE` (`min_gap` gives 1.999999999999993 for a gap of exactly 2). Otherwise
   the candidate is rejected (not shortened). This catches holes on perpendicular faces near a
   shared edge, whose axes cross at 0 mm in a 2 × 2 × 2 grid, and coaxial holes drilled from
   opposite faces of a thin piece. Two shortcuts give the same answer faster: bounding boxes
   w apart mean far enough, and an axis that meets the other hole (one ray cast) means the
   holes cross; `min_gap` costs 2 ms on crossing solids against 0.15 ms otherwise.
5. **Accept**: the connector records L and h(L) on each side (0 on a peg's side); its holes
   join the piece's list for the later checks.

**6. Diagnostics**, per face in face order: **W001** when the face has no connector (no
room, or every candidate tried failed the checks), otherwise **W002** when some pins are
shorter than L_max (one diagnostic listing them) and **W009** when there is exactly one.

**7. Invariants.** Every axis point lies strictly inside its face's safe region (I6, asserted:
`AssertionError`, exit 4). No two holes of a piece are closer than w (I5, by the collision
check; tested on the 2 × 2 × 2 cube and the 3 × 3 × 3 grid of 15 mm pieces).

Holes are built by revolving their profile, not as a union of a cylinder and a cone:
manifold3d evaluates booleans lazily, and that union costs about 3 ms at its first query
against 0.14 ms for the revolve (docs/LIBRARY_NOTES.md). On the 2 × 2 × 2 cube, placement
tries 541 candidates for 48 connectors in about 1.5 s (3.8 s with the union).

Examples: a 200 × 100 × 100 box cut once gives 4 connectors in the corners of the safe
region; an 80 × 40 × 40 box gives 2 on the diagonal; a 45 mm cube on a 30³ bed (15 mm pieces)
gives one connector on 13 faces (W009) and none on the other 41 (W001), because the holes of
a 15 mm piece collide.

Tests: `tests/unit/test_placement.py` (safe region, candidates, count rule, trial order,
trial cap, standard lengths), `tests/integration/test_connectors.py` (the 100 and 40 mm
faces, the ring, the U, the `wedge`, a void between the rays, 12 and 6 mm behind the face,
the 2 × 2 × 2 cube, 15 mm pieces, pegs, `--connector none`), `tests/unit/test_geometry.py`
(holes).

## Plane nudging

Moves each plane of the even grid a little, so that it avoids thin features and faces with no
room for a connector, without breaking the bed fit and without moving planes for no gain
(ADR-0003). Input: the normalized body (cutting frame), the even `Grid` and the configuration.
Output: the same grid with some plane offsets changed (indices, U, counts and extent are
unchanged). Code: `grid.nudge` and the functions below; W_n = `advanced.nudge_window` (5 mm),
δ_n = `advanced.nudge_step` (0.5 mm).

**1. Order.** Planes are taken one after the other: X planes, then Y, then Z, each axis by
increasing offset. Each plane is scored on the grid as the planes before it left it, so a
move changes the room the next planes have (task 3). A plane is never revisited.

**2. Candidate moves** (`candidate_shifts`). δ = j · δ_n for whole numbers j (so the steps
don't add up rounding errors) with |j| ≤ N, the window counted in steps:
N = floor(W_n / δ_n + 1e-9) (`derived(cfg).nudge_steps`, 10 by default). The slack
`STEP_COUNT_TOLERANCE` is there because 0.3 / 0.1 is 2.9999999999999996 in floats.
Validation keeps N ≤ 100 (`MAX_NUDGE_STEPS`; W_n / δ_n over 100 exits 1, PLAN.md Appendix E,
r9), so a plane has at most 201 positions: a tiny `nudge_step` made the search build millions
of them, or overflow. A move is kept when:

- the plane stays strictly between its neighbours (the previous and next planes, or 0 and
  the extent; r9);
- both cells it bounds still fit U, by `grid.fits`, the count's own arithmetic.

These two are the plane's **slack**, side by side, so the window is min(W_n, slack) on each
side. Three cells of 238 mm on U = 240 leave each plane 2 mm either way; once the first plane
has moved 1.5 mm up, the middle cell is 236.5 mm and the second plane may move up to 3.5 mm
up. With N = 0 (W_n = 0, or a window under one step) nudging does nothing; with a slack
under one step, the plane stays without being scored.

**3. Score** of a position (`plane_regions`, `score_regions`): the plane's contact region
(`geometry.cut_region`, ADR-0002), clipped to every pair of cells across it
(`geometry.clip_to_cells`, the pairs from `grid.cell_pairs`, as the cutting does), then a tuple
compared lexicographically, lower is better:

1. the number of regions whose safe region (`connectors.safe_region`, inset 5.1 mm) is empty;
2. the number of tiny islands: regions under 4 · π · (d/2)² (78.5 mm² at d = 5);
3. |δ|;
4. δ.

The last two keep a plane where it is when moving gains nothing, and make the choice unique,
so it doesn't depend on the order in which the moves are generated. With the defaults a tiny
island never has room (a disc of radius 5.1 is already 81.7 mm²), so the second key only
matters as a tie-break between positions with the same number of faces without room, or with
a large d (at d = 10 a 9 mm disc has room and is still an island).

**4. Choice** (`choose_shift`). Moves are scored from the smallest |δ| outwards, −δ before
+δ, and scoring stops at the first position that scores (0, 0): nothing after it can beat it.
The result is the one scoring every move would give, and most planes of a solid model cost a
single score (δ = 0).

**5. Check.** After the last plane, every cell must fit U and the bounds must increase
strictly (`grid.check_fits`, the check `even_grid` runs too); otherwise `AssertionError`, a bug
(exit 4).

**No coplanar-vertex rule** (task 5). manifold3d splits through mesh vertices, and
`cut_region` gives the true contact when a model face lies on the plane, so planes never need
to keep away from either. An earlier rule ("no vertex within 0.01 mm of the plane") never
terminates on a dense mesh: a 1M-triangle model has dozens of vertices within any such band.

Example: `tall_figure` is two 60 × 60 boxes joined by a 6 × 6 neck from z = 148 to 153, 300 mm
tall. The default bed (U_z = 240) puts the even plane at z = 150, in the neck: one region of
36 mm², no room and a tiny island, score (1, 1). The moves are tried in the order 0, −0.5,
+0.5, −1, … At z = 148 the contact is still the neck (the slices at 147.99 and 148.01
intersect in the neck). z = 147.5 (δ = −2.5) cuts the lower box, a 60 × 60 face scoring
(0, 0), and wins over z = 153.5 (δ = +3.5). A neck from 140 to 160 fills the whole window:
every position scores (1, 1), and the plane stays at 150.

Edge cases and limits:

- A plane in a gap between bodies cuts nothing: it scores (0, 0) where it is, and stays.
- **The score is 2D.** It sees the face, not the material behind it. Moved just off a neck,
  the plane leaves a thin slab of the box under the neck (0.5 mm for `tall_figure`), so the
  holes on that side have no depth and the face still gets W001 from the 3D checks. The face
  is still the full 3600 mm² section, glued, instead of the 36 mm² neck.
- **One plane at a time.** A plane is scored with the planes of the axes after it still at
  their even positions, and isn't revisited when they move (ADR-0003, "Consequences").
- **Cost.** Each position scored is two slices of the whole body. The polygons are not
  sorted by polylabel point (`ordered=False`): a score only counts them, and polylabel took
  97 % of the time on the hollow sphere (4.9 s for its 3 planes, 0.11 s without). Worst case
  measured: a 1M-triangle hollow sphere, whose faces never have room, so all 21 positions of
  its 3 planes are scored: 2.1 s. At the limit of 100 steps, a plane can cost 201 scores,
  about 7 s at 1M triangles.

Tests: `tests/unit/test_nudge.py` (the 500 mm box keeps 500/3 and 1000/3 exactly, the fit
check, candidate moves and slack, the window tolerance, the score, ties, the hypothesis
properties
`test_every_candidate_shift_keeps_both_cells_within_u` and
`test_choice_does_not_depend_on_candidate_order`), `tests/integration/test_nudge.py` (the
tall figure, a neck longer than the window, a gap between bodies, W_n = 0, the slack left by
the plane before,
the hypothesis property `test_every_cell_fits_u_after_nudging`), `tests/unit/test_cli.py`
(the dry run prints the nudged planes).

## Tool solids, pins and the calibration kit

`tools.apply` turns the placed connectors into real holes and pegs and groups the loose pins.
`calibrate.build_kit` builds the clearance test kit. Numbers below use the defaults (d = 5,
c = 0.2, ch_h = 0.4, ch_p = 0.5, f = 0.4, n_seg = 64).

### Tool solids

**Input:** pieces, faces and connectors, cutting frame. **Output:** new pieces in the same
order, and the pin groups.

For each piece, exactly three booleans:

1. one batched union of its hole cutters (`geometry.union_all`);
2. one subtraction from the piece;
3. one batched union of its pegs, added to the result. Pegs come last, so a hole can't eat one.

- **Holes** are `connectors.hole_solids`, the solids the collision check measured (ADR-0014):
  a bore with its flats at r_h = 2.7, and a 45° mouth chamfer from r_h + ch_h at the plane to
  r_h at depth ch_h. Both sides are built from the same (u, v), so they line up by
  construction. Each piece is cut with its own side: the two together are one tool, and cutting
  with the whole of it removes the same volume, because each side lies inside its own piece.
- **Pegs** (`tools.peg_solid`) stand on the neg piece: radius d/2, up to L/2 above the plane,
  with a tip chamfer ch_p. The pos piece gets a hole of depth h(L) = L/2 + a, so the tip keeps
  the axial play a.
- **Tools overlap the face by `TOOL_OVERLAP` (0.01 mm).** A cut face isn't exactly on its plane:
  a torus cut at y = 29.5 has vertices at 29.499999999999993. A peg based exactly on the plane
  then misses the face by 7e-15 mm and stays a **separate shell** with the right volume and a
  valid status. So pegs reach 0.01 mm into the face and hole cutters 0.01 mm past it
  (docs/LIBRARY_NOTES.md, `manifold.face_float_noise`). The volume checks use the tools without
  the overlap.

**Checks** (`tools.check_piece`, a failure is a bug, exit 4), for every piece:

- `NoError`, a positive volume, and as many outer shells as before (I1). Void shells aren't
  counted: a hole may swallow a void small enough for the containment check to tolerate;
- the volume removed equals the holes' volume, and the volume added the pegs', within 5 %;
- the piece fits `derived(cfg).printable`, bed − 2·margin (I2). In peg mode cells fit the
  reduced U (100 mm on a 120 mm bed) so that a full cell plus its peg (110 mm) still fits the
  printable volume (ADR-0005).

### Pins

`tools.pin_solid` revolves a profile of radius d/2 and length L with a chamfer ch_p at both
ends, cuts the flat by difference (`geometry.split_at`), and lays the pin down with a proper
rotation: axis along X, flat on z = 0. The flat is 2·√(r² − (r − f)²) = 2.71 mm wide. With
f = 0 the pin is round and rests on one polygon edge.

The polygon is turned half a segment so an **edge** faces the bed: towards a vertex, a shallow
flat clips only a sliver (half the nominal area at 16 segments and f = 0.05). The cut then goes
where the polygon is exactly as wide as the round pin's flat, at most twice the polygon's
sagitta deeper than f (0.0033 mm with the defaults).

`tools.pin_groups` groups pins by (d, L), longest first: one file
`dowels/dowel_d{d:.1f}_l{L:.1f}.stl` per group, with its quantity. Pegs are part of their piece.
File names keep one decimal, so 15.25 and 15.15 mm would share `l15.2`. `tools.check_pin_names`
refuses that with exit 1, in a dry run too, rather than lose one of the two pins.

### Calibration

`calibrate.build_kit` builds one bar from PLAN.md §6.3 (50 × 12.4 × 13.5 mm by default):

- one hole per clearance, `h(L_max)` deep, radius d/2 + c, in a row centred across the width,
  at x = w_cal + hole_outer / 2 + i · pitch. A second bar, turned half a turn about its long
  axis and laid on the first, lines up hole for hole with the same clearances;
- each hole's **code** engraved `labels.depth` deep on the long side face y = 0, under the
  hole, read from outside with its top towards the holes' mouths.

**Codes** are the clearance in hundredths of a millimetre, without trailing zeros: `10` for
0.10, `12.3` for 0.123 (two decimals at most). Two clearances that would read the same are an
error (exit 1, naming `advanced.calibration_clearances`).

**Code height** is H_min (4 mm), reduced only when it wouldn't fit: a code is at most
pitch − `CALIBRATION_CODE_GAP` wide (1 mm between neighbours), and at most
thickness − 2 × that gap tall. At d = 2 the pitch is 6.4 mm and two digits at 4 mm are 6.75 mm
wide, so the codes shrink.

**Refused with exit 1**, before anything is built: a bar that doesn't fit the printable volume
(it may be turned a quarter turn on the plate), an engraving as deep as the wall to the widest
hole, and holes that would touch. §6.3 sizes the walls from the nominal diameter, but a polygon's
vertices reach r / cos(π / n), so these two checks measure from there.

**Tests:** `tests/integration/test_tools.py`, `tests/integration/test_calibrate.py`.

## Label layout

**Inputs:** the pieces, their cut faces and the connectors (cutting frame, mm), the
configuration and the font file. **Outputs:** each piece with its `Label` (text, face, outline in
plane-local (u, v), height), and one W003 per piece that has a cut face but no room.
`labels.layout`; `tools.apply` engraves the result.

**Text.** The grid digits and the suffix: `X1-Y0-Z2-b` reads `1-0-2b`. Glyphs come from
`TextPath` with `DejaVuSans-Bold.ttf`, loaded by file path so every machine draws the same
outline, and are filled with EvenOdd because TrueType outer contours are clockwise (ADR-0009).

**Where a label may go** (`label_region`), on each of the piece's faces:

1. the region inset by w (2 mm);
2. minus a disk of radius r_h + ch_h + w (5.1 mm) around each connector of that face;
3. minus every point closer than w to a spot that lacks t_lab + w (2.6 mm) of material behind the
   face. A probe the shape of the region goes that deep into the drilled piece; what it finds
   missing (a thin plate, a sloped surface, a void, a hole of another face) is projected on the
   face and grown by w. The round corners are compensated, so their flats are at w.

Step 3 is what keeps an engraving from going through the piece: the counters of `0`, `8` and `b`
would come off as loose shells, and the piece would fail its check (exit 4).

**Choosing the face.** Faces are tried by decreasing area of that region (ties: face ID) until
the text fits. W003 means that none has room.

**Fitting the text** (`fit_text`):

- The anchor (`label_anchor`) is the point of the region's largest part with the clearance of its
  polylabel point, within 0.01 mm, nearest the part's centroid. The polylabel point alone won't
  do: on a long face every point of the middle line ties, and the library returns one near an
  end, so a 100 × 8 face would get (4, 4) and the text would run off it.
- The height is bisected between H_min and H_max (12 steps), at 0° and at 90°. A size is accepted
  when the region contains the text. Containment isn't always monotonic in the height, so only
  sizes actually tested are kept.
- The largest height wins, 0° on a tie.
- If not even H_min fits at the anchor (at a T junction it overflows both arms), each part of the
  region, largest first, tries its anchor and then up to 256 grid points (step H_min / 2) by
  distance to it, and the first position that fits is kept. A label that fits at the anchor
  never moves.

**Viewing side.** The neg piece's face is seen from +z, so its text is drawn as is. The pos
piece's face is seen from −z, where u runs the other way, so its text is mirrored in u about the
anchor, before the containment test: the shape tested is the shape engraved.

**Engraving** (`tools.label_solid`). The outline is extruded `labels.depth` into the piece and
reaches `TOOL_OVERLAP` past the face. It joins the piece's holes in the one subtraction, and its
volume counts in `check_piece`. Labels are engraved, not embossed, since embossing would collide
with the mating piece.

**Font.** A run that draws text refuses (exit 1) a file that isn't a font, or one without its own
glyph for each digit, `-`, `.` and a to z (`io.check_label_font`).

**Edge cases.** A piece without a cut face gets no label (W008), and labels never go on exterior
surfaces. With `--no-label` nothing is laid out or reported. Both pieces of a face may label it:
their engravings don't touch, each being in its own piece.

**Tests:** `tests/unit/test_labels.py`, `tests/integration/test_labels.py`.

## Assembly order
TODO (Phase 9)
