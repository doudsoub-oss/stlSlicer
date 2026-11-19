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
