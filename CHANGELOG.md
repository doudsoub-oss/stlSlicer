# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) from 1.0.0 on (CONTRIBUTING.md,
"Release a version").

## [Unreleased]

### Added
- Project scaffolding: installable `stlsplit` package with `--help` and `--version`,
  `scripts/check.py`, CI, the documentation skeleton, ADR-0001 to ADR-0014, and
  `scripts/api_spike.py` recording the library behaviours the code relies on.
- Every command-line option and TOML setting, merged as built-in defaults ← `--config` file ←
  typed options, and validated with messages that name the option and the allowed range
  (docs/CONFIGURATION.md).
- `--print-config` prints the effective configuration as TOML (pure ASCII), readable back with
  `--config`, which accepts UTF-8 with or without a BOM and UTF-16 with a BOM.
- Modes (split, `--dry-run`, `--calibrate`, `--print-config`) are checked before anything is
  read or written. The split, dry run and calibration stop with a warning until the pipeline
  exists.
- Output-directory policy: a non-empty `-o` directory needs `--force`, which deletes only
  stlsplit's own outputs and never follows symlinks.
- Exit codes 0–4 (docs/TROUBLESHOOTING.md): one line per error, the traceback with `-v`;
  logging levels with `-q` and `-v`, stage timings with `-v`.
- Loading the input STL (any extension; `--scale` applied), with W006 for a model under 1 mm
  or over 5 m. An empty, unreadable or truncated file exits 1.
- Try-first repair (ADR-0007): a valid mesh is used as is; otherwise basic repair (W007), then
  pymeshlab with `--deep-repair` (extra `deep-repair`; a missing pymeshlab or filter plugin is
  reported with what to install). A mesh that stays open or
  non-manifold, or encloses no volume, exits 2 with the open-edge, non-manifold-edge and body
  counts and what to try next.
- Shell normalization: overlapping shells are unioned (W010), voids are kept at any depth of
  nesting (a body loose inside a void too, and overlapping hollow parts keep their walls), and
  inside-out shells are turned the right way out (W011), even when the whole model is inside
  out. Basic repair keeps each shell's majority orientation, so one reversed triangle can't
  fill a void.
- `--simplify TOL` simplifies the repaired mesh; a tolerance that erases the model exits 1.
- Split and dry run log a one-line model summary (triangles, bodies, voids, size, volume,
  repair steps). The input is loaded and repaired before the output directory is touched, so
  a failing input never creates it and `--force` never deletes the previous outputs for it.
- Auto-orientation (`--auto-orient`, on by default): of the six axis orders, the one that needs
  the fewest pieces, always as a rotation, never a mirror image; on a tie the model stays as it
  is when it can. The model then moves so its bounding box starts at the origin; the transform
  from the input is kept for `assembly.json`.
- Even grid: each axis is split into the fewest equal cells that fit the usable volume
  (bed − 2 × margin, minus half a pin with `--connector peg`), so pieces have similar sizes.
  W012 when the model already fits. The log shows the grid, e.g.
  `grid: 1 x 1 x 2 = 2 cells; rotation 90 deg about Y`.
- `--dry-run` prints the orientation, the input-to-cutting matrix, the model's size, the usable
  volume, the cell counts and the plane positions on standard output.
- Cutting: the model is split along the grid into pieces with stable IDs (`X1-Y0-Z2`, plus
  `-a`, `-b`, … for several bodies in one cell), keeping internal voids, and every contact
  between two pieces becomes a cut face (`X0-Y0-Z0~X1-Y0-Z0`). A model face lying exactly on a
  cut plane (a step) gives the true contact and clean pieces, with no leftover sheet. The log shows `cutting: 8 pieces, 12 cut
  faces`; `--dry-run` also lists every piece (volume) and face (plane, area).
- Small pieces (under `small_piece_volume`, 500 mm³) crossing a plane by a little are merged
  into the piece they touch when the merged piece still fits and can be put in place with one
  straight move (W005); otherwise they stay on their own with the reason (W004). Pieces
  without a cut face are reported (W008).
- Plane nudging (ADR-0003): each cut plane may move up to `advanced.nudge_window` (5 mm) in
  steps of `advanced.nudge_step` (0.5 mm) to a position with fewer faces that have no room
  for a connector, then fewer tiny regions (under 4 · π · (d/2)²), and stays where it is
  unless moving gains something. Every piece still fits the usable volume. A plane through a
  6 × 6 neck moves off it onto the 60 × 60 section next to it. The log shows
  `nudging: 1 of 1 plane moved (Z 150 -> 147.5)`; `--dry-run` prints the nudged planes.
  `nudge_window = 0` turns it off. `nudge_window / nudge_step` may be at most 100 (exit 1
  otherwise, naming `advanced.nudge_step`): a tiny step made the search run out of memory or
  exit 4.
