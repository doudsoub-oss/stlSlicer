# Troubleshooting

For users. Every exit code and diagnostic code, with its cause and fix. The codes are defined in
`src/stlsplit/errors.py`; a test (`tests/unit/test_docs_drift.py`) keeps the two in sync. Codes
are never reused or renumbered.

Every error is one line on stderr, starting with `stlsplit: error:`. Run the same command with
`-v` to see the traceback as well.

## Exit codes

### 0 — Success
Diagnostics of severity `info` or `warning` may have been printed.

### 1 — Invalid input
Invalid input file, arguments, configuration or output directory. The message names the problem.
Common cases:

| Message starts with | Cause | Fix |
|---|---|---|
| `missing INPUT file`, `give either an INPUT file or --calibrate`, `--print-config takes no INPUT`, `--dry-run needs an INPUT file` | The arguments don't select exactly one mode | Pick one mode ([CONFIGURATION.md](CONFIGURATION.md#modes)) |
| `missing -o/--output DIR` | A split or a calibration needs an output directory | Add `-o DIR`, or use `--dry-run` |
| `argument --margin: invalid float value` (or another `argument ...`) | A value of the wrong type, a missing value, or an unknown option | See `stlsplit --help` |
| `--margin (printer.margin): must be >= 0, got -1.0` | A value outside its allowed range; the message gives the range | Fix the value on the command line or in the `--config` file |
| `connectors.clearence: unknown key in my.toml` | A typo in the TOML file, or a key from another version | Use a key listed in the message ([CONFIGURATION.md](CONFIGURATION.md)) |
| `my.toml: invalid TOML` | The file isn't valid TOML; the message gives the line and column | Fix the syntax, or regenerate the file with `stlsplit --print-config` |
| `--config my.toml: can't read it` | The file doesn't exist or isn't readable | Check the path |
| `--config my.toml: not valid UTF-8 text` | The file was saved in another encoding | Save it as UTF-8 (or UTF-16 with a byte order mark) |
| `advanced.label_font: no such font file` | The font is neither a font bundled with matplotlib nor an existing absolute path | Use the default `DejaVuSans-Bold.ttf` or an absolute path |
| `INPUT model.stl: no such file` | The input path is wrong | Check the path |
| `output directory out is not empty` | stlsplit refuses to mix its outputs with existing files | Use an empty directory, or add `--force`: it replaces only stlsplit's own outputs and keeps everything else |
| `output directory out exists and is not a directory` | `-o` points to a file | Choose another path |

### 2 — Mesh can't be repaired
TODO (Phase 2): cause and fix (`--deep-repair`, repairing in a mesh editor).

### 3 — Partial success
At least one diagnostic of severity `partial` (for example W001). The files are written; read
the diagnostics before printing.

### 4 — Internal error
A bug. Please report it with the full output of the same command run with `-v`.

## Diagnostic codes

Diagnostics report something worth knowing without stopping the run. They are printed on stderr
as `CODE message [IDs]`; `info` ones are hidden by `-q`. Any `partial` diagnostic makes the run
exit with 3.

| Code | Severity | Meaning |
|---|---|---|
| W001 | partial | A cut face got no connector |
| W002 | warning | A pin was shortened to a standard length below `--dowel-length` |
| W003 | warning | A label was skipped: no room for the minimum text height |
| W004 | warning | A small piece was left on its own |
| W005 | info | A small piece was merged into a neighbour |
| W006 | warning | Suspicious scale: model smaller than 1 mm or larger than 5 m |
| W007 | info | The mesh was repaired |
| W008 | info | A piece has no cut face (a separate body): no connector, no label |
| W009 | info | A face has a single connector: the pieces can rotate around it until glued |
| W010 | info | Overlapping shells were merged |
| W011 | warning | An inside-out body was flipped |
| W012 | info | The model already fits: nothing to cut |

### W001 — Cut face without connector (partial)
TODO (Phase 5)

### W002 — Pin shortened (warning)
TODO (Phase 5)

### W003 — Label skipped (warning)
TODO (Phase 8)

### W004 — Small piece left on its own (warning)
TODO (Phase 4)

### W005 — Small piece merged (info)
TODO (Phase 4)

### W006 — Suspicious scale (warning)
TODO (Phase 2)

### W007 — Mesh repaired (info)
TODO (Phase 2)

### W008 — Piece without cut face (info)
TODO (Phase 4)

### W009 — Single connector on a face (info)
TODO (Phase 5)

### W010 — Overlapping shells merged (info)
TODO (Phase 2)

### W011 — Inside-out body flipped (warning)
TODO (Phase 2)

### W012 — Model already fits (info)
TODO (Phase 3)

## Common problems

TODO (Phase 11)
