# PLAN.md — `stlsplit`: split oversized STL models into printable, connectable parts

> Implementation plan and living specification, written for Claude Code and for the people who will
> maintain the project afterwards. Revision **r12** (2026-11-21); r2 (2026-11-17) was rewritten
> after a technical review. See Appendix E for what changed and why.
>
> **Claude Code:** at the start of each phase, read §0–§9 and that phase's section in §10. Don't read
> the other phases. Follow the phase protocol in §9.1.

## Contents

0. How to use this plan (and progress)
1. Goal, scope and requirements
2. Tech stack
3. Repository layout
4. Conventions: units, frames, identifiers, determinism, diagnostics
5. Pipeline and data model
6. Parameters and formulas (single source of truth)
7. CLI and configuration
8. Documentation system
9. Engineering workflow (Claude Code protocol, commits, tests, CI)
10. Implementation phases (Phase 0 to Phase 11)
11. v2 ideas (out of scope)
12. Key decisions (ADR index)
13. Pitfalls
14. Definition of done (v1)
- Appendix A: ADR template
- Appendix B: CLAUDE.md template
- Appendix C: Phase completion checklist
- Appendix D: Test fixture catalogue
- Appendix E: Plan revisions

---

## 0. How to use this plan

**Who reads what**

| Reader | Reads | Purpose |
|---|---|---|
| Claude Code (implementer) | §0–§9, then one phase of §10 at a time | Build the tool phase by phase |
| Maintainer taking over the project | `docs/ONBOARDING.md` first, then `docs/ARCHITECTURE.md`, the ADR index and this plan | Understand, run and change the tool |
| Users | `README.md` | Install and use the tool |

**Source of truth.** Until v1.0, this plan is the source of truth for *what to build*. As phases land,
`docs/` and the ADRs become the source of truth for *how it works and why*. After v1.0, PLAN.md stays
as the roadmap and history: the progress table, §11 and Appendix E.

**One phase per Claude Code session.** Each phase is meant to fit in one session. If one doesn't,
split it (for example 5a and 5b) and note the split in the progress table. A phase lists the files
to touch, the tasks, the tests to write first, the docs to update and the "done when" criteria. When
a phase is finished, Claude Code updates the progress table below and commits.

**When reality differs from the plan** (a library behaves differently, a formula is wrong, a test is
impossible), don't work around it silently. Stop, explain, and propose a fix. Agreed changes go into
this file (the affected section plus Appendix E) in the same commit as the code.

### Progress

Claude Code updates this table at the end of every phase. Status values: `todo`, `in progress`,
`done`, `blocked: <reason>`. The Notes column is for whoever opens the next session: what's left,
what surprised you, what to watch.

