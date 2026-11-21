# Configuration

For users. Every option: its CLI flag, TOML key, default, unit and allowed values. A test
(`tests/unit/test_docs_drift.py`) checks that every option in the code has a row here and that
every default below matches the code.

```bash
stlsplit model.stl -o ./out --bed 220 220 250            # split for a 220 × 220 × 250 bed
stlsplit model.stl -o ./out --config my_printer.toml     # settings from a file
stlsplit model.stl -o ./out --config my_printer.toml --clearance 0.25   # file + one override
stlsplit model.stl --dry-run                             # check everything, write nothing
stlsplit --calibrate -o ./calibration                    # print once, then pick your clearance
stlsplit --print-config --config my_printer.toml         # show the effective settings
```

> **Status (Phase 7):** `--calibrate` and `--print-config` are complete. A split runs up to the
> tool booleans and writes the loose pins (`dowels/`), and a dry run stops after the connector
> placement; both then end with a warning until labels and the piece export land (PLAN.md §10).

## Modes

| Mode | Command | Writes files | Exit codes |
|---|---|---|---|
| Split | `stlsplit INPUT -o DIR [options]` | yes | 0, 1, 2, 3 or 4 |
| Dry run | `stlsplit INPUT --dry-run [options]` | no | as a split would |
| Calibration | `stlsplit --calibrate -o DIR [connector options]` | yes | 0, 1 or 4 |
| Show config | `stlsplit --print-config [--config FILE] [options]` | no | 0 or 1 |

These combinations are refused with exit code 1, before anything is read or written:

- no `INPUT`, no `--calibrate` and no `--print-config`;
- `INPUT` together with `--calibrate`;
- `--print-config` together with `INPUT` or `--calibrate`;
- `--dry-run` without `INPUT`;
- a split or a calibration without `-o DIR`.

`-o` is accepted with `--dry-run` and ignored: a dry run writes nothing.

The dry run prints its plan on standard output, and the log (including diagnostics) on standard
error, so `-q` hides the log but not the plan, and `stlsplit model.stl --dry-run > plan.txt`
saves the plan alone. The plan grows as features land. Today it has the orientation and the
grid:

```text
rotation: 90 deg about Y; cutting (X, Y, Z) = input (+Z, +Y, -X)
input_to_cutting: [0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 465], [0, 0, 0, 1]
extent: 100 x 100 x 460 mm
usable volume: 210 x 210 x 240 mm
cells: 1 x 1 x 2 = 2
planes X: none
planes Y: none
planes Z: 230
```

## Precedence

Built-in defaults ← TOML file (`--config FILE`) ← options typed on the command line.

An option you don't type never overrides the file, even if the file sets a value equal to the
built-in default, and an option you type always wins, even if its value equals the built-in
default (ADR-0011):

```toml
# my_printer.toml
[connectors]
clearance = 0.3
```

```bash
stlsplit --print-config --config my_printer.toml                   # clearance = 0.3 (file)
stlsplit --print-config --config my_printer.toml --clearance 0.2   # clearance = 0.2 (typed)
```

`--print-config` prints the whole effective configuration as TOML. Its output is itself a valid
configuration file: `stlsplit --print-config > my_printer.toml` is a good way to start one. The
output is pure ASCII (other characters are written as `\u` escapes), so it reads back whatever
the encoding of your console.

Unknown tables and keys are errors, so a typo never goes unnoticed:

```text
$ stlsplit --print-config --config bad.toml
stlsplit: error: connectors.clearence: unknown key in bad.toml; the keys of [connectors] are: type, diameter, length, clearance, min_wall, max_per_face
```

Values are checked against the rules in the tables below. A bad value exits with code 1 and a
message naming the option, the allowed range and the value found:

```text
$ stlsplit --print-config --margin -1
stlsplit: error: --margin (printer.margin): must be >= 0, got -1.0
```

## Options

