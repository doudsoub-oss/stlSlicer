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
