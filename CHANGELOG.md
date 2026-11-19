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
  pymeshlab with `--deep-repair` (extra `deep-repair`). A mesh that stays open or
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