TOML integers are accepted where a number is expected (`margin = 4`). Every number must be
finite, and integers must fit in 64 bits. A `--config` file is UTF-8, with or without a byte order
mark; UTF-16 with a byte order mark (what PowerShell 5.1's `>` writes) is accepted too.

| CLI | TOML key | Default | Unit | Meaning | Allowed values |
|---|---|---|---|---|---|
| `INPUT` | — | — | — | The `.stl` file to split | Required unless `--calibrate` or `--print-config`; must exist |
| `-o DIR`, `--output DIR` | — | — | — | Output directory, created with its parents if missing ([Output directory](#output-directory)) | Required unless `--dry-run` or `--print-config` |
| `--force` | — | off | — | Allow a non-empty output directory: only stlsplit's own outputs in it are replaced | — |
| `--config FILE` | — | — | — | TOML configuration file | Must exist; UTF-8, or UTF-16 with a byte order mark |
| `--dry-run` | — | off | — | Check everything and print the plan, write nothing ([Modes](#modes)) | Needs `INPUT` |
| `--calibrate` | — | off | — | Write the clearance calibration kit ([Modes](#modes)) | Not with `INPUT` |
| `--print-config` | — | off | — | Print the effective configuration as TOML and exit | Not with `INPUT` or `--calibrate` |
| `--bed X Y Z` | `printer.bed` | `[220, 220, 250]` | mm | Build volume | Three values > 0 |
| `--margin MM` | `printer.margin` | `5.0` | mm | Kept free on **each side** of every axis: usable size U = bed − 2 × margin | ≥ 0, and 2 × margin < the smallest bed dimension |
| `--scale FACTOR` | `model.scale` | `1.0` | — | Uniform scale applied after loading (25.4 for a model exported in inches) | > 0 |
| `--auto-orient` / `--no-auto-orient` | `model.auto_orient` | `true` | — | Try the 6 axis orders (as rotations, never mirrored) and keep the one with the fewest cells; on a tie, the model stays as it is when it can ([details](ALGORITHMS.md#auto-orientation)) | — |
| `--simplify TOL` | `model.simplify` | `0.0` | mm | Simplify the mesh; surfaces move by less than TOL. 0 turns it off | ≥ 0 |
| `--deep-repair` | `repair.deep` | `false` | — | Fall back to pymeshlab if basic repair fails (install the `deep-repair` extra, GPL-3.0) | — |
| `--connector TYPE` | `connectors.type` | `"dowel"` | — | `dowel` (holes on both sides, loose pins), `peg` (pegs on one side) or `none` (ADR-0005) | `dowel`, `peg`, `none` |
| `--dowel-diameter MM` | `connectors.diameter` | `5.0` | mm | Pin diameter d | ≥ 0.1 |
| `--dowel-length MM` | `connectors.length` | `20.0` | mm | Exact length of a full pin, L_max. Shallow faces get shorter standard lengths (PLAN.md §6.2) | ≥ L_min = `pin_min_length_factor` × d (15 by default); ≤ the longer side of the bed plate, max(bed X, bed Y) (pins are printed lying down); in peg mode, length / 2 < U on every axis |
| `--clearance MM` | `connectors.clearance` | `0.2` | mm | Radial clearance added to holes; depends on your printer, measure it with `--calibrate` | ≥ 0 |
| `--min-wall MM` | `connectors.min_wall` | `2.0` | mm | Minimum material around and between holes | > 0 |
| `--max-connectors-per-face N` | `connectors.max_per_face` | `4` | — | Maximum connectors per cut face | Integer ≥ 1 |
| `--label` / `--no-label` | `labels.enabled` | `true` | — | Engrave each piece's ID on one of its cut faces | — |
| `--label-depth MM` | `labels.depth` | `0.6` | mm | Engraving depth | > 0 and < `min_wall` |
| `--preview` / `--no-preview` | `output.preview` | `true` | — | Write `preview_exploded.glb` | — |
| `-v` | — | — | — | Also show debug messages, stage timings and error tracebacks | Not with `-q` |
| `-q` | — | — | — | Show warnings and errors only | Not with `-v` |
| `--version` | — | — | — | Print the version and exit | — |
| `-h`, `--help` | — | — | — | Print the help and exit | — |

## Advanced options (`[advanced]`, TOML only)

They tune the formulas of PLAN.md §6 without code changes. d is `connectors.diameter`, w is
`connectors.min_wall`.

| TOML key | Default | Unit | Meaning | Allowed values |
|---|---|---|---|---|
| `advanced.axial_play` | `0.5` | mm | Each hole is this much deeper than the pin end (glue room) | ≥ 0 |
| `advanced.pin_length_step` | `2.0` | mm | Step between standard pin lengths (20, 18, 16 by default) | ≥ 0.1. A run stops with exit 1 if two lengths it uses would share a file name (15.25 and 15.15 both read `l15.2`): use a length and a step that are multiples of 0.1 |
| `advanced.pin_min_length_factor` | `3.0` | — | Shortest allowed pin L_min = factor × d | > 0 |
| `advanced.pin_chamfer` | `0.5` | mm | Chamfer on pin and peg ends | ≥ 0, < L_min / 4 and < d / 2 |
| `advanced.pin_flat` | `0.4` | mm | Depth of the flat pins are printed on (0 = round pins) | ≥ 0 and < d / 4 |
| `advanced.hole_chamfer` | `0.4` | mm | Chamfer at the hole mouth | ≥ 0 and ≤ w / 2 |
| `advanced.circular_segments` | `64` | — | Segments per circle | Integer from 16 to 256 |
| `advanced.connector_spacing_factor` | `3.0` | — | Minimum distance between connectors of one face = factor × d | > 0 |
| `advanced.connector_area_factor` | `6.0` | — | Face area per connector = (factor × d)² | > 0 |
| `advanced.section_epsilon` | `0.01` | mm | Half-thickness of the section probe (ADR-0002) | > 0 and ≤ 0.1 |
| `advanced.nudge_window` | `5.0` | mm | How far a cut plane may be moved to a better position: fewer faces without room for a connector, then fewer tiny regions ([details](ALGORITHMS.md#plane-nudging)); never further than every piece still fitting the usable volume allows; 0 disables nudging | ≥ 0 |
| `advanced.nudge_step` | `0.5` | mm | Step of the nudge search: planes move by whole multiples of it, at most 100 on each side | > 0 and ≥ `nudge_window` / 100 |
| `advanced.small_piece_volume` | `500.0` | mm³ | Pieces smaller than this are merged into the piece they touch when that is safe (W005; otherwise W004; [details](ALGORITHMS.md#small-piece-merge)); 0 disables merging | ≥ 0 |
| `advanced.label_font` | `"DejaVuSans-Bold.ttf"` | — | Label font: a font bundled with matplotlib (bare file name) or an absolute path | Must resolve to an existing file |
| `advanced.label_min_height` | `4.0` | mm | Smallest label text height | > 0 and ≤ `label_max_height` |
| `advanced.label_max_height` | `12.0` | mm | Largest label text height | ≥ `label_min_height` |
| `advanced.calibration_clearances` | `[0.10, 0.15, 0.20, 0.25, 0.30]` | mm | Clearances of the calibration kit's holes, engraved in hundredths of a millimetre (0.123 reads `12.3`) | 1 to 10 values, each ≥ 0, strictly increasing; `--calibrate` also needs them at least 0.0001 apart, so that their codes differ, and refuses a bar that doesn't fit the printer, an engraving that would reach a hole, or holes that would touch |
| `advanced.preview_spread` | `0.15` | — | Exploded-view offset per grid step, as a fraction of the model size | ≥ 0 |

The values derived from these (usable volume, standard pin lengths, hole depths, hole radius, …)
are listed with their formulas in PLAN.md §6 and computed in one place, `config.derived()`.

## Output directory

- `-o DIR` is created, with its parents, if it doesn't exist. An empty directory is used as is.
- A non-empty directory is refused (exit 1) unless you pass `--force`.
- With `--force`, only the outputs stlsplit owns are deleted: `parts/`, `dowels/`,
  `calibration/`, `assembly.json`, `assembly.md` and `preview_exploded.glb`. Everything else
  in the directory is kept, and the directory itself is never deleted.
- An owned name that is a symlink is unlinked; what it points to is never touched.
- `--force` refuses (exit 1, before any work) to run when it would delete a file the run reads:
  the input, the `--config` file or a custom label font inside one of those outputs, such as
  `stlsplit out/parts/model.stl -o out --force`.

## Example configuration

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
