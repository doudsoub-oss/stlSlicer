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
| `models` | Dataclasses only | — | ✓ (`Axis` only; dataclasses in Phase 1) |
| `errors` | Exit codes, exception types, diagnostic registry | `models` | ✓ |
| `config` | `Config` dataclasses, defaults, TOML, validation, `derived()` | `errors` | TODO (Phase 1) |
| `geometry` | Thin wrappers around library calls; frames; sections; rays; cylinders | `config`, `models` | ✓ (sections in Phase 4) |
| `repair` | Try-first repair, shell normalization | `geometry` | TODO (Phase 2) |
| `connectors` | Connector placement | `geometry` | TODO (Phase 5) |
| `grid` | Usable volume, auto-orient, even grid, nudging | `geometry`, `connectors` | TODO (Phase 3) |
| `cutting` | Splitting, piece IDs, cut faces, small-piece merge | `geometry` | TODO (Phase 4) |
| `labels` | Text outlines and layout on a face | `geometry` | TODO (Phase 8) |
| `tools` | Hole, peg, pin and label solids; batched booleans | `geometry` | TODO (Phase 7) |
| `calibrate` | Calibration kit | `tools`, `labels` | TODO (Phase 7) |
| `assembly` | Assembly order; JSON and Markdown; preview scene | `models`, `config` | TODO (Phase 9) |
| `io` | Reading and writing files; output-directory policy | `models`, `config` | TODO (Phase 2) |
| `cli` | Argument parsing, orchestration, logging, exit codes | everything | ✓ (`--help`, `--version`) |

`__init__` exposes `__version__` (from the package metadata) and `__main__` runs `cli.main`.

## Data model

TODO (Phase 1): `Plane`, `Grid`, `Piece`, `CutFace`, `Connector`, `Label`, `AssemblyStep`,
`Diagnostic` (PLAN.md §5.2).

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

TODO (Phase 1): how stages emit diagnostics and how the CLI turns them into an exit code.
