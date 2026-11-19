# Architecture

For maintainers. How the code is organised and the rules it follows. The reasons behind the
choices are in the [ADRs](adr/README.md); the numbers are in PLAN.md §6 and `config.py`.

## Pipeline

TODO (Phase 9): final diagram with the functions that exist. The planned pipeline is PLAN.md §5.1:

```
input.stl → io.load_stl → repair.prepare → grid.orient → grid.even_grid → grid.nudge
  → cutting.split_cells → cutting.cut_faces → cutting.merge_small_pieces → connectors.place
  → labels.layout → tools.apply → assembly.plan_steps → io.write_outputs
```

## Module map

`✓` = exists now. A module only imports modules listed above it (no import cycles). Only
`io` and `cli` touch the file system; everything else is pure.

| Module | Responsibility | May import | Status |
|---|---|---|---|
| `models` | Dataclasses only | — | ✓ (`Axis`, `Diagnostic`; the others come with their phase) |
| `errors` | Exit codes, exception types, diagnostic registry | `models` | ✓ |
| `config` | `Config` dataclasses, defaults, TOML, validation, `derived()` | `errors` | ✓ |
| `geometry` | Thin wrappers around library calls; mesh repair; frames; sections; rays; cylinders | `config`, `models` | ✓ (sections in Phase 4) |
| `repair` | Try-first repair, shell normalization | `geometry` | ✓ |
| `connectors` | Connector placement | `geometry` | TODO (Phase 5) |
| `grid` | Usable volume, auto-orient, even grid, nudging | `geometry`, `connectors` | TODO (Phase 3) |
| `cutting` | Splitting, piece IDs, cut faces, small-piece merge | `geometry` | TODO (Phase 4) |
| `labels` | Text outlines and layout on a face | `geometry` | TODO (Phase 8) |
| `tools` | Hole, peg, pin and label solids; batched booleans | `geometry` | TODO (Phase 7) |
| `calibrate` | Calibration kit | `tools`, `labels` | TODO (Phase 7) |
| `assembly` | Assembly order; JSON and Markdown; preview scene | `models`, `config` | TODO (Phase 9) |
| `io` | Reading and writing files; output-directory policy | `errors`, `models`, `config` | ✓ (STL loading, output-directory policy, label-font lookup; writing in Phase 9) |
| `cli` | Argument parsing, orchestration, logging, exit codes | everything | ✓ (split and dry run stop after repair until the next stages exist) |

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

Planned: `Plane`, `Grid` (Phase 3), `Piece`, `CutFace` (Phase 4), `Connector` (Phase 5),
`Label` (Phase 8), `AssemblyStep` (Phase 9).

## Frames

| Frame | Definition | Used for |
|---|---|---|
| Input | STL coordinates × `--scale` | Loading, repair, original bounding box |
| Cutting | `x_cut = R · x_in + t`; R a proper rotation (ADR-0008), t moves the bbox minimum to the origin | Everything after orientation, every output file |
| Plane-local | For a plane of axis a: the axes below; 2D (u, v) = local (x, y) | Cut regions, connectors, labels |

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

TODO (Phase 4): I1–I7 (PLAN.md §5.3), with where each is asserted and tested.

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
