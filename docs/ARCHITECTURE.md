# Architecture

For maintainers. How the code is organised and the rules it follows. The reasons behind the
choices are in the [ADRs](adr/README.md); the numbers are in PLAN.md §6 and `config.py`.

## Pipeline

```
input.stl → io.load_stl → repair.prepare → grid.orient → grid.even_grid → grid.nudge
  → cutting.split_cells → cutting.cut_faces → cutting.merge_small_pieces → connectors.place
  → labels.layout → tools.apply → assembly.plan_steps → assembly.build_document
  → io.encode_stl / io.encode_preview → io.prepare_output_dir → io.write_outputs
```

## Module map

`✓` = exists now. A module only imports modules listed above it (no import cycles). Only
`io` and `cli` touch the file system; everything else is pure.

| Module | Responsibility | May import | Status |
|---|---|---|---|
| `models` | Dataclasses only | — | ✓ (`Axis`, `Diagnostic`, `Orientation`, `Plane`, `Grid`, `Piece`, `CutFace`, `Connector`; the others come with their phase) |
| `errors` | Exit codes, exception types, diagnostic registry | `models` | ✓ |
| `config` | `Config` dataclasses, defaults, TOML, validation, `derived()` | `errors` | ✓ |
| `geometry` | Thin wrappers around library calls; mesh repair; frames; sections, regions, shadows, prisms, bodies; rays; cylinders and holes | `config`, `models` | ✓ |
| `repair` | Try-first repair, shell normalization | `geometry` | ✓ |
| `connectors` | Connector placement: safe regions, candidates, trial order, 3D checks | `geometry` (and `config`, `errors`, `models`) | ✓ |
| `grid` | Auto-orient, cutting frame, even grid, nudging (U itself comes from `config.derived`) | `geometry`, `connectors` (for `safe_region`) | ✓ |
| `cutting` | Splitting, piece IDs, cut faces, small-piece merge | `geometry`, `grid` | ✓ |
| `labels` | Text outlines and layout on a face | `geometry`, `connectors` (for `hole_solids`) | ✓ |
| `tools` | Hole, peg, pin and label solids; batched booleans | `geometry`, `connectors` (for `hole_solids`), `grid` (for `fits`) | ✓ |
| `calibrate` | Calibration kit | `tools`, `labels` | ✓ |
| `assembly` | Assembly order; JSON and Markdown; preview layout | `models`, `config`, `errors`, `geometry` (r12) | ✓ |
| `io` | Reading and writing files; output-directory policy | `errors`, `models`, `config` | ✓ (STL loading, output-directory policy, label-font lookup, encoding and writing every output) |
| `cli` | Argument parsing, orchestration, logging, exit codes | everything | ✓ |

`__init__` exposes `__version__` (from the package metadata) and `__main__` runs `cli.main`.

## Configuration flow

```
built-in defaults (Config())  ←  --config FILE (config.parse_toml)  ←  typed options
        │                                                    (cli: dest = "table.key", SUPPRESS)
        ▼
config.with_overrides → config.validate → io.resolve_label_font → one frozen Config
        ▼
config.derived(cfg) → Derived: U, L_min, standard lengths, h(L), r_h, r_model, inset, …
```

- `Config` has one frozen dataclass per TOML table; field names are the TOML keys. The field
  types drive TOML type checking, `config.keys()` and `config.to_toml()`.
- Every argparse option defaults to `SUPPRESS`, so an option the user didn't type is absent and
  can't override the file (ADR-0011). Configuration options store their value under the dotted
  TOML key, which is also how validation errors name them; `cli.config_flags()` maps a key back
  to its flag for the message.
- argparse's own usage errors would exit 2, which means "unrepairable" here; `cli` makes them
  raise `InputError` (exit 1).
- Stages never read argparse values: only the merged `Config` and `derived(cfg)`.

## Load and repair