- Connector placement: every cut face gets up to `--max-connectors-per-face` dowel positions
  (two whenever two fit, so the pieces can't rotate), spread out over the face and kept
  `--min-wall` from its edges. Each hole is checked in 3D: enough material behind the face on
  both sides (otherwise the longest standard pin that fits, W002), a wall all around it further
  in, and `--min-wall` from the holes of the piece's other faces. A face without room gets
  W001 (exit 3), a face with a single connector W009. With `--connector peg`, only the hole
  side is checked. The log shows `connectors: 8 on 2 of 2 cut faces`; `--dry-run` lists every
  connector (position, pin length, hole depths) and the pins to print by diameter and length.
- `--dowel-length` can't exceed the longer side of the bed plate, max(bed X, bed Y): pins are
  printed lying down (exit 1 otherwise, naming the option).
- Tool solids: every connector is applied with one batched boolean per piece. Dowel holes with a
  mouth chamfer line up on both pieces; with `--connector peg`, the peg is fused to one piece and
  the other gets the hole. Each piece is checked afterwards (valid, one shell per body, volumes
  within 5 %, fits bed − 2 × margin).
- Loose pins: a split writes one STL per pin length in `dowels/`, lying on its flat, and the log
  says how many of each to print (`pins: print 6 x dowels/dowel_d5.0_l20.0.stl`).
- `stlsplit --calibrate` writes the calibration kit to `calibration/`: a bar with one hole per
  clearance and its engraved code, the test pin, and a README on printing, testing and choosing
  a clearance.
- Piece labels: each piece's short ID (`X1-Y0-Z2-b` reads `1-0-2b`) is engraved on one of its cut
  faces, readable from outside and clear of the connectors, at the largest height that fits
  (4 to 12 mm). A label never goes through a thin part of the piece. A piece with no room on any
  face gets warning W003. `--dry-run` lists the labels, and `--no-label` turns them off.
- A split now writes every output: `parts/*.stl` (binary, in the model's frame),
  `assembly.json` (schema version 1), `assembly.md` (print list and steps by stage),
  `preview_exploded.glb` (`--no-preview` skips it) and a final summary with the exit code. Two
  runs give byte-identical folders.
- Assembly order: X joins, then Y, then Z, each join one straight move along its pins. New
  diagnostic W013 (exit 3) for a move that can't be shown to have a clear path.

- `-v` also shows the time of the stage that failed, and the total time.
- Ctrl-C stops a run with one line and exit code 130.
- End-to-end suite: every catalogue fixture and three real scans run through the CLI, checking
  watertight pieces, fit, volume balance, aligned holes, wall between holes, byte-identical
  reruns and the exit code. `scripts/check.py` now fails under 85 % coverage.

### Changed
- A model that would need more than 1000 grid cells, or a `--scale` that puts coordinates beyond
  5e9 mm, exits 1 at once with a message naming `--scale`. These runs used to hang, exit 4 or end
  in a misleading repair error.
- Running out of memory exits 1 with a suggestion, instead of being reported as a bug.
- Replacing the outputs is all or nothing, for a split and `--calibrate`: files are prepared in a
  staging folder and swapped in at the end, so a failed run, a full disk included, keeps the
  previous outputs. `--force` used to delete them first.
- A run that draws text exits 1 when `advanced.label_font` isn't a font, or is a symbol or
  placeholder font that can't draw the labels. A file that wasn't a font used to exit 4.
- `advanced.pin_chamfer` must now be smaller than the pin's radius (exit 1 otherwise): a larger
  chamfer can't be built. With the default 0.5 mm, this rejects a pin diameter of 1 mm or less
  unless the chamfer is lowered too.
- `--dowel-diameter` must be at least 0.1 mm: thinner pins collapsed into empty or open meshes.
- A run stops with exit 1 when two pin lengths it uses would share a file name (15.25 and
  15.15 mm both read `l15.2`), instead of losing one of them.
- `--calibrate` exits 1 for a bar that doesn't fit the printer, an engraving that would reach a
  hole, or holes that would touch.

### Fixed
- `--force` could delete the file it was reading: `stlsplit out/parts/model.stl -o out --force`
  removed the input with `parts/`. It now exits 1 before any work when the input, the `--config`
  file or a custom label font lies inside an output it would delete.
- A very small model (a 10 mm cube at `--scale 0.001`) no longer exits 4: it was dropped as debris.
  A model with a piece under 5e-7 mm³, too small for `assembly.json` to record, exits 1.
- An input file name that isn't valid UTF-8 now works. It is recorded with the invalid bytes
  escaped.
- `--dry-run | head` no longer reports an internal error, and a closed stderr no longer changes
  the exit code, including when a stream is closed from the start.
- Ctrl-C during the final swap could delete previous outputs. The swap now finishes first.
- A face where no pin fits no longer tries every standard length at every position: with a 60 mm
  pin and a 0.1 mm step, one such face went from over 200 s to about 2 s. Results are unchanged.