| Phase | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 0 | Scaffolding, documentation skeleton, API spike | done | `2060291`, `44c2cdb` (tag `v0.0.0`) | CI green on Linux 3.12/3.13/3.14, Windows 3.13 and macOS 3.13 (macOS runners can queue for a long time; a job that is never acquired is a capacity problem, re-run it). CI actions are on v7 (Node 24). Dev machine has no system Python ≥ 3.12: use uv (CONTRIBUTING.md). For Phase 1: move `geometry.POLYLABEL_TOLERANCE` to `config.py`; `models.py` holds only `Axis` so far; `errors.py` already has `ExitCode` and the W001–W012 registry. Frames: plane at local z = o both ways (Appendix E, r3). `ruff format` excludes `*.md` (it was rewriting PLAN.md code blocks); manifold3d is in mypy's `ignore_missing_imports` (its `.pyi` has no `py.typed`). Python 3.14 is added to Linux CI. |
| 1 | Configuration and CLI shell | done | `e869e3b` | For Phase 2: `io.py` exists (output-directory policy, `OWNED_OUTPUTS`, label-font lookup); `io.load_stl` goes there. `cli._run` stops every mode with a "not implemented yet" warning after the checks: replace that stub as stages land; `cli._require_input_file` can move into `io.load_stl`. Stages build diagnostics with `errors.diagnostic()` and return them; `cli.report_diagnostics()` turns them into the exit code. Numbers come from `config.derived(cfg)` only. `pin_length_step` ≥ 0.1 and `circular_segments` ≤ 256 were added after the review (r4). Still open: in dowel mode `connectors.length` has no upper bound, so a huge `--dowel-length` would make `derived()` build (L_max − L_min) / 0.1 standard lengths; bound it (e.g. by the usable volume) when Phase 5 starts using the lengths. `--print-config` writes ASCII; `--config` reads UTF-8 (BOM or not) and UTF-16 with a BOM, for Windows. Symlink tests skip only if the OS refuses to create a symlink. The review found two bugs (huge TOML integers exited 4; the Windows `--print-config > file` round trip), both fixed and tested (PLAN r4). |
| 2 | Load, repair, shell normalization | done | `f7e568d`, `8d8e6d2` (tag `v0.2.0`) | For Phase 3: `cli._run` loads and repairs (`io.load_stl` → `repair.prepare` → body in the **input frame** plus `RepairReport.reference_volume`, measured after `--simplify`), then stops with a "not implemented yet (Phase 3 onwards)" warning: replace that stub with `grid.orient`. Load and repair run before `io.prepare_output_dir` on purpose (a broken input never touches `-o`). The CLI logs each stage's diagnostics as soon as it returns and keeps the highest exit code. Plan changes in Appendix E r5: the review found that the sign-only shell normalization filled voids (whole model inside out; overlapping hollow parts), so roles now come from containment plus relative orientation, any nesting depth; basic repair keeps each shell's majority orientation (trimesh's `fix_winding` follows one reference face). Edge-touching cubes are valid as is; `finned_cube` is the `--deep-repair` fixture. Fixture gotcha: `Manifold.compose` collapses inside-out shells, so build reversed shells with trimesh concatenation (`tests/conftest.py`). pymeshlab is installed only in the Linux 3.13 and weekly CI jobs; locally `pip install -e ".[dev,deep-repair]"`. Its filter plugins need the system's `libOpenGL.so.0` (Ubuntu: `libopengl0`, installed in CI); without it `geometry.deep_repair_problem()` makes `--deep-repair` exit 2 with that cause instead of crashing (`8d8e6d2`). |
| 3 | Orientation and even grid | done | `b354c40`, `f63cee3` (tag `v0.3.0`) | For Phase 4: `cli._run` now runs `grid.orient` → `grid.even_grid` after repair, then stops with a "not implemented yet (Phase 4 onwards)" warning: replace that stub with `cutting.split_cells`. From there `body` is in the **cutting frame** (bounding-box minimum exactly at the origin, LIBRARY_NOTES `manifold.signed_permutation_exact`) and `layout` is the `Grid`; `grid.axis_bounds`, `grid.cell_indices` (sorted (i, j, k)) and `grid.cell_bounds` give the cells. `Orientation.input_to_cutting` (4×4, tuples) is for `assembly.json` in Phase 9. Plan changes in Appendix E r6: the cell-fit check is relative (`≤ U · (1 + GRID_TOLERANCE)`; the absolute `U + 1e-9` contradicted the count's relative slack) and, after the review, evaluated in the count's own arithmetic (`grid.fits`: `size / U − tol ≤ 1`), since `size <= U * (1 + tol)` rounded the other way for one float and a valid box exited 4 (`f63cee3`); use `grid.fits` whenever nudging (Phase 6) checks a cell; the six rotations and their tie order are in `grid.ROTATIONS`; `Orientation` lives in `models`; the dry-run plan goes to stdout (`cli.dry_run_report`, extend it as stages land), logs to stderr. First hypothesis tests: `tests/conftest.py` loads a derandomized `ci` profile when `CI` is set. `chiral_l` is a three-armed corner, not a flat L (a flat L is its own mirror image). The grid has no upper bound on the cell count (a 5 m model on a tiny bed): Phase 10 territory. |
| 4 | Sections, cutting, cut faces, small-piece merge | done | `2180729` | For Phase 5: `cli._run` now runs `cutting.cut` after the grid (pieces, faces, W004/W005/W008; I1 and I3 checked, `AssertionError` = exit 4), then stops with a "not implemented yet (Phase 5 onwards)" warning: replace that stub with `connectors.place`. Faces are `models.CutFace` with the region in plane-local (u, v), from the normalized body (ADR-0002); `geometry.section`, `polylabel_point`, `shadow`, `grow`, `prism`, `rectangle`, `bodies`, `split_at` and `clip` are there to reuse. Pieces without faces (W008) get no connectors. **Cut solids only by difference** (`geometry.split_at`, `geometry.clip`): `split_by_plane`, `trim_by_plane` and `^` leave a zero-thickness flap where a model face lies on the cut (spike `manifold.coplanar_cuts`); this matters for Phase 7's booleans too. Plan changes in Appendix E r7: a merged piece is cut again from the body, never glued (a union of split halves keeps an internal face when the plane passes through mesh vertices; spike `manifold.union_of_split_halves`); bodies keep their voids (`decompose()` returns voids as separate inside-out shells); `geometry.reverse_winding` now goes through `Mesh64` (float64); `cutting` imports `grid`; three bugs found by the review (flaps, merged body picked by volume, prisms reaching other cells), fixed and tested. Performance: `polylabel` at 1e-3 mm is slow on thin regions (about 30 ms for a 2 mm ring); `geometry.polylabel_point` caches it, which took the hollow sphere on 27 cells from 3.4 s to 0.4 s. The merge (booleans on two cells) and polylabel are the hot spots to watch in Phase 10. |
| 5 | Connector placement | done | `f935d6f` | For Phase 6: `cli._run` now runs `connectors.place` after the cutting, then stops with a "not implemented yet (Phase 6 onwards)" warning. Nudging goes between `grid.even_grid` and `cutting.cut`; its scores can use `geometry.cut_region` and `connectors.safe_region(region, cfg)` (a `MultiPolygon`, possibly empty). `grid` may import `connectors`: it imports only `geometry`, `config`, `errors` and `models`. For Phase 7: cut the holes with `geometry.hole_solid` (bore r_h plus mouth chamfer, radii compensated), the shape the collision check used; `connectors.hole_solids(connector, face, cfg)` gives them per piece; a peg stands on the neg piece (`hole_depth_neg = 0`). Plan changes in Appendix E r8: face order, not ID string order; farthest-point sampling from the accepted connectors; at most 256 trials per face (`MAX_CANDIDATE_TRIALS`); `connectors.length` ≤ max(bed X, bed Y) (a bound by U would have broken the margin boundary test); depths measured from the face; `min_gap` compared with `LENGTH_TOLERANCE` (it gives 1.999999999999993 for 2 mm); W002 once per face; `wide_u_shape` fixture. **manifold3d booleans are lazy**: the cost shows at the first query (a cylinder-plus-cone union cost 3 ms there), so holes are revolved (0.14 ms), and `_too_close` checks bounding boxes and a ray cast along the axis before `min_gap` (2 ms on crossing solids). Performance: placement takes 1.5 s on the 2×2×2 cube (541 trials for 48 connectors). The review found no correctness bug, and one item for Phase 10: the containment fallback tries every standard length, so with `pin_length_step = 0.1` and a 60 mm pin (451 lengths) a rejected candidate costs about 330 ms and a face where all 256 trials fail about 84 s. A binary search over the lengths would fix it, but take care at the 1e-6 tolerance edge, where containment isn't monotonic in L. |
| 6 | Plane nudging | done | `e6bdb67` | For Phase 7: `cli._run` now runs `grid.nudge` between `grid.even_grid` and `cutting.cut`, then stops with a "not implemented yet (Phase 7 onwards)" warning: replace that stub with `tools.apply`. Cells are no longer all equal once a plane moves; everything downstream must take bounds from `grid.axis_bounds` / `grid.cell_bounds`, never `extent / n`. Plan changes in Appendix E r9: a plane stays strictly between its neighbours (`grid.check_fits` also asserts increasing bounds); `grid.cell_pairs` is shared by nudging and `cutting.cut_faces`; scoring calls `geometry.cut_region` and `clip_to_cells` with `ordered=False` (the polylabel sort was 97 % of the time: hollow sphere 4.9 s, now 0.11 s); scoring stops at the first (0, 0) score; `nudge_window / nudge_step` ≤ 100 (`MAX_NUDGE_STEPS`), with the window counted in steps (`derived(cfg).nudge_steps`); the example test command is now `tests/unit/test_nudge.py -k slack`. **The score is 2D**: moved just off a neck, a plane leaves a thin slab on the neck side, so `tall_figure` still gets W001 from the 3D checks (0.5 mm of box under the neck); a depth-aware score is a Phase 10 or v2 question (ADR-0003, "Consequences"). Performance: a 1M-triangle hollow sphere, where every position is scored (63), takes 2.1 s; at the 100-step limit one plane costs up to 201 scores, about 7 s at 1M triangles. The review found one bug (a tiny `nudge_step` overflowed, exit 4, or ran out of memory), fixed by the step limit and tested. |
| 7 | Tool solids, booleans, dowels, calibration kit | done | `b760e4d` | For Phase 8: `cli._run` now runs `tools.apply` after `connectors.place`, writes `dowels/`, then stops with a "not implemented yet (Phase 8 onwards)" warning; the labels go between the placement and `tools.apply`, and their solids join the piece's one subtraction (`tools._apply_to_piece`, with their volume in `check_piece`). `labels.text_outline(text, height, font)` exists (centred, EvenOdd); `labels` can't import `io`, so the CLI passes the font path. **Any tool must reach `TOOL_OVERLAP` past a cut face**: its vertices can be a few ulps off the plane, and a peg based exactly on it stayed a separate shell (`manifold.face_float_noise`). For Phase 9: write `Applied.pieces` with `io.write_stl_files`, which refuses names outside `OWNED_OUTPUTS`. Final pieces fit `derived(cfg).printable` (bed − 2·margin), cells fit U (r10). The review added exit 1 refusals, agreed with the maintainer (Appendix E, r10): pin lengths sharing a file name, a kit that doesn't fit or whose walls fail, `diameter` ≥ 0.1. The review also found an older bug, fixed here: `--force` deleted an input inside an owned folder; `io.check_force_keeps` now refuses it (§7.6). |
| 8 | Labels | done | `53624bc` | For Phase 9: `cli._run` now runs `labels.layout` after the placement and `tools.apply` engraves the labels, then stops with a "not implemented yet (Phase 9 onwards)" warning. `Applied.pieces` carry `Piece.label` (`text`, `face_id`, `outline`, `height`) for `assembly.json`; a piece can have none (W003, W008 or `--no-label`). Plan changes in Appendix E r11, all agreed with the maintainer: a label needs `labels.depth + min_wall` of material behind it (the literal spec made `tall_figure` exit 4); faces, then up to 256 positions per region part, are tried before W003; the anchor is centred on long faces (`u_shape` and a T-beam got false W003s); the guard's round corners are compensated; a run that draws text refuses a font that can't draw the labels (exit 1), while `--print-config` and `--no-label` don't read its content. `labels` imports `connectors`. Thin shells get W003 by design: a 2 mm hollow sphere has no label, since its wall is under the 2.6 mm backing. Checked after the review: 276 runs on 69 models (dowel, peg, none, depth 1.9) with no label-related exit 4. |
| 9 | Assembly order, export, assembly map, preview | todo | | |
| 10 | Robustness and performance | todo | | |
| 11 | End-to-end suite, docs completion, v1.0 and handover | todo | | |

---

## 1. Goal, scope and requirements

### 1.1 Goal

A command-line Python tool that takes one STL file that is too big for the user's printer and outputs:

- one closed, watertight STL **per piece**, each fitting the printer's build volume;
- **connector features** on every cut face that has room for them (dowel holes, or pegs and holes), so
  the pieces align when assembled;
- the **loose dowel pins** as STL files (one file per pin length, with the quantity to print);
- an **ID label** engraved on a hidden face of each piece;
- an **assembly map** (JSON and Markdown) saying which piece goes where, what connects to what, and
  an assembly order that can actually be followed by hand.

Target usage:

```bash
stlsplit model.stl -o ./out --bed 220 220 250
stlsplit model.stl -o ./out --config my_printer.toml --connector peg --clearance 0.25
stlsplit model.stl --dry-run                       # print the plan, write nothing
stlsplit --calibrate -o ./calibration              # print once, then pick your clearance
stlsplit --print-config --config my_printer.toml   # show the effective settings
```

### 1.2 Functional requirements

| ID | Requirement |
|---|---|
| F1 | Split one STL into pieces that each fit the usable build volume U (§6). |
| F2 | Every piece is a closed, valid (manifold) solid. |
| F3 | Put connectors on every cut face that has room for one; report every face that doesn't. |
| F4 | Export dowel pins as separate STLs grouped by length, with counts. Pegs are an option. |
| F5 | Engrave each piece's ID on one of its cut faces (hidden once assembled). |
| F6 | Write `assembly.json` and `assembly.md`, including an assembly order that is physically possible. |
| F7 | Generate a calibration kit to choose the hole clearance for the user's printer. |
| F8 | Offer a dry run that prints the plan without writing files. |
| F9 | Export an exploded preview (`.glb`) for a visual check in any glTF viewer. |

### 1.3 Non-functional requirements

| ID | Requirement |
|---|---|
| N1 | **Deterministic:** same input, settings and dependency versions give byte-identical output. |
| N2 | **Performance:** a 1M-triangle model split into about 8 pieces in under 2 minutes on a laptop. |
| N3 | **Robustness:** never crash on a readable STL; every failure has an exit code and a one-line message. |
| N4 | **Maintainability:** every module, option and decision documented; docs checked against code by tests; ≥ 85 % line coverage; typed public functions. |
| N5 | **Portability:** Linux, macOS and Windows; Python ≥ 3.12. |
| N6 | **Licensing:** core dependencies permissive; GPL code only as an optional extra. |

### 1.4 Constraints

- Python only, installable with `pip install -e .`, exposing the `stlsplit` console script.
- Cuts are axis-aligned planes on a grid (ADR-0013).
- STL has no units: everything is in **millimetres**. `--scale` handles models exported in other units.

### 1.5 Non-goals (v1)

- No GUI and no 3D viewer: the optional `preview_exploded.glb` opens in any glTF viewer.
- No G-code or slicing: the output STLs go into PrusaSlicer, OrcaSlicer or Cura as usual.
- No hollowing, no curved or organic cut surfaces, no dovetails or snap-fits, no non-axis-aligned
  cuts. These are v2 ideas (§11).

---

## 2. Tech stack

Versions marked "plan time" were installed and exercised on 2026-11-17 (Python 3.13). Phase 0
re-verifies everything on the development machine and pins `>=` minimums to what it verified.

| Purpose | Package | Plan time | Notes |
|---|---|---|---|
| All solid geometry: booleans, plane splits, sections, ray casts, gaps, simplification, extrusion | `manifold3d` | 3.5.5 | Apache-2.0. The core of the tool's reliability (ADR-0001). |
| Mesh file I/O, basic repair, GLB preview | `trimesh` | 5.2.1 | MIT. Use only for I/O, repair and the preview scene. |
| Graph engines that trimesh needs | `scipy`, `networkx` | 1.18.1, 3.7 | Verified: `fill_holes` needs networkx, graph operations need scipy or networkx. Don't use `trimesh[easy]`: it pulls in about 20 packages we don't use. |
| 2D polygons on cut faces | `shapely` | 2.2.0 | BSD. Negative `buffer`, `polylabel`, `contains`, `intersection`. |
| Glyph outlines for labels | `matplotlib` | 3.11.2 | Core dependency, since labels are on by default. Only `TextPath` and the bundled fonts are used. |
| Numerics | `numpy` | 2.5.3 | |
| CLI | `argparse` (stdlib) | — | ADR-0011. |
| Config | `tomllib` (stdlib) | — | |
| Optional repair fallback | `pymeshlab` | — | GPL-3.0. Optional extra `deep-repair`, imported lazily only with `--deep-repair`. |
| Tests | `pytest`, `pytest-cov`, `hypothesis`, `jsonschema` | — | Dev extra. |
| Quality | `ruff` (lint and format), `mypy` | — | Dev extra. |

**Python ≥ 3.12.** numpy 2.5, scipy 1.18 and networkx 3.7 all declare `Requires-Python >= 3.12`
(checked at plan time). CI runs 3.12 and 3.13. Add 3.14 once Phase 0 confirms wheels exist for every
dependency (networkx 3.7 excludes 3.14.1 specifically).

---

## 3. Repository layout

```
stlsplit/
├── pyproject.toml
├── README.md                    # users: install, quick start, examples, calibration, output, limits
├── CHANGELOG.md                 # Keep a Changelog + SemVer
├── CONTRIBUTING.md              # maintainers: setup, commands, conventions, definition of done, recipes
├── CLAUDE.md                    # Claude Code: short pointers and rules (Appendix B)
├── PLAN.md                      # this file: roadmap, progress, plan revisions
├── LICENSE
├── .gitignore
├── .github/workflows/ci.yml
├── scripts/
│   ├── check.py                 # lint + format check + type check + tests, one command
│   └── api_spike.py             # executable record of library behaviours; rerun after upgrades
├── docs/
│   ├── ONBOARDING.md            # start here if you are taking over the project
│   ├── ARCHITECTURE.md
│   ├── ALGORITHMS.md
│   ├── CONFIGURATION.md
│   ├── OUTPUT_FORMAT.md
│   ├── TROUBLESHOOTING.md
│   ├── LIBRARY_NOTES.md
│   ├── GLOSSARY.md
│   └── adr/
│       ├── README.md            # ADR index
│       ├── 0000-template.md
│       └── 0001-...md … 0014-...md
├── src/stlsplit/
│   ├── __init__.py              # __version__ (read from package metadata)
│   ├── __main__.py              # python -m stlsplit
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── models.py
│   ├── geometry.py
│   ├── io.py
│   ├── repair.py
│   ├── grid.py
│   ├── cutting.py
│   ├── connectors.py
│   ├── tools.py
│   ├── labels.py
│   ├── assembly.py
│   ├── calibrate.py
│   └── schemas/assembly.schema.json
└── tests/
    ├── conftest.py              # fixture generators (Appendix D)
    ├── fixtures/
    │   ├── README.md            # credits and licences for the real models
    │   └── real/                # 2–3 small CC0 / CC-BY STL files (committed)
    ├── unit/
    ├── integration/
    └── e2e/
```

### 3.1 Module responsibilities

| Module | Responsibility | May import (inside the package) |
|---|---|---|
| `models` | Dataclasses only (§5.2) | — |
| `errors` | Exception types mapped to exit codes; registry of diagnostic codes | `models` |
| `config` | `Config` dataclasses, defaults, TOML loading, validation, `derived()` values | `errors` |
| `geometry` | Thin wrappers around library calls; frames; sections; rays; cylinders; CrossSection ↔ shapely | `config`, `models` |
| `repair` | Try-first repair, shell normalization | `geometry` |
| `connectors` | Connector placement (2D candidates + 3D checks) | `geometry` |
| `grid` | Usable volume, auto-orient, even grid, plane nudging | `geometry`, `connectors` (for `safe_region`) |
| `cutting` | Splitting, piece IDs, cut faces, small-piece merge | `geometry`, `grid` (r7) |
| `labels` | Text outlines and layout on a face | `geometry`, `connectors` (`hole_solids`; r11) |
| `tools` | Hole, peg, pin and label solids; batched booleans | `geometry`, `connectors` (`hole_solids`), `grid` (`fits`) (r10) |
| `calibrate` | Calibration kit | `tools`, `labels` |
| `assembly` | Assembly order; JSON and Markdown content; preview layout | `models`, `config`, `errors`, `geometry` (r12) |
| `io` | Reading and writing files; output-directory policy | `errors`, `models`, `config` |
| `cli` | Argument parsing, orchestration, logging, exit codes | everything |

**Rules.** Only `io.py` and `cli.py` touch the file system (matplotlib reading its own font file is the
one accepted exception). Everything else is pure: geometry in, geometry out. A module only imports
modules listed above it in this table, so there are no import cycles.

---

## 4. Conventions

### 4.1 Units and numbers

- Lengths in mm, areas in mm², volumes in mm³, angles in degrees (in config and docs).
- Floats written to JSON or Markdown are rounded to 6 decimals.
- Tolerances are named constants in `config.py`; no bare `1e-9` scattered through the code.

### 4.2 Coordinate frames

| Frame | Definition | Used for |
|---|---|---|
| Input | STL coordinates × `--scale` | Loading, repair, reporting the original bounding box |
| Cutting | `x_cut = R · x_in + t`. R is the auto-orient rotation (proper rotation, det = +1), t moves the bounding-box minimum to the origin | Everything after orientation, and every output file |
| Plane-local | For a plane of axis a at offset o: the axes in the table below. The plane is local z = o; 2D coordinates (u, v) are local (x, y) | Cut regions, connector positions, labels |

Plane-local axes (verified at plan time with `Manifold.transform` followed by `slice`):

| Plane axis | local x (u) | local y (v) | local z (normal) |
|---|---|---|---|
| X | world Y | world Z | world X |
| Y | world Z | world X | world Y |
| Z | world X | world Y | world Z |

- World → local is a cyclic permutation of the axes (det = +1); local → world is its transpose.
- The **neg piece** of a cut face is on the local z < o side, the **pos piece** on the z > o side.
- A face is viewed from outside its piece: the neg piece's face from +z (u to the right, v up), the
  pos piece's face from −z, so text engraved there must be mirrored in u.
- The 4×4 input → cutting transform is stored in `assembly.json` (`frame.input_to_cutting`).

### 4.3 Identifiers

| Thing | Format | Example | Ordering rule |
|---|---|---|---|
| Cell | (i, j, k), 0-based along X, Y, Z | (1, 0, 2) | |
| Piece | `X{i}-Y{j}-Z{k}`, plus `-a`, `-b`, … (after `-z`: `-aa`, `-ab`, …; r7) when the cell holds several bodies | `X1-Y0-Z2-b` | Suffixes by (bbox min z, min y, min x, then larger volume first); piece order is cell, then suffix |
| Cut face | `{neg piece}~{pos piece}`, plus `#2`, `#3`, … when the same pair shares several regions | `X0-Y0-Z0~X1-Y0-Z0#2` | Regions by their polylabel point (u, v) |
| Connector | `{face}/c{n}` | `X0-Y0-Z0~X1-Y0-Z0/c1` | Acceptance order (Phase 5) |
| Label text | Grid digits plus suffix | `1-0-2b` | |
| Files | `parts/{piece}.stl`, `dowels/dowel_d{d:.1f}_l{L:.1f}.stl` | `dowels/dowel_d5.0_l20.0.stl` | |

A small piece merged into a neighbour disappears; the surviving piece keeps its own ID and lists the
absorbed IDs in `merged_from`.

### 4.4 Determinism rules (ADR-0010)

1. No randomness anywhere. Hypothesis runs with `derandomize=True` in CI.
2. Every collection that affects output, or whose iteration order affects a result, is sorted with an
   explicit key.
3. Every choice between equal candidates has a documented tie-break.
4. Floats in JSON and Markdown are rounded to 6 decimals.
5. No timestamps, host names, user names or absolute paths in outputs (the input *file name* only).
6. Fixed preview colour palette and fixed font file.
7. Tested end to end: two runs in separate processes give byte-identical output directories. This
   was checked as feasible at plan time: manifold3d produced identical bytes in three separate runs,
   and trimesh writes an all-zero binary STL header.

### 4.5 Diagnostics and exit codes

| Exit code | Meaning |
|---|---|
| 0 | Success. Diagnostics of severity `info` or `warning` may exist. |
| 1 | Invalid input file, arguments, configuration or output directory. |
| 2 | The mesh can't be repaired into a valid solid. |
| 3 | Partial success: at least one diagnostic of severity `partial`. |
| 4 | Internal error (a bug). The message asks for a report with the `-v` output. |

Diagnostics live in a registry in `errors.py` and are documented in `docs/TROUBLESHOOTING.md`
(a test keeps the two in sync). Codes are never reused or renumbered; retired codes stay listed as
retired.

| Code | Severity | Meaning |
|---|---|---|
| W001 | partial | A cut face got no connector (no room, or every candidate failed the 3D checks). |
| W002 | warning | A pin was shortened to a standard length below `--dowel-length`. |
| W003 | warning | Label skipped: no room for the minimum text height. |
| W004 | warning | A small piece was left on its own (merge not allowed, see Phase 4). |
| W005 | info | A small piece was merged into a neighbour. |
| W006 | warning | Suspicious scale: model smaller than 1 mm or larger than 5 m. |
| W007 | info | The mesh was repaired (lists the steps applied). |
| W008 | info | A piece has no cut face (a separate body): no connector, no label. |
| W009 | info | A face has a single connector: the pieces can rotate around it until glued. |
| W010 | info | Overlapping shells were merged. |
| W011 | warning | An inside-out body was flipped. |
| W012 | info | The model already fits: nothing to cut. |
| W013 | partial | No clear straight path could be shown for an assembly step (r12). |

---

## 5. Pipeline and data model

### 5.1 Runtime pipeline

```
input.stl
  │  io.load_stl              trimesh load (merges vertices), --scale, scale sanity check
  ▼
repair.prepare                 try Manifold as-is → basic repair → optional deep repair
  │                            → shell normalization → optional --simplify
  ▼
grid.orient                    proper rotation (auto-orient) → translate bbox min to origin
  ▼
grid.even_grid → grid.nudge    planes per axis; nudge scores use geometry.cut_region
  │                            and connectors.safe_region
  ▼
cutting.split_cells            split_by_plane X → Y → Z, decompose, piece IDs
  ▼
cutting.cut_faces → cutting.merge_small_pieces
  ▼
connectors.place               2D candidates → 3D checks (rays, containment, min_gap)
  ▼
labels.layout                  one label per piece, on one of its cut faces
  ▼
tools.apply                    hole, peg and label solids; one batched boolean per piece; pins
  ▼
assembly.plan_steps            stage 1: X joins (rows) → stage 2: Y joins (layers) → stage 3: Z joins
  ▼
io.write_outputs               parts/*.stl, dowels/*.stl, assembly.json, assembly.md, preview_exploded.glb
```

The implementation phases (§10) don't follow this order exactly. Nudging is built in Phase 6, after
the section and placement code it relies on (Phases 4 and 5).

### 5.2 Data model (`models.py`)

Geometry stays in `manifold3d.Manifold` during processing. Conversion to trimesh happens only in
`geometry.py` wrappers, for repair and export.

```python
Axis = Literal[0, 1, 2]                       # 0 = X, 1 = Y, 2 = Z (cutting frame)

@dataclass(frozen=True)
class Orientation:                            # r6: assembly (Phase 9) writes it, so it lives here
    name: str                                 # rotation name from grid.ROTATIONS, e.g. "90 deg about Y"
    input_to_cutting: tuple[tuple[float, float, float, float], ...]   # 4×4 [[R, t], [0, 0, 0, 1]]

@dataclass(frozen=True)
class Plane:
    axis: Axis
    index: int                                # 0-based position among this axis' planes
    offset: float                             # mm, cutting frame

@dataclass(frozen=True)
class Grid:
    usable: tuple[float, float, float]        # U per axis, mm (peg-adjusted in peg mode)
    counts: tuple[int, int, int]              # number of cells per axis
    planes: tuple[tuple[Plane, ...], ...]     # per axis, sorted by offset
    extent: tuple[float, float, float]        # model size per axis in the cutting frame, mm

@dataclass
class Piece:
    id: str
    grid_index: tuple[int, int, int]
    body: manifold3d.Manifold
    face_ids: list[str]
    merged_from: list[str]                    # IDs of small pieces merged into this one
    label: "Label | None"

@dataclass(frozen=True)
class CutFace:
    id: str
    plane: Plane
    piece_neg: str
    piece_pos: str
    region: shapely.Polygon                   # plane-local (u, v); may have holes

@dataclass(frozen=True)
class Connector:
    id: str
    face_id: str
    kind: Literal["dowel", "peg"]
    position_uv: tuple[float, float]          # plane-local, mm
    diameter: float                           # d
    pin_length: float                         # L, a standard length (§6.2); for pegs, 2 × protrusion
    hole_depth_neg: float                     # 0 on the peg side
    hole_depth_pos: float

@dataclass(frozen=True)
class Label:
    text: str
    face_id: str
    outline: shapely.MultiPolygon             # plane-local, already mirrored for its viewing side
    height: float                             # mm

@dataclass(frozen=True)
class AssemblyStep:
    number: str                               # "2.3" = stage 2 (Y joins), third join
    axis: Axis
    moving: tuple[str, ...]                   # piece IDs of the sub-assembly that moves
    static: tuple[str, ...]
    direction: str                            # e.g. "-y"
    face_ids: tuple[str, ...]
    connector_count: int
    clear_path: bool = True                   # r12: False = no clear path shown (W013)

@dataclass(frozen=True)
class Diagnostic:
    code: str                                 # "W001"
    severity: Literal["info", "warning", "partial"]
    message: str
    refs: tuple[str, ...]                     # piece / face / connector IDs
```

### 5.3 Invariants

Asserted in code where cheap, tested everywhere else.

| ID | Invariant |
|---|---|
| I1 | Every piece body has status `NoError` and a positive volume. |
| I2 | Every cell fits U, and every final piece (connectors and pegs included) fits inside bed − 2·margin, which in peg mode is U + L_max/2 (r10). |
| I3 | Before tools are applied, the piece volumes add up to the reference volume (Phase 2) within 0.1 %. |
| I4 | Every cut face has exactly one piece on each side, and its region lies inside both pieces' sections. |
| I5 | No two holes in the same piece are closer than `min_wall` (measured with `min_gap`). |
| I6 | Every connector's axis point lies inside its face's safe region. |
| I7 | Every assembly step joins two different sub-assemblies with one straight move (r12), and all its faces are perpendicular to its axis. |

---

## 6. Parameters and formulas (single source of truth)

Every number the code uses comes from this section, either as a user option or named constant in
`config.py` or as a derived value from `config.derived()`. Nothing is recomputed elsewhere. Changing
a default means changing it here, in `config.py` and in `docs/CONFIGURATION.md`, in the same commit.

### 6.1 Main table

| Symbol | Meaning | Source | Default / derived value |
|---|---|---|---|
| bed | Build volume | `printer.bed` | 220 × 220 × 250 mm |
| m | Margin kept free on each side of every axis | `printer.margin` | 5 mm |
| U | Usable volume per axis: what a cell must fit | `bed − 2·m`; peg mode: also `− L_max/2` | 210 × 210 × 240 (peg mode: 200 × 200 × 230) |
| U_print | Printable volume per axis: what a final piece must fit, its pegs included (r10) | `bed − 2·m` | 210 × 210 × 240 |
| d | Pin diameter | `connectors.diameter` | 5.0 |
| c | Radial clearance added to holes | `connectors.clearance` | 0.2 |
| w | Minimum wall around and between holes | `connectors.min_wall` | 2.0 |
| L_max | Length of a full pin | `connectors.length` | 20.0 |
| a | Axial play per side (hole deeper than the pin end) | `advanced.axial_play` | 0.5 |
| Δ | Step between standard pin lengths | `advanced.pin_length_step` | 2.0 |
| L_min | Shortest allowed pin | `advanced.pin_min_length_factor · d` | 3 × 5 = 15 |
| 𝓛 | Standard pin lengths | `{L_max − k·Δ ≥ L_min}` | 20, 18, 16 |
| h(L) | Hole depth per side for a pin of length L | `L/2 + a` | 10.5, 9.5, 8.5 |
| p | Peg protrusion (peg mode) | `L/2` | 10 for L_max |
| r_h | Hole radius | `d/2 + c` | 2.7 |
| n_seg | Segments per circle | `advanced.circular_segments` | 64 |
| r_model | Modelled hole radius (polygon flats at r_h) | `r_h / cos(π / n_seg)` | 2.7033 |
| ch_h | Hole mouth chamfer | `advanced.hole_chamfer` | 0.4 |
| ch_p | Pin and peg end chamfer | `advanced.pin_chamfer` | 0.5 |
| f | Depth of the flat on pins | `advanced.pin_flat` | 0.4 (flat 2.71 mm wide at d = 5) |
| inset | Inset of a cut region to get its safe region | `w + r_h + ch_h` | 5.1 |
| g | Candidate grid step | `d / 4` | 1.25 |
| s_min | Minimum distance between connectors of one face | `advanced.connector_spacing_factor · d` | 15 |
| A | Face area per connector | `(advanced.connector_area_factor · d)²` | 900 mm² |
| k_max | Maximum connectors per face | `connectors.max_per_face` | 4 |
| island | "Tiny island" area threshold (nudging) | `4 · π · (d/2)²` | 78.5 mm² |
| ε | Half-thickness of the section probe | `advanced.section_epsilon` | 0.01 |
| ε_ray | Ray start offset inside a piece | constant `RAY_START_OFFSET` | 0.01 |
| ε_tool | How far hole cutters and pegs reach past a cut face (r10) | constant `TOOL_OVERLAP` | 0.01 |
| keep-out | Label keep-out radius around a connector | `r_h + ch_h + w` | 5.1 |
| label backing | Material required behind a label, measured from the face (r11) | `t_lab + w` | 2.6 |
| anchor slack | Clearance a label's anchor may give up to sit nearest the centroid (r11) | constant `LABEL_ANCHOR_SLACK` | 0.01 |
| label positions | Fallback positions per region part, on a grid of step `H_min / LABEL_ANCHOR_GRID_DIVISOR` (r11) | constant `LABEL_MAX_ANCHORS` | 256, step 2 mm |
| r_probe | Radius of the circle of depth rays and of the containment cylinder (r8) | `r_h + w` | 4.7 |
| ray length | Length of the depth rays (r8) | `h(L_max) + w + RAY_LENGTH_MARGIN` (1 mm) | 13.5 |
| T_max | Candidates of a face that go through the 3D checks at most (r8) | constant `MAX_CANDIDATE_TRIALS` | 256 |
| t_lab | Label engraving depth | `labels.depth` | 0.6 |
| H_min, H_max | Label text height range | `advanced.label_min_height`, `advanced.label_max_height` | 4.0, 12.0 |
| V_small | Small-piece volume threshold | `advanced.small_piece_volume` | 500 mm³ |
| W_n, δ_n | Nudge window and step | `advanced.nudge_window`, `advanced.nudge_step` | 5.0, 0.5 |
| path slack | Slack when comparing positions along an assembly move (r12) | constant `ASSEMBLY_PATH_TOLERANCE` | 1e-6 |
| order search | States the search for a fully clear join order may visit per cluster (r12) | constant `ASSEMBLY_SEARCH_STATES` | 4096 |

### 6.2 Pin lengths, hole depths and why they're defined this way

- `--dowel-length` is the **exact length of a full pin** (L_max). There is one definition, used everywhere.
- Each hole is `h(L) = L/2 + a` deep, so a pin of length L has `a` of play at each end (glue room,
  and it never bottoms out).
- When a piece is too shallow behind a face for a full pin, the connector uses the longest standard
  length that fits (20 → 18 → 16 with the defaults). That keeps the number of pin files small, and
  Phase 7 groups identical pins into one STL with a count. Anything shorter than L_min is rejected.
- Pins are symmetric (the same depth on both sides), so the user never has to orient them.
- Pins are printed lying on a small flat of depth f: a round pin touches the bed along a single line.
  The flat also lets glue and air escape from the blind holes.
- Circles are modelled with `n_seg` segments, and holes use r_model so the polygon *flats* sit at r_h.
  With manifold3d's default segment count (16 at d = 5) the flats would sit 0.05 mm inside, about a
  quarter of a 0.2 mm clearance, and the loss would change with the diameter.

### 6.3 Calibration kit dimensions

| Symbol | Meaning | Formula | Default |
|---|---|---|---|
| c_max | Largest clearance tested | `max(advanced.calibration_clearances)` | 0.30 |
| hole_outer | Hole diameter at the mouth, chamfer included | `d + 2·c_max + 2·ch_h` | 6.4 |
| w_cal | Wall used in the kit | `max(w, 3.0)` | 3.0 |
| n_cal | Number of holes | `len(calibration_clearances)` | 5 |
| pitch | Distance between hole centres | `hole_outer + w_cal` | 9.4 |
| length | Bar length | `n_cal·hole_outer + (n_cal + 1)·w_cal` | 50.0 |
| width | Bar width | `hole_outer + 2·w_cal` | 12.4 |
| thickness | Bar thickness | `h(L_max) + w_cal` | 13.5 |

The holes sit in one row, centred across the width, so two identical bars flipped face to face line
up hole for hole, with the same clearance. Each hole's code is engraved on one long side face, under
the hole, at height H_min. The code is the clearance in hundredths of a millimetre (`10`, `15`, `20`,
`25`, `30`), with up to two decimals when needed (`12.3` for 0.123; r10). With the defaults two digits
fit within one pitch, and the engraving leaves 2.4 mm of wall to the hole mouth (≥ w). When a code
wouldn't fit (a small pin, a long code), the height shrinks just enough: a code is at most
pitch − `CALIBRATION_CODE_GAP` (1 mm) wide and thickness − 2 mm tall (r10). Clearances that would get
the same code are an error (exit 1), and so are a bar that doesn't fit the printable volume, an
engraving that would reach a hole, and holes that would touch (r10).

---

## 7. CLI and configuration

### 7.1 Modes

| Mode | Command | Writes files | Exit code |
|---|---|---|---|
| Split | `stlsplit INPUT -o DIR [options]` | yes | 0, 1, 2, 3 or 4 |
| Dry run | `stlsplit INPUT --dry-run [options]` | no | as a split would |
| Calibration | `stlsplit --calibrate -o DIR [connector options]` | yes | 0, 1 or 4 |
| Show config | `stlsplit --print-config [--config FILE] [options]` | no | 0 or 1 |

The dry run goes through every step up to connector placement and label layout, then plans the
assembly order so that it reports W013 and exits as a split would (r12), skipping the tool
booleans and file writing. It prints the orientation, grid, planes, pieces, faces, connectors, pin
groups and diagnostics. Its output grows as phases land (Phase 3 prints the grid only). The plan
goes to stdout and the log, diagnostics included, to stderr, so `-q` doesn't hide the plan (r6).

### 7.2 Options

| CLI | TOML key | Default | Meaning |
|---|---|---|---|
| `INPUT` (positional, optional) | — | — | Input `.stl`. Required unless `--calibrate` or `--print-config` is used. |
| `-o, --output DIR` | — | — | Output directory, created if missing. Required unless `--dry-run` or `--print-config`. |
| `--force` | — | off | Allow a non-empty output directory (§7.6). |
| `--config FILE` | — | — | TOML file; explicit CLI options override it. |
| `--bed X Y Z` | `printer.bed` | `220 220 250` | Build volume, mm. |
| `--margin` | `printer.margin` | `5.0` | Kept free on **each side** of every axis: `U = bed − 2·margin`. |
| `--scale` | `model.scale` | `1.0` | Uniform scale applied after loading. |
| `--auto-orient` / `--no-auto-orient` | `model.auto_orient` | on | Try the 6 axis orders and keep the one with the fewest cells. |
| `--simplify TOL` | `model.simplify` | `0` (off) | `Manifold.simplify` tolerance in mm: surfaces move by less than TOL. |
| `--deep-repair` | `repair.deep` | off | pymeshlab fallback if basic repair fails (extra `deep-repair`). |
| `--connector` | `connectors.type` | `dowel` | `dowel`, `peg` or `none`. |
| `--dowel-diameter` | `connectors.diameter` | `5.0` | d, mm. |
| `--dowel-length` | `connectors.length` | `20.0` | L_max: exact length of a full pin, mm (§6.2). |
| `--clearance` | `connectors.clearance` | `0.2` | Radial clearance added to holes, mm (printer-dependent). |
| `--min-wall` | `connectors.min_wall` | `2.0` | Minimum material around and between holes, mm. |
| `--max-connectors-per-face` | `connectors.max_per_face` | `4` | |
| `--label` / `--no-label` | `labels.enabled` | on | Engrave piece IDs. |
| `--label-depth` | `labels.depth` | `0.6` | mm. |
| `--preview` / `--no-preview` | `output.preview` | on | Write `preview_exploded.glb`. |
| `--dry-run` | — | off | §7.1. |
| `--calibrate` | — | off | §7.1. |
| `--print-config` | — | off | Print the effective configuration as TOML and exit. |
| `-v` / `-q` | — | — | More or less logging; `-v` adds stage timings and tracebacks. |
| `--version` | — | — | |

### 7.3 Advanced options (TOML only, table `[advanced]`)

All of these appear in §6. They exist so behaviour can be tuned without code changes.

| Key | Default | Meaning |
|---|---|---|
| `axial_play` | 0.5 | a, mm |
| `pin_length_step` | 2.0 | Δ, mm |
| `pin_min_length_factor` | 3.0 | L_min = factor · d |
| `pin_chamfer` | 0.5 | ch_p, mm |
| `pin_flat` | 0.4 | f, mm (0 = round pins) |
| `hole_chamfer` | 0.4 | ch_h, mm |
| `circular_segments` | 64 | n_seg |
| `connector_spacing_factor` | 3.0 | s_min = factor · d |
| `connector_area_factor` | 6.0 | A = (factor · d)² |
| `section_epsilon` | 0.01 | ε, mm |
| `nudge_window` | 5.0 | W_n, mm (0 disables nudging) |
| `nudge_step` | 0.5 | δ_n, mm |
| `small_piece_volume` | 500.0 | V_small, mm³ (0 disables merging) |
| `label_font` | `"DejaVuSans-Bold.ttf"` | A font bundled with matplotlib, or an absolute path |
| `label_min_height` | 4.0 | H_min, mm |
| `label_max_height` | 12.0 | H_max, mm |
| `calibration_clearances` | `[0.10, 0.15, 0.20, 0.25, 0.30]` | mm |
| `preview_spread` | 0.15 | Exploded-view offset per grid step, as a fraction of the model size |

### 7.4 Precedence

Built-in defaults ← TOML file ← **explicitly passed** CLI options. Every argparse option uses
`default=argparse.SUPPRESS`, so an option the user didn't type is absent from the namespace and can't
override the TOML value. (With ordinary defaults you can't tell "the user typed 220" from "default
220", and the TOML file always loses.) Unknown TOML tables or keys are an error (exit 1) that names
the key.

### 7.5 Validation (exit 1 with a message naming the option and the allowed range)

- Every number is finite (TOML accepts `inf` and `nan`), and integers fit in 64 bits.
- `bed`: three values > 0. `margin` ≥ 0 and `2·margin` < the smallest bed dimension.
- `scale` > 0. `simplify` ≥ 0.
- `diameter` ≥ 0.1 (r10), `clearance` ≥ 0, `min_wall` > 0, `max_per_face` ≥ 1.
- `length` ≥ L_min (so a full pin is never shorter than the shortest allowed pin), and
  `length` ≤ max(bed X, bed Y): pins are printed lying down (r8).
- `labels.depth` > 0 and < `min_wall`.
- Peg mode: every `U_i − L_max/2` > 0.
- Advanced: `axial_play` ≥ 0; `pin_length_step` ≥ 0.1; `pin_min_length_factor` > 0;
  0 ≤ `pin_flat` < d/4; 0 ≤ `pin_chamfer` < min(L_min/4, d/2) (r10); 0 ≤ `hole_chamfer` ≤ w/2;
  16 ≤ `circular_segments` ≤ 256; `connector_spacing_factor` > 0; `connector_area_factor` > 0;
  `nudge_window` ≥ 0; `nudge_step` > 0 and `nudge_window / nudge_step` ≤ 100 (r9);
  0 < `section_epsilon` ≤ 0.1; `small_piece_volume` ≥ 0;
  0 < `label_min_height` ≤ `label_max_height`; `calibration_clearances` has 1 to 10 values, each
  ≥ 0, strictly increasing; `preview_spread` ≥ 0; `label_font` resolves to an existing file and, in
  any run that draws text (a split or dry run with labels on, or `--calibrate`), is a readable font
  with its own glyph for each digit, `-`, `.` and a to z (r11).
- Modes: exactly one of `INPUT`, `--calibrate` or a bare `--print-config` (`--print-config` with
  `INPUT` or `--calibrate` is an error); `--dry-run` needs `INPUT`; `-o` present unless
  `--dry-run` or `--print-config` (with `--dry-run` it is accepted and ignored).

### 7.6 Output directory policy

- `-o DIR` is created (with parents) if it doesn't exist.
- If DIR exists and is not empty: without `--force`, exit 1. With `--force`, delete only the outputs
  stlsplit owns, `parts/`, `dowels/`, `calibration/`, `assembly.json`, `assembly.md` and
  `preview_exploded.glb`, and keep everything else. Never delete DIR itself. A symlink with one of
  those names is unlinked, never followed. If that would delete a file the run reads (the input,
  the `--config` file or the label font), exit 1 before any work (r10).
- The list of owned names is a single constant in `io.py`, used by both the writer and `--force`.

### 7.7 Example configuration (`my_printer.toml`)

```toml
[printer]
bed = [180, 180, 180]
margin = 4

[connectors]
type = "dowel"
diameter = 6.0
length = 24.0        # full pin; shorter standard lengths: 22, 20, 18 (L_min = 3 × 6 = 18)
clearance = 0.25
min_wall = 2.5

[labels]
enabled = true
depth = 0.6

[advanced]
pin_flat = 0.4
```

---

## 8. Documentation system

The project will be maintained by people who didn't write it, so documentation is a deliverable of
every phase, not a final chore. The phase sections in §10 each list the docs they must update.

### 8.1 Principles

- **Write for the reader.** Each document has one audience (table below).
- **Most useful information first.** Commands and examples before explanations.
- **Show, don't tell.** Real commands, real output excerpts, formulas with the default numbers filled in.
- **Keep it current.** A change ships with its docs in the same commit. The drift tests (§8.5) fail
  when code and docs disagree. Outdated docs are worse than none.
- **Link, don't duplicate.** Each fact has one home. Numbers live in §6 and `config.py`; docs link to
  them instead of copying. Code comments cite ADRs (`# see ADR-0004`) instead of re-arguing them.

### 8.2 Documentation map

| File | Audience | Content | Updated when |
|---|---|---|---|
| `README.md` | Users | What and why; install; 5-minute quick start; examples; calibration workflow; output folder; printing the dowels; assembling; known limits; measured performance; real test-print result | CLI, behaviour or output changes |
| `CHANGELOG.md` | Users, maintainers | Keep a Changelog sections under `[Unreleased]`, one entry per user-visible change | Every user-visible change |
| `CONTRIBUTING.md` | Maintainers | Dev setup; commands; code style; commit convention; definition of done for a change; recipes (§8.7) | Process changes |
| `CLAUDE.md` | Claude Code | Short: commands, rules, where to look (Appendix B) | Rarely; prune when it grows |
| `PLAN.md` | Maintainers, Claude Code | This plan, progress table, plan revisions | Every phase |
| `docs/ONBOARDING.md` | A new maintainer | Start-here guide (§8.7) | Structure changes |
| `docs/ARCHITECTURE.md` | Maintainers | Pipeline diagram, module map and import rules, data model, frames, invariants, diagnostics flow | Structure changes |
| `docs/ALGORITHMS.md` | Maintainers | One section per algorithm: inputs, outputs, formulas, rationale, edge cases, links to its tests | Algorithm changes |
| `docs/CONFIGURATION.md` | Users | Every option: CLI flag, TOML key, default, unit, validation rule | Option changes (drift-tested) |
| `docs/OUTPUT_FORMAT.md` | Users, tool authors | Folder layout, file naming, every `assembly.json` field, `schema_version` history | Output changes (drift-tested) |
| `docs/TROUBLESHOOTING.md` | Users | Every exit code and diagnostic code with cause and fix; common problems | New codes (drift-tested) |
| `docs/LIBRARY_NOTES.md` | Maintainers | Each verified library behaviour the code relies on, with the version and the spike check that proves it | Dependency upgrades |
| `docs/GLOSSARY.md` | Everyone | Cell, piece, body, cut face, region, safe region, usable volume, standard length, … | New concepts |
| `docs/adr/` | Maintainers | Architecture Decision Records and their index | A decision is made or changed |

### 8.3 Architecture Decision Records

- One file per decision, `docs/adr/NNNN-short-title.md`, never renumbered. Template in Appendix A.
- Write an ADR when choosing between real alternatives, when a choice is expensive to reverse, or for
  anything a future maintainer would ask "why is it like this?" about.
- Changing a decision means writing a new ADR that supersedes the old one. The old one gets the
  status "Superseded by ADR-XXXX" and stays in place.
- Phase 0 writes ADR-0001 to ADR-0014 from §12. `docs/adr/README.md` is the index (number, title,
  status).

### 8.4 Code documentation standard

- **Every module** starts with a docstring: its place in the pipeline (§5.1), its main inputs and
  outputs, and the invariants it guarantees.
- **Every public function** has a Google-style docstring giving the unit and frame of every
  geometric argument, the ordering of returned collections, the exceptions raised, and references
  (§ or ADR) for non-obvious choices.
- **Comments explain why**, not what.
- **Type hints** on every public function; mypy runs in CI.
- **No magic numbers.** Constants live in `config.py` with a comment pointing to §6.

```python
def cut_region(body: Manifold, plane: Plane, eps: float) -> list[Polygon]:
    """Return the contact region between the two sides of a cut plane.

    The region is the intersection of the slices at ``plane.offset - eps`` and
    ``plane.offset + eps``. A single slice is one-sided when a model face lies exactly
    on the plane (ADR-0002).

    Args:
        body: Normalized input manifold, cutting frame, mm.
        plane: The cut plane.
        eps: Half-thickness of the probe, mm (``advanced.section_epsilon``).

    Returns:
        Connected polygons with holes, in plane-local (u, v) coordinates
        (docs/ARCHITECTURE.md, "Frames"), sorted by their polylabel point.
    """
```

### 8.5 Drift tests (`tests/unit/test_docs_drift.py`)

| Check | Fails when |
|---|---|
| Every `Config` field and every CLI flag appears in `docs/CONFIGURATION.md` | An option is added or renamed without docs |
| Every exit code and diagnostic code in `errors.py` has a heading in `docs/TROUBLESHOOTING.md` | A code is added without docs |
| Every top-level property of `assembly.schema.json` appears in `docs/OUTPUT_FORMAT.md` | The output format changes without docs |
| Every file in `docs/adr/` is listed in `docs/adr/README.md`, and every listed ADR exists | An ADR isn't indexed |
| Every module in `src/stlsplit/` is named in `docs/ARCHITECTURE.md` | A module is added without docs |

### 8.6 Changelog and versioning

- `CHANGELOG.md` follows Keep a Changelog: Added, Changed, Fixed and Removed under `[Unreleased]`.
- During development, tag `v0.N.0` when phase N is done (handy for bisecting). Phase 11 tags `v1.0.0`.
- After 1.0, SemVer: MAJOR for breaking CLI or output changes, MINOR for features, PATCH for fixes.
- `assembly.json` carries an integer `schema_version`. A breaking change (a field removed, renamed or
  given a new meaning) increments it; an additive change doesn't. Every version is described in
  `docs/OUTPUT_FORMAT.md`.

### 8.7 Onboarding, handover and recipes

`docs/ONBOARDING.md` is the start-here guide for whoever takes the project over:

1. What stlsplit does, in five lines, and where the user docs are.
2. Ten-minute setup: clone, `pip install -e ".[dev]"`, `python scripts/check.py`, the README quick start.
3. Reading order: ARCHITECTURE → ADR index → ALGORITHMS (skim) → CONTRIBUTING.
4. Trace one model: run with `-v` on one of the real fixtures and match each log line to its stage.
5. A table "I want to… → module, doc and test to change" (built from the recipes below).
6. Working with Claude Code on this repository: `CLAUDE.md`, the protocol in §9.1, the review step.
7. Upgrading dependencies: run `scripts/api_spike.py`, update `docs/LIBRARY_NOTES.md`.
8. History: decisions are in the ADRs, plan changes in PLAN.md Appendix E, and the original author
   is named here for questions.

`CONTRIBUTING.md` holds the **definition of done for any change** (code, tests, docs, CHANGELOG entry,
`scripts/check.py` green, commit message per §9.3) and these recipes, each listing the files, tests
and docs to touch:

- Add a CLI or TOML option.
- Add a diagnostic code.
- Add a connector type.
- Add a test fixture.
- Change an output file or the `assembly.json` schema.
- Upgrade a dependency.
- Record or change a decision (ADR).
- Release a version.

---

## 9. Engineering workflow

### 9.1 Phase protocol for Claude Code

This protocol follows Anthropic's Claude Code best practices: explore, then plan, then implement,
then commit; give Claude a check it can run; start from a clean context for each task; and have an
independent reviewer check the result.

1. **Fresh session per phase.** Start a new session (or `/clear`) for each phase. The progress table
   and the git log tell the new session where things stand.
2. **Explore and plan in plan mode.** Example prompt:

   ```text
   Read CLAUDE.md, PLAN.md sections 0–9 and "Phase N" in section 10. Don't read other phases.
   Read the existing files the phase lists. Then propose an implementation plan for Phase N only:
   files and functions, the tests from the phase's list, and the docs to update.
   Wait for my approval before writing code.
   ```

   Skip plan mode only for changes you could describe in one sentence.
3. **Tests first.** Write the phase's tests, run them, and confirm they fail for the expected reason.
4. **Implement** until the tests pass, then run `python scripts/check.py` and **show the output**:
   evidence, not "it works".
5. **Docs.** Update every document listed in the phase, add the CHANGELOG entry, and update
   `docs/LIBRARY_NOTES.md` or an ADR if a library or decision turned out differently.
6. **Independent review.** Example prompt:

   ```text
   Use a subagent to review the current diff against PLAN.md "Phase N". Check that every task is
   implemented, every listed test exists and passes, the listed docs were updated, and nothing outside
   the phase changed. Report only gaps that affect correctness or the stated requirements.
   ```

   Fix real gaps. Don't chase style findings: that leads to over-engineering.
7. **Commit** (§9.3), and update the progress table: status, short commit hash, notes for the next
   session.
8. **When the plan is wrong or ambiguous,** stop and say so, with a proposed fix. Once the human
   agrees, update the affected section and Appendix E in the same commit as the code.

### 9.2 Rules

- Geometry goes through manifold3d; trimesh is only used through the wrappers in `geometry.py` and
  `io.py` (ADR-0001).
- Units are mm; pipeline geometry is in the cutting frame (§4.2).
- Pure functions everywhere except `io.py` and `cli.py` (§3.1).
- Every number comes from `config.py` or `config.derived()` (§6).
- Determinism rules (§4.4) apply to every change.
- No GUI and no web server. For visual debugging, export a `.glb` to the output folder.
- **Never weaken, skip or delete a test to make it pass.** If a test looks wrong, say so and ask.

**Stop and ask the human** before:

- changing anything an ADR decided;
- adding a runtime dependency;
- changing an output format or the `assembly.json` schema;
- accepting a phase whose acceptance criterion can't be met as written;
- accepting a performance result more than 2× over target;
- choosing the project's licence (Phase 0).

### 9.3 Commits, branches and tags

- One branch per phase, `phase-NN-short-name`, merged into `main` once the checklist in Appendix C is
  complete.
- Commit message: `[TAG] Phase N: summary` during the plan, `[TAG] summary` after v1.
- Tags (the project's convention):
  - `[INIT]` creating the repository (the first commit of Phase 0 only);
  - `[FEAT]` a new feature or a phase deliverable;
  - `[ADD]` an addition to existing code (an option, a test, a docs section);
  - `[FIX]` a bug fix;
  - `[DEL]` removing a feature, a function or dead code.
- One logical change per commit, with its code, tests and docs together.

### 9.4 Testing strategy

| Layer | Scope | Location | Budget |
|---|---|---|---|
| Unit | Pure functions: frames, sections, inset, connector count, trial order, standard lengths, label layout, assembly order on synthetic graphs, config | `tests/unit` | whole layer < 15 s |
| Integration | One stage on a fixture: repair, cutting, placement and tools, labels, export | `tests/integration` | whole layer < 2 min |
| End-to-end | The CLI in a subprocess on every fixture; global properties; determinism | `tests/e2e` (marker `e2e`) | < 10 min |
| Slow | Performance on 1M+ triangles | marker `slow` | manual and weekly CI |

- Fixtures are generated in code (Appendix D). The only binary files in git are the 2–3 small real models.
- Property tests use hypothesis, derandomized in CI.
- Coverage is reported from Phase 0 and enforced at ≥ 85 % from Phase 11.
- Test names describe behaviour: `test_hollow_sphere_keeps_its_void`, not `test_repair_3`.

### 9.5 Continuous integration (GitHub Actions; adapt if the repository lives elsewhere)

- **On every push and pull request:** Python 3.12 and 3.13 on Linux, plus 3.13 on Windows and macOS:
  `pip install -e ".[dev]"`, then `python scripts/check.py`.
- **Weekly:** upgrade every dependency to its latest version, then run `python scripts/api_spike.py`
  and the fast tests. This catches upstream breakage before users do.

### 9.6 Everyday commands

```bash
pip install -e ".[dev]"                     # development environment
python scripts/check.py                     # ruff, ruff format --check, mypy, all tests except slow
python scripts/check.py --fast              # same, without the e2e tests
pytest -q tests/unit/test_nudge.py -k slack # one test
python scripts/api_spike.py                 # after any dependency upgrade
```

---

## 10. Implementation phases

Every phase has the same shape: **Goal**, **Files**, **Tasks**, **Tests** (write them first),
**Docs** (update them before committing) and **Done when**. "Done when" always also includes the
checklist in Appendix C.

### Phase 0 — Scaffolding, documentation skeleton, API spike

**Goal.** An installable empty package, the whole documentation skeleton with the initial ADRs, one
command that runs every check, CI, and an executable record of every library behaviour the code
will rely on.

**Files.** `pyproject.toml`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `LICENSE`,
`.gitignore`, `.github/workflows/ci.yml`, `scripts/check.py`, `scripts/api_spike.py`, every file of
`docs/` (§8.2) as a skeleton, `docs/adr/0000-template.md` to `0014-*.md` and `docs/adr/README.md`,
`src/stlsplit/{__init__,__main__,cli,errors,geometry}.py`, `tests/conftest.py`,
`tests/unit/test_geometry.py`, `tests/test_api_spike.py`.

**Tasks.**
1. `git init`. `pyproject.toml`: setuptools with the `src/` layout; console script
   `stlsplit = "stlsplit.cli:main"`; runtime dependencies from §2 with `>=` minimums set to the
   versions verified in task 6; extras `dev` and `deep-repair`; ruff, mypy and pytest configuration
   (markers `e2e` and `slow`). Version `0.0.0`. **Ask the human which licence to use** (MIT fits: every
   core dependency is permissive, and pymeshlab is an optional extra).
2. `scripts/check.py`: runs `ruff check .`, `ruff format --check .`, `mypy src`, then pytest
   (`-m "not slow"`, or `-m "not slow and not e2e"` with `--fast`). Prints each command and stops at
   the first failure with a non-zero exit code. Pure Python, so it works on Windows too.
3. CI workflow as described in §9.5.
4. Documentation skeleton: every file of §8.2 with its section headings and `TODO (Phase N)` markers.
   Seed `docs/GLOSSARY.md` from §4–§6. Fill in `CONTRIBUTING.md` setup, commands, commit convention
   and definition of done, with the recipe headings. Write `CLAUDE.md` from Appendix B, and
   `CHANGELOG.md` with an `[Unreleased]` section.
5. ADR-0001 to ADR-0014 from §12 using the template in Appendix A (status Accepted), plus the index.
6. `scripts/api_spike.py`: an executable check that prints the installed versions and **asserts**
   each behaviour below, exiting non-zero on the first failure. It records what this plan found on
   2026-11-17; if a result differs on the development machine, follow §0 ("When reality differs").
   - **manifold3d:**
     - `Mesh` takes C-contiguous `vert_properties` (float32, N×3) and `tri_verts` (uint32, M×3).
       Arrays returned by `to_mesh()` are read-only views; copy them before passing them back.
     - `status()` and `volume()` work as expected.
     - `split_by_plane(normal, offset)` returns (the side the normal points to, the other side).
     - `trim_by_plane`, `decompose`, `batch_boolean(list, OpType.Add)` and `project()` all work.
     - `cylinder(height, radius_low, radius_high=-1, circular_segments=0, center=False)` uses
       16 segments at r = 2.5 by default.
     - `transform(3×4)` followed by `slice(z)` maps axes as in §4.2.
     - `CrossSection(contours, FillRule.EvenOdd)`, `decompose()` and `to_polygons()` work; outer
       contours have positive area and holes negative.
     - `^` intersects two CrossSections; `Manifold.extrude(cs, h)` works.
     - `ray_cast(origin, endpoint)` returns hits sorted by distance. `RayHit.distance` is a
       **fraction of the segment**, not mm; `RayHit.position` is in mm. A face the origin lies on
       is not reported.
     - `min_gap(other, search_length)` returns 2.0 for two r = 2.7 cylinders with axes 7.4 mm
       apart, and 0 when they cross.
     - `simplify(tolerance)` keeps the result manifold.
     - A difference whose cutter face is coplanar with a model face leaves the hole open; a union
       whose face is coplanar with a model face gives one body with the exact volume.
     - `slice` exactly at a step height is one-sided (column under a plate: 1600 mm² instead of
       the 100 mm² contact), while the intersection of the slices at ±ε gives 100 mm² for both
       step directions.
   - **trimesh:**
     - `load(..., force="mesh")` merges vertices by default.
     - `nondegenerate_faces`, `unique_faces`, `update_faces` and `remove_unreferenced_vertices`
       work.
     - `fill_holes` closes a quad hole but not a large one, and needs networkx.
     - `fix_normals(multibody=False)` keeps a hollow sphere's void, while `multibody=True` turns it
       solid.
     - Binary STL export starts with an 80-byte zero header.
     - `Scene.export(file_type="glb")` works with only scipy and networkx installed.
   - **shapely:** negative `buffer`, `ops.polylabel`, `contains` and `intersection`.
   - **matplotlib:** the bundled `DejaVuSans-Bold.ttf` exists at
     `matplotlib.get_data_path()/fonts/ttf/`, and the outer contours of `TextPath` glyphs are
     clockwise (so the EvenOdd rule is required).
   - **Determinism:** a small split-and-drill pipeline run in two subprocesses gives identical bytes.
7. Copy the results and versions into `docs/LIBRARY_NOTES.md`, one row per behaviour: what it is, the
   version verified, which code depends on it, and the spike check that proves it.
8. `geometry.py` wrappers, with unit tests:
   - `to_manifold(trimesh)` and `to_trimesh(manifold)`;
   - `world_to_local(axis)` returning the 3×4 matrix, and `local_to_world(axis)` returning its
     exact inverse (the transpose, also 3×4). The plane stays at local z = o both ways (§4.2);
   - `cylinder_solid(radius, z0, z1, segments, compensate)`, where `compensate=True` puts the
     polygon flats at `radius`;
   - `crosssection_from_contours(contours)` (EvenOdd) and `crosssection_to_polygons(cs)`;
   - `ray_depth(body, origin, direction, max_length)` returning mm (computed from
     `RayHit.position`) or `None`;
   - `union_all(solids)`.

   The section helpers come in Phase 4.
9. `stlsplit --help` and `stlsplit --version` work. The full CLI comes in Phase 1.

**Tests.**
- trimesh ↔ manifold round trip keeps the volume.
- The frame matrices have det = +1 and map axes as in §4.2.
- A compensated cylinder's flat-to-centre distance equals the requested radius (±1e-9).
- The glyph "0" built with EvenOdd keeps its hole.
- `ray_depth` returns mm.
- `tests/test_api_spike.py` runs the spike's `main()` and expects success.

**Docs.**
- `docs/LIBRARY_NOTES.md` complete.
- ADRs and their index.
- All skeletons.
- `CONTRIBUTING.md` setup and commands.
- CHANGELOG: "Added: project scaffolding".

**Done when.**
- `pip install -e ".[dev]"` works in a fresh virtual environment.
- `python scripts/check.py` passes and CI is green.
- `python scripts/api_spike.py` passes.
- Commit: `[INIT] Phase 0: scaffolding, documentation skeleton, API spike`.

---

### Phase 1 — Configuration and CLI shell

**Goal.** Every option in §7 parsed, merged, validated and documented. Exit codes and the
output-directory policy work end to end, before any geometry exists.

**Files.** `config.py`, `cli.py`, `errors.py`, `io.py` (output-directory policy only),
`tests/unit/test_config.py`, `tests/unit/test_cli.py`, `tests/unit/test_docs_drift.py`.

**Tasks.**
1. Frozen `Config` dataclasses mirroring the TOML tables (`printer`, `model`, `repair`, `connectors`,
   `labels`, `output`, `advanced`), with the defaults from §6 and §7. `config.derived(cfg)` computes
   every derived value of §6 (U, L_min, the standard lengths, h(L), r_h, r_model, inset, …) in one
   place.
2. TOML loading with unknown-table and unknown-key detection; the error names the key.
3. argparse parser with `default=argparse.SUPPRESS` on every option. Merge order: built-in defaults,
   then TOML, then explicit CLI options (§7.4).
4. Validation (§7.5), with messages that name the option and the allowed range.
5. Mode validation (§7.1, §7.5).
6. Output-directory policy (§7.6) in `io.prepare_output_dir()`.
7. `--print-config` prints the effective configuration as TOML that the loader reads back.
8. Errors: exception classes mapped to exit codes (§4.5). `main()` prints one line per error, adds the
   traceback with `-v`, and maps unexpected exceptions to exit 4.
9. Logging: `-q` shows warnings and errors, the default shows info, `-v` shows debug messages with
   stage timings.
10. The diagnostics registry (§4.5) in `errors.py`.

**Tests.**
- Precedence default < TOML < CLI, for at least one float, one boolean flag pair, the `--bed` triple
  and the `--connector` choice.
- An unknown TOML key exits with 1 and the message names it.
- Every validation rule rejects a bad value (parametrized).
- Mode errors:
  - neither INPUT nor `--calibrate` → exit 1;
  - both → exit 1;
  - no `-o` without `--dry-run` → exit 1.
- Output directory:
  - non-empty without `--force` → exit 1;
  - with `--force`, only the owned names are deleted (a `notes.txt` survives);
  - a symlink named `parts` is unlinked, not followed.
- `--print-config` output loads back into an equal `Config`.
- Drift tests (§8.5) for configuration, exit codes and diagnostic codes.

**Docs.**
- `docs/CONFIGURATION.md` complete. It may be generated from `Config`, as long as a test keeps it in
  sync.
- README "Usage".
- `docs/TROUBLESHOOTING.md`: exit codes and the diagnostics table.

**Done when.** The tests pass through `scripts/check.py`. Commit:
`[FEAT] Phase 1: configuration and CLI shell`.

---

### Phase 2 — Load, repair, shell normalization

**Goal.** Any reasonable STL becomes one valid, normalized `Manifold` (overlapping shells unioned,
internal voids kept). If that's impossible, the tool exits with code 2 and actionable diagnostics.

**Files.** `io.py` (loading), `repair.py`, `tests/conftest.py` (fixtures), `tests/integration/test_repair.py`.

**Tasks.**
1. `io.load_stl(path, scale)`:
   - `trimesh.load(path, file_type="stl", force="mesh")` (merges vertices by default, drops
     triangles with a non-finite coordinate).
   - An empty or unreadable file raises an input error (exit 1).
   - Apply the scale.
   - W006 if the largest dimension is under 1 mm or over 5000 mm.
2. `repair.prepare(mesh, cfg) -> (Manifold, RepairReport)` (ADR-0007):
   1. Try `Manifold(mesh)` first. If the status is `NoError`, skip repair entirely: valid models pass
      through untouched.
   2. Otherwise, basic repair in this order:
      - `merge_vertices`;
      - drop degenerate and duplicate faces;
      - `remove_unreferenced_vertices`;
      - `fix_normals(multibody=False)`, keeping each shell's majority orientation (r5: its
        `fix_winding` follows one reference face, so one reversed triangle could reverse a whole
        void's shell). **Never `multibody=True`:** it flips internal voids outward. At plan time
        it turned a hollow sphere of 557k mm³ into 27.6M mm³;
      - `fill_holes`, which only closes single-triangle and quad holes.

      Retry the conversion. W007 lists the steps applied.
   3. Still failing: with `--deep-repair`, run pymeshlab (remove non-manifold edges and vertices,
      close holes, re-orient faces) and retry. Without it, raise a repair error (exit 2) that
      reports:
      - the open-edge count;
      - the non-manifold-edge count;
      - the number of bodies;
      - a hint: `--deep-repair`, or a repair in MeshLab or the slicer's "fix model", then try again.
3. Shell normalization, only when `decompose()` returns more than one component, or one
   component with a negative volume (a model inside-out as a whole; r5) (ADR-0007):
   - (Rewritten in r5 after the review.) Each shell, as a solid, gets a container: the
     smallest other shell it lies inside (`(S − T).volume()` ≤ 1e-6 × `S.volume()`).
   - Roles, from the outside in: a shell without a container is a solid, turned the right way
     out if it faces inwards (W011), unless it lies inside the union of the outermost solids
     (a void spanning overlapping solids). A shell facing the same way as its container plays
     the same role; facing the other way, the opposite role (a void in a solid, a ball in the
     void, and so on at any depth).
   - Each solid shell minus the voids it directly contains is a piece; the result is the union
     of the pieces (minus the spanning voids). A void is never subtracted from a shell that
     doesn't contain it.
   - If the union of the pieces is smaller than the sum of their volumes, shells overlapped:
     emit W010.
   - **Never union every component blindly.** `batch_boolean(decompose(), Add)` fills voids: at plan
     time it turned the hollow sphere solid (14.1M mm³ instead of 557k).
4. `--simplify TOL` (when > 0): `Manifold.simplify(TOL)` after normalization. Surfaces move by less
   than TOL and the result stays manifold.
5. Log a summary: triangles, bounding box, volume, bodies, voids, repair steps.
6. The volume of the returned body, after `--simplify`, becomes the **reference volume** for
   every later volume check (I3, Phase 11): that body is the one cut (r5).
7. A result that encloses no volume (a closed but flat surface) is a repair error (exit 2);
   a `--simplify` tolerance that erases the model is an input error naming the option (exit 1).

**Tests** (fixtures from Appendix D).
- Clean cube: volume within 1e-6 relative; the report says no repair was done.
- Soup cube (built with `process=False`, written to STL): loads watertight. This documents trimesh's
  merge-on-load behaviour.
- Cube missing a face: repaired, with W007.
- Sphere missing a cap: exit 2, and the message includes the open-edge count.
- Cube with a stray triangle on one edge (r5; it replaces two cubes touching along an edge,
  which manifold3d accepts as is):
  - exit 2 without `--deep-repair`, the message giving 2 open edges, 1 non-manifold edge,
    1 body;
  - repaired with it (test skipped if pymeshlab isn't installed).
- Two cubes touching along one edge: accepted as is, as two bodies (r5).
- Overlapping shells (two 20 mm cubes offset by 10 mm): volume 12 000 mm³ and W010.
- Hollow sphere (r = 150, 2 mm shell): the void is kept, volume = ⁴⁄₃π(150³ − 148³) within 1 %.
- Ball inside the hollow sphere's void: kept, no W010 (r5); a void inside that ball: kept too.
- Inverted body next to a normal cube: both kept, total volume = sum of both, W011.
- A single inside-out cube: flipped, +1000 mm³, W011 (r5).
- The hollow sphere inside out as a whole: the void is kept, W011 (r5, review).
- The hollow sphere with the one reversed triangle trimesh orients a shell by: the void is kept
  (r5, review).
- Two overlapping hollow spheres: their walls are kept, W010 (r5, review).
- A cube embedded in a bigger cube: absorbed, W010; a void across two overlapping cubes: kept,
  with or without a body floating in it; a duplicated body (outwards or inside out): merged.
- `--simplify` larger than the model: exit 1 naming `--simplify` (r5, review).
- Two separate bodies: both kept.
- A closed flat surface: exit 2 (r5).
- `--simplify 0.05` on a dense sphere: fewer triangles, volume within 0.5 %; the reference
  volume is the simplified body's.

**Docs.**
- `docs/ALGORITHMS.md` "Repair and shell normalization".
- `docs/ARCHITECTURE.md` "Load and repair".
- `docs/TROUBLESHOOTING.md`: exit 2, W006, W007, W010, W011.

**Done when.** The tests pass. Commit: `[FEAT] Phase 2: load, repair, shell normalization`.

---

### Phase 3 — Orientation and even grid

**Goal.** A cutting frame and an even grid of cells that each fit U, with as few cells as possible.

**Files.** `grid.py`, `tests/unit/test_grid.py`.

**Tasks.**
1. Usable volume U per §6.1. In peg mode, also subtract L_max/2 on every axis, because pegs stick
   out of their cell (ADR-0005).
2. Auto-orient (if on), ADR-0008:
   - Evaluate the 6 assignments of the model's axes to the bed axes, each built as a **proper
     rotation** (det = +1). An odd permutation swaps two axes; it is built as the +90° turn
     about the third axis, which negates one of the swapped axes (r6).
   - Cell count = Π n_i, with n_i from task 4. Keep the lowest count.
   - Ties: the first in this order (`grid.ROTATIONS`, r6). Rows of R are cutting axes:

     | # | Rotation | cutting (X, Y, Z) = input |
     |---|---|---|
     | 1 | identity | (+x, +y, +z) |
     | 2 | 90° about Z | (−y, +x, +z) |
     | 3 | 90° about X | (+x, −z, +y) |
     | 4 | 90° about Y | (+z, +y, −x) |
     | 5 | 120° about (1,1,1) | (+z, +x, +y) |
     | 6 | 240° about (1,1,1) | (+y, +z, +x) |

     The model as it is first, then the quarter turn that keeps its Z up, then the other
     quarter turns, then the turns about the diagonal.
   - Assert det(R) = +1.
3. Cutting frame: rotate, then translate the bounding-box minimum to the origin. Store the 4×4
   input → cutting transform.
4. Even grid: `n_i = max(1, ceil(extent_i / U_i − 1e-9))`, with planes at `k · extent_i / n_i` for
   k = 1 … n_i − 1. Even spacing gives pieces of similar size, instead of filling one bed and
   leaving a sliver. The 1e-9 is `config.GRID_TOLERANCE`, a relative slack.
5. Cells and their bounds; assert every cell ≤ U_i · (1 + 1e-9). The bound is relative, like the
   slack in task 4, and evaluated as `cell / U_i − 1e-9 ≤ 1`, task 4's own expression (r6).
6. If n = 1 on every axis: W012. The pipeline continues with one piece (no faces, connectors or
   labels) and exits 0.
7. `--dry-run` prints the rotation, extents, U, cell counts, plane offsets and number of cells,
   on stdout (r6).

**Tests.**
- A 500×100×100 box with bed 220³ and margin 5: 3 cells along X, planes at 500/3 and 1000/3 (±1e-6).
- A 460×100×100 box on the default bed (U = 210 × 210 × 240): rotated so the 460 mm side lies
  along Z, giving 2 cells instead of 3.
- All six candidate rotations have det = +1. The chiral fixture keeps its handedness: the sign of
  the triple product of three marked edge vectors doesn't change.
- Hypothesis, over random extents and beds:
  - every cell fits U;
  - each n_i is minimal (n_i − 1 cells wouldn't fit).
- Peg mode: U is reduced by L_max/2 on every axis.
- A model that already fits: one cell and W012.

**Docs.**
- `docs/ALGORITHMS.md` "Orientation and grid".
- `docs/ARCHITECTURE.md` "Frames", with the table from §4.2.
- `docs/GLOSSARY.md`: cell, usable volume, cutting frame.

**Done when.** The tests pass. Commit: `[FEAT] Phase 3: orientation and even grid`.

---

### Phase 4 — Sections, cutting, cut faces, small-piece merge

**Goal.** Watertight pieces with stable IDs, and one cut face per contact region between two pieces,
computed from a single source of truth.

**Files.** `geometry.py` (section helpers), `cutting.py`, `tests/unit/test_sections.py`,
`tests/integration/test_cutting.py`.

**Tasks.**
1. `geometry.cut_region(body, plane, eps)` (ADR-0002):
   - Transform to plane-local coordinates.
   - Slice at `offset − ε` and `offset + ε`, and intersect the two slices with `^`.
   - Convert to shapely polygons, one per `CrossSection.decompose()` component: the contour with
     positive area is the exterior, the negative ones are holes.

   A single `slice(offset)` is one-sided when a model face lies exactly on the plane. At plan time,
   a plate on a column sliced at the step returned the plate (1600 mm²) instead of the 100 mm²
   contact. The intersection is correct in both step directions. This removes the need for any
   "keep planes away from coplanar faces" rule.
2. `geometry.clip_to_cells(polygons, axis, cell_a, cell_b)`: clip to the rectangle that two
   adjacent cells share in the plane.
3. Split the normalized body: X planes first, then Y planes on each slab, then Z planes. Cut each
   side by difference, the body minus a box covering the other side (`geometry.split_at`):
   `split_by_plane`, `trim_by_plane` and intersections leave a zero-thickness flap where a model
   face lies on the plane (r7). Drop empty results.
4. Bodies:
   - Split each cell into bodies, each an outer shell minus the voids it holds
     (`geometry.bodies`), and drop bodies under 1e-6 mm³. `decompose()` alone returns a void
     as an inside-out shell of its own; dropping it would fill the void (r7).
   - Order the rest by (bbox min z, min y, min x, larger volume first) and assign IDs per §4.3.
5. Cut faces. For every plane and every pair of cells adjacent across it:
   1. region = `clip_to_cells(cut_region(normalized body, plane))`, split into connected polygons.
   2. For each polygon, take p = `polylabel(polygon)`.
   3. The neg piece is the piece of the neg cell whose section at `offset − 0.05` contains p; the
      pos piece is the one whose section at `offset + 0.05` contains p. Cache piece sections per
      plane.
   4. If no piece matches on a side, retry with 0.005 mm. If none matches still, skip the polygon
      and log it at debug level: it's too thin for a connector anyway.
   5. Create one `CutFace` per (polygon, neg piece, pos piece) with IDs per §4.3.
6. Small-piece merge (ADR-0012), for each piece S with volume < V_small, in piece order (cell,
   then suffix; r7). Merge S into its neighbour P only if all of these hold:
   - S shares cut faces with **exactly one** piece P. With two or more, emit W004. With none, S is a
     separate body: no merge (W008, below).
   - S hasn't absorbed a piece itself: it would then span two cells, and the guard below is
     defined for one (W004; r7).
   - The union's bounding box fits U (peg-adjusted).
   - **Footprint guard:** no other piece in S's cell overlaps S's projection along the axis of the
     shared faces, grown by `MERGE_MARGIN` = 0.05 mm (r7). Compute the projections with
     `project()` after rotating that axis to Z, and treat an overlap area > 1e-6 mm² as an
     overlap. This guard keeps every assembly step a single straight motion; the proof sketch
     belongs in `docs/ALGORITHMS.md`.

   If they do: cut P again from the normalized body, by difference, as P's cell joined to a prism
   over S's grown projection kept within S's cell, so the plane is never cut there and nothing is
   glued (a union P ∪ S keeps a face inside where the plane passes through mesh vertices; r7).
   The merged piece is the body that holds S; if its volume isn't P + S within 1e-6, emit W004. Otherwise drop the faces between them, record S in
   `merged_from`, emit W005. When a condition fails, emit W004. After the merges, every piece
   without a cut face gets W008, unless the grid is a single cell (W012 already says nothing
   was cut; r7).
7. Validation: every piece has status `NoError`, and the piece volumes add up to the reference
   volume within 0.1 % (I3).

**Tests.**
- Sections:
  - a ring gives one polygon with one hole;
  - a U shape gives one polygon;
  - two separate squares give two polygons;
  - both step fixtures (`plinth_step`, `overhang_step`) give a 100 mm² contact region.
- A 200 mm cube with bed 120³ (U = 110) gives 8 pieces and 12 cut faces, each 100×100 mm (area
  10 000 within 1e-6 relative).
- A torus cut through its hole by one plane gives 2 pieces and 2 cut faces on that plane.
- Hollow sphere (r = 150, 2 mm shell) with bed `320 320 220` (U = 310 × 310 × 210): one Z cut,
  2 pieces. The face is a ring with one hole, area π(150² − 148²) ≈ 1872 mm² within 2 %.
- A cell with two bodies: suffixes `-a` and `-b` in the documented order.
- `knob` fixture: the knob is merged (W005). With a second body in the knob's cell that overlaps its
  footprint, it isn't (W004).
- Hypothesis: the piece volumes add up to the reference volume on random unions of boxes and spheres.
- Determinism: the same input twice gives identical IDs, volumes and faces.

**Docs.**
- `docs/ALGORITHMS.md`: "Sections and cut faces" and "Small-piece merge" (with the proof sketch).
- `docs/GLOSSARY.md`: body, piece, cut face, region.

**Done when.** The tests pass. Commit:
`[FEAT] Phase 4: sections, cutting, cut faces, small-piece merge`.

---

### Phase 5 — Connector placement

**Goal.** For every cut face, a deterministic set of connector positions and pin lengths that keeps at
least `min_wall` of material around every hole and between any two holes of the same piece.

**Files.** `connectors.py`, `tests/unit/test_placement.py`, `tests/integration/test_connectors.py`.

**Tasks** (every value from §6).
1. `safe_region(region, cfg) = region.buffer(−inset)`, with inset = w + r_h + ch_h. If it's empty,
   emit W001 for the face (unless the connector type is `none`).
2. Candidates: the grid points at multiples of g in (u, v) that lie inside the safe region, plus
   the polylabel point of each part of the safe region. Sort them by (u, v).
3. Connector count k:
   - 0 if there are no candidates;
   - 1 if no two candidates are at least s_min apart (check on the convex hull of the candidates);
   - otherwise `clamp(floor(area(safe) / A), 2, k_max)`.

   **Two connectors whenever two fit:** a single round pin lets the parts rotate.
4. Trial order:
   - k = 1: polylabel of the largest part first, then the other candidates by decreasing distance
     to the safe boundary.
   - k ≥ 2: the farthest-apart pair first (the hull diameter), then farthest-point sampling:
     the untried candidate farthest from the connectors accepted on this face, or from the
     tried candidates while none is accepted (r8).
   - Ties go to the lexicographic order of (u, v).
   - Skip a candidate closer than s_min to a connector already accepted on this face.
   - At most T_max candidates per face go through the 3D checks (r8).
5. 3D checks for each candidate, on the sides that need a hole (both for dowels, the pos side only
   for pegs):
   1. **Depth.** Cast 9 rays per side with `geometry.ray_depth`: one on the axis and 8 on a circle of
      radius r_h + w.
      - Each ray starts ε_ray inside the piece, points along the inward normal, and is
        h(L_max) + w + 1 mm long.
      - Available depth = the smallest first-hit depth, measured from the face (r8), minus w,
        or "enough" if no ray hits.
      - **Never start a ray exactly on the face.** Whether the face itself is reported depends on
        the library: trimesh reports it at distance 0, which would reject every candidate, while
        manifold3d didn't at plan time. Starting inside the piece makes this irrelevant.
   2. **Pin length.** Take the longest standard length L with h(L) ≤ the available depth on every
      side that needs a hole. If none fits, reject the candidate.
   3. **Exact containment.** On each side that needs a hole, take a cylinder of radius r_h + w
      running from the face to depth h(L) + w. Subtract the piece from it; the remainder's volume
      must be ≤ 1e-6 × the cylinder's volume.
      - If not, try the next shorter L; if none passes, reject the candidate.
      - This catches pieces that narrow behind the face, which the rays can miss.
      - Cost at plan time: 14 ms per check on a 524k-triangle piece.
   4. **Collisions.** `min_gap(this hole tool, every hole tool already accepted in the same piece)`
      must be ≥ w (search length w + 1), up to `LENGTH_TOLERANCE`. Otherwise reject the
      candidate. The hole tool is `geometry.hole_solid`, mouth chamfer included, the shape
      Phase 7 cuts (r8).
      - This catches holes on perpendicular faces near a shared edge. In the review's 2×2×2 cube
        simulation, their axes crossed at 0 mm.
      - It also catches coaxial holes drilled from opposite faces of a thin piece.
   5. **Accept.** Record the connector with its L and the hole depth h(L) on each side (0 on the
      peg side).
6. Process faces in face order (`cutting.cut_faces`; not ID string order, r8) and accept
   connectors in trial order, so the result is deterministic.
7. Diagnostics:
   - W002 when L < L_max;
   - W009 when a face ends up with exactly one connector;
   - W001 when it ends up with none.

**Tests.**
- A 100×100 face (200×100×100 box cut once) with d = 5: 4 connectors, all inside the safe region,
  pairwise distances ≥ 15 mm, the same positions on every run.
- A 40×40 face: the safe region is 29.8 × 29.8 mm (888 mm² < A), yet it gets **2** connectors.
- The hollow-sphere ring: no connector, W001.
- A U-shaped face: connectors in both arms.
- `wedge` fixture, where a side wall comes within r_h + w of the hole although the axis ray is
  long: the connector is shortened or rejected.
- Material behind the face:
  - 12 mm: L = 18, with W002 (available depth 10; h(20) = 10.5 is too deep, h(18) = 9.5 fits);
  - 6 mm: rejected, with W001.
- The 2×2×2 cube (bed 120³): in every piece, every pair of hole tools has `min_gap` ≥ w.
- 45 mm cube with bed 30³, giving 15 mm pieces: no piece contains intersecting holes, and faces
  without room get W001.
- `--connector none`: no connectors and no W001.

**Docs.**
- `docs/ALGORITHMS.md` "Connector placement": safe region, count rule, trial order, the four 3D
  checks, standard lengths.
- `docs/GLOSSARY.md`: safe region, standard length, axial play.
- `docs/TROUBLESHOOTING.md`: W001, W002, W009.

**Done when.** The tests pass. Commit: `[FEAT] Phase 5: connector placement`.

---

### Phase 6 — Plane nudging

**Goal.** Move each plane within a small window so it avoids thin features and faces with no room for
a connector, without breaking the bed fit and without moving planes for no gain.

**Files.** `grid.py` (nudging), `tests/unit/test_nudge.py`, `tests/integration/test_nudge.py`.

**Tasks.**
1. For each plane, in axis order X, Y, Z and then by increasing offset:
   - Its slack is how far it can move while both neighbouring cells still fit U and it stays
     strictly between its neighbouring planes (or 0 and the extent; r9).
   - window = min(W_n, slack).
   - Candidate shifts: δ ∈ {0, ±δ_n, ±2δ_n, …} within the window.
2. Score each candidate with a tuple compared lexicographically (lower is better). The cut regions
   are computed after clipping to cell pairs, exactly as in Phase 4.
   - **First:** the number of cut regions whose safe region is empty.
   - **Second:** the number of tiny islands (regions with area < island).
   - **Third:** |δ|.
   - **Fourth:** δ itself.

   The last two make ties deterministic and keep a plane where it is when moving gains nothing.
3. Planes are processed one after another; each move updates its neighbours' slack.
4. Assert every cell still fits U. `nudge_window = 0` disables nudging.
5. There is deliberately **no coplanar-vertex rule.** Manifold handles coplanar splits, and
   `cut_region` handles faces lying on the plane (ADR-0002). The earlier rule ("no vertex within
   0.01 mm of the plane") never terminates on dense meshes: a 1M-triangle model has dozens of
   vertices within any such band.

**Tests.**
- The 500 mm box keeps its planes at exactly 500/3 and 1000/3.
- `tall_figure`, with a thin neck inside the window: the plane moves off the neck (fewer tiny islands).
- Hypothesis: every cell still fits U after nudging, and the result doesn't depend on the order in
  which candidates are generated.

**Docs.** `docs/ALGORITHMS.md` "Plane nudging"; ADR-0003.

**Done when.** The tests pass. Commit: `[FEAT] Phase 6: plane nudging`.

---

### Phase 7 — Tool solids, booleans, dowels, calibration kit

**Goal.** Apply every connector feature with one batched boolean per piece, export the pins, and
generate the calibration kit.

**Files.** `tools.py`, `calibrate.py`, `labels.py` (text outlines only, r10), `tests/integration/test_tools.py`,
`tests/integration/test_calibrate.py`; small changes to `config.py`, `geometry.py`, `connectors.py`,
`io.py` and `cli.py` (r10).

**Tasks.**
1. **Hole tool**, one per connector, built in plane-local coordinates and mapped to the world with the
   plane frame:
   - A cylinder of radius r_model (so the polygon flats sit at r_h, §6.2) from h_neg below the
     plane to h_pos above it.
   - A mouth chamfer on each side: a cone from r_h + ch_h at the plane to r_h at ±ch_h.

   **Both sides come from the same axis point** (`connectors.hole_solids`), so the holes line up
   by construction; each piece is cut with its own side, which removes the same volume as one
   shared tool (r10). Each cutter reaches `TOOL_OVERLAP` past the face (r10).
2. **Pegs** (peg mode):
   - The peg is a cylinder of radius d/2, from the plane to L/2 into the pos side, with a tip
     chamfer ch_p. It is unioned with the neg piece, reaching `TOOL_OVERLAP` into it (r10).
   - The pos piece gets the hole tool with depth h(L).
3. **Batching.** Per piece:
   - collect its tools and union them once with `batch_boolean(..., OpType.Add)`;
   - do one subtraction (holes, plus label solids from Phase 8);
   - do one union (pegs).
4. **Pins.**
   - Geometry: a cylinder of radius d/2 with n_seg segments, length L, a chamfer ch_p at both ends,
     and a flat of depth f along its length.
   - Exported lying on the flat: axis along X, flat on z = 0.
   - One file per (d, L), `dowels/dowel_d{d:.1f}_l{L:.1f}.stl`, with the count in the report.
5. **Validation.**
   - Every piece still has status `NoError` and the same number of outer shells (r10).
   - The volume removed from each piece equals the volume of its tools inside it, within 5 %. Phase 5
     guarantees the tools don't overlap.
   - Every piece fits bed − 2·margin (I2, r10).
6. **Calibration kit** (`--calibrate`, no input file; dimensions in §6.3):
   - **The bar.** One hole per clearance in `calibration_clearances`, all h(L_max) deep, in a row
     centred across the bar's width. Each hole's code is engraved on one long side face, under the
     hole.
   - **Two identical bars.** Test a pin in a single hole, then flip one bar onto the other: matching
     holes face each other, so you can also test a full joint.
   - **Outputs:**
     - `calibration/block.stl` (print 2);
     - `calibration/pin_d{d:.1f}_l{L_max:.1f}.stl` (print one per hole);
     - `calibration/README.md`, explaining how to print (holes vertical), how to test, how to read
       the codes, and to pick one step looser if most holes in the real pieces will be horizontal
       (horizontal holes print tighter).

**Tests.**
- A 200×100×100 box cut once, with 2 dowels:
  - each half has 2 holes;
  - the volume removed from each half equals the hole-plus-chamfer volume within 5 %.
- Holes line up: slicing both halves 1 mm from the plane gives hole centres equal within 0.01 mm.
- Peg mode:
  - the pegged piece gains the peg volume and the other piece loses the hole volume (within 2 %);
  - the pegged piece fits bed − 2·margin (r10: a full cell plus its peg is over the peg-adjusted U
    by design; on a 120 mm bed, U = 100 and the pegged piece is 110).
- A pin STL lies flat: its bottom face area is at least 0.9 × flat width × (L − 2·ch_p).
- Shortened pins go to separate files, and the counts add up to the number of connectors.
- Calibration kit:
  - the bar has the §6.3 dimensions and one hole per clearance;
  - the codes are engraved (the volume decreases);
  - the pin count equals the number of clearances;
  - the README exists.

**Docs.**
- `docs/ALGORITHMS.md`: "Tool solids" and "Calibration".
- README: "Calibration workflow" and "Printing the dowels" (flat side down, one copy per count).
- `docs/OUTPUT_FORMAT.md`: `dowels/` and `calibration/`.
- ADR-0005 and ADR-0006.

**Done when.** The tests pass. Commit: `[FEAT] Phase 7: tool solids, dowels, calibration kit`.

---

### Phase 8 — Labels

**Goal.** Engrave each piece's short ID on one of its cut faces, readable from outside the piece and
never touching a connector.

**Files.** `labels.py`, `tests/unit/test_labels.py`, `tests/integration/test_labels.py`; also
`models.py`, `config.py`, `geometry.py`, `tools.py`, `io.py`, `cli.py` and `scripts/api_spike.py`
(r11).

**Tasks.**
1. Text: `X1-Y0-Z2-b` becomes `1-0-2b`.
2. Region on each of the piece's faces: `region.buffer(−w)` minus a disk of radius keep-out around
   every connector of that face, minus every point closer than w to a spot without `t_lab + w` of
   material behind the face, holes counted (r11). Try the faces by decreasing region area (ties:
   face ID) until the text fits (r11).
3. Glyphs:
   - Use `TextPath` with the bundled `DejaVuSans-Bold.ttf`, loaded **by file path** so every
     machine uses the same font. At 4 mm text height the regular weight's strokes are 0.52 mm
     (about one nozzle width) and the bold ones 0.94 mm.
   - Build the solid with `CrossSection(contours, FillRule.EvenOdd)`. The default Positive rule
     erased the glyph "0" entirely at plan time, because TrueType outer contours are clockwise.
4. Layout:
   - The anchor is the point of the largest part of the region that has the polylabel point's
     clearance (within `LABEL_ANCHOR_SLACK`) and is nearest the part's centroid (r11).
   - Binary-search the text height between H_min and H_max (12 iterations), at 0° and 90°, accepting
     a size when `region.contains(text)`.
   - Keep the largest height (0° on ties).
   - If H_min doesn't fit at the anchor, try each part of the region, largest first: its anchor,
     then up to `LABEL_MAX_ANCHORS` grid points by distance to it, keeping the first that fits (r11).
   - If nothing fits on any face: W003, no label.
5. Orientation: faces of neg pieces are seen from +z (no mirroring), faces of pos pieces from −z
   (mirror in u).
6. Solid: extrude to `labels.depth` into the piece, map it with the plane frame, and add it to the
   piece's subtraction batch (Phase 7). Engraving never collides with the mating piece; embossing
   would.
7. Pieces without cut faces get no label (W008). Labels are never put on exterior surfaces, where
   they would show on the finished model.

**Tests.**
- A labelled piece is still valid, and its volume decreases by text area × depth (within 10 %).
- The label outline doesn't intersect any connector keep-out disk.
- A piece whose only face is 10×10 mm gets no label and W003.
- A label on a pos-side face, viewed from outside, matches the unmirrored text (IoU > 0.95).
- Text with counters (`0`, `8`, `b`) keeps its holes (its area equals the EvenOdd area).
- The bundled font path exists. This fails loudly if a matplotlib release moves it.

**Docs.**
- `docs/ALGORITHMS.md` "Labels".
- README: label format.
- ADR-0009.

**Done when.** The tests pass. Commit: `[FEAT] Phase 8: labels`.

---

### Phase 9 — Assembly order, export, assembly map, preview

**Goal.** Write every output, including assembly instructions a person can actually follow.

**Files.** `assembly.py`, `io.py`, `src/stlsplit/schemas/assembly.schema.json`,
`tests/unit/test_assembly_order.py`, `tests/integration/test_export.py`.

**Tasks.**
1. **Assembly order** (ADR-0004). Three stages: X joins, then Y joins, then Z joins.
   - **Within a stage (r12):** take that axis' planes in increasing order. On one plane, take the
     sub-assemblies its faces connect apart one at a time, each leaving the others connected and
     having a clear path away from the plane, and join them in the reverse order. A bounded
     search with backtracking looks for such an order. Each join covers *all* faces between the
     two sub-assemblies.
   - **Motion:** the sub-assembly with more pieces stays still and the other slides along ±axis.
     On a tie, the one holding the first piece in piece order stays (r12).
   - **Why this works:** a sub-assembly not yet joined on a plane lies on one side of it, so every
     join is one straight motion parallel to all its pins.
   - **No clear path:** the step stays in the order, marked `clear_path: false`, with W013 (r12).
   - **Why bottom-up doesn't:** a piece-by-piece order fails. In any 2×2 layer, the last piece
     would have to slide along two perpendicular directions at once.
   - Joins without connectors are listed as "glue only".
   - Groups that are never joined are listed as separate parts.
2. **Pieces.** Export them as binary STL in the cutting frame, not re-centred, so each file fits the
   bed as loaded.
3. **`assembly.json`** follows `assembly.schema.json`, with `schema_version: 1`. It contains:
   - the tool version and the effective settings;
   - the input *file name* (no path);
   - the frame transform and the grid;
   - pieces, faces and connectors (positions in the cutting frame);
   - pin groups;
   - assembly steps and diagnostics.

   Floats are rounded to 6 decimals, and there are no timestamps.
4. **`assembly.md`** contains:
   - a summary;
   - the print list: parts, and dowels with their counts;
   - the assembly steps grouped by stage, with "let the glue set before the next stage";
   - the diagnostics, each naming its section of `docs/TROUBLESHOOTING.md` in plain text: a
     relative link wouldn't resolve from the output folder (r12).
5. **`preview_exploded.glb`**: each piece is moved away from the centre by `preview_spread` × the
   model size per grid step, coloured from a fixed 12-colour palette.
6. **Console summary:** pieces, connectors, dowels to print, diagnostics, output path, and the exit
   code (§4.5).

**Tests.**
- A 2×2×1 split gives 2 X joins in stage 1 and 1 Y join in stage 2. No step mixes axes.
- On synthetic graphs:
  - every connected group is joined exactly once per stage;
  - the order is deterministic.
- Every exported STL reloads watertight and fits the printable volume; without pegs it also fits U
  (r10, r12).
- `assembly.json` validates against the schema and has `schema_version`.
- No output contains the temporary directory's absolute path or an ISO timestamp.
- Two runs in separate processes give byte-identical output directories.

**Docs.**
- `docs/OUTPUT_FORMAT.md` complete.
- README: "Output folder" and "Assembling".
- `docs/ARCHITECTURE.md` "Outputs".
- ADR-0004.

**Done when.** The tests pass. Commit: `[FEAT] Phase 9: assembly order, export, preview`.

---

### Phase 10 — Robustness and performance

**Goal.** Known, documented behaviour on large and difficult inputs, and measured performance.

**Files.** Whatever the measurements point to; `tests/e2e/test_robustness.py`,
`tests/e2e/test_performance.py`.

**Tasks.**
1. Stage timings in the `-v` log.
2. Performance on a 1–2M-triangle model split into about 8 pieces: use a synthetic model (refined
   sphere unions), plus a real scan if one is available. The target is under 2 minutes on a laptop.
   Record the machine and timings in the README.
   - **Plan-time reference numbers:**
     - split of a 524k-triangle mesh: 0.22 s;
     - one containment check: 14 ms;
     - one ray cast: 0.01 ms.
   - **Measure first, then fix only the stage that dominates:**
     - check that tool booleans are batched;
     - suggest `--simplify`;
     - process pieces in parallel with `ProcessPoolExecutor`, passing mesh arrays, since Manifold
       objects can't be pickled.

     manifold3d may already use several threads, so measure before parallelizing.
3. Robustness matrix:
   - 100+ bodies;
   - every face too thin for a connector (W001 everywhere, exit 3);
   - a model that already fits;
   - very thin features;
   - extreme scales.
4. Every early exit prints one line, with no traceback unless `-v`. Exit 4 asks for a bug report with
   the `-v` output.

**Tests.**
- The robustness cases as e2e tests.
- The performance test marked `slow`: not in the default run, run weekly in CI.

**Docs.**
- README: performance section with the measured numbers.
- `docs/TROUBLESHOOTING.md`: common problems.

**Done when.** The tests pass and the timings are recorded. Commit:
`[ADD] Phase 10: robustness and performance`.

---

### Phase 11 — End-to-end suite, real models, docs completion, v1.0 and handover

**Goal.** Prove the global properties on every fixture, finish the documentation, release v1.0.0, and
hand over.

**Files.** `tests/e2e/`, `tests/fixtures/real/`, `tests/fixtures/README.md`, every document.

**Tasks.**
1. Complete the fixture catalogue (Appendix D). Add 2–3 small CC0 or CC-BY real models in
   `tests/fixtures/real/`, credited in `tests/fixtures/README.md`.
2. End-to-end properties: run the CLI in a subprocess on every fixture and check all of these.
   1. Every piece is watertight.
   2. Every piece fits U (peg-adjusted).
   3. The piece volumes + the volume removed by tools − the peg volumes = the reference volume, within
      0.5 %.
   4. Holes line up across every cut face.
   5. No two holes in the same piece are closer than w.
   6. Two runs give byte-identical output.
   7. The exit code matches the one listed for the fixture.
3. Enforce coverage ≥ 85 % in CI.
4. Documentation:
   - every file in §8.2 complete, with the drift tests green;
   - the ADRs current;
   - `docs/ONBOARDING.md` checked by following it from a fresh clone.
5. Manual test print: a 2–4 piece model assembled with the generated dowels. Record the printer, the
   clearance chosen with the calibration kit and the result in the README.
6. `CHANGELOG.md` 1.0.0 and the tag `v1.0.0`.
7. Handover checklist, written in `docs/ONBOARDING.md`. Someone other than the author follows it:
   1. fresh clone;
   2. `pip install -e ".[dev]"`;
   3. `python scripts/check.py`;
   4. `python scripts/api_spike.py`;
   5. the README quick start;
   6. read ARCHITECTURE and the ADR index.
8. Optional: a project skill `.claude/skills/stlsplit-change/SKILL.md` that walks Claude Code through
   CONTRIBUTING's definition of done and recipes. Skills load on demand, so `CLAUDE.md` stays short.

**Done when.** The definition of done (§14) is met. Commit:
`[FEAT] Phase 11: end-to-end suite, docs, v1.0.0`.

---

## 11. v2 ideas (out of scope)

Most of these plug into extension points v1 already has (the nudge score, the connector-type recipe,
the diagnostics). The last one doesn't, on purpose.

- **Smarter cut placement:** avoid faces, eyes and fingers; prefer flat regions; minimise visible
  seams. New criteria plug into the score tuple of Phase 6.
- **Thin-shell joints** for faces where round pins don't fit (helmets, vases): an internal
  tongue-and-groove lip that follows the shell wall, or a sliding wavy joint. Today these faces get
  W001.
- **Dovetails and snap-fits:** a new connector type, following the CONTRIBUTING recipe.
- **Hollowing** with a configurable wall thickness and drain holes.
- **Per-piece print orientation:** choose the face each piece is printed on.
- **Asymmetric pins:** use the deeper side when one side is shallow, instead of shortening both.
- **Teardrop holes** for horizontal holes, which print tighter than vertical ones.
- **Non-axis-aligned cuts:** these need a new data model, because the grid indices, the IDs and the
  assembly order all assume axis-aligned planes. Start with an ADR that supersedes ADR-0013. v1 code
  shouldn't be generalized for this in advance.

---

## 12. Key decisions (ADR index)

Phase 0 turns each row into `docs/adr/NNNN-*.md` using Appendix A.

| ADR | Decision | Why |
|---|---|---|
| 0001 | manifold3d for all solid geometry. trimesh only for file I/O, basic repair and the GLB preview. | Guaranteed-manifold booleans, fast native slice, ray cast and min_gap, one geometry kernel. Hand-made booleans are the main source of broken STLs. |
| 0002 | Cut regions are the intersection of the slices at offset ± ε of the normalized input body. | One source of truth for both sides of a face, and correct when a model face lies on the plane. |
| 0003 | Even grid plus a bounded nudge with a lexicographic score. | Predictable, always fits; ties keep planes in place; a global optimiser is a v2 problem. |
| 0004 | Assembly in stages: X rows, then Y layers, then the Z stack (within a plane: r12). | Every join is one straight move along its pins; a move that can't be shown clear gets W013. |
| 0005 | Dowels by default; pegs optional on any face, with U reduced by the protrusion. | Pins printed lying flat are the strongest; pegs either print vertically (weak) or need support. |
| 0006 | Standard pin lengths, symmetric pins, explicit axial play; `--dowel-length` is the exact pin length. | One definition of length, and only a few pin files to print. |
| 0007 | Try the mesh as-is first; sign-aware shell normalization; never `fix_normals(multibody=True)`. | Don't damage valid models; keep voids; fix overlapping shells. |
| 0008 | Auto-orient uses proper rotations only (det = +1). | A permutation matrix for an odd permutation silently mirrors the model. |
| 0009 | Labels engraved on cut faces, bundled DejaVu Sans Bold, EvenOdd fill. | Hidden after assembly; same font everywhere; strokes thick enough to print. |
| 0010 | Deterministic output. | Trivial regression tests and reproducible bug reports. |
| 0011 | argparse CLI; defaults < TOML < explicit CLI options; a `--calibrate` mode; exit codes 0–4. | No dependency, and an unambiguous merge. |
| 0012 | Small pieces are merged only under the footprint guard. | Avoids slivers without breaking the assembly order. |
| 0013 | The grid model is axis-aligned by design. | IDs, nudging and the assembly order depend on it. |
| 0014 | Every hole is verified in 3D: rays, an exact containment check, and min_gap between holes. | The 2D inset alone misses pieces that narrow behind a face and holes that collide inside a piece. |

---

## 13. Pitfalls

| Pitfall | What to do | Where |
|---|---|---|
| Thin walls (hollow models): the safe region is empty | W001, keep going, never crash | Phase 5 |
| Piece-by-piece assembly orders are impossible on any 2×2 layer | Staged sub-assemblies | ADR-0004 |
| Tolerances depend on the printer | `--clearance` plus the calibration kit | Phase 7 |
| A model face lying exactly on a cut plane makes a single slice one-sided | Intersect the slices at ±ε | ADR-0002 |
| A ray starting on a surface hits that surface at distance 0 (trimesh) | Start rays ε_ray inside the piece | Phase 5 |
| `RayHit.distance` is a fraction of the segment | Compute depths from `RayHit.position` | Phase 0 |
| Overlapping shells and internal voids | Sign-aware normalization; never union everything | ADR-0007 |
| `fix_normals(multibody=True)` flips voids outward | Use `multibody=False`, and only when repair is needed | ADR-0007 |
| TrueType glyphs have clockwise outer contours | `FillRule.EvenOdd` | ADR-0009 |
| An odd permutation matrix mirrors the model | Proper rotations only | ADR-0008 |
| Faceted holes eat part of the clearance | Explicit segments and radius compensation | §6.2 |
| Holes on perpendicular faces collide near shared edges | `min_gap` check per piece | ADR-0014 |
| Pegs stick out of their cell | U reduced in peg mode | ADR-0005 |
| Scale mistakes (a model in metres looks 0.2 mm tall) | W006 | Phase 2 |
| trimesh merges vertices on load | Build "soup" fixtures with `process=False` | Phase 2 |
| Arrays returned by manifold3d's `Mesh` are read-only | Copy them before reuse | Phase 0 |
| `trimesh[easy]` pulls in about 20 packages | Depend on trimesh, scipy and networkx explicitly | §2 |
| numpy 2.5, scipy 1.18 and networkx 3.7 need Python 3.12 | Python ≥ 3.12 | §2 |

---

## 14. Definition of done (v1)

- `stlsplit model.stl -o out --bed X Y Z` works on every fixture and real model, with the documented
  exit code.
- `python scripts/check.py` passes locally and in CI (3.12 and 3.13 on Linux, 3.13 on Windows and
  macOS), with coverage ≥ 85 %.
- The end-to-end properties of Phase 11 hold on every fixture.
- Every document in §8.2 is complete, the drift tests are green, the ADR index is current, and someone
  other than the author has followed `docs/ONBOARDING.md` successfully from a fresh clone.
- A real 2–4 piece print has been assembled with the generated dowels, and the result is in the README.
- `CHANGELOG.md` has a 1.0.0 entry and `v1.0.0` is tagged.

---

## Appendix A — ADR template (`docs/adr/0000-template.md`)

```markdown
# ADR-NNNN: <short title>

- **Status:** Proposed | Accepted | Superseded by ADR-XXXX | Deprecated
- **Date:** YYYY-MM-DD
- **Deciders:** <names>
- **Related:** PLAN.md §…, tests …, other ADRs …

## Context
What forces a decision: constraints, facts, measurements.

## Decision
What we do, stated precisely enough that a reader can check the code against it.

## Options considered
### Option A — <name>
Pros, cons, complexity, risk.
### Option B — <name>
Pros, cons, complexity, risk.

## Consequences
- Easier: …
- Harder: …
- Revisit when: … (the event that should make us reconsider)
```

## Appendix B — `CLAUDE.md` template

Keep it short. Claude Code loads `CLAUDE.md` at the start of every session, and a long file makes
it ignore rules. Point to documents instead of importing them: an imported file costs the same
context as if it were pasted in.

```markdown
# stlsplit — notes for Claude Code

CLI that splits an oversized STL into printable, connectable parts. Python ≥ 3.12, src layout.

## Commands
- Dev install: `pip install -e ".[dev]"`
- All checks (run before every commit): `python scripts/check.py`
- Without e2e tests: `python scripts/check.py --fast`
- One test: `pytest -q tests/unit/test_nudge.py -k slack`
- After a dependency upgrade: `python scripts/api_spike.py`

## Where to look
- Plan, progress and the phase protocol: PLAN.md (read §0–§9 and the current phase only)
- Module map, frames, invariants: docs/ARCHITECTURE.md
- Why things are the way they are: docs/adr/
- Verified library quirks: docs/LIBRARY_NOTES.md

## Rules
- Solid geometry goes through manifold3d; trimesh only for I/O, repair and the GLB preview.
- Units are mm; pipeline geometry is in the cutting frame.
- Numbers come from config.py / config.derived(); no magic numbers.
- No randomness, timestamps or absolute paths in outputs.
- Code, tests and docs of a change go in the same commit (CONTRIBUTING.md, "Definition of done").
- Commit messages: `[TAG] summary`, TAG one of [INIT] [FEAT] [ADD] [FIX] [DEL].
- IMPORTANT: never weaken, skip or delete a test to make it pass. Ask instead.
- When compacting, keep the list of modified files and the test commands.
```

## Appendix C — Phase completion checklist

Copy this into the pull request description (or the final message of the session) for every phase.

- [ ] The phase's tests were written first, and they now pass.
- [ ] `python scripts/check.py` output is shown.
- [ ] Every document listed in the phase is updated; drift tests pass.
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry.
- [ ] An ADR was added or superseded if a decision changed.
- [ ] `docs/LIBRARY_NOTES.md` is updated if a library behaved differently than recorded.
- [ ] The review subagent ran against this phase, and its correctness gaps are fixed.
- [ ] The progress table in §0 is updated (status, commit, notes).
- [ ] The commit message follows §9.3.

## Appendix D — Test fixture catalogue

Fixtures are functions in `tests/conftest.py` that return a `Manifold`, plus a helper that writes one
to an STL file in `tmp_path`. Only the real models in `tests/fixtures/real/` are committed.

| Fixture | Construction | Used for |
|---|---|---|
| `cube(size)` | `Manifold.cube` | Splits, connectors |
| `long_box` | 500 × 100 × 100 box | Grid |
| `cylinder` | `Manifold.cylinder` | Round cut faces |
| `torus` | `Manifold.revolve` of a circle | Two regions on one plane |
| `hollow_sphere` | sphere r = 150 minus sphere r = 148 | Void preservation, thin ring, W001 |
| `two_bodies` | Two cubes 10 mm apart | `decompose`, suffixes |
| `overlapping_shells` | Two 20 mm cubes offset by 10 mm, concatenated with trimesh | Shell union (12 000 mm³), W010 |
| `inverted_body` | A cube with reversed winding next to a normal cube | W011 |
| `soup_cube` | Unmerged triangles built with `process=False`, written to STL | Merge on load |
| `missing_face_cube` | Cube without two triangles | `fill_holes`, W007 |
| `capless_sphere` | Sphere without a cap | Exit 2 |
| `edge_touching_cubes` | Two cubes sharing one edge | Accepted as is by manifold3d: two bodies (r5) |
| `finned_cube` | Cube with a stray triangle on one edge | Non-manifold input, exit 2, `--deep-repair` (r5) |
| `inside_out_cube` | One cube with reversed winding | Single inverted shell, W011 (r5) |
| `ball_in_hollow_sphere` | `hollow_sphere` plus a ball r = 100 in its void | Nesting (r5) |
| `void_in_ball_in_hollow_sphere` | `ball_in_hollow_sphere` plus a void r = 50 in the ball | Two levels of nesting (r5) |
| `inside_out_hollow_sphere` | `hollow_sphere` with every triangle reversed | Whole model inside out (r5) |
| `hollow_sphere_with_a_flipped_triangle` | `hollow_sphere` with the reference triangle of one shell reversed | Majority orientation in basic repair (r5) |
| `overlapping_hollow_spheres` | Two `hollow_sphere`s 200 mm apart | Overlapping hollow parts keep their walls (r5) |
| `embedded_cube` | A 5 mm cube inside a 20 mm cube, both facing out | Redundant part, W010 (r5) |
| `void_across_two_cubes(body_inside)` | Two overlapping cubes and a void inside their union only, optionally with a small cube in the void | Void spanning solids (r5) |
| `duplicated_cube(inside_out)` | The same cube twice | Identical shells merged, W010 (r5) |
| `flat_sheet` | A square, its two triangles facing both ways | Closed but no volume, exit 2 (r5) |
| `dense_sphere` | `Manifold.sphere(20, 256)` | `--simplify` |
| `tall_figure(height, necks)` | 60 × 60 boxes stacked along Z, joined by 6 × 6 necks; by default 300 mm tall with one neck from z = 148 to 153 (r9) | Nudging |
| `plinth_step` | 10 × 10 × 20 box on a 40 × 40 × 10 plinth | Contact region at a step |
| `overhang_step` | 40 × 40 × 10 plate on a 10 × 10 × 10 column | Contact region, other step direction |
| `knob` | Box with a small knob crossing a plane | Small-piece merge |
| `u_shape` | U-shaped extrusion, 10 mm arms | One polygon per U-shaped region |
| `wide_u_shape` | U-shaped extrusion, 20 mm arms on a 10 mm base, 60 mm deep (r8) | Connectors in both arms |
| `wedge` | 40 mm block whose top falls 0.4 mm per mm behind its cut face at x = 40 | Depth and containment checks |
| `chiral_l` | Corner cube with arms of 3, 2 and 1 cubes along X, Y and Z (a flat L would be its own mirror image) | No mirroring (r6) |
| `crossed_loop` | One closed loop crossing x = 25 four times, two bodies on each side, one plate in the other's way along X | Assembly order within a plane (r12) |
| `hooked_strips` | Three strips on each side of x = 10, woven into one solid, a hook of the third behind the first | The order search must backtrack (r12) |
| `interlocked_bodies` | Two bodies below x = 10, each in the other's way along X, held by a block above | W013, in a split and a dry run (r12) |

## Appendix E — Plan revisions

**r12 — 2026-11-21 (Phase 9).** Found while planning and implementing Phase 9, agreed with the
maintainer:

- **Join rule within a plane** (Phase 9, task 1; ADR-0004). Joining in plain face order can pair
  two sub-assemblies that each hold pieces on both sides of a plane: on a valid loop crossing a
  plane four times, the third join needed +X and −X at once. Sub-assemblies are now taken apart
  one at a time along a clear path, and joined in reverse. The stages don't change.
- **Order search** (task 1). Found by the review: taking off the first clear candidate can strand
  another piece and report a blocked step when a clear order exists. A depth-first search with
  backtracking now looks for one, up to `ASSEMBLY_SEARCH_STATES` states.
- **W013** (§4.5, partial) and `AssemblyStep.clear_path` (§5.2): a move that can't be shown clear
  is reported. The check (`geometry.blocks_exit`) is conservative.
- **The dry run plans the order** (§7.1). Found by the review: it exited 0 where the split exited
  3 on W013. Both now check the same solids, pegs on and holes not cut (`tools.with_pegs`).
- **Fit test** (Phase 9). "Fits U (peg-adjusted)" contradicted r10: a pegged piece exceeds U by
  the peg, by design. Exported pieces are tested against the printable volume, and against U
  without pegs.
- **Troubleshooting references** (task 4). A relative link breaks in the user's output folder and
  the project has no public URL, so `assembly.md` names the section in plain text.
- **`assembly` imports `geometry` and `errors`** (§3.1), for connector positions, the clear-path
  check and W013; no cycle.
- **`label_font` in `assembly.json`** (task 3) is a file name only: the setting may be an absolute
  path, which outputs must not contain (§4.4).

**r11 — 2026-11-21 (Phase 8).** Found while planning and implementing Phase 8, agreed with the
maintainer:

- **Material behind a label** (Phase 8, task 2; §6.1). The plan only checked the face in 2D. Where
  a piece is thinner than the engraving, the text went through it, the counters of `0`, `8` and
  `b` came off as separate shells and the run exited 4; the `tall_figure` fixture does this. A
  label now needs `t_lab + w` of material behind it, holes counted, and stays w away from any
  spot that lacks it.
- **Next face before W003** (task 2). Only the largest region was tried, so a piece could get
  W003 with room on a smaller face. Faces are now tried by decreasing area.
- **Centred anchor** (task 4). On a long face every point of the middle line ties for the
  polylabel point, and the library returns one near an end (a 100 × 8 face gets (4, 4)), so the
  text ran off the face and all four pieces of `u_shape` got a false W003. The anchor is now the
  point with that clearance (within `LABEL_ANCHOR_SLACK`) nearest the part's centroid.
- **Fallback positions** (task 4). Found by the review: one anchor in one part still gave false
  W003s. At a T junction the text overflows both arms (a T-beam got no label), and a thin largest
  part hid a smaller one with room. When H_min doesn't fit at the anchor, each part tries up to
  256 grid positions nearest its anchor; a label that fits at the anchor doesn't move.
- **The wall is measured at the flats** (task 2). The round corners of the material guard had
  their vertices at w, so their flats fell up to 29 % short of it. They are now compensated.
- **`label_font` must be able to draw the labels** (§7.5). A file that wasn't a font exited 4, and
  16 of matplotlib's 40 bundled fonts (symbols, Last Resort) exited 0 with unreadable text. Runs
  that draw text now exit 1. `--print-config` and `--no-label` runs don't read the font's content.
- **`labels` imports `connectors`** (§3.1), for `hole_solids`; no cycle.

**r10 — 2026-11-21 (Phase 7).** Found while planning and implementing Phase 7, agreed with the
maintainer:

- **What a pegged piece must fit** (I2, §6.1, the Phase 7 test). The plan said the pegged piece
  fits the peg-adjusted U, which is impossible for a full cell: on a 120 mm bed U is 100, the
  cell is 100 and the pegged piece 110. ADR-0005 reduces U precisely so that a cell plus its peg
  fits the build volume, so cells fit U and final pieces fit `bed − 2·margin`
  (`derived(cfg).printable`).
- **`pin_chamfer < d/2`** (§7.5). A chamfer as wide as the radius can't be built, and the old
  rule accepted one (d = 0.8 with the default 0.5).
- **Calibration codes** (§6.3). Two digits at H_min are 6.75 mm wide, over the 6.4 mm pitch at
  d = 2, and 0.123 and 0.124 both rounded to `12`. Codes now keep up to two decimals, shrink only
  when they wouldn't fit, and clearances that would still read the same are an error.
- **`tools` imports `connectors` and `grid`** (§3.1), for `hole_solids` and `fits`; no cycle.
  Each piece is cut with its own side of the hole rather than one shared tool: same axis point,
  same volume removed.
- **Tools overlap the face by 0.01 mm** (`TOOL_OVERLAP`, §6.1), found by running every fixture
  through the stage. A cut face's vertices can be a few ulps off its plane (29.499999999999993
  for 29.5), so a peg based exactly on the plane stayed a separate shell on one torus piece, with
  the right volume and `NoError`. `tools.check_piece` now also asserts the number of outer shells
  (LIBRARY_NOTES, `manifold.face_float_noise`).
- **`labels.py` starts here** with `text_outline` only, because the kit engraves its codes
  before Phase 8. `calibrate` can't import `io`, so the CLI passes the resolved font path.

Found by the Phase 7 review and agreed with the maintainer. Each refuses a bad input with exit 1
and changes no output format:

- **Pin file names** (§4.3 unchanged). `{L:.1f}` maps 15.25 and 15.15 to `l15.2`, and one pin was
  silently lost. `tools.check_pin_names` now refuses it, in a dry run too. The alternative, more
  decimals in the names, would change an output format.
- **Calibration kit** (§6.3). A bar that doesn't fit the printable volume, an engraving reaching
  a hole and holes that touch are refused: the polygon's vertices reach past the nominal wall,
  and absurd values gave an exit 4 or an empty STL.
- **`diameter` ≥ 0.1** (§7.5): thinner pins collapsed into empty or open meshes.

- **`--force` never deletes a file the run reads** (§7.6), a bug older than this phase:
  `stlsplit out/parts/in.stl -o out --force` deleted its own input with `parts/`. The same held
  for the `--config` file and a custom label font. `io.check_force_keeps` refuses it before any
  work; a dry run deletes nothing, so it isn't refused.

Also from the review, with no new rule: only outer shells are counted (a hole may swallow a void
the containment check tolerates, which made a valid model exit 4), and a pin's polygon has an edge
towards the bed, cut where it is as wide as the round pin's flat, so the flat meets the area
criterion at low segment counts.

**r9 — 2026-11-19 (Phase 6).** Found while planning and implementing Phase 6, agreed with the
maintainer:

- **A plane stays strictly between its neighbours** (task 1). The slack was defined only by
  both neighbouring cells fitting U; with a large `nudge_window` a plane could then pass its
  neighbour, since a cell of negative size passes the fit check. `grid.check_fits` now also
  asserts that the bounds increase strictly.
- **Shared cell pairs**: `grid.cell_pairs` lists the cell pairs across a plane for both
  nudging and `cutting.cut_faces`, so the regions nudging scores are clipped exactly as the
  cut faces are.
- **No polylabel sort when scoring**: `geometry.cut_region` and `geometry.clip_to_cells` take
  `ordered=False`. A score only counts regions, and the sort took 97 % of the nudging time on
  the hollow sphere (4.9 s for 3 planes, 0.11 s without).
- **Scoring stops early**: moves are scored from the smallest |δ| outwards and scoring stops
  at the first (0, 0). The result is the one scoring every move would give.
- **The 2D score has a limit** (recorded, not changed): a plane moved just off a neck leaves
  a thin slab on the neck side, so the face can still get W001 from the 3D checks
  (`tall_figure`: 0.5 mm of the lower box stays with the neck). ADR-0003, "Consequences".
- **`nudge_window / nudge_step` ≤ 100** (§7.5), found by the review: `nudge_step` was only
  checked > 0, so 5e-324 overflowed (exit 4) and 1e-9 ran out of memory. The window is now
  counted in steps, `floor(W_n / δ_n + 1e-9)` (`derived(cfg).nudge_steps`), and validation
  uses the same expression, so a plane has at most 201 positions (`MAX_NUDGE_STEPS`). The
  absolute `|δ| ≤ W_n + 1e-9 mm` it replaces would have let a sub-nanometre window hold
  10⁵ steps of 1e-14 mm.
- **Example test command**: `pytest -q tests/unit/test_nudge.py -k slack` replaces
  `tests/unit/test_grid.py -k nudge`, which selects nothing now that the nudging tests have
  their own file (§9.6, Appendix B, CLAUDE.md, CONTRIBUTING.md).

**r8 — 2026-11-19 (Phase 5).** Found while planning and implementing Phase 5, agreed with the
maintainer:

- **Face order, not face-ID order** (task 6): faces are processed in the order
  `cutting.cut_faces` returns them, as "ID order" for pieces became piece order in r7; sorted
  ID strings put `X10-…` before `X2-…`.
- **Farthest-point sampling after a rejection** (task 4): the next trial is the untried
  candidate farthest from the connectors accepted on the face, or from the tried candidates
  while none is accepted. A rejection is then followed by its neighbours, so the connectors
  stay spread out.
- **At most T_max = 256 candidates per face** go through the 3D checks
  (`MAX_CANDIDATE_TRIALS`). A 210 mm face has 25 000 candidates, and the containment boolean
  costs up to 7 ms on a dense mesh, so a face where everything fails could take minutes; after
  256 it gets W001, whose message says so.
- **`connectors.length` ≤ max(bed X, bed Y)** (§7.5): it had no upper bound (Phase 1 notes),
  so a huge `--dowel-length` made `derived()` build millions of standard lengths. Pins are
  printed lying down, so they must fit the bed plate. The planned bound, by U, would have made
  any margin near half the bed invalid (U = 0.2 mm on a 220 mm bed with a 109.9 mm margin,
  a boundary the margin rule accepts and a test checks).
- **Hole tool with its chamfer** (task 5.4): the collision check uses `geometry.hole_solid`,
  the bore plus the mouth chamfer, the solid Phase 7 cuts: a chamfer near a shared edge takes
  up to ch_h off the wall. Holes are built by revolving their profile: manifold3d evaluates
  booleans lazily, and a cylinder-plus-cone union cost 3 ms at its first query, against
  0.14 ms (spike check `manifold.revolve_hole`).
- **Float noise in `min_gap`**: two holes exactly 2 mm apart give 1.999999999999993, so the
  gap is compared to w − `LENGTH_TOLERANCE`. Two shortcuts give the same answer faster: bounding
  boxes w apart mean far enough, and an axis meeting the other hole (a ray cast) means they
  cross; `min_gap` costs 2 ms on crossing solids.
- **Depths are measured from the face** (task 5.1): the ray starts ε_ray inside, and that
  offset is added back, so 12 mm behind the face gives the available depth 10 of the tests.
- **New §6.1 values:** r_probe = r_h + w (4.7) and the ray length h(L_max) + w + 1 (13.5) are
  in `derived()`; the 8 circle rays, the 1 mm margins of the rays and of the `min_gap`
  search, and T_max are named constants.
- **W002 once per face**, listing its shortened connectors and their lengths, rather than once
  per pin.
- **Fixtures:** `u_shape`'s 10 mm arms have no room for a connector (inset 5.1 on each side),
  so "connectors in both arms" uses `wide_u_shape` (20 mm arms); `wedge` is specified in
  Appendix D.
- **The CLI runs the placement** after the cutting; the dry run lists every connector and the
  pins by diameter and length (§7.1).

**r7 — 2026-11-19 (Phase 4).** Found while planning and implementing Phase 4, agreed with the
maintainer:

- **A merged piece is cut, never glued.** `P ← P ∪ S` leaves a face inside the merged piece
  whenever the plane passes through existing mesh vertices: 100 mm² in a box with a vertex
  ring on the plane, 28–117 mm² for a rounded knob cut through its equator, still `NoError`
  with the exact volume, so nothing noticed. The merged piece is now cut again from the
  normalized body: the body trimmed to the cells involved, intersected with P's cell joined to
  a prism over S's shadow grown by `MERGE_MARGIN` (0.05 mm). Inside the prism the plane is
  never cut. If no resulting body has the volume P + S within `MERGE_VOLUME_TOLERANCE`
  (1e-6), the merge is refused (W004). Spike check `manifold.union_of_split_halves`.
- **The footprint guard uses the grown shadow** (`MERGE_MARGIN`), the footprint the prism
  cuts with. Otherwise a piece closer than 0.05 mm to S's shadow passed the guard and the
  prism took a sliver of it along (0.76 mm³, under the volume tolerance), so two pieces would
  overlap.
- **Bodies keep their voids.** `decompose()` returns a void as an inside-out shell of its own,
  so task 4 as written ("drop bodies under 1e-6 mm³") deleted it and filled the void; a box
  with a bubble away from the planes then failed I3 (exit 4). A body is now an outer shell
  minus the voids it holds (`geometry.bodies`). `geometry.reverse_winding` goes through
  `Mesh64` so the voids of split pieces, whose vertices are doubles, are reversed exactly
  (spike check `manifold.decompose_void_shells`).
- **`cutting` imports `grid`** (§3.1) for `cell_indices`, `cell_bounds` and `fits`: the fit
  check of a merged piece uses the count's arithmetic, as r6 asks.
- **Merge order and chains:** "ID order" is piece order (cell, then suffix), not string order
  (`X10-…` sorts before `X2-…`). A piece that has absorbed a small piece is never merged
  itself (W004): it spans two cells, and the guard is defined for one. The two small halves of
  a tiny body still end as one piece: the first merges into the second, which has no cut face
  left (W008).
- **W008 for every piece without a cut face**, not only small ones (§4.5 describes it that
  way, and Phases 5 and 8 skip those pieces), except when the grid is a single cell: W012
  already says nothing was cut.
- **Suffixes after `-z`** continue `-aa`, `-ab`, … (§4.3), so a cell with more than 26 bodies
  still gets distinct IDs. Remaining ties in the body order keep `decompose()` order, which is
  deterministic.
- **`clip_to_cells` takes the plane axis** (task 2), and drops clipped parts of 1e-6 mm² or
  less (`config.AREA_TOLERANCE`, also the footprint guard's overlap threshold).
- **The CLI runs the cutting stage** after the grid, and the dry run lists the pieces and cut
  faces (§7.1).
- **Found by the Phase 4 review:**
  - **Cuts by difference.** `split_by_plane` (task 3), `trim_by_plane` and intersections keep a
    model face lying exactly on the plane as a zero-thickness two-sided sheet on the kept side.
    A column on a plinth cut at the step had 4000 mm² of surface instead of 1000 and a 40 × 40
    bounding box and shadow. That joined two columns standing on the plinth into one piece,
    sorted suffixes by the wrong bounding box, and made a 180 mm³ nub on a plate fail the
    footprint guard (W004 instead of W005) through the even grid itself. Each side is now cut as
    the body minus a box covering the other side (`geometry.split_at`, `geometry.clip`); task 1's
    "no rule keeping planes away from model faces" holds again. Spike check
    `manifold.coplanar_cuts`; hypothesis property on boxes aligned with the planes
    (`test_cutting_adds_no_surface_but_the_cut_faces`).
  - **The merged body is the one holding S**, chosen by its overlap with S, not by volume alone:
    with a second body of the same volume in P's cell, the merge took a copy of that body and
    P ∪ S disappeared, with I3 still satisfied.
  - **Each prism stays in its own cell.** A piece absorbing small pieces across two planes
    clipped the body to their hull, and a grown prism reached into a neighbouring cell the guard
    doesn't check: two pieces overlapped by 0.0072 mm³, under the volume tolerance.

**r6 — 2026-11-19 (Phase 3).** Found while planning Phase 3, agreed with the maintainer:

- **Cell-fit check:** task 4's slack is relative (`ceil(extent / U − 1e-9)`), so a cell can be
  up to `U · (1 + 1e-9)`: 2.1e-7 mm over U = 210. Task 5's absolute `cell ≤ U + 1e-9` would
  then fail with exit 4 on a valid model, e.g. 210.0000001 mm (a vertex a hair below zero, as
  CAD exports often have). The check is now relative, `cell ≤ U · (1 + GRID_TOLERANCE)`, with
  one constant `config.GRID_TOLERANCE = 1e-9`. With the formula as written, n is also
  minimal: n − 1 cells would each be larger than U.
- **Fit check in the count's arithmetic (Phase 3 review):** `size <= U * (1 + tol)` and
  `ceil(size / U − tol)` round differently for one float at the edge, so a 100 × 100 × 230 box
  with its bottom 2.3e-7 mm below zero still exited 4 in peg mode (one cell on U = 230, then
  "over U"). The check is now `size / U − tol ≤ 1` (`grid.fits`), the count's own expression,
  and a hypothesis property probes extents within 64 floats of `n · U · (1 + tol)`. The §4.1
  rounding is the named constant `config.OUTPUT_DECIMALS`.
- **Odd axis orders:** ADR-0008 leaves the exact construction to Phase 3, which only said
  "negate one axis". The six rotations and their tie-break order are now listed in Phase 3,
  task 2, and in `grid.ROTATIONS`.
- **`Orientation` in `models`:** the input → cutting transform needs a home that `assembly`
  (Phase 9, which may import only `models` and `config`) can read, so §5.2 gains the
  `Orientation` dataclass.
- **Dry-run output on stdout:** the plan goes to stdout, the log to stderr (§7.1), so `-q`
  doesn't hide the plan and it can be redirected alone.
- **`chiral_l` fixture:** a flat L-shaped polycube is its own mirror image through its
  mid-plane, so it can't detect mirroring; the fixture is a corner cube with arms of three
  different lengths (Appendix D).
- **Hypothesis profile:** `tests/conftest.py` registers a `ci` profile with
  `derandomize=True`, loaded when the `CI` environment variable is set (§4.4, rule 1); these
  are the first hypothesis tests.

**r5 — 2026-11-19 (Phase 2).** Found while planning and implementing Phase 2, agreed with the
maintainer:

- **Shell normalization ran too rarely:** a model inside-out as a whole is one component with
  a negative volume (manifold3d accepts it: `NoError`, −1000 mm³ for a cube), so "only when
  `decompose()` returns more than one component" let it through and broke I1. Normalization
  now also runs for a single negative component, which is flipped (W011).
- **A body inside a void was deleted:** subtracting a void also removed a ball loose inside it
  (a ball r = 100 in the hollow sphere came out at 554 829 mm³ instead of 4 719 966) and
  raised a false W010. First fixed for one level of nesting, then superseded by the rewrite
  below.
- **Shell normalization rewritten after the Phase 2 review.** The sign-only classification
  still gave wrong volumes with exit 0: a hollow sphere inside out as a whole came out solid
  (14.06M mm³ instead of 554 829), and two overlapping hollow spheres lost their walls where
  each crosses the other's void (927 978 mm³ instead of 1 106 891), because every void was
  subtracted from the union of every solid. Now each shell's role comes from its orientation
  relative to the smallest shell containing it, and a void is subtracted only from that
  shell. Nesting works at any depth. Still sign-aware, as ADR-0007 decided.
- **Basic repair keeps each shell's majority orientation:** trimesh's `fix_winding` (inside
  `fix_normals`) orients each shell like one reference triangle; with that triangle reversed
  in a hollow sphere's void, it reversed the other 2047 and the void was filled. A shell where
  more than half the faces changed is reversed back (spike check
  `trimesh.fix_winding_reference_face`).
- **W010 wording:** comparing the final volume with the sum of the positive volumes would flag
  every hollow model; the check compares the union of the solid pieces with the sum of their
  volumes.
- **`--simplify` erasing the model** exits 1 naming the option, instead of exit 2 blaming the
  mesh (found by the review).
- **Reference volume:** measured after `--simplify`, not just after normalization, since the
  simplified body is the one cut (simplify may move the volume by up to 0.5 %, I3 allows
  0.1 %).
- **Edge-touching cubes aren't a repair case:** manifold3d accepts two cubes sharing one edge
  as is (the four half-edges pair up: `NoError`, two shells, 2000 mm³), so "exit 2 without
  `--deep-repair`" couldn't hold. The `--deep-repair` tests use `finned_cube` (a stray
  triangle on an edge) instead, and edge-touching cubes are tested as accepted.
- **Empty result:** a closed but flat surface is a valid, empty manifold; it is now exit 2.
- **Loading:** the file is read with `file_type="stl"` whatever its extension. trimesh drops
  triangles with a non-finite coordinate while loading, so no separate NaN check is needed
  (spike check `trimesh.load_drops_non_finite`).
- **CI:** the Linux 3.13 job and the weekly upgrade job install the `deep-repair` extra, so
  the pymeshlab code runs somewhere; the spike reports the pymeshlab check as skipped when the
  extra isn't installed. `pymeshlab>=2025.7.post1` is the verified minimum. The first CI run
  showed that pymeshlab's filter plugins need the system's `libOpenGL.so.0` (absent from the
  Ubuntu image): CI installs `libopengl0`, and a missing filter is now an exit 2 saying what
  to install instead of an `AttributeError` (exit 4).

**r4 — 2026-11-19 (Phase 1).** Gaps in §7.5 found while planning Phase 1, agreed with the
maintainer:

- **Validation:** every number must be finite (TOML accepts `inf` and `nan`, and `inf` passed
  rules such as `scale > 0`). `pin_min_length_factor > 0` is added: with L_min ≤ 0 a 0 mm pin
  became a "standard length". `connector_spacing_factor > 0` and `connector_area_factor > 0` are
  added. `calibration_clearances` must be strictly increasing (a duplicate gave two identical
  holes with the same engraved code).
- **Modes:** `--print-config` with `INPUT` or `--calibrate` is an error, `--dry-run` needs `INPUT`,
  and `-o` is accepted and ignored with `--dry-run`.
- **Found by the Phase 1 review:** integers must fit in 64 bits (the TOML range; `tomllib`
  accepts any size, and a huge integer made `float()` overflow, giving exit 4 instead of 1).
  `--print-config` writes pure ASCII and `--config` also reads UTF-8 with a BOM and UTF-16 with
  a BOM: on Windows a redirected stdout isn't UTF-8 (PowerShell 5.1 writes UTF-16), so
  `--print-config > file` didn't read back. §3.1 lists `errors` among the modules `io` imports.
- **Bounds agreed after the review:** `pin_length_step` ≥ 0.1 (it was only > 0, and 1e-6 made
  `derived()` build 5 million standard lengths; 1e-300 never finished) and `circular_segments`
  ≤ 256 (it had no upper bound; at 256 a 5.4 mm hole's polygon is within 0.0002 mm of its
  circle, and more segments only add triangles).

**r3 — 2026-11-18 (Phase 0).**

- **Frames:** Phase 0 task 8 specified `local_to_world(axis, offset)` returning 4×4, which
  implied a plane-relative frame (plane at local z = 0), while §4.2 puts the plane at local
  z = o and makes local → world the plain transpose. The review found that the two functions
  were not inverses: a point in the §4.2 frame came back shifted by o along the axis.
  Decision (agreed with the maintainer): strict §4.2. `local_to_world(axis)` is the transpose
  (3×4, no `offset`), and tool solids are built around local z = o.

**r2 — 2026-11-17.** Rewritten after a technical review. The library claims were checked against
manifold3d 3.5.5, trimesh 5.2.1, shapely 2.2.0 and matplotlib 3.11.2.

- **Assembly order:** staged sub-assemblies replace "bottom-up, piece by piece", which is impossible
  in any 2×2 layer. Avoiding the deadlock is now credited to the order, not to dowels. Pegs are
  allowed on any face, and the "pegs on Z faces only" rule is removed.
- **Connector placement:**
  - rays now start inside the piece (one cast from a surface hits that surface at distance 0);
  - an exact containment check and a `min_gap` check between holes of the same piece were added
    (holes on perpendicular faces near a shared edge crossed at 0 mm in a simulation);
  - two connectors whenever two fit;
  - the pin length is defined once, with standard shorter lengths. Before, three different values
    appeared: 20, 20.5 and 19.5.
- **Repair:**
  - the mesh is tried as-is first;
  - sign-aware shell normalization (a naive union filled hollow models);
  - never `fix_normals(multibody=True)`.
- **Sections:**
  - taken from the normalized manifold, as the intersection of slices at ±ε (a single slice is
    one-sided at a step);
  - the coplanar vertex rule, which never terminates on dense meshes, is removed.
- **Grid:**
  - proper rotations only;
  - U reduced in peg mode;
  - nudging moved after placement (Phase 6), so it no longer depends on later phases, with a
    deterministic tie-break.
- **Labels:**
  - matplotlib is now a core dependency (labels are on by default);
  - bundled DejaVu Sans Bold;
  - EvenOdd fill;
  - a simple layout search instead of a "largest rectangle" that no library provides.
- **Tools:**
  - explicit circle segments and hole-radius compensation;
  - pins with a flat to lie on the bed;
  - calibration kit dimensions derived from the parameters (20 × 20 × 10 blocks couldn't hold five
    holes, or a 10.7 mm-deep hole), with engraved codes.
- **CLI:**
  - argparse with `SUPPRESS` defaults, so the TOML file isn't always overridden;
  - `--calibrate` without an input file;
  - `--force` deletes only stlsplit's own outputs;
  - `--print-config`;
  - exit code 4 for internal errors;
  - `--dry-run` runs through placement;
  - `--decimate` replaced by `--simplify TOL`.
- **Dependencies:**
  - Python ≥ 3.12 (required by numpy 2.5, scipy 1.18 and networkx 3.7);
  - explicit scipy and networkx instead of `trimesh[easy]`.
- **New:**
  - small-piece merge with a footprint guard;
  - diagnostic codes;
  - the documentation system (§8) with ADRs, drift tests and onboarding;
  - the Claude Code phase protocol (§9.1);
  - the progress table;
  - the project's commit convention.
- **Tests fixed:**
  - the "soup" test, which tested nothing because trimesh merges on load;
  - the hollow-sphere test, which gave 8 pieces on the default bed;
  - the repair tests, made deterministic.

  Added: collision, assembly-order, contact-region-at-a-step and determinism tests.

**r1.** The initial plan.