```
INPUT ──io.load_stl──▶ trimesh mesh (input frame, ×scale)  + W006
          │              trimesh.load(file_type="stl", force="mesh"): vertices merged,
          │              non-finite triangles dropped; no triangle → InputError (exit 1)
          ▼
repair.prepare ──▶ Manifold (input frame) + RepairReport
   1. geometry.to_manifold(mesh): NoError? → skip repair entirely      (ADR-0007)
   2. geometry.basic_repair (trimesh)                                   → W007
   3. geometry.deep_repair (pymeshlab, only with --deep-repair)        → W007
      still invalid → RepairError (exit 2): open / non-manifold edges, bodies, hint
   4. repair.normalize_shells: roles from containment and orientation;
      union solids, keep voids at any depth, turn inside-out shells    → W010, W011
   5. empty result → RepairError (exit 2)
   6. Manifold.simplify(--simplify) when > 0; erases everything → ConfigError (exit 1)
```

- **Library boundary.** `repair` never calls trimesh or pymeshlab: every call is a wrapper in
  `geometry` (ADR-0001). pymeshlab (GPL-3.0, extra `deep-repair`) is imported only inside
  `geometry.deep_repair_problem()` and `geometry.deep_repair`, and only when deep repair is
  needed. `deep_repair_problem()` checks that pymeshlab is installed (without importing it),
  then that its filter plugins loaded; either problem is an exit 2 that says what to install.
- **`RepairReport`** (in `repair`, not `models`: only the CLI reads it) holds the repair steps,
  the counts of bodies, voids and shells turned the right way out, the diagnostics, and
  `reference_volume`: the volume of the returned body, measured after `--simplify`, the
  reference of I3.
- **Order in the CLI.** Load and repair run before `io.prepare_output_dir`, so an input that
  fails (exit 1 or 2) never creates the output directory, and `--force` never deletes the
  previous outputs for it. Each stage's diagnostics are logged as soon as it returns, so W006
  still shows when repair then fails. The summary line, at info level:
  `model: 12 triangles, 1 body, 0 voids; 10 x 10 x 10 mm from (0, 0, 0); volume 1000 mm^3;
  repair: none`.
- The algorithm and its limits: [ALGORITHMS.md](ALGORITHMS.md#repair-and-shell-normalization).

## Data model

Dataclasses of PLAN.md §5.2, added by the phase that first uses them.

| Dataclass | Module | Since | Purpose |
|---|---|---|---|
| `Diagnostic` | `models` | Phase 1 | A code from the registry, its severity, a message and the IDs it refers to |
| `Orientation` | `models` | Phase 3 | The chosen rotation's name and the 4×4 input → cutting transform (in `models`, not `grid`, because `assembly` writes it to `assembly.json` in Phase 9) |
| `Plane` | `models` | Phase 3 | A cut plane: axis, index among its axis' planes, offset (mm, cutting frame) |
| `Grid` | `models` | Phase 3 | U, cell counts and planes per axis, and the model's extent in the cutting frame |
| `Piece` | `models` | Phase 4 | ID, cell, body (cutting frame), face IDs, the IDs of the small pieces merged into it, and its `Label` (Phase 8) |
| `CutFace` | `models` | Phase 4 | ID, plane, neg and pos piece IDs, and the contact region (shapely polygon in plane-local (u, v)) |
| `Connector` | `models` | Phase 5 | ID `{face}/c{n}`, face, kind (`dowel` or `peg`), axis point (u, v), d, pin length L, hole depth on each side (0 on a peg's side) |
| `Label` | `models` | Phase 8 | Short ID, cut face, glyph outline in plane-local (u, v), already mirrored for its viewing side, and text height |
| `AssemblyStep` | `models` | Phase 9 | Number `stage.join`, axis, moving and static piece IDs, direction, face IDs, connector count, and whether the path was shown clear (r12) |

`grid.Rotation` (a candidate of auto-orient: name and 3×3 integer matrix) stays in `grid`:
only `grid` uses it.

`cutting.Cut` (pieces, faces, diagnostics: what the cutting stage returns) stays in `cutting`:
only the CLI reads it. `connectors.Placement` (connectors, diagnostics) likewise stays in
`connectors`, with `Selection`, `Hole` and `Fit`, which only the placement uses.
`tools.Applied` (pieces, pins), `tools.PinGroup` and `calibrate.Kit` likewise stay in their
modules, as do `labels.Labelled` and `labels.Fitted`. `assembly.AssemblyPlan`, `assembly.PinCount`, `assembly.PreviewItem` and `io.PreviewMesh` likewise
stay in their modules.

## Cutting

```
body (cutting frame) + Grid
  │  cutting.split_cells     geometry.split_at (by difference): X planes, then Y, then Z
  │                          geometry.bodies per cell (outer shell − its voids), drop < 1e-6 mm³
  │                          order (min z, min y, min x, −volume) → IDs X1-Y0-Z2, X1-Y0-Z2-a, …
  ▼
cutting.cut_faces            per plane: geometry.cut_region(body) = slice(o−ε) ∩ slice(o+ε)
  │                          per cell pair: geometry.clip_to_cells → polygons
  │                          polylabel point in the sections at o ∓ 0.05 → neg / pos piece
  ▼
cutting.merge_small_pieces   W004 / W005; a merged piece is cut again from the body
  ▼
cutting.check_pieces         I1, I3 (AssertionError = exit 4); W008 for faceless pieces
```

- Regions always come from the normalized body, never from the pieces (ADR-0002), so both
  pieces of a face see the same region.
- Solids are only ever cut by difference (`geometry.split_at`, `geometry.clip`): an
  intersection leaves a zero-thickness flap where a model face lies on the cut
  (docs/LIBRARY_NOTES.md). A merged piece is cut from the body, never glued (ADR-0012).
- Every collection comes out in a documented order: pieces in cell order then suffix, faces
  by plane, neg cell, then polylabel point (docs/ALGORITHMS.md, "Sections and cut faces").
- `cutting` imports `grid` for `cell_indices`, `cell_bounds` and `fits` (PLAN.md Appendix E,
  r7). The CLI logs `cutting: 8 pieces, 12 cut faces` and the dry run lists every piece
  (volume, `merged_from`) and face (plane, area).

## Connector placement

```
pieces + faces (face order)
  │  per face:
  │  connectors.safe_region     region.buffer(−(w + r_h + ch_h))          → MultiPolygon
  │  connectors.candidates      g grid inside + polylabel per part, (u, v) order
  │  connectors.connector_count 0 / 1 (hull diameter < s_min) / clamp(area / A, 2, k_max)
  │  connectors.select          hull-diameter pair, then farthest from the accepted ones
  │    └─ check_candidate       rays → standard length → containment → min_gap vs the piece's holes
  ▼
Placement: connectors (face order, then acceptance) + W002 / W009 or W001
```

- Every number comes from `config.derived(cfg)` (cached in `connectors`, a `Config` is
  hashable) and the constants `RAY_START_OFFSET`, `RAY_CIRCLE_COUNT`, `RAY_LENGTH_MARGIN`,
  `GAP_SEARCH_MARGIN`, `MAX_CANDIDATE_TRIALS`, `LENGTH_TOLERANCE`.
- `select` takes the 3D checks as a callback, so the trial order is unit-tested in 2D
  (`tests/unit/test_placement.py`).
- The holes accepted so far, per piece, are the only state carried from face to face: a hole
  accepted on one face rejects colliding candidates on the faces after it.
- Holes are `geometry.hole_solid` (a revolved profile: bore r_h plus the mouth chamfer, radii
  compensated), the solids Phase 7's tools will cut, so the collision check and the output
  agree.
- The CLI logs `connectors: 8 on 2 of 2 cut faces`; the dry run lists every connector and the
  loose pins by diameter and length.

## Tools and calibration

```
pieces + faces + connectors
  │  tools.apply, per piece:
  │    union of its hole cutters (connectors.hole_solids, overlap = TOOL_OVERLAP) → subtract
  │    union of its pegs (tools.peg_solid, overlap = TOOL_OVERLAP)                → add
  │    tools.check_piece    valid, same outer shell count, volumes within 5 %, fits printable
  ▼
Applied: new pieces (same order) + pin groups (tools.pin_groups, longest first)
  ▼
cli: assembly order, then the outputs (see Outputs)

--calibrate:  calibrate.build_kit(cfg, font) → io.prepare_output_dir
              → io.write_stl_files + io.write_text_file (calibration/)
```

- The tools run before the output directory is prepared, so a failure keeps the previous outputs.
  A dry run skips them.
- Tools reach `TOOL_OVERLAP` past a cut face, because a face's vertices can be off its plane by
  float noise (docs/LIBRARY_NOTES.md, `manifold.face_float_noise`).
- `calibrate` can't import `io`, so the CLI resolves the font and passes its path.
- The writers refuse any path outside `io.OWNED_OUTPUTS`, the names `--force` may delete.
  With `--force`, `io.check_force_keeps` first refuses a run whose input, `--config` file or
  label font lies inside one of those names.
- The algorithms: [ALGORITHMS.md](ALGORITHMS.md#tool-solids-pins-and-the-calibration-kit).

## Outputs

```
Applied pieces + faces + connectors
  │  assembly.plan_steps       the order (ALGORITHMS.md, "Assembly order"), on tools.with_pegs
  │  assembly.build_document   one dict: everything assembly.json holds, floats rounded
  │  assembly.to_json, to_markdown      both rendered from that dict
  │  assembly.preview_items    offsets and colours (pure)
  │  io.encode_stl, encode_preview      bytes of every file
  ▼
io.prepare_output_dir → io.write_outputs
```

- Everything is encoded **before** the output directory is prepared, so a failure up to that
  point keeps the previous outputs. A failure during the write itself (a full disk) can leave a
  partial folder, and with `--force` the old outputs are already gone by then.
- A dry run also plans the order, on the same solids (`tools.with_pegs`), so it reports W013 and
  exits as a split would (PLAN.md §7.1).
- `assembly` stays pure: the CLI converts solids with `geometry.to_trimesh`, and only `io` builds
  the glTF scene.
- `jsonschema` is a development dependency: the tests validate `assembly.json`, a normal run
  doesn't load the schema.
- `assembly.json` keeps only the file names of the input and of `label_font`, since either could
  reveal an absolute path (ADR-0010).
- Layout and fields: [OUTPUT_FORMAT.md](OUTPUT_FORMAT.md).

## Frames

| Frame | Definition | Used for |
|---|---|---|
| Input | STL coordinates × `--scale` | Loading, repair, original bounding box |
| Cutting | `x_cut = R · x_in + t`; R a proper rotation (ADR-0008), t moves the bbox minimum to the origin | Everything after orientation, every output file |
| Plane-local | For a plane of axis a: the axes below; 2D (u, v) = local (x, y) | Cut regions, connectors, labels |

**Input → cutting.** `grid.orient` builds the cutting frame right after repair:

```
repaired body (input frame)
  │  grid.choose_rotation   fewest cells over the 6 proper rotations of grid.ROTATIONS
  │                         (ties: table order; --no-auto-orient: identity)
  ▼
grid.to_cutting_frame       transform(R), then translate(−bbox min): bbox min exactly (0, 0, 0)
  ▼
body (cutting frame) + Orientation(name, input_to_cutting = [[R, t], [0, 0, 0, 1]])
  │  grid.even_grid(grid.extent(body), config.derived(cfg).usable)
  ▼
Grid (counts, planes, U, extent) + W012 when it already fits
```

- R is always a signed permutation with det = +1, never a mirror (ADR-0008); the six
  matrices and their order are in [ALGORITHMS.md](ALGORITHMS.md#auto-orientation).
- Every stage after `grid.orient`, and every output file, works in the cutting frame. Only the
  model summary line (bounding box and volume after repair) is in the input frame.
- The CLI logs `grid: 1 x 1 x 2 = 2 cells; rotation 90 deg about Y`, and the dry run prints the
  rotation, the matrix, the extent, U, the counts and the plane offsets on **stdout** (logs are
  on stderr), so `-q` doesn't hide the plan.

Plane-local axes:

| Plane axis | local x (u) | local y (v) | local z (normal) |
|---|---|---|---|
| X | world Y | world Z | world X |
| Y | world Z | world X | world Y |
| Z | world X | world Y | world Z |

- `geometry.world_to_local(axis)` (3×4, rotation only): after it, the plane at offset o is local
  z = o and `slice(o)` gives the section in (u, v).
- `geometry.local_to_world(axis)` (3×4, rotation only): the exact inverse, the transpose. The
  plane stays at local z = o in both directions, so tool solids for a plane are built around
  z = o (a hole from o − h to o + h), then mapped back with this matrix. One rule everywhere:
  there is no plane-relative frame with the plane at z = 0 (PLAN.md Appendix E, r3).
- The neg piece of a cut face is on the local z < o side, the pos piece on z > o. A face is viewed
  from outside its piece, so text on the pos piece's face is mirrored in u.

## Invariants

PLAN.md §5.3. "Asserted" means checked at run time (a failure is a bug: exit 4).

| ID | Invariant | Asserted | Tested |
|---|---|---|---|
| I1 | Every piece body is `NoError` with a positive volume | `repair.prepare` (the body), `cutting.check_pieces` (the pieces), `tools.check_piece` (after the tools, with the same number of outer shells) | `tests/integration/test_repair.py`, `tests/integration/test_cutting.py` (hypothesis property), `tests/integration/test_tools.py` |
| I2 | Cells fit U, and every final piece, pegs included, fits bed − 2·margin (`derived(cfg).printable`) | `grid.even_grid` (cells, via `grid.fits`); `cutting.merge_small_pieces` refuses a merge that wouldn't fit; `tools.check_piece` (final pieces) | `tests/unit/test_grid.py`, `test_cutting.py`, `tests/integration/test_tools.py` |
| I3 | Before tools, the piece volumes add up to the reference volume within 0.1 % | `cutting.check_pieces` | `test_cutting.py` (hypothesis property, voids, merges) |
| I4 | Every cut face has one piece on each side, and its region lies inside both sections | by construction (`cutting.cut_faces`) | `test_cutting.py` (`assert_regions_lie_in_both_pieces`) |
| I5 | No two holes of a piece are closer than `min_wall` | by construction (`connectors.check_candidate` rejects a closer hole, `min_gap`) | `tests/integration/test_connectors.py` (2 × 2 × 2 cube, 15 mm pieces) |
| I6 | Every connector's axis point lies in its face's safe region | `connectors.place` (`AssertionError`) | `tests/integration/test_connectors.py` (`assert_inside_safe_regions`) |
| I7 | Every assembly step joins two different sub-assemblies with one straight move, along faces perpendicular to its axis | `assembly.plan_steps` (`AssertionError`); the merge's footprint guard keeps it possible (docs/ALGORITHMS.md) | `tests/unit/test_assembly_order.py` (hypothesis property), `tests/integration/test_export.py` |

## Diagnostics flow

Exit codes and the diagnostic registry live in `errors.py` (`ExitCode`, `DIAGNOSTIC_CODES`) and
are documented in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

- **Failures** are exceptions: `InputError` (exit 1, `ConfigError` for a bad key or value),
  `RepairError` (exit 2, raised by `repair.prepare`). `cli.main` prints each as one line, `stlsplit: error: …`, plus the
  traceback with `-v`. Any other exception is a bug: exit 4 and a request for a report.
- **Diagnostics** don't stop the run. A stage builds them with `errors.diagnostic(code,
  message, refs)`, which takes the severity from the registry, and returns them with its
  result (stages stay pure). `cli.report_diagnostics` logs them in order and returns
  `errors.exit_code_for(...)`: 3 if any is `partial`, else 0. The CLI calls it after each
  stage and keeps the highest code.
- **Logging:** the `stlsplit` logger writes to stderr; `-q` shows warnings and errors, the
  default adds info, `-v` adds debug messages and the stage timings from `cli.stage(name)`.
